"""이미지 블럭에 Vision LLM 설명을 추가하는 enricher.

파이프라인에서 추출된 이미지를 Vision API로 분석하여:
1. 이미지 설명 (2-3문장) + caption (10-30자)
2. 이미지 타입 분류 (LLM 출력 파싱용 enum — 콘텐츠 + 장식·반복)
3. **is_decorative / should_index** — *주된 노이즈 게이트* (사용자 절칙: LLM 판단 우선)
4. 텍스트 보강 (OCR + Vision 결합)
5. 주변 컨텍스트 (heading_path / 직전·직후 단락) inject

D17 (2026-05-08) 강화:
- IMAGE_TYPE_CATEGORIES enum 풀세트 (콘텐츠 + 장식)
- is_decorative / should_index / decorative_rationale 출력
- 컨텍스트 inject 지원 (heading_path / page_number / prev/next paragraph)
- caption / summary / ocr_text / visible_entities / relation_to_neighbor 별 metadata 필드
"""

from __future__ import annotations

import base64
import json
import os
import re

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType

log = get_logger(__name__)


# LLM 출력 파싱용 허용 enum (사용자 절칙: 키워드 리스트로 *제외 결정 X*).
# 노이즈 결정은 별도 is_decorative (boolean) LLM 판단이 함.
IMAGE_TYPE_CATEGORIES: frozenset[str] = frozenset({
    # 콘텐츠
    "chart",
    "diagram",
    "screenshot",
    "photo",
    "icon",
    "process_flow",
    "table_image",
    # 장식·반복 (분류 보조 — 제외 게이트는 is_decorative)
    "logo",
    "header",
    "footer",
    "watermark",
    "decorative",
    # fallback
    "other",
})


def _parse_strict_bool(value: object, *, default: bool) -> bool:
    """LLM 출력의 boolean 을 엄밀 파싱.

    Python `bool("false")` 가 True 인 함정을 회피. "true"/"false"/"0"/"1"/숫자/
    실제 boolean 모두 안전 정규화. 인식 불가 시 default 반환.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "yes", "1", "y", "t", "참"):
            return True
        if s in ("false", "no", "0", "n", "f", "거짓"):
            return False
        return default
    return default


_VISION_PROMPT_TEMPLATE = """당신은 매뉴얼/SOP/지식 문서의 시각 자료를 분석하는 전문가입니다.

## 문서 컨텍스트
- 문서 제목: {document_title}
- 현재 섹션 (heading_path): {heading_chain}
- 페이지 번호: {page_number}
- 직전 단락 (≤200자): {prev_paragraph}
- 직후 단락 (≤200자): {next_paragraph}

## 분석 항목
1. **is_decorative (boolean)**: 이 그림이 *콘텐츠 가치 0* 인가?
   - true: 페이지마다 반복 등장하는 회사 로고/헤더 띠/푸터 띠/워터마크/장식선/빈 여백 등 *문서 의미 없음*
   - false: KRX 거래 화면, 차트, 다이어그램, 인포그래픽, 스크린샷 등 *콘텐츠*
   - **모호하면 false (보존)** — 검색 회귀 방지
2. **should_index (boolean, default true)**: 검색 인덱스에 포함할지. is_decorative=true 면 자동 false.
3. **decorative_rationale (1문장)**: is_decorative 판단 근거 (디버깅용).
4. **image_type (enum)**: 다음 중 하나
   - 콘텐츠: `chart` `diagram` `screenshot` `photo` `icon` `process_flow` `table_image`
   - 장식·반복: `logo` `header` `footer` `watermark` `decorative`
   - 모름: `other`
5. **caption (10-30자)**: 짧은 라벨 (검색 표시용). 예: "KRX 소수점 주식 주문 화면"
6. **summary (50-200자)**: 자연어. 매뉴얼 답변 prompt 에 inline inject — *그림 없이도 이 글만 읽고 답할 수 있어야 함*.
7. **ocr_text**: 그림 안의 모든 텍스트 (로고 텍스트 제외, 표 셀/라벨/안내 문구 포함). Markdown 표 형식 지원.
8. **visible_entities (배열)**: 그림에 보이는 고유명사·수치·식별자.
9. **relation_to_neighbor (1-2문장)**: 직전/직후 단락과의 관계. 예: "직전 문단의 KRX 거래시간 설명을 화면 캡쳐로 보여줌".

