"""블럭 PDF bbox 복구 모듈 — LLM + fuzzy 매칭 기반.

블럭의 source_location에 bbox가 없거나 부정확한 경우,
원본 PDF의 word-level bbox 정보와 블럭 내용을 조합하여 위치를 추정한다.

전략:
1. pdfplumber 로 해당 페이지의 단어별 bbox 추출
2. LLM에게 블럭 내용과 페이지 단어 목록을 주고, 시작/끝 단어 인덱스 매칭 요청
3. LLM 실패 시 fuzzy string matching fallback
4. 매칭된 단어 span의 bbox를 합산하여 최종 bbox 계산
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger

logger = get_logger(__name__)

# LLM bbox 매핑 시스템 프롬프트
BBOX_SYSTEM_PROMPT = """당신은 PDF 문서에서 텍스트 위치를 찾는 전문가입니다.
PDF 페이지에서 추출한 단어 목록과 찾아야 할 텍스트가 주어지면,
텍스트가 시작되는 단어 인덱스와 끝나는 단어 인덱스를 찾아야 합니다.

규칙:
- 정확히 일치하지 않더라도 가장 근접한 위치를 찾으세요
- 줄바꿈이나 공백 차이는 무시하세요
- 응답은 반드시 JSON 형식이어야 합니다"""

BBOX_USER_PROMPT_TEMPLATE = """다음 텍스트가 PDF 페이지의 어느 단어부터 어느 단어까지인지 찾아주세요.

## 찾아야 할 텍스트:
{block_content}

## PDF 페이지 단어 목록 (인덱스: 텍스트):
{word_list}

