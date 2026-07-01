"""LLMBlockSegmenter — LLM 을 사용하여 문서를 의미 완결 블럭으로 분할한다.

specs/06 2A 알고리즘:
1. ParseResult.pages 의 텍스트를 배치로 LLM 에 전달
2. LLM 이 의미 단락 경계를 JSON 으로 반환
3. TableContent → TableBlock (1:1)
4. ImageContent → ImageBlock (1:1)
5. 모든 블럭을 문서 읽기 순서대로 block_index 부여
"""

from __future__ import annotations

import json
import re
from uuid import UUID, uuid4

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType
from src.pipeline.models.document import ProcessingConfig, SourceLocation
from src.pipeline.models.parse_result import PageContent, ParseResult
from src.pipeline.segmenters.base import BaseSegmenter
from src.pipeline.segmenters.fallback_segmenter import FallbackSegmenter

# doc_type slug 변환 (한국어 → 영문 slug)
try:
    from src.pipeline.stages.doc_type_map import to_slug as _to_slug
except ImportError:
    def _to_slug(s: str) -> str:  # type: ignore[misc]
        return "generic"

# ParseMap 타입 힌트용 (optional import — 런타임 의존 없음)
try:
    from src.pipeline.stages.layout_map import ParseMap as _ParseMap
except ImportError:
    _ParseMap = None  # type: ignore[assignment, misc]

log = get_logger(__name__)

# LLM 배치 크기 (한 번에 처리할 페이지 수)
_DEFAULT_BATCH_PAGES = 5


def _detect_document_type(text: str, filename: str = "") -> str:
    """문서 타입 탐지 — 파일명 + 첫 페이지 샘플 기반 휴리스틱.

    Returns: 'faq', 'manual', 'slide', 'report', 'memo', 'generic'
    """
    name_lower = (filename or "").lower()
    text_sample = (text or "")[:3000]

    # 파일명 기반
    if any(k in name_lower for k in ("faq", "q&a", "qna", "자주묻는", "질문", "문답")):
        return "faq"
    if any(k in name_lower for k in ("manual", "guide", "매뉴얼", "가이드", "길라잡이")):
        return "manual"
    if any(k in name_lower for k in ("slide", "presentation", "ppt")):
        return "slide"
    if any(k in name_lower for k in ("report", "보고서", "리포트")):
        return "report"
    if any(k in name_lower for k in ("memo", "메모", "회의록")):
        return "memo"

    # 내용 기반 — Q. 나 질문: 패턴이 3개 이상 연속 출현하면 FAQ
    q_pattern = re.compile(r"^\s*(?:Q\s*[.:]|질문\s*[.:]|문\s*[.:]|Question\s*[.:])", re.MULTILINE | re.IGNORECASE)
    q_count = len(q_pattern.findall(text_sample))
    if q_count >= 3:
        return "faq"

    # 헤딩이 많으면 manual
    h_pattern = re.compile(r"^#+\s|^제\s*\d+\s*[장절편]", re.MULTILINE)
    h_count = len(h_pattern.findall(text_sample))
    if h_count >= 5:
        return "manual"

    return "generic"

# 프롬프트 모듈 임포트 (병렬 작업 중일 수 있으므로 fallback 포함)
try:
    from src.pipeline.prompts.block_segmentation import build_segmentation_prompt
except ImportError:
    log.warning("block_segmentation_prompt_module_not_found_using_fallback")

    def build_segmentation_prompt(text: str, max_tokens: int = 800) -> str:  # noqa: ARG001
        """폴백 프롬프트 -- prompts 모듈이 아직 준비되지 않았을 때 사용."""
        return f"""아래 텍스트를 의미 완결 블럭 단위로 분할하세요.

규칙:
- 하나의 블럭은 하나의 완결된 의미 단위 (한 문단, 한 항목, 한 절차 등)
- 제목/소제목은 독립 블럭으로 분리하고 type 을 heading_1/heading_2/heading_3 으로 지정
- 번호가 매겨진 리스트는 numbered_list, 글머리 기호 리스트는 bulleted_list
- 코드 블럭은 code, 인용은 quote
- 블럭이 {max_tokens}자를 초과하면 자연스러운 지점에서 분할
- 빈 줄이나 공백만 있는 구간은 포함하지 않음

출력: JSON 배열만 반환. 다른 텍스트 없이.
- start: 시작 문자 오프셋 (0-based, inclusive)
- end: 끝 문자 오프셋 (exclusive)
- type: 블럭 타입 (paragraph, heading_1, heading_2, heading_3, bulleted_list, numbered_list, code, quote, callout, to_do, toggle, divider)
- hint: 블럭 내용 한줄 요약
- properties: 추가 속성 객체 (없으면 {{}})

예시:
[{{"start":0,"end":50,"type":"heading_1","hint":"개요","properties":{{}}}},{{"start":51,"end":245,"type":"paragraph","hint":"서론","properties":{{}}}},{{"start":246,"end":580,"type":"numbered_list","hint":"요구사항","properties":{{}}}}]

텍스트:
{text}"""


def _build_text_table_hint(parse_map: object, page_number: int) -> str:
    """LayoutMapper 가 감지한 표/도표 영역을 text 경로 prompt hint 로.

    좌표는 정밀 매칭이 아니라 *해당 페이지에 표/도표가 존재한다는 신호*.
    grid/box 별 좌표계가 다를 수 있음.
    """
    if parse_map is None:
        return ""
    try:
        tables = parse_map.tables_for_page(page_number)  # type: ignore[union-attr]
    except Exception:
        return ""
    if not tables:
        return ""
    lines = []
    for t in tables:
        lines.append(f"- {t.kind} 영역 bbox={t.bbox}")
    return (
        "## 사전 감지된 표/도표 영역 (LayoutMapper)\n"
        "이 페이지에 표/도표 영역이 존재함이 사전 감지됨. 좌표는 위치 참고용 신호.\n"
        "해당 영역은 반드시 table 블럭으로 분할하고, 열(column) 경계를 보존해\n"
        "*열 우선* 으로 markdown 표 생성. 행 우선 flatten 금지.\n"
        + "\n".join(lines) + "\n"
    )


