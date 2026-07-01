"""1단계: 문서 전체 이해.

첫 3페이지 이미지를 Vision LLM에 전달하여 문서 전체를 파악한다.
1회 호출로 완료. 결과는 2단계 모든 호출에 전달.
"""

from __future__ import annotations

from src.common.logging import get_logger
from src.pipeline.stages.llm_client import VisionLLMClient
from src.pipeline.stages.models import DocumentContext

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 프롬프트 (간결할수록 JSON 파싱 성공률 높음)
# ---------------------------------------------------------------------------
_STAGE1_PROMPT = """이 문서의 첫 페이지들을 보고 파악하세요.

JSON만 반환:
{"document_type": "매뉴얼/보고서/사양서/단가표/계약서/논문/기타 중 하나", "title": "제목", "core_topic": "주제 1-2문장", "noise_patterns": ["반복되는 불필요 패턴들 (헤더/푸터/페이지번호/워터마크 등)"], "search_scenarios": ["이 문서에서 사용자가 검색할 질문 5개"], "language": "ko 또는 en"}"""

# PPT 전용 프롬프트 — 슬라이드는 순차 의미가 아니라 전체 흐름이 중요하므로
# 전체 슬라이드 샘플을 함께 보고 핵심 주제/구조를 파악한다.
_STAGE1_PPT_PROMPT = """이 PPT 문서의 슬라이드 샘플 전체를 보고 파악하세요.
슬라이드는 순차 의미가 아니라 전체 발표 흐름을 함께 봐야 이해됩니다.

JSON만 반환:
{"document_type": "발표자료/제안서/교육자료/보고서/기타 중 하나", "title": "제목", "core_topic": "전체 발표의 주제 1-2문장", "key_sections": ["주요 섹션/주제 그룹들 (5개 내외)"], "noise_patterns": ["반복되는 장식/페이지번호/회사로고 등"], "search_scenarios": ["이 발표에서 사용자가 검색할 질문 5개"], "language": "ko 또는 en"}"""


class DocumentUnderstanding:
    """1단계: 문서 이해 스테이지."""

    def __init__(self, llm_client: VisionLLMClient) -> None:
        self._client = llm_client

    async def analyze(
        self,
        page_images: list[bytes],
        is_ppt: bool = False,
    ) -> DocumentContext:
        """문서 이해 분석.

        - 일반 문서: 첫 3페이지 이미지로 1회 LLM 호출.
        - PPT (is_ppt=True): 전체 슬라이드 샘플(최대 12장)을 한 번에 분석하여
          전체 발표 맥락을 파악. `key_sections` 가 추가로 채워진다.

        Args:
            page_images: PNG 바이트 리스트.
            is_ppt: PPT 모드 여부.

        Returns:
            DocumentContext: 문서 맥락 정보.
        """
        if not page_images:
            log.warning("stage1_no_images", msg="페이지 이미지가 없어 기본값 반환")
            return DocumentContext()

        # PPT 는 호출 측이 이미 샘플링했으므로 그대로, 일반은 최대 3장.
        images = page_images if is_ppt else page_images[:3]
        prompt = _STAGE1_PPT_PROMPT if is_ppt else _STAGE1_PROMPT

        log.info("stage1_start", image_count=len(images), is_ppt=is_ppt)

        raw = await self._client.call(
            prompt=prompt,
            images=images,
            max_tokens=1024,
        )

        parsed = self._client.parse_json(raw)
        if not isinstance(parsed, dict):
            log.warning("stage1_parse_failed", raw_preview=raw[:300])
            return DocumentContext()

        context = DocumentContext(
            document_type=parsed.get("document_type", ""),
            title=parsed.get("title", ""),
            core_topic=parsed.get("core_topic", ""),
            noise_patterns=parsed.get("noise_patterns", []),
            search_scenarios=parsed.get("search_scenarios", []),
            language=parsed.get("language", "ko"),
        )
        if is_ppt:
            key_sections = parsed.get("key_sections")
            if isinstance(key_sections, list) and key_sections:
                context.key_sections = [str(s) for s in key_sections]

        log.info(
            "stage1_complete",
            document_type=context.document_type,
            title=context.title,
            noise_count=len(context.noise_patterns),
        )
        return context