## 응답 형식 (JSON):
{{"start_index": <시작 단어 인덱스>, "end_index": <끝 단어 인덱스>, "confidence": <0.0~1.0>}}"""


class BboxMapper:
    """블럭의 PDF bbox를 복구하는 유틸리티."""

    def close(self) -> None:
        """MinIO 에서 내려받은 임시 원본을 정리한다(엔드포인트 처리 종료 시 호출)."""
        from src.pipeline.storage.source_files import cleanup_temp

        for local_path, is_temp in getattr(self, "_src_cache", {}).values():
            cleanup_temp(local_path, is_temp)
        self._src_cache = {}

    async def recover_bbox(
        self,
        block: Any,
        document: Any,
        db: AsyncSession,
    ) -> Any:
        """블럭의 bbox를 추정하여 source_location에 기록한다.

        Args:
            block: Block ORM 객체
            document: Document ORM 객체
            db: DB 세션

        Returns:
            업데이트된 Block 객체
        """
        source_loc = dict(block.source_location or {})
        page_number = source_loc.get("page_number")

        # 페이지 번호가 없으면 첫 번째 페이지로 시도
        if page_number is None:
            page_number = 1
            source_loc["page_number"] = page_number

        # PDF 파일에서 word-level bbox 추출
        words = await self._extract_page_words(document, page_number)
        if not words:
            logger.warning(
                "bbox_mapper_no_words",
                block_id=str(block.id),
                page_number=page_number,
            )
            return block

        # LLM 매핑 시도
        bbox = await self._llm_match(block.content, words, page_number)

        # LLM 실패 시 fuzzy fallback
        if bbox is None:
            logger.info(
                "bbox_mapper_llm_fallback",
                block_id=str(block.id),
                page_number=page_number,
            )
            bbox = self._fuzzy_match(block.content, words)

        if bbox:
            source_loc["bbox"] = bbox
            block.source_location = source_loc

            # DB 업데이트
            from sqlalchemy import update
            from src.core.models.block import Block as BlockModel

            await db.execute(
                update(BlockModel)
                .where(BlockModel.id == block.id)
                .values(source_location=source_loc)
            )
            await db.commit()

            logger.info(
                "bbox_recovered",
                block_id=str(block.id),
                bbox=bbox,
                page_number=page_number,
            )
        else:
            logger.warning(
                "bbox_recovery_failed_no_match",
                block_id=str(block.id),
                page_number=page_number,
            )

        return block

    async def _extract_page_words(
        self,
        document: Any,
        page_number: int,
    ) -> list[dict]:
        """PDF 파일에서 특정 페이지의 word-level bbox를 추출한다.

        Returns:
            [{"text": str, "x0": float, "top": float, "x1": float, "bottom": float}, ...]
        """
        import asyncio

        source_path = document.source_file
        if not source_path:
            return []

        # 원본을 MinIO 단일 원천에서 로컬로 구체화(로컬 존재 시 그대로).
        # recover_all 은 블럭마다 호출되므로 문서 단위로 1회만 받아 캐시한다.
        # 사용 후 정리는 호출측 엔드포인트가 close() 로 수행한다.
        from src.pipeline.storage.source_files import ext_from, materialize_source

        cache = getattr(self, "_src_cache", None)
        if cache is None:
            cache = {}
            self._src_cache = cache
        ckey = str(getattr(document, "id", "")) or source_path
        if ckey in cache:
            local_path, _is_temp = cache[ckey]
        else:
            try:
                local_path, _is_temp = await materialize_source(
                    source_path,
                    tenant_id=str(getattr(document, "tenant_id", "")),
                    document_id=str(getattr(document, "id", "")),
                    ext=ext_from(None, getattr(document, "source_format", None)),
                )
            except FileNotFoundError:
                local_path, _is_temp = "", False
            cache[ckey] = (local_path, _is_temp)

        if not local_path:
            return []
        file_path = Path(local_path)
        if not file_path.exists():
            return []

        def _extract_sync() -> list[dict]:
            try:
                import pdfplumber

                with pdfplumber.open(str(file_path)) as pdf:
                    if page_number < 1 or page_number > len(pdf.pages):
                        return []
                    page = pdf.pages[page_number - 1]
                    raw_words = page.extract_words(
                        keep_blank_chars=False,
                        extra_attrs=["top", "bottom", "x0", "x1"],
                    )
                    return [
                        {
                            "text": w.get("text", ""),
                            "x0": float(w.get("x0", 0)),
                            "top": float(w.get("top", 0)),
                            "x1": float(w.get("x1", 0)),
                            "bottom": float(w.get("bottom", 0)),
                        }
                        for w in raw_words
                    ]
            except Exception as exc:
                logger.warning("pdfplumber_word_extraction_failed", error=str(exc))
                return []

        return await asyncio.to_thread(_extract_sync)

    async def _llm_match(
        self,
        block_content: str,
        words: list[dict],
        page_number: int,
    ) -> Optional[list[float]]:
        """LLM을 사용하여 블럭 내용과 페이지 단어를 매칭한다.

        Returns:
            bbox [x0, y0, x1, y1] 또는 None
        """
        if not words:
            return None

        # 블럭 내용을 200자로 제한 (프롬프트 크기 관리)
        content_preview = block_content[:500]

        # 단어 목록을 인덱스: 텍스트 형식으로 구성 (최대 300단어)
        word_entries = []
        for i, w in enumerate(words[:300]):
            word_entries.append(f"{i}: {w['text']}")
        word_list_str = "\n".join(word_entries)

        prompt = BBOX_USER_PROMPT_TEMPLATE.format(
            block_content=content_preview,
            word_list=word_list_str,
        )

        try:
            from src.common.llm.router import llm_router
            from src.common.llm.base import LLMRequest, LLMTask

            request = LLMRequest(
                prompt=prompt,
                system_prompt=BBOX_SYSTEM_PROMPT,
                max_tokens=200,
                temperature=0.1,
                response_format="json",
            )
            response = await llm_router.route(
                task=LLMTask.METADATA_EXTRACTION,
                request=request,
            )

            # JSON 파싱
            result = self._parse_llm_response(response.text)
            if result is None:
                return None

            start_idx = result.get("start_index")
            end_idx = result.get("end_index")
            confidence = result.get("confidence", 0.0)

            if start_idx is None or end_idx is None:
                return None

            if confidence < 0.3:
                logger.info(
                    "bbox_llm_low_confidence",
                    confidence=confidence,
                    page_number=page_number,
                )
                return None

            # 인덱스 범위 검증
            start_idx = max(0, min(start_idx, len(words) - 1))
            end_idx = max(start_idx, min(end_idx, len(words) - 1))

            # 단어 span으로부터 bbox 계산
            return self._compute_bbox_from_word_span(words, start_idx, end_idx)

        except Exception as exc:
            logger.warning("bbox_llm_match_failed", error=str(exc))
            return None

    def _parse_llm_response(self, text: str) -> Optional[dict]:
        """LLM 응답에서 JSON을 추출한다."""
        text = text.strip()

        # JSON 블럭 추출
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()

        # { } 블럭 추출
        if "{" in text:
            start = text.index("{")
            end = text.rindex("}") + 1
            text = text[start:end]

        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

    def _fuzzy_match(
        self,
        block_content: str,
        words: list[dict],
    ) -> Optional[list[float]]:
        """Fuzzy string matching 으로 블럭 위치를 추정한다.

        페이지의 전체 텍스트에서 블럭 내용의 시작/끝 위치를 찾고,
        해당 범위의 단어 bbox를 합산한다.
        """
        if not words:
            return None

        # 페이지 텍스트 재구성 (단어 인덱스 매핑)
        page_text_parts = []
        word_char_starts = []
        running_offset = 0

        for w in words:
            word_char_starts.append(running_offset)
            page_text_parts.append(w["text"])
            running_offset += len(w["text"]) + 1  # 공백 포함

        page_text = " ".join(page_text_parts)

        # 블럭 내용의 앞부분으로 매칭 (긴 블럭은 전체 매칭 불필요)
        search_text = block_content[:200].strip()

        # SequenceMatcher로 가장 유사한 부분 찾기
        matcher = SequenceMatcher(None, page_text.lower(), search_text.lower())
        match = matcher.find_longest_match(0, len(page_text), 0, len(search_text))

        if match.size < 10:
            # 매칭 길이가 너무 짧으면 실패
            return None

        # 매칭된 문자 위치 → 단어 인덱스 변환
        match_start_char = match.a
        match_end_char = match.a + match.size

        start_word_idx = 0
        end_word_idx = len(words) - 1

        for i, char_start in enumerate(word_char_starts):
            if char_start <= match_start_char:
                start_word_idx = i
            if char_start <= match_end_char:
                end_word_idx = i

        return self._compute_bbox_from_word_span(words, start_word_idx, end_word_idx)

    def _compute_bbox_from_word_span(
        self,
        words: list[dict],
        start_idx: int,
        end_idx: int,
    ) -> list[float]:
        """단어 span의 bbox를 합산하여 최종 bbox를 계산한다.

        Returns:
            [x0, y0, x1, y1] — PDF pt 단위
        """
        span_words = words[start_idx : end_idx + 1]
        if not span_words:
            return [0, 0, 0, 0]

        x0 = min(w["x0"] for w in span_words)
        y0 = min(w["top"] for w in span_words)
        x1 = max(w["x1"] for w in span_words)
        y1 = max(w["bottom"] for w in span_words)

        return [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]