## 출력
JSON 만 (마크다운 펜스 X):
{{
  "is_decorative": false,
  "should_index": true,
  "decorative_rationale": "...",
  "image_type": "screenshot",
  "caption": "...",
  "summary": "...",
  "ocr_text": "...",
  "visible_entities": [],
  "relation_to_neighbor": "..."
}}"""


class ImageDescriber:
    """이미지 블럭에 Vision LLM 기반 설명·노이즈 판단을 추가한다."""

    def __init__(self, llm_client: object | None = None) -> None:
        self._llm_client = llm_client

    async def describe_blocks(
        self,
        blocks: list[BlockObject],
        document_title: str = "",
    ) -> list[BlockObject]:
        """이미지 블럭에 Vision 설명 + LLM 노이즈 판단을 추가한다.

        Parameters
        ----------
        blocks : list[BlockObject]
            처리 대상 블럭 목록. IMAGE 타입만 처리.
        document_title : str
            문서 제목 (vision prompt 컨텍스트에 inject).
        """
        for idx, block in enumerate(blocks):
            if block.block_type != BlockType.IMAGE:
                continue
            meta = block.metadata or {}
            if block.image_description and meta.get("is_decorative") is not None:
                continue  # 이미 분석됨
            if not block.image_path:
                continue

            try:
                context = self._build_context(blocks, idx, document_title)
                analysis = await self._analyze_image(block.image_path, context)
                self._apply_analysis(block, analysis)
            except Exception as exc:
                log.warning(
                    "image_description_failed",
                    image_path=block.image_path,
                    error=str(exc),
                )

        return blocks

    @staticmethod
    def _build_context(
        blocks: list[BlockObject],
        idx: int,
        document_title: str,
    ) -> dict:
        """현재 image block 의 주변 컨텍스트를 구성한다.

        - heading_path: source_location.heading_path (P1 heading_propagator 후 채워짐)
        - page_number: source_location.page_number
        - prev/next paragraph: 직전·직후 텍스트 블럭의 content (≤200자)
        """
        block = blocks[idx]
        heading_chain = ""
        page_number = ""
        try:
            sl = block.source_location
            heading_path = getattr(sl, "heading_path", []) or []
            if heading_path:
                heading_chain = " > ".join(str(h) for h in heading_path)
            page_number = str(getattr(sl, "page_number", "") or "")
        except Exception:
            pass

        TEXT_TYPES = {
            BlockType.PARAGRAPH,
            BlockType.HEADING_1,
            BlockType.HEADING_2,
            BlockType.HEADING_3,
            BlockType.BULLETED_LIST,
            BlockType.NUMBERED_LIST,
            BlockType.CALLOUT,
            BlockType.QUOTE,
        }

        prev_text = ""
        for j in range(idx - 1, max(-1, idx - 6), -1):
            b = blocks[j]
            if b.block_type in TEXT_TYPES and b.content:
                prev_text = b.content.strip()[:200]
                break

        next_text = ""
        for j in range(idx + 1, min(len(blocks), idx + 6)):
            b = blocks[j]
            if b.block_type in TEXT_TYPES and b.content:
                next_text = b.content.strip()[:200]
                break

        return {
            "document_title": document_title or "(제목 없음)",
            "heading_chain": heading_chain or "(섹션 정보 없음)",
            "page_number": page_number or "(페이지 정보 없음)",
            "prev_paragraph": prev_text or "(직전 단락 없음)",
            "next_paragraph": next_text or "(직후 단락 없음)",
        }

    async def _analyze_image(self, image_path: str, context: dict) -> dict:
        """Vision API 로 이미지를 컨텍스트와 함께 분석한다."""
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        b64 = base64.b64encode(image_bytes).decode()

        prompt = _VISION_PROMPT_TEMPLATE.format(**context)
        response_text = await self._call_vision_llm(prompt, b64)
        return self._parse_vision_response(response_text)

    async def _call_vision_llm(self, prompt: str, image_b64: str) -> str:
        """Vision LLM API를 호출한다.

        llm_router (vllm B200) → OpenAI 순.
        """
        # 1) llm_router 우선 (B200 vllm = gemma-4-31b vision 지원)
        try:
            import base64 as _b64

            from src.common.llm.base import LLMTask, LLMVisionRequest
            from src.common.llm.router import llm_router

            img_bytes = _b64.b64decode(image_b64)
            response = await llm_router.route_vision(
                task=LLMTask.VISION_OCR,
                request=LLMVisionRequest(
                    prompt=prompt,
                    images=[img_bytes],
                    max_tokens=800,
                ),
            )
            if response and response.text:
                return response.text
        except Exception as exc:  # noqa: BLE001
            log.debug("router_vision_failed", error=str(exc))

        # OpenAI-compatible Vision (vLLM)
        try:
            from openai import AsyncOpenAI

            if isinstance(self._llm_client, AsyncOpenAI):
                response = await self._llm_client.chat.completions.create(
                    model=os.environ.get("KMS_VISION_MODEL", "gpt-5.5"),
                    max_tokens=800,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{image_b64}",
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                )
                return response.choices[0].message.content or ""
        except ImportError:
            log.debug("openai_sdk_not_installed")
        except Exception as exc:
            log.debug("openai_vision_failed", error=str(exc))

        raise RuntimeError("Vision LLM 사용 불가: 클라이언트가 설정되지 않았거나 API 호출 실패")

    @staticmethod
    def _parse_vision_response(text: str) -> dict:
        """Vision JSON 응답을 파싱한다 — 신규 풀세트 필드.

        Returns dict with keys: is_decorative, should_index, decorative_rationale,
        image_type, caption, summary, ocr_text, visible_entities, relation_to_neighbor,
        description (= summary, 하위 호환).
        """
        # <think> 태그 제거 (일부 모델의 reasoning 출력)
        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
        cleaned = text.strip()

        # 코드 블럭에 감싸진 JSON 처리
        if "```" in cleaned:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("vision_json_parse_failed", text_head=cleaned[:200])
            return {
                "is_decorative": False,  # 사용자 절칙: 모호하면 보존 (시연 안전)
                "should_index": True,
                "decorative_rationale": "JSON 파싱 실패 — 안전 보존",
                "image_type": "other",
                "caption": "",
                "summary": cleaned[:500],
                "description": cleaned[:500],
                "ocr_text": "",
                "visible_entities": [],
                "relation_to_neighbor": "",
            }

        # image_type 검증 (LLM 출력 파싱용 enum — 미허용 값은 'other' fallback)
        image_type = str(data.get("image_type", "other") or "other").lower()
        if image_type not in IMAGE_TYPE_CATEGORIES:
            log.debug("image_type_unknown_fallback", got=image_type)
            image_type = "other"

        # boolean 필드 strict 변환 — bool("false") == True 버그 방어 (GPT-5 phase 1 발견)
        is_decorative = _parse_strict_bool(data.get("is_decorative"), default=False)
        if "should_index" in data:
            should_index = _parse_strict_bool(data.get("should_index"), default=True)
        else:
            # should_index 누락 시: is_decorative=true 면 자동 false, 아니면 true
            should_index = not is_decorative

        summary = str(data.get("summary", "") or "")
        return {
            "is_decorative": is_decorative,
            "should_index": should_index,
            "decorative_rationale": str(data.get("decorative_rationale", "") or "")[:500],
            "image_type": image_type,
            "caption": str(data.get("caption", "") or "")[:120],
            "summary": summary,
            "description": summary,  # 하위 호환 (기존 image_description 호출자)
            "ocr_text": str(data.get("ocr_text", "") or ""),
            "visible_entities": data.get("visible_entities", []) or [],
            "relation_to_neighbor": str(data.get("relation_to_neighbor", "") or "")[:500],
        }

    @staticmethod
    def _apply_analysis(block: BlockObject, analysis: dict) -> None:
        """LLM 분석 결과를 block 에 적용한다."""
        block.image_description = analysis.get("description", "")
        if analysis.get("ocr_text") and not block.ocr_text:
            block.ocr_text = analysis["ocr_text"]

        meta = block.metadata
        meta["image_type"] = analysis["image_type"]
        meta["is_decorative"] = analysis["is_decorative"]
        meta["should_index"] = analysis["should_index"]
        if analysis.get("decorative_rationale"):
            meta["decorative_rationale"] = analysis["decorative_rationale"]
        if analysis.get("caption"):
            meta["caption"] = analysis["caption"]
        if analysis.get("summary"):
            meta["summary"] = analysis["summary"]
        if analysis.get("ocr_text"):
            meta["ocr_text"] = analysis["ocr_text"]
        if analysis.get("visible_entities"):
            meta["visible_entities"] = analysis["visible_entities"]
        if analysis.get("relation_to_neighbor"):
            meta["relation_to_neighbor"] = analysis["relation_to_neighbor"]

        # content 재구성 — 검색·임베딩에 사용
        block.content = ImageDescriber._build_image_content(
            description=analysis.get("description", ""),
            ocr_text=block.ocr_text,
            image_type=analysis["image_type"],
            caption=analysis.get("caption", ""),
        )
        block.compute_hash()

    @staticmethod
    def _build_image_content(
        description: str,
        ocr_text: str | None,
        image_type: str,
        caption: str = "",
    ) -> str:
        """이미지 블럭의 content 를 구성한다.

        Vision 설명 + caption + OCR 텍스트를 결합하여 검색·임베딩 텍스트 생성.
        """
        parts: list[str] = []
        if image_type and image_type != "other":
            parts.append(f"[{image_type}]")
        if caption:
            parts.append(caption)
        if description:
            parts.append(description)
        if ocr_text:
            parts.append(f"텍스트: {ocr_text}")
        return " ".join(parts) if parts else "[이미지]"
