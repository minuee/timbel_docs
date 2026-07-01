"""3단계: 블럭별 상세 처리.

table/image 블럭만 추가 LLM 호출. paragraph는 그대로 통과.
- table: 자연어 해석(table_nl) 강화, 컬럼 타입 분석
- image: Vision 설명 생성 (페이지 이미지에서 해당 영역)
- 모든 블럭: 검색 키워드 추출 (LLM 호출 없이 TF 기반)
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter

from src.common.logging import get_logger
from src.pipeline.stages.llm_client import VisionLLMClient
from src.pipeline.stages.models import DocumentContext, RawBlock

log = get_logger(__name__)

# 병렬 처리 배치 크기
_ENRICH_CONCURRENCY = 5

# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------
_TABLE_ENRICH_PROMPT = """이 표를 분석하세요:
{table_content}

문서 맥락: {doc_type} — "{title}"

JSON으로 반환:
{{"table_nl": "이 표에 따르면...(자연어 해석 3-5문장)", "table_type": "data/comparison/specification/pricing", "column_types": ["text", "numeric", "date"]}}"""

_IMAGE_ENRICH_PROMPT = """이 페이지에서 아래 위치의 이미지를 설명하세요:
{image_context}

문서 맥락: {doc_type} — "{title}"

JSON으로 반환:
{{"description": "이미지 설명 2-3문장", "image_type": "chart/diagram/photo/table/screenshot"}}"""

_CLASSIFY_PROMPT = """블럭을 분류하세요.

문서: {doc_type} — "{title}"
블럭 타입: {block_type}
내용: {content}

JSON으로 반환:
{{
  "nature": "fact/opinion/schedule/record/reference/casual 중 하나",
  "time_reference": {{"raw": "원문 시간표현", "resolved": "ISO날짜", "basis": "근거"}} 또는 {{}},
  "entities": {{"speakers": [], "people": [], "orgs": [], "locations": []}},
  "confidence": 0.0,
  "reasoning": "분류 근거 한 문장"
}}

