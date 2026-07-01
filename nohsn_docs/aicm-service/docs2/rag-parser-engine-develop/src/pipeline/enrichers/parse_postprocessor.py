"""LLM 기반 PDF 파싱 후처리기.

PDF 파서 출력을 LLM으로 정제한다:
1. 노이즈 제거 (헤더/푸터/페이지번호/워터마크)
2. 줄바꿈/페이지 경계 단어 분리 복원
3. 멀티컬럼 읽기 순서 재정렬

Phase 2 Task — Pipeline Quality 향상.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from copy import deepcopy
from typing import Optional

from src.common.logging import get_logger
from src.pipeline.models.parse_result import PageContent, ParseResult, TextBlock

log = get_logger(__name__)

# 동시 LLM 호출 제한 (페이지 병렬 처리용)
_MAX_CONCURRENT_PAGES = 1

# Redis 캐시 TTL (초) — 동일 페이지 텍스트 재처리 방지
_CACHE_TTL_SECONDS = 86400  # 1일

# 노이즈 제거 최소 confidence 임계값
_NOISE_CONFIDENCE_THRESHOLD = 0.6

# 단어 분리 복원 최소 confidence 임계값
_WORD_FIX_CONFIDENCE_THRESHOLD = 0.8

# 컬럼 재정렬 최소 confidence 임계값
_REORDER_CONFIDENCE_THRESHOLD = 0.7

# 후처리 적용 최소 페이지 수 (이하일 경우 스킵)
_MIN_PAGES_FOR_LLM = 3


class ParsePostprocessor:
    """LLM 기반 PDF 파싱 후처리기.

    ParseResult를 입력받아 노이즈 제거, 단어 복원, 컬럼 재정렬을 수행하고
    정제된 ParseResult를 반환한다.

    성능 최적화:
    - 페이지별 병렬 처리 (semaphore=4)
    - Redis 해시 기반 캐싱 (1일 TTL)
    - confidence 임계값 미달 시 원본 유지
    """

    async def process(self, parse_result: ParseResult) -> ParseResult:
        """전체 후처리 파이프라인을 실행한다.

        순서: 노이즈 제거 → 단어 분리 복원 → 컬럼 재정렬

        Args:
            parse_result: 파서 출력 결과.

        Returns:
            정제된 ParseResult. 실패 시 원본을 그대로 반환.
        """
        page_count = len(parse_result.pages)
        if page_count < _MIN_PAGES_FOR_LLM:
            log.info(
                "parse_postprocessor_skipped",
                reason="too_few_pages",
                page_count=page_count,
                threshold=_MIN_PAGES_FOR_LLM,
            )
            return parse_result

        log.info("parse_postprocessor_start", page_count=page_count)

        result = parse_result

        # Step 1: 노이즈 제거
        result = await self.clean_pages(result)

        # Step 2: 단어 분리 복원
        result = await self.fix_word_breaks(result)

        # Step 3: 멀티컬럼 재정렬
        result = await self.reorder_columns(result)

        log.info("parse_postprocessor_complete", page_count=page_count)
        return result

    # ------------------------------------------------------------------
    # Step 1: 노이즈 제거
    # ------------------------------------------------------------------

    async def clean_pages(self, parse_result: ParseResult) -> ParseResult:
        """LLM으로 각 페이지의 노이즈(헤더/푸터/페이지번호 등)를 식별하여 제거한다.

        Args:
            parse_result: 파서 출력 결과.

        Returns:
            노이즈가 제거된 ParseResult. 원본 텍스트는 page.metadata에 보존.
        """
        result = deepcopy(parse_result)
        sem = asyncio.Semaphore(_MAX_CONCURRENT_PAGES)
        total_removed = 0

        async def _clean_one_page(page: PageContent) -> int:
            """단일 페이지 노이즈 제거. 제거된 라인 수를 반환한다."""
            nonlocal total_removed
            async with sem:
                if not page.text.strip():
                    return 0

                try:
                    noise_lines = await self._identify_noise(
                        page.text, page.page_number
                    )
                    if not noise_lines:
                        return 0

                    removed = self._apply_noise_removal(page, noise_lines)
                    return removed
                except Exception as exc:
                    log.warning(
                        "page_noise_removal_failed",
                        page_number=page.page_number,
                        error=str(exc),
                    )
                    return 0

        tasks = [_clean_one_page(page) for page in result.pages]
        removed_counts = await asyncio.gather(*tasks)
        total_removed = sum(removed_counts)

        # raw_text 재구성
        if total_removed > 0:
            result.raw_text = "\n\n".join(
                page.text for page in result.pages if page.text.strip()
            )

        log.info(
            "clean_pages_complete",
            pages_processed=len(result.pages),
            total_lines_removed=total_removed,
        )
        return result

    async def _identify_noise(
        self, page_text: str, page_number: int
    ) -> list[str]:
        """LLM을 호출하여 노이즈 라인을 식별한다. 캐시를 먼저 확인한다."""
        # 캐시 확인
        cache_key = self._make_cache_key("noise", page_text)
        cached = await self._get_cache(cache_key)
        if cached is not None:
            log.debug("noise_cache_hit", page_number=page_number)
            return cached

        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router
        from src.pipeline.prompts.parse_postprocessor import (
            build_noise_removal_prompt,
        )

        prompt = build_noise_removal_prompt(page_text, page_number)
        request = LLMRequest(
            prompt=prompt,
            system_prompt="PDF 문서 노이즈 식별 전문가. JSON만 출력.",
            max_tokens=500,
            temperature=0.1,
            response_format="json",
        )

        response = await llm_router.route(LLMTask.PARSE_NOISE_REMOVAL, request)
        parsed = self._parse_json_response(response.text)

        if parsed is None:
            return []

        confidence = parsed.get("confidence", 0.0)
        if confidence < _NOISE_CONFIDENCE_THRESHOLD:
            log.debug(
                "noise_low_confidence",
                page_number=page_number,
                confidence=confidence,
            )
            return []

        noise_lines: list[str] = parsed.get("noise_lines", [])

        # 캐시 저장
        await self._set_cache(cache_key, noise_lines)

        return noise_lines

    @staticmethod
    def _apply_noise_removal(
        page: PageContent, noise_lines: list[str]
    ) -> int:
        """페이지에서 노이즈 라인을 실제로 제거한다.

        Args:
            page: 대상 페이지 (in-place 수정).
            noise_lines: 제거할 라인 텍스트 목록.

        Returns:
            제거된 라인 수.
        """
        if not noise_lines:
            return 0

        # 원본 보존
        if not hasattr(page, "metadata") or not isinstance(
            getattr(page, "metadata", None), dict
        ):
            pass  # PageContent에 metadata 필드가 없을 수 있음
        # PageContent는 Pydantic — model_extra 또는 별도 필드 사용 불가이므로
        # parse_result.metadata에 원본 보존

        noise_set = {line.strip() for line in noise_lines if line.strip()}
        removed_count = 0

        # page.text에서 노이즈 라인 제거
        original_lines = page.text.split("\n")
        cleaned_lines: list[str] = []
        for line in original_lines:
            stripped = line.strip()
            if stripped in noise_set:
                removed_count += 1
                continue
            cleaned_lines.append(line)
        page.text = "\n".join(cleaned_lines)

        # text_blocks에서도 노이즈 제거
        if page.text_blocks:
            kept_blocks: list[TextBlock] = []
            for block in page.text_blocks:
                if block.text.strip() not in noise_set:
                    kept_blocks.append(block)
            page.text_blocks = kept_blocks

        return removed_count

    # ------------------------------------------------------------------
    # Step 2: 단어 분리 복원
    # ------------------------------------------------------------------

    async def fix_word_breaks(self, parse_result: ParseResult) -> ParseResult:
        """줄바꿈/페이지 경계에서 분리된 단어를 LLM으로 복원한다.

        대상:
        - 하이픈으로 끝나는 줄 (예: "autom-\\natically")
        - 페이지 경계에서 잘린 단어

        Args:
            parse_result: 파서 출력 결과.

        Returns:
            단어가 복원된 ParseResult.
        """
        result = deepcopy(parse_result)
        total_fixes = 0

        # 페이지 내 줄바꿈 하이픈 복원
        for page in result.pages:
            fixes = await self._fix_hyphenated_breaks_in_page(page)
            total_fixes += fixes

        # 페이지 간 경계 단어 복원
        for i in range(len(result.pages) - 1):
            current_page = result.pages[i]
            next_page = result.pages[i + 1]
            fixed = await self._fix_page_boundary_word(current_page, next_page)
            if fixed:
                total_fixes += 1

        # raw_text 재구성
        if total_fixes > 0:
            result.raw_text = "\n\n".join(
                page.text for page in result.pages if page.text.strip()
            )

        log.info("fix_word_breaks_complete", total_fixes=total_fixes)
        return result

    async def _fix_hyphenated_breaks_in_page(self, page: PageContent) -> int:
        """페이지 내에서 하이픈으로 분리된 단어를 복원한다."""
        if not page.text:
            return 0

        # "단어-\n단어" 패턴 탐지
        pattern = re.compile(r"(\S+)-\n(\S+)")
        matches = list(pattern.finditer(page.text))
        if not matches:
            return 0

        fixes = 0
        sem = asyncio.Semaphore(_MAX_CONCURRENT_PAGES)

        async def _check_one(match: re.Match) -> Optional[tuple[str, str]]:
            """단일 하이픈 분리 검사. (원본, 복원) 튜플 또는 None을 반환."""
            async with sem:
                fragment_end = match.group(1)
                fragment_start = match.group(2)
                full_match = match.group(0)

                # 맥락 추출
                start_pos = max(0, match.start() - 100)
                end_pos = min(len(page.text), match.end() + 100)
                context = page.text[start_pos:end_pos]

                try:
                    merged = await self._check_word_merge(
                        f"{fragment_end}-",
                        fragment_start,
                        context,
                    )
                    if merged:
                        return (full_match, merged)
                except Exception as exc:
                    log.debug(
                        "word_break_fix_failed",
                        fragment_end=fragment_end,
                        fragment_start=fragment_start,
                        error=str(exc),
                    )
                return None

        results = await asyncio.gather(*[_check_one(m) for m in matches])

        for result_item in results:
            if result_item is not None:
                original, merged = result_item
                page.text = page.text.replace(original, merged, 1)
                fixes += 1

        return fixes

    async def _fix_page_boundary_word(
        self,
        current_page: PageContent,
        next_page: PageContent,
    ) -> bool:
        """페이지 경계에서 잘린 단어를 복원한다."""
        if not current_page.text or not next_page.text:
            return False

        # 현재 페이지 마지막 단어
        current_lines = current_page.text.rstrip().split("\n")
        if not current_lines:
            return False
        last_line = current_lines[-1].rstrip()
        if not last_line:
            return False

        # 다음 페이지 첫 단어
        next_lines = next_page.text.lstrip().split("\n")
        if not next_lines:
            return False
        first_line = next_lines[0].lstrip()
        if not first_line:
            return False

        last_word = last_line.split()[-1] if last_line.split() else ""
        first_word = first_line.split()[0] if first_line.split() else ""

        if not last_word or not first_word:
            return False

        # 하이픈으로 끝나는 경우만 우선 처리
        if not last_word.endswith("-"):
            return False

        context = f"...{last_line}\n{first_line}..."

        try:
            merged = await self._check_word_merge(last_word, first_word, context)
            if not merged:
                return False

            # 현재 페이지 마지막 줄에서 하이픈 단어 교체
            current_lines[-1] = last_line[: -len(last_word)] + merged
            current_page.text = "\n".join(current_lines)

            # 다음 페이지 첫 줄에서 병합된 부분 제거
            remaining = first_line[len(first_word) :].lstrip()
            if remaining:
                next_lines[0] = remaining
            else:
                next_lines = next_lines[1:]
            next_page.text = "\n".join(next_lines)

            return True
        except Exception as exc:
            log.debug(
                "page_boundary_fix_failed",
                error=str(exc),
            )
            return False

    async def _check_word_merge(
        self,
        line_end_fragment: str,
        next_line_start_fragment: str,
        surrounding_context: str,
    ) -> Optional[str]:
        """LLM으로 두 조각이 하나의 단어인지 확인한다.

        Returns:
            병합된 단어 문자열, 또는 병합 불필요 시 None.
        """
        cache_key = self._make_cache_key(
            "wordfix", f"{line_end_fragment}|{next_line_start_fragment}"
        )
        cached = await self._get_cache(cache_key)
        if cached is not None:
            return cached if cached else None

        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router
        from src.pipeline.prompts.parse_postprocessor import (
            build_word_break_fix_prompt,
        )

        prompt = build_word_break_fix_prompt(
            line_end_fragment, next_line_start_fragment, surrounding_context
        )
        request = LLMRequest(
            prompt=prompt,
            system_prompt="PDF 텍스트 복원 전문가. JSON만 출력.",
            max_tokens=200,
            temperature=0.1,
            response_format="json",
        )

        response = await llm_router.route(LLMTask.PARSE_WORD_FIX, request)
        parsed = self._parse_json_response(response.text)

        if parsed is None:
            return None

        should_merge = parsed.get("should_merge", False)
        confidence = parsed.get("confidence", 0.0)
        merged_word = parsed.get("merged_word", "")

        if not should_merge or confidence < _WORD_FIX_CONFIDENCE_THRESHOLD:
            await self._set_cache(cache_key, "")
            return None

        if merged_word:
            await self._set_cache(cache_key, merged_word)
            return merged_word

        return None

    # ------------------------------------------------------------------
    # Step 3: 멀티컬럼 재정렬
    # ------------------------------------------------------------------

    async def reorder_columns(self, parse_result: ParseResult) -> ParseResult:
        """멀티컬럼 레이아웃 페이지의 읽기 순서를 LLM으로 재정렬한다.

        layout_type이 "multi_column"인 페이지에서만 동작한다.

        Args:
            parse_result: 파서 출력 결과.

        Returns:
            재정렬된 ParseResult.
        """
        result = deepcopy(parse_result)
        sem = asyncio.Semaphore(_MAX_CONCURRENT_PAGES)
        reordered_count = 0

        multi_col_pages = [
            page
            for page in result.pages
            if page.layout_type in ("multi_column", "mixed")
        ]

        if not multi_col_pages:
            log.debug("reorder_columns_skipped", reason="no_multi_column_pages")
            return result

        async def _reorder_one(page: PageContent) -> bool:
            async with sem:
                try:
                    return await self._reorder_page(page)
                except Exception as exc:
                    log.warning(
                        "column_reorder_failed",
                        page_number=page.page_number,
                        error=str(exc),
                    )
                    return False

        results = await asyncio.gather(*[_reorder_one(p) for p in multi_col_pages])
        reordered_count = sum(1 for r in results if r)

        # raw_text 재구성
        if reordered_count > 0:
            result.raw_text = "\n\n".join(
                page.text for page in result.pages if page.text.strip()
            )

        log.info(
            "reorder_columns_complete",
            multi_column_pages=len(multi_col_pages),
            actually_reordered=reordered_count,
        )
        return result

    async def _reorder_page(self, page: PageContent) -> bool:
        """단일 페이지의 컬럼 순서를 재정렬한다.

        Returns:
            재정렬이 실제로 적용되었으면 True.
        """
        if not page.text.strip():
            return False

        cache_key = self._make_cache_key("reorder", page.text)
        cached = await self._get_cache(cache_key)
        if cached is not None:
            if cached:
                page.text = cached
                return True
            return False

        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router
        from src.pipeline.prompts.parse_postprocessor import (
            build_column_reorder_prompt,
        )

        prompt = build_column_reorder_prompt(page.text, page.page_number)
        request = LLMRequest(
            prompt=prompt,
            system_prompt="PDF 레이아웃 분석 전문가. JSON만 출력.",
            max_tokens=4000,
            temperature=0.1,
            response_format="json",
        )

        response = await llm_router.route(LLMTask.PARSE_REORDER, request)
        parsed = self._parse_json_response(response.text)

        if parsed is None:
            await self._set_cache(cache_key, "")
            return False

        reordered = parsed.get("reordered", False)
        confidence = parsed.get("confidence", 0.0)
        reordered_text = parsed.get("reordered_text", "")

        if not reordered or confidence < _REORDER_CONFIDENCE_THRESHOLD:
            await self._set_cache(cache_key, "")
            return False

        if reordered_text:
            page.text = reordered_text
            await self._set_cache(cache_key, reordered_text)
            return True

        return False

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_response(text: str) -> Optional[dict]:
        """LLM 응답에서 JSON을 추출한다. thinking 태그 및 마크다운 코드블럭을 처리."""
        cleaned = text.strip()

        # Qwen thinking 태그 제거
        cleaned = re.sub(r"<think>.*?</think>\s*", "", cleaned, flags=re.DOTALL)

        # 마크다운 코드블럭 내부 추출
        if "```" in cleaned:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]

        # 순수 JSON 파싱
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            log.debug("json_parse_failed", text_preview=cleaned[:200])
            return None

    @staticmethod
    def _make_cache_key(prefix: str, content: str) -> str:
        """컨텐츠 해시 기반 Redis 캐시 키를 생성한다."""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        return f"aicm:parse_postproc:{prefix}:{content_hash}"

    @staticmethod
    async def _get_cache(key: str) -> Optional[str | list]:
        """Redis에서 캐시를 조회한다. 연결 실패 시 None을 반환한다."""
        try:
            from src.common.redis import get_redis_client

            redis = await get_redis_client()
            value = await redis.get(key)
            if value is not None:
                return json.loads(value)
        except Exception:
            pass
        return None

    @staticmethod
    async def _set_cache(key: str, value: str | list) -> None:
        """Redis에 캐시를 저장한다. 연결 실패 시 무시한다."""
        try:
            from src.common.redis import get_redis_client

            redis = await get_redis_client()
            await redis.set(key, json.dumps(value), ex=_CACHE_TTL_SECONDS)
        except Exception:
            pass