class LLMBlockSegmenter(BaseSegmenter):
    """LLM 기반 의미 블럭 세그멘터.

    LLM 호출 실패 시 FallbackSegmenter 로 자동 전환한다.
    """

    def __init__(
        self,
        config: ProcessingConfig,
        llm_client: object | None = None,
        batch_pages: int = _DEFAULT_BATCH_PAGES,
    ) -> None:
        super().__init__(config)
        self._llm_client = llm_client
        self._batch_pages = batch_pages
        self._fallback = FallbackSegmenter(config)
        # block_boundary_model이 비어있으면 settings에서 가져오기
        if not config.block_boundary_model:
            from src.common.config import settings
            config.block_boundary_model = settings.VLLM_MODEL or "gemma-4-31b"

    async def segment(
        self,
        parse_result: ParseResult,
        *,
        document_id: UUID,
        parse_map: object = None,
        source_file_url: str = "",
        doc_type: str = "",
    ) -> list[BlockObject]:
        """ParseResult → 블럭 목록.

        Parameters
        ----------
        parse_result : ParseResult
        document_id : UUID
        parse_map : ParseMap | None
            LayoutMapper 출력. text 경로 표/도표 hint 주입에 사용.
        source_file_url : str
            SourceLocation.file_url 에 채울 URL. 예: /repos/{rid}/docs/{did}.
        doc_type : str
            Stage1 산출 document_type (한국어 자유 문자열). 비어있으면 내부 휴리스틱으로 탐지.
        """
        # ── 마크다운 구조 FAQ: gemma 우회, 결정적 분할 (정책 A: QnA만) ──
        # 원본에 명시된 `#`/`##`/`###` 구조를 신뢰해 질문=qna_title·답변=content 로 분할.
        # 마크다운 구조 + 질문 레벨 감지(=FAQ)일 때만. 일반/비마크다운은 아래 기존 경로 유지.
        from src.pipeline.segmenters.markdown_faq import (
            detect_question_level,
            is_markdown_structured,
            segment_markdown_text,
        )

        _full_text = "\n".join(p.text for p in parse_result.pages if p.text)
        if is_markdown_structured(_full_text) and detect_question_level(_full_text) is not None:
            log.info(
                "markdown_faq_deterministic_segmentation",
                document_id=str(document_id),
            )
            md_blocks = segment_markdown_text(
                _full_text,
                document_id=document_id,
                source_file_path=parse_result.source_file_path or "",
                source_file_url=source_file_url,
            )
            # 표/이미지는 별도 1:1 매핑(기존 경로와 동일 패턴).
            for page in parse_result.pages:
                for table in page.tables:
                    md_blocks.append(
                        self._fallback._table_to_block(
                            table, document_id, parse_result.source_file_path,
                            source_file_url,
                        )
                    )
                for image in page.images:
                    md_blocks.append(
                        self._fallback._image_to_block(
                            image, document_id, parse_result.source_file_path,
                            source_file_url,
                        )
                    )
            for idx, b in enumerate(md_blocks):
                b.block_index = idx
            return md_blocks

        if self._llm_client is None:
            log.warning("llm_client_not_configured_using_fallback")
            return await self._fallback.segment(
                parse_result, document_id=document_id, source_file_url=source_file_url
            )

        blocks: list[BlockObject] = []

        # ── 문서 레벨 타입 탐지 ──
        # 외부에서 doc_type 이 주어지면 slug 변환 후 사용.
        # 없으면 기존 내부 휴리스틱(_detect_document_type) 으로 탐지.
        sample_pages = parse_result.pages[:3]
        sample_text = "\n\n".join(p.text for p in sample_pages if p.text)[:5000]
        if doc_type:
            detected_doc_type = _to_slug(doc_type)
        else:
            detected_doc_type = _detect_document_type(sample_text, parse_result.source_file_path or "")
        log.info(
            "doc_type_detected",
            doc_type=detected_doc_type,
            source_doc_type_raw=doc_type or "(internal)",
            source_file=parse_result.source_file_path,
            sample_pages=len(sample_pages),
        )
        # 이하 코드에서 doc_type 변수를 detected_doc_type 으로 대체
        doc_type = detected_doc_type

        # FAQ 는 답변이 길어 한 배치에 너무 많이 들어가면 LLM 응답 잘림 → 배치 작게
        effective_batch_pages = self._batch_pages
        if doc_type == "faq":
            effective_batch_pages = max(1, min(2, self._batch_pages))
            log.info("faq_smaller_batches", batch_pages=effective_batch_pages)

        # 페이지를 배치로 묶어 LLM 처리 — 타입은 전체 배치에 동일 적용
        page_batches: list[list[PageContent]] = []
        for i in range(0, len(parse_result.pages), effective_batch_pages):
            page_batches.append(parse_result.pages[i : i + effective_batch_pages])

        for batch in page_batches:
            try:
                text_blocks = await self._segment_batch(
                    batch, document_id, parse_result.source_file_path,
                    doc_type=doc_type,
                    parse_map=parse_map,
                    source_file_url=source_file_url,
                )
                blocks.extend(text_blocks)
            except Exception as exc:
                log.warning(
                    "llm_segmentation_failed_using_fallback",
                    error=str(exc),
                    pages=[p.page_number for p in batch],
                )
                # 해당 배치만 폴백 처리
                fallback_result = ParseResult(
                    pages=batch,
                    source_file_path=parse_result.source_file_path,
                )
                fb_blocks = await self._fallback.segment(
                    fallback_result, document_id=document_id,
                    source_file_url=source_file_url,
                )
                blocks.extend(fb_blocks)

        # 표/이미지 블럭은 전체에서 한 번만 추가 (폴백 사용 시 중복 방지)
        existing_table_indices = {b.source_location.table_index for b in blocks if b.block_type == BlockType.TABLE}
        existing_image_pages = {
            (b.source_location.page_number, b.metadata.get("image_index"))
            for b in blocks if b.block_type == BlockType.IMAGE
        }

        for page in parse_result.pages:
            for table in page.tables:
                if table.table_index not in existing_table_indices:
                    blocks.append(
                        FallbackSegmenter._table_to_block(
                            table, document_id, parse_result.source_file_path,
                            source_file_url,
                        )
                    )
            for image in page.images:
                key = (image.page_number, image.image_index)
                if key not in existing_image_pages:
                    blocks.append(
                        FallbackSegmenter._image_to_block(
                            image, document_id, parse_result.source_file_path,
                            source_file_url,
                        )
                    )

        # block_index 재정렬
        for i, block in enumerate(blocks):
            block.block_index = i

        # ── Q&A 후처리: Q. 로 시작하는 블럭과 이어지는 답변 조각 강제 병합 ──
        # FAQ 문서, 또는 (doc_type 오분류 대비) 실제 Q. 질문이 다수 있는 문서에만 적용한다.
        # generic/약관/manual 등 비-FAQ 문서는 _is_question_block 이 heading 을 질문으로 오탐해
        # 문서 전체를 단일 qna 로 과병합하고 제목을 qna_title 로 흡수(제목/구조 소실)하므로 건너뛴다.
        # 내용 기반 보강(_blocks_have_real_questions)은 heading 을 질문으로 보지 않아 약관은 안전.
        if doc_type == "faq" or _blocks_have_real_questions(blocks):
            blocks = _merge_qna_blocks(blocks)

        # ── BlockVerifier: LLM 기반 블럭 경계 검증 + 헤딩 교정 + 과대 분할 ──
        if self._llm_client is not None and len(blocks) >= 3:
            try:
                from src.pipeline.enrichers.block_verifier import BlockVerifier

                verifier = BlockVerifier()
                blocks = await verifier.run(blocks)
            except Exception as exc:
                log.warning(
                    "block_verifier_failed_skipping",
                    error=str(exc),
                    document_id=str(document_id),
                    block_count=len(blocks),
                )

        log.info(
            "llm_segmentation_complete",
            document_id=str(document_id),
            block_count=len(blocks),
            text_blocks=sum(1 for b in blocks if b.block_type == BlockType.PARAGRAPH),
            table_blocks=sum(1 for b in blocks if b.block_type == BlockType.TABLE),
            image_blocks=sum(1 for b in blocks if b.block_type == BlockType.IMAGE),
        )
        return blocks

    def _make_batches(self, pages: list[PageContent]) -> list[list[PageContent]]:
        """페이지를 배치 크기로 묶는다."""
        batches: list[list[PageContent]] = []
        for i in range(0, len(pages), self._batch_pages):
            batches.append(pages[i : i + self._batch_pages])
        return batches

    async def _segment_batch(
        self,
        pages: list[PageContent],
        document_id: UUID,
        source_file_path: str,
        doc_type: str = "generic",
        parse_map: object = None,
        source_file_url: str = "",
    ) -> list[BlockObject]:
        """한 배치의 페이지를 LLM 으로 세그멘테이션한다."""
        # 페이지 텍스트 결합 (페이지 경계 표시)
        combined_text = ""
        page_offsets: list[tuple[int, int, PageContent]] = []

        for page in pages:
            start = len(combined_text)
            combined_text += page.text
            end = len(combined_text)
            page_offsets.append((start, end, page))
            combined_text += "\n\n"

        combined_text = combined_text.strip()
        if not combined_text:
            return []

        # LLM 호출
        source_text = combined_text[:15000]

        # 배치 내 모든 페이지의 표/도표 hint 수집 (LayoutMapper 사전 감지 결과)
        batch_page_nums = [p.page_number for p in pages]
        table_hint_parts = []
        for pn in batch_page_nums:
            hint = _build_text_table_hint(parse_map, pn)
            if hint:
                table_hint_parts.append(f"[페이지 {pn}]\n{hint}")
        batch_table_hint = "\n".join(table_hint_parts)

        # FAQ 는 markdown pre-split 건너뛰고 직접 LLM 에 풀 텍스트 보냄 (Q&A 그룹핑 보존)
        pre_split = [] if doc_type == "faq" else _markdown_pre_split(source_text)
        if pre_split and len(pre_split) > 1:
            log.debug("markdown_pre_split", sections=len(pre_split))
            items = await self._refine_sections_with_llm(pre_split)
        else:
            prompt = build_segmentation_prompt(
                source_text,
                self.config.block_max_tokens,
                doc_type=doc_type,
                table_hint=batch_table_hint,
            )
            response_text = await self._call_llm(prompt)
            items = self._parse_llm_response(
                response_text, len(combined_text), source_text=source_text
            )

        # 안전망: heading 블럭이 제목+본문을 흡수한 경우 분리(두 경로 공통, audit C9 방어)
        items = _split_heading_with_body(items)

        # content 기반으로 블럭 생성 (오프셋은 find로 재계산)
        blocks: list[BlockObject] = []
        search_cursor = 0  # 원문에서 다음 검색 시작 위치 (중복 매치 방지)
        _MIN_CONTENT_LEN = 10  # 최소 블럭 길이 (이하는 merge/skip)

        noise_skipped = 0
        for item in items:
            content = item.get("content", "").strip()
            if not content:
                continue

            # LLM이 noise로 분류한 블럭은 is_noise 플래그를 달아 보존 (검토용)
            item_type = (item.get("type") or "").lower()
            is_noise_block = item_type == "noise"
            if is_noise_block:
                noise_skipped += 1

            # 너무 짧은 비-노이즈 블럭은 이전 블럭에 병합 (LLM이 실수로 조각낸 경우 복구)
            if not is_noise_block and len(content) < _MIN_CONTENT_LEN and blocks:
                blocks[-1].content = blocks[-1].content + " " + content
                blocks[-1].compute_hash()
                continue

            # 원문에서 content 위치 찾기 (오프셋/페이지 매핑용)
            start_offset = combined_text.find(content, search_cursor)
            if start_offset < 0:
                # 찾지 못하면 cursor 초기화 후 재시도
                start_offset = combined_text.find(content)
            if start_offset < 0:
                start_offset = search_cursor  # 최선 추정값
            end_offset = start_offset + len(content)
            search_cursor = max(search_cursor, end_offset)

            # LLM 응답의 type 문자열을 BlockType enum 으로 변환
            # noise 블럭은 paragraph으로 저장 (is_noise 플래그로 구분)
            if is_noise_block:
                block_type = BlockType.PARAGRAPH
            else:
                block_type = self._map_block_type(item.get("type", "paragraph"))

            # 해당 오프셋이 속하는 페이지 찾기
            page = self._find_page_for_offset(start_offset, page_offsets)
            sl = SourceLocation(
                file_path=source_file_path,
                page_number=page.page_number if page else None,
                start_char_offset=start_offset,
                end_char_offset=end_offset,
                file_url=source_file_url or None,
            )

            # 소스 TextBlock 에서 bbox 상속
            if page:
                for tb in page.text_blocks:
                    if content[:50] in tb.text or tb.text[:50] in content:
                        sl.bbox = tb.bbox
                        sl.paragraph_index = tb.paragraph_index
                        break

            # LLM 이 반환한 properties 를 메타데이터에 병합
            metadata: dict = {"hint": item.get("hint", "")}
            llm_properties = item.get("properties", {})
            if llm_properties:
                metadata["properties"] = llm_properties

            # 노이즈 블럭 플래그
            if is_noise_block:
                metadata["is_noise"] = True
                metadata["noise_reason"] = item.get("reason", "") or item.get("hint", "")

            block = BlockObject(
                id=uuid4(),
                document_id=document_id,
                block_type=block_type,
                content=content,
                block_index=0,
                token_count=len(content),
                source_location=sl,
                metadata=metadata,
            )
            block.compute_hash()
            blocks.append(block)

        if noise_skipped:
            log.info(
                "llm_noise_blocks_preserved",
                document_id=str(document_id),
                noise_count=noise_skipped,
                total=len(blocks),
            )
        return blocks

    async def _call_llm(self, prompt: str) -> str:
        """LLM API 를 호출한다.

        지원 클라이언트:
        1. OpenAI / AsyncOpenAI (vLLM, OpenAI 호환 서버)
        2. (removed — OpenAI-compatible only)
        3. 제네릭 (generate 메서드)
        """
        # OpenAI 호환 (vLLM, Qwen 등)
        try:
            from openai import AsyncOpenAI, OpenAI

            if isinstance(self._llm_client, AsyncOpenAI):
                response = await self._llm_client.chat.completions.create(
                    model=self.config.block_boundary_model,
                    messages=[
                        {"role": "system", "content": "당신은 문서 구조 분석 전문가입니다. JSON만 출력하세요."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=8000,
                )
                return _strip_thinking(response.choices[0].message.content or "")

            if isinstance(self._llm_client, OpenAI):
                import asyncio

                response = await asyncio.to_thread(
                    self._llm_client.chat.completions.create,
                    model=self.config.block_boundary_model,
                    messages=[
                        {"role": "system", "content": "당신은 문서 구조 분석 전문가입니다. JSON만 출력하세요."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=8000,
                )
                return _strip_thinking(response.choices[0].message.content or "")
        except ImportError:
            pass


        # 제네릭
        if hasattr(self._llm_client, "generate"):
            return await self._llm_client.generate(prompt)  # type: ignore[union-attr]

        raise RuntimeError("LLM 클라이언트를 지원하지 않습니다 (OpenAI/Anthropic/generate)")

    @staticmethod
    def _parse_llm_response(response: str, text_length: int, source_text: str = "") -> list[dict]:
        """LLM 응답을 파싱하여 블럭 목록을 반환한다.

        v2.0.0: content 직접 반환 방식 (offset 계산 오류 해결).
        이전 버전 호환: start/end 필드도 있으면 사용.
        """
        cleaned = response.strip()
        if "```" in cleaned:
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]

        try:
            items = json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("llm_response_json_parse_failed", response=cleaned[:200])
            return [{
                "content": source_text[:text_length] if source_text else "",
                "hint": "전체",
                "type": "paragraph",
                "properties": {},
            }]

        if not isinstance(items, list):
            return [{
                "content": source_text[:text_length] if source_text else "",
                "hint": "전체",
                "type": "paragraph",
                "properties": {},
            }]

        valid: list[dict] = []
        for b in items:
            if not isinstance(b, dict):
                continue

            # v2.0.0: content 직접 반환 방식 우선
            content = b.get("content")
            if isinstance(content, str) and content.strip():
                valid.append({
                    "content": content.strip(),
                    "hint": b.get("hint", ""),
                    "type": b.get("type", "paragraph"),
                    "properties": b.get("properties", {}),
                })
                continue

            # 하위 호환: start/end offset 방식 (이전 응답)
            start = b.get("start")
            end = b.get("end")
            if isinstance(start, int) and isinstance(end, int) and end > start and source_text:
                extracted = source_text[start : min(end, text_length)].strip()
                if extracted:
                    valid.append({
                        "content": extracted,
                        "hint": b.get("hint", ""),
                        "type": b.get("type", "paragraph"),
                        "properties": b.get("properties", {}),
                    })

        if valid:
            return valid

        # 완전 실패 시 전체를 한 블럭으로
        return [{
            "content": source_text[:text_length] if source_text else "",
            "hint": "전체",
            "type": "paragraph",
            "properties": {},
        }]

    async def _refine_sections_with_llm(self, sections: list[dict]) -> list[dict]:
        """Pre-split된 섹션의 타입을 LLM으로 분류한다.

        각 섹션의 content는 구조적으로 올바르게 분할되어 있고,
        LLM은 type 분류 + hint만 보강한다.
        """
        # 섹션이 적으면 일괄 처리, 많으면 배치 처리
        sections_to_classify = [
            s for s in sections
            if s.get("type") == "paragraph" and len(s["content"]) > 20
        ]

        if not sections_to_classify:
            return sections

        # 타입 분류 전용 경량 프롬프트
        section_list = "\n\n".join([
            f"[{i}] {s['content'][:300]}"
            for i, s in enumerate(sections_to_classify)
        ])

        prompt = f"""다음 텍스트 섹션들의 블럭 타입을 분류하세요.

타입 옵션: paragraph, heading_1, heading_2, heading_3, bulleted_list, numbered_list, to_do, code, quote, callout, divider

각 섹션은 이미 구조적으로 분할되어 있습니다. 내용을 수정하지 말고 타입만 분류하세요.

## 섹션들

{section_list}

JSON 배열로 반환:
[{{"index": 0, "type": "heading_1", "hint": "제목"}}, ...]"""

        try:
            response = await self._call_llm(prompt)
            cleaned = response.strip()
            if "```" in cleaned:
                s = cleaned.find("[")
                e = cleaned.rfind("]")
                if s >= 0 and e > s:
                    cleaned = cleaned[s : e + 1]
            type_assignments = json.loads(cleaned)

            # 분류 결과를 sections_to_classify에 매핑
            for assignment in type_assignments:
                if not isinstance(assignment, dict):
                    continue
                idx = assignment.get("index")
                if not isinstance(idx, int) or idx >= len(sections_to_classify):
                    continue
                sections_to_classify[idx]["type"] = assignment.get("type", "paragraph")
                sections_to_classify[idx]["hint"] = assignment.get("hint", "")
        except Exception as exc:
            log.warning("section_type_classification_failed", error=str(exc))

        return sections

    @staticmethod
    def _map_block_type(type_str: str) -> BlockType:
        """LLM 응답의 type 문자열을 BlockType enum 으로 매핑한다."""
        try:
            return BlockType(type_str)
        except ValueError:
            # 호환성: 이전 "text" → PARAGRAPH
            if type_str == "text":
                return BlockType.PARAGRAPH
            log.warning("unknown_block_type_falling_back_to_paragraph", type_str=type_str)
            return BlockType.PARAGRAPH

    @staticmethod
    def _find_page_for_offset(
        offset: int,
        page_offsets: list[tuple[int, int, PageContent]],
    ) -> PageContent | None:
        """문자 오프셋이 속하는 페이지를 찾는다."""
        for start, end, page in page_offsets:
            if start <= offset < end:
                return page
        return page_offsets[-1][2] if page_offsets else None


def _markdown_pre_split(text: str) -> list[dict]:
    """마크다운/텍스트를 구조 기반으로 사전 분할한다.

    헤딩, 코드블럭, 체크리스트, 리스트 경계를 존중하며 분할.
    LLM은 타입 분류만 담당.

    Returns:
        [{"content": "...", "type": "heading_1", "hint": "..."}, ...]
    """
    import re

    if not text or not text.strip():
        return []

    sections: list[dict] = []
    lines = text.split("\n")
    current_lines: list[str] = []
    current_type: str | None = None
    in_code_block = False
    code_fence = ""

    def _flush() -> None:
        """현재 버퍼를 섹션으로 플러시."""
        nonlocal current_lines, current_type
        if not current_lines:
            return
        content = "\n".join(current_lines).strip()
        if content:
            sections.append({
                "content": content,
                "type": current_type or "paragraph",
                "hint": "",
                "properties": {},
            })
        current_lines = []
        current_type = None

    for line in lines:
        stripped = line.strip()

        # 코드블럭 처리 (``` 또는 ~~~)
        fence_match = re.match(r"^(```|~~~)", stripped)
        if fence_match:
            if in_code_block and fence_match.group(1) == code_fence:
                # 코드블럭 종료
                current_lines.append(line)
                _flush()
                in_code_block = False
                code_fence = ""
                continue
            elif not in_code_block:
                # 코드블럭 시작 — 이전 내용 플러시
                _flush()
                in_code_block = True
                code_fence = fence_match.group(1)
                current_type = "code"
                current_lines.append(line)
                continue

        if in_code_block:
            current_lines.append(line)
            continue

        # 헤딩 인식 (# 로 시작)
        heading_match = re.match(r"^(#{1,6})\s+(.+)", stripped)
        if heading_match:
            _flush()
            level = len(heading_match.group(1))
            current_type = f"heading_{min(level, 3)}"
            current_lines = [line]
            _flush()
            continue

        # 불릿 섹션 헤더 인식 (■ ▶ ● ◆ ▪ ○ 등 으로 시작하는 짧은 제목 라인)
        # 예: "■ Wafer Lapping :" "▶ 개요" "● 목차"
        # 조건: 특수 불릿 + 공백 + 내용(80자 이내) → 섹션 구분 헤더로 간주
        bullet_heading = re.match(
            r"^[■▶●◆▪○□◇※✔✓▲▼→\u2022]\s+(.{1,80})$",
            stripped,
        )
        if bullet_heading:
            _flush()
            current_type = "heading_3"
            current_lines = [line]
            _flush()
            continue

        # 구분선 (--- ***)
        if re.match(r"^(-{3,}|\*{3,}|_{3,}|={3,})$", stripped):
            _flush()
            current_type = "divider"
            current_lines = [line]
            _flush()
            continue

        # 인용 (> 로 시작)
        if stripped.startswith(">"):
            if current_type != "quote":
                _flush()
                current_type = "quote"
            current_lines.append(line)
            continue

        # 체크리스트 ([ ] [x] 포함)
        checkbox = re.match(r"^[-*+]\s+\[[ xX]\]\s+", stripped)
        if checkbox:
            if current_type != "to_do":
                _flush()
                current_type = "to_do"
            current_lines.append(line)
            continue

        # 순서 목록 (1. 2. ...)
        if re.match(r"^\d+\.\s+", stripped):
            if current_type != "numbered_list":
                _flush()
                current_type = "numbered_list"
            current_lines.append(line)
            continue

        # 비순서 목록 (- * +)
        if re.match(r"^[-*+]\s+", stripped):
            if current_type != "bulleted_list":
                _flush()
                current_type = "bulleted_list"
            current_lines.append(line)
            continue

        # 빈 줄 — 섹션 경계
        if not stripped:
            if current_lines:
                _flush()
            continue

        # 일반 텍스트 (paragraph)
        if current_type not in (None, "paragraph"):
            _flush()
        current_type = "paragraph"
        current_lines.append(line)

    _flush()

    # 1) 헤딩 자동 병합: 헤딩 + 다음 콘텐츠를 하나의 블럭으로 합침
    # 헤딩만 단독 블럭이면 검색에 노이즈가 됨 (의미 정보 부족)
    # 결과 블럭 타입은 콘텐츠 타입을 따름 (heading_2 + numbered_list → numbered_list)
    _HEADING_TYPES = {"heading_1", "heading_2", "heading_3", "heading_4", "heading_5", "heading_6"}
    _MIN_BLOCK_LEN = 50  # 최소 블럭 길이 (이하면 다음 콘텐츠와 병합)

    merged_with_heading: list[dict] = []
    pending_heading: dict | None = None  # 병합 대기 중인 헤딩

    for s in sections:
        if s["type"] in _HEADING_TYPES:
            # 이전에 대기 중이던 헤딩이 있으면 그대로 쌓아둠 (예: # 제목 + ## 부제목)
            if pending_heading:
                # 헤딩끼리 만나면 이전 헤딩은 단독으로 추가 (다음 콘텐츠 없음)
                # 단, 이전 헤딩 길이가 30자 이상이면 단독 유지, 짧으면 합침
                if len(pending_heading["content"]) >= 30:
                    merged_with_heading.append(pending_heading)
                    pending_heading = s
                else:
                    # 두 헤딩을 묶어 새 헤딩으로 (level은 작은 쪽 유지)
                    pending_heading["content"] += "\n" + s["content"]
                    # 더 깊은 level을 채택 (heading_2 + heading_3 → heading_3)
                    if int(s["type"][-1]) > int(pending_heading["type"][-1]):
                        pending_heading["type"] = s["type"]
            else:
                pending_heading = s
        elif s["type"] == "divider":
            # 구분선은 헤딩 병합 흐름을 끊음
            if pending_heading:
                merged_with_heading.append(pending_heading)
                pending_heading = None
            merged_with_heading.append(s)
        else:
            # 콘텐츠 블럭: 대기 중인 헤딩과 병합
            if pending_heading:
                heading_text = pending_heading["content"]
                content_text = s["content"]
                merged_block = {
                    "content": f"{heading_text}\n\n{content_text}",
                    "type": s["type"],  # 콘텐츠 타입을 우선 (검색용)
                    "hint": pending_heading.get("hint", "") or s.get("hint", ""),
                    "properties": {
                        **s.get("properties", {}),
                        "merged_from_heading": pending_heading["type"],
                        "heading_text": heading_text,
                    },
                }
                merged_with_heading.append(merged_block)
                pending_heading = None
            else:
                merged_with_heading.append(s)

    # 마지막에 남은 헤딩 (콘텐츠 없이 끝난 경우)
    if pending_heading:
        merged_with_heading.append(pending_heading)

    # 2) 너무 짧은 블럭 추가 병합 (50자 미만은 다음 블럭과 합침)
    final_merged: list[dict] = []
    for s in merged_with_heading:
        # 보호 타입은 유지 (구분선)
        if s["type"] == "divider":
            final_merged.append(s)
            continue
        # 짧은 블럭 + 직전 블럭 같은 타입 → 병합
        if (
            len(s["content"]) < _MIN_BLOCK_LEN
            and final_merged
            and final_merged[-1]["type"] == s["type"]
            and final_merged[-1]["type"] != "divider"
        ):
            final_merged[-1]["content"] += "\n" + s["content"]
        else:
            final_merged.append(s)

    return final_merged


# heading 블럭이 "제목 줄 + 이어지는 본문"을 하나로 흡수한 경우 분리하는 안전망.
# LLM(gemma) 세그멘터가 프롬프트 규칙8을 오해해 문서 제목과 첫 단락을 한 heading
# 블럭으로 묶는 사례가 재발한다(heading_propagator audit C9). 프롬프트 수정(규칙8 명확화)이
# 근본이지만 LLM 비결정성을 결정적으로 방어하기 위한 후처리.
_HEADING_TYPES_LITERAL = {
    "heading_1", "heading_2", "heading_3", "heading_4", "heading_5", "heading_6",
}
_HEADING_BODY_MIN = 30   # 제목 뒤 본문이 이 길이 이상이면 분리(짧은 다줄 제목은 보존)
_HEADING_FIRST_MAX = 80  # 첫 줄이 이보다 길면 제목이 아니라 본문 오라벨 → 분리하지 않음


def _split_heading_with_body(items: list[dict]) -> list[dict]:
    """heading 타입 블럭이 본문을 흡수했으면 heading + paragraph 로 분리한다.

    조건: 타입이 heading_* 이고, content 가 여러 줄이며, 첫 줄(제목)이 짧고
    (<= _HEADING_FIRST_MAX), 첫 줄 뒤 본문이 실질적(>= _HEADING_BODY_MIN)일 때.
    제목은 첫 줄만 heading 으로 남기고 나머지를 paragraph 블럭으로 분리한다.
    """
    result: list[dict] = []
    for item in items:
        itype = (item.get("type") or "").lower()
        content = item.get("content", "") or ""
        if itype in _HEADING_TYPES_LITERAL and "\n" in content:
            first_line, _, rest = content.partition("\n")
            first_line = first_line.strip()
            rest = rest.strip()
            if (
                rest
                and len(rest) >= _HEADING_BODY_MIN
                and 0 < len(first_line) <= _HEADING_FIRST_MAX
            ):
                heading_item = {**item, "content": first_line}
                body_item = {"content": rest, "type": "paragraph", "hint": item.get("hint", "")}
                result.append(heading_item)
                result.append(body_item)
                continue
        result.append(item)
    return result


def _strip_thinking(text: str) -> str:
    """Qwen 모델의 thinking 출력을 제거한다.

    처리 패턴:
    1. <think>...</think> 태그 (정상)
    2. <think>... (닫는 태그 없이 잘린 경우)
    3. "Thinking Process:" 텍스트 형태 (태그 없이 출력되는 경우)
    """
    import re

    # 1. <think>...</think> 태그
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    # 2. 닫는 태그 없이 잘린 경우
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL)
    # 3. "Thinking Process:" 텍스트 패턴 (JSON/실제 답변 이전의 사고 과정)
    # JSON 배열이나 실제 답변이 시작되는 지점을 찾아 그 앞을 제거
    if "Thinking Process:" in text or "Thinking process:" in text:
        # JSON 시작 지점 찾기
        for marker in ("[", "{", "```"):
            idx = text.find(marker)
            if idx > 0:
                text = text[idx:]
                break
        else:
            # JSON 마커 없으면 마지막 빈 줄 이후를 실제 답변으로 간주
            parts = text.split("\n\n")
            # 마지막 비어있지 않은 파트를 답변으로
            for i in range(len(parts) - 1, -1, -1):
                if parts[i].strip() and not parts[i].strip().startswith("Thinking"):
                    text = "\n\n".join(parts[i:])
                    break

    return text.strip()


# ─────────────────────────────────────────────────────────────────────
# Q&A 후처리: FAQ 문서의 Q/A 쌍을 하나의 블럭으로 강제 병합
# ─────────────────────────────────────────────────────────────────────
_QNA_Q_PATTERN = re.compile(
    r"^\s*(?:Q\s*[.:]|질문\s*[.:]|문\s*[.:]|Question\s*[.:])",
    re.IGNORECASE,
)
_QNA_CATEGORY_PATTERN = re.compile(
    r"^\s*\d+\s*\.\s+[가-힣A-Za-z]",  # "1. 주식", "2. 계좌개설"
)
# 마크다운 헤딩 라인("### 질문") — 끝 구두점(?/./없음) 무관. FAQ 가 "Q."/"질문:" 접두사 없이
# "### 질문" 헤딩만 쓰는 경우를 Q&A 시작으로 인식한다.
_QNA_HEADING_PATTERN = re.compile(r"^\s*#{1,6}\s+\S")


def _is_qna_question_start(content: str) -> bool:
    """블럭 content 가 Q. 패턴 또는 마크다운 헤딩("### ...")으로 시작하는지."""
    first_line = content.strip().split("\n", 1)[0] if content else ""
    return bool(_QNA_Q_PATTERN.match(first_line) or _QNA_HEADING_PATTERN.match(first_line))


def _blocks_have_real_questions(blocks: list, min_count: int = 2) -> bool:
    """블럭들에 '실제 질문'(Q./질문:/문:/Question:) 으로 시작하는 블럭이 min_count 개 이상인지.

    내용 기반 qna 후처리 게이트용. doc_type 자동분류가 FAQ 를 놓쳐도 실제 Q&A 내용이면
    병합을 허용한다. **heading 은 질문으로 보지 않는다** — heading 을 질문으로 오탐하던 것이
    generic 약관(조문 heading) 과병합의 원인이었기 때문. 첫 매치 누적으로 조기 종료(저비용).
    """
    count = 0
    for b in blocks:
        content = getattr(b, "content", "") or ""
        first_line = content.strip().split("\n", 1)[0] if content else ""
        if _QNA_Q_PATTERN.match(first_line):
            count += 1
            if count >= min_count:
                return True
    return False


def _is_question_block(block) -> bool:
    """블럭이 Q&A 질문 시작인지 — content 패턴(Q./### …) 또는 블럭 타입이 heading 인 경우.

    파서가 "### 질문" 을 heading 타입으로 변환하며 content 에서 ### 를 떼어내는 경우(평문 질문,
    물음표/마침표 무관)도 잡기 위해 블럭 타입으로도 판정한다.
    """
    content = getattr(block, "content", "") or ""
    if _is_qna_question_start(content):
        return True
    bt = getattr(block, "block_type", None)
    bt_name = (getattr(bt, "name", "") or str(bt or "")).upper()
    return "HEADING" in bt_name


def _clean_qna_title(text: str) -> str:
    """질문 헤딩 첫 줄에서 마크다운 헤더 마커(###)를 제거해 깔끔한 제목(질문)을 만든다."""
    first_line = (text or "").strip().split("\n", 1)[0].strip()
    return re.sub(r"^#{1,6}\s*", "", first_line).strip()


def _is_category_heading(content: str) -> bool:
    """카테고리 제목인지 (Q&A 병합 경계)."""
    stripped = (content or "").strip()
    if len(stripped) > 50:  # 카테고리는 짧음
        return False
    return bool(_QNA_CATEGORY_PATTERN.match(stripped))


def _split_block_on_qna_patterns(content: str) -> list[tuple[str, str]]:
    """블럭 내부에 여러 Q. 패턴이 있으면 분리. (type, content) 튜플 리스트 반환.

    반환 타입: 'heading' (카테고리 제목), 'qna' (Q+A), 'text' (기타)
    """
    if not content:
        return []

    lines = content.split("\n")
    result: list[tuple[str, str]] = []
    current_type = None
    current_buf: list[str] = []

    def flush():
        if current_buf:
            joined = "\n".join(current_buf).strip()
            if joined:
                result.append((current_type or "text", joined))

    for line in lines:
        stripped = line.strip()
        # Q. 또는 ### 헤딩 질문 시작
        if _QNA_Q_PATTERN.match(stripped) or _QNA_HEADING_PATTERN.match(stripped):
            flush()
            current_buf = [line]
            current_type = "qna"
        # 카테고리 제목 ("1. 주식" 같은 짧은 줄)
        elif _QNA_CATEGORY_PATTERN.match(stripped) and len(stripped) <= 50 and current_type != "qna":
            flush()
            current_buf = [line]
            current_type = "heading"
            flush()
            current_buf = []
            current_type = None
        # 카테고리 제목이 qna 중간에 나오면 qna 종결
        elif _QNA_CATEGORY_PATTERN.match(stripped) and len(stripped) <= 50 and current_type == "qna":
            flush()
            current_buf = [line]
            current_type = "heading"
            flush()
            current_buf = []
            current_type = None
        else:
            if current_type is None:
                current_type = "text"
            current_buf.append(line)

    flush()
    return result


def _merge_qna_blocks(blocks: list) -> list:
    """FAQ Q&A 병합 + 블럭 내부 여러 Q. 패턴 있으면 분리.

    2 단계:
    1. 먼저 각 블럭의 content 내부에 여러 Q. 가 있으면 분리
    2. 그 다음 인접 Q-시작 블럭 + 답변 블럭 병합
    """
    if not blocks:
        return blocks

    try:
        from src.pipeline.models.block import BlockType
    except ImportError:
        return blocks

    import copy as _copy
    import hashlib

    # ── Phase 1: 블럭 내부 Q. 분리 ──
    expanded: list = []
    for b in blocks:
        content = getattr(b, "content", "") or ""
        btype = getattr(b, "block_type", None)

        # table/image/code 는 분리하지 않음
        if btype in (BlockType.TABLE, BlockType.IMAGE, BlockType.CODE, BlockType.DIVIDER):
            expanded.append(b)
            continue

        # 내부에 Q. 또는 ### 헤딩 질문 개수 세기 (한 블럭에 여러 Q&A 가 묶인 경우 분리 대상)
        q_count = len(re.findall(r"(?:^|\n)\s*(?:Q\s*[.:]|질문\s*[.:]|문\s*[.:])",
                                 content, re.IGNORECASE))
        q_count += sum(1 for _ln in content.split("\n") if _QNA_HEADING_PATTERN.match(_ln.strip()))
        # Q 가 하나 이하면 그대로
        if q_count <= 1 and btype != BlockType.QNA:
            expanded.append(b)
            continue
        # Q 가 하나 이하지만 이미 qna 타입이면 그대로
        if q_count <= 1 and btype == BlockType.QNA:
            expanded.append(b)
            continue

        # 분리
        parts = _split_block_on_qna_patterns(content)
        if len(parts) <= 1:
            expanded.append(b)
            continue

        log.info("qna_block_split", original_id=str(getattr(b, "id", "")),
                 original_q_count=q_count, split_parts=len(parts))

        for ptype, ptext in parts:
            new_b = _copy.copy(b)
            new_b.content = ptext
            # #79 fix — source_location 깊은 복사. shallow copy 시 모든 split 블럭이
            # 같은 SourceLocation 인스턴스를 공유해 block_worker:1510 의
            # `page_number += page_offset` 가 N 회 누적 적용되어 page_number 가
            # 4-10x 부풀어 색인됨 (예: PDF p.73 → page=253).
            if new_b.source_location is not None:
                try:
                    new_b.source_location = new_b.source_location.model_copy(deep=True)
                except Exception:
                    new_b.source_location = _copy.deepcopy(new_b.source_location)
            if ptype == "qna":
                new_b.block_type = BlockType.QNA
            elif ptype == "heading":
                new_b.block_type = BlockType.HEADING_1
            else:
                # text: 원본 타입 유지 (paragraph 등)
                pass
            new_b.block_hash = hashlib.sha256(ptext.encode("utf-8")).hexdigest()
            # 새 ID 생성 (중복 방지)
            try:
                from uuid import uuid4
                new_b.id = uuid4()
            except Exception:
                pass
            expanded.append(new_b)

    # ── Phase 2: 인접 Q-시작 + 답변 블럭 병합 ──
    merged: list = []
    i = 0
    n = len(expanded)

    while i < n:
        b = expanded[i]
        content = getattr(b, "content", "") or ""

        if not _is_question_block(b):
            merged.append(b)
            i += 1
            continue

        # 질문 블럭 발견 → 질문(qna_title)과 다음 질문 전까지의 답변(content)을 1개 QNA 블럭으로.
        question_title = _clean_qna_title(content)
        answer_parts: list[str] = []
        # 질문 블럭 content 에 첫 줄(질문) 뒤 본문이 함께 있으면(예: "### 질문\n\n도입문") 답변으로 편입.
        _split = content.strip().split("\n", 1)
        if len(_split) > 1 and _split[1].strip():
            answer_parts.append(_split[1].strip())

        j = i + 1
        while j < n:
            next_b = expanded[j]
            next_content = getattr(next_b, "content", "") or ""

            next_type = getattr(next_b, "block_type", None)
            if next_type in (BlockType.TABLE, BlockType.IMAGE):
                break
            # 다음 질문/섹션(### heading 또는 heading 타입)에서만 끊는다. 카테고리 경계는
            # _is_question_block(heading)이 처리하므로, 짧은 번호 답변 항목("2. …")을
            # 카테고리로 오탐해 답변 병합이 중간에 끊기지 않도록 _is_category_heading break 는 쓰지 않는다.
            if _is_question_block(next_b):
                break

            answer_parts.append(next_content)
            j += 1

        # 질문 = metadata.qna_title (1곳에만 저장 → 중복 없음), content = 답변 전체(병합).
        answer_content = "\n\n".join(p.strip() for p in answer_parts if p.strip())
        b.content = answer_content if answer_content else question_title
        if b.metadata is None:
            b.metadata = {}
        b.metadata["qna_title"] = question_title
        b.block_type = BlockType.QNA if hasattr(BlockType, "QNA") else b.block_type
        try:
            b.block_hash = hashlib.sha256((b.content or "").encode("utf-8")).hexdigest()
        except Exception:
            pass

        if b.source_location is not None and j > i + 1:
            last_answer = expanded[j - 1]
            last_sl = getattr(last_answer, "source_location", None)
            if last_sl is not None and last_sl.end_char_offset is not None:
                b.source_location.end_char_offset = last_sl.end_char_offset

        merged.append(b)
        i = j

    # block_index 재정렬
    for idx, blk in enumerate(merged):
        blk.block_index = idx

    log.info(
        "qna_postprocess_applied",
        before_phase1=len(blocks),
        after_phase1=len(expanded),
        after_phase2=len(merged),
    )
    return merged