nature 기준:
- fact: 객관적 사실/수치/결정사항
- opinion: 주관적 의견/평가
- schedule: 일정/계획/마감일
- record: 기록/로그/회의록
- reference: 참조자료/가이드/매뉴얼
- casual: 일상대화/잡담"""

# ---------------------------------------------------------------------------
# 한국어/영어 불용어
# ---------------------------------------------------------------------------
_STOP_WORDS_KO = frozenset(
    [
        "있는", "하는", "되는", "이는", "그는", "것은", "등의", "에서", "으로", "하여",
        "대한", "위한", "통해", "따라", "경우", "때문", "이상", "이하", "이후", "이전",
        "사용", "필요", "가능", "관련", "포함", "제공", "수행", "처리", "설정", "확인",
        "해당", "기본", "전체", "일부", "각각", "아래", "위의", "다음", "이전",
    ]
)

_STOP_WORDS_EN = frozenset(
    [
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "has",
        "her", "was", "one", "our", "out", "with", "this", "that", "from",
        "they", "been", "have", "many", "some", "them", "than", "its",
        "will", "each", "make", "like", "into", "over", "such", "also",
    ]
)


class BlockEnrichment:
    """3단계: 블럭 보강 스테이지."""

    def __init__(self, llm_client: VisionLLMClient) -> None:
        self._client = llm_client

    async def enrich_all(
        self,
        blocks: list[RawBlock],
        page_images: dict[int, bytes],
        context: DocumentContext,
    ) -> list[RawBlock]:
        """블럭 상세 처리. table/image만 추가 LLM 호출.

        Args:
            blocks: 2단계에서 생성된 블럭 리스트.
            page_images: page_num -> PNG 바이트 매핑.
            context: 1단계 문서 이해 결과.

        Returns:
            보강된 블럭 리스트 (in-place 수정).
        """
        # table/image 블럭 중 보강이 필요한 것만 수집
        enrich_tasks: list[tuple[int, RawBlock]] = []
        for idx, block in enumerate(blocks):
            if block.type == "table" and not block.table_nl:
                enrich_tasks.append((idx, block))
            elif block.type == "image" and not block.image_description:
                page_img = page_images.get(block.page)
                if page_img:
                    enrich_tasks.append((idx, block))

        if enrich_tasks:
            log.info("stage3_enrich_start", total_tasks=len(enrich_tasks))

            # 병렬 처리 (최대 _ENRICH_CONCURRENCY개씩)
            for batch_start in range(0, len(enrich_tasks), _ENRICH_CONCURRENCY):
                batch = enrich_tasks[batch_start : batch_start + _ENRICH_CONCURRENCY]
                coros = []
                for _idx, block in batch:
                    if block.type == "table":
                        coros.append(self._enrich_table(block, context))
                    elif block.type == "image":
                        page_img = page_images.get(block.page)
                        if page_img:
                            coros.append(self._enrich_image(block, page_img, context))

                if coros:
                    results = await asyncio.gather(*coros, return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception):
                            log.warning("stage3_enrich_error", error=str(result))

            log.info("stage3_enrich_complete", enriched_count=len(enrich_tasks))

        # 모든 블럭에 키워드 추출 (텍스트만으로, LLM 호출 없이)
        keyword_count = 0
        for block in blocks:
            if block.type not in ("noise", "divider") and not block.keywords:
                block.keywords = self._extract_keywords_simple(block.content)
                if block.keywords:
                    keyword_count += 1

        log.info("stage3_keywords_complete", blocks_with_keywords=keyword_count)

        # 온톨로지 분류 (모든 비-noise 블럭)
        classify_tasks = []
        for block in blocks:
            if block.type not in ("noise", "divider"):
                classify_tasks.append(self._classify_block(block, context))

        if classify_tasks:
            log.info("stage3_classify_start", total_blocks=len(classify_tasks))
            # 배치 처리 (5개씩)
            for i in range(0, len(classify_tasks), _ENRICH_CONCURRENCY):
                batch = classify_tasks[i : i + _ENRICH_CONCURRENCY]
                results = await asyncio.gather(*batch, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        log.warning("stage3_classify_error", error=str(result))
            log.info("stage3_classify_complete", classified_count=len(classify_tasks))

        return blocks

    async def _enrich_table(self, block: RawBlock, context: DocumentContext) -> None:
        """표 블럭 보강: 자연어 해석 + 컬럼 타입 분석."""
        prompt = _TABLE_ENRICH_PROMPT.format(
            table_content=block.content[:3000],  # 표 내용 길이 제한
            doc_type=context.document_type or "문서",
            title=context.title or "제목 없음",
        )

        try:
            raw = await self._client.call(
                prompt=prompt,
                max_tokens=1024,
                temperature=0.1,
            )
            parsed = self._client.parse_json(raw)
            if isinstance(parsed, dict):
                block.table_nl = parsed.get("table_nl", "")
                block.properties["table_type"] = parsed.get("table_type", "")
                block.properties["column_types"] = parsed.get("column_types", [])
                log.debug("stage3_table_enriched", page=block.page, nl_len=len(block.table_nl))
        except Exception as e:
            log.warning("stage3_table_enrich_failed", page=block.page, error=str(e))

    async def _enrich_image(
        self,
        block: RawBlock,
        page_image: bytes,
        context: DocumentContext,
    ) -> None:
        """이미지 블럭 보강: Vision 설명 생성."""
        prompt = _IMAGE_ENRICH_PROMPT.format(
            image_context=block.content[:500] if block.content else "페이지 내 이미지",
            doc_type=context.document_type or "문서",
            title=context.title or "제목 없음",
        )

        try:
            raw = await self._client.call(
                prompt=prompt,
                images=[page_image],
                max_tokens=512,
                temperature=0.1,
            )
            parsed = self._client.parse_json(raw)
            if isinstance(parsed, dict):
                block.image_description = parsed.get("description", "")
                block.properties["image_type"] = parsed.get("image_type", "")
                log.debug(
                    "stage3_image_enriched",
                    page=block.page,
                    desc_len=len(block.image_description),
                )
        except Exception as e:
            log.warning("stage3_image_enrich_failed", page=block.page, error=str(e))

    async def _classify_block(
        self,
        block: RawBlock,
        context: DocumentContext,
    ) -> None:
        """블럭의 온톨로지 분류를 수행한다 (nature, time, entities, categories).

        LLM 호출 실패 시 필드를 빈 값으로 유지한다 (graceful degradation).
        """
        prompt = _CLASSIFY_PROMPT.format(
            doc_type=context.document_type or "문서",
            title=context.title or "제목 없음",
            block_type=block.type,
            content=block.content[:500],
        )

        try:
            raw = await self._client.call(
                prompt=prompt,
                max_tokens=512,
                temperature=0.1,
            )
            parsed = self._client.parse_json(raw)
            if isinstance(parsed, dict):
                _VALID_NATURES = {"fact", "opinion", "schedule", "record", "reference", "casual"}
                nature = parsed.get("nature", "")
                block.nature = nature if nature in _VALID_NATURES else ""

                time_ref = parsed.get("time_reference", {})
                block.time_reference = time_ref if isinstance(time_ref, dict) else {}

                entities = parsed.get("entities", {})
                block.entities = entities if isinstance(entities, dict) else {}

                confidence = parsed.get("confidence", 0.0)
                block.classification_confidence = (
                    float(confidence) if isinstance(confidence, (int, float)) else 0.0
                )

                block.classification_reasoning = str(parsed.get("reasoning", ""))

                log.debug(
                    "stage3_block_classified",
                    page=block.page,
                    nature=block.nature,
                    confidence=block.classification_confidence,
                )
        except Exception as e:
            log.warning("stage3_classify_failed", page=block.page, error=str(e))

    @staticmethod
    def _extract_keywords_simple(text: str, max_keywords: int = 5) -> list[str]:
        """간단한 키워드 추출 (LLM 호출 없이).

        한국어 + 영어 단어 빈도 기반으로 상위 키워드를 추출한다.
        불용어를 제거하고 2글자 이상 단어만 사용.
        """
        if not text or len(text) < 5:
            return []

        # 한국어 2글자 이상 + 영어 3글자 이상 단어 추출
        words = re.findall(r"[가-힣]{2,}|[a-zA-Z]{3,}", text)

        if not words:
            return []

        # 불용어 제거 + 소문자 정규화
        filtered: list[str] = []
        for w in words:
            lower = w.lower()
            if lower in _STOP_WORDS_EN or w in _STOP_WORDS_KO:
                continue
            filtered.append(w)

        if not filtered:
            return []

        # 빈도 기반 상위 키워드
        counter = Counter(filtered)
        # 빈도 1회인 단어 중 긴 단어도 키워드 후보 (고유명사/전문용어)
        candidates = counter.most_common(max_keywords * 2)

        keywords: list[str] = []
        seen: set[str] = set()
        for word, _count in candidates:
            normalized = word.lower()
            if normalized not in seen:
                seen.add(normalized)
                keywords.append(word)
            if len(keywords) >= max_keywords:
                break

        return keywords
