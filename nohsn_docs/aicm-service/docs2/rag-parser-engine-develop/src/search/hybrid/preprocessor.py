"""질의 전처리기 — 형태소 분석, 불용어 제거, 키워드 추출, 동의어 확장."""

from __future__ import annotations

import re
import time
from uuid import UUID

from src.common.logging import get_logger

try:
    from konlpy.tag import Okt
    _HAS_OKT = True
except (ImportError, Exception):
    _HAS_OKT = False
from src.search.models import ProcessedQuery, SearchTraceStep

log = get_logger(__name__)

# 한국어 불용어 목록
KOREAN_STOPWORDS: set[str] = {
    "이", "그", "저", "것", "수", "등", "및", "또", "또는",
    "의", "가", "이", "은", "들", "는", "좀", "잘", "걍",
    "과", "도", "를", "으로", "자", "에", "와", "한", "하다",
    "에서", "에게", "까지", "부터", "로", "으로", "에서",
    "하는", "있는", "되는", "없는", "않는", "같은",
    "하고", "있고", "되고", "없고",
    "해서", "있어서", "되어서",
    "하면", "있으면", "되면",
    "합니다", "입니다", "습니다", "됩니다",
    "해요", "있어요", "돼요",
    "뭐", "어떤", "어떻게", "왜", "어디",
    "대한", "위한", "통한", "관한",
}

# 형태소 분석에서 키워드로 사용할 품사 태그
KEYWORD_POS_TAGS: set[str] = {"Noun", "Verb", "Adjective", "Alpha", "Number", "Foreign"}


class QueryPreprocessor:
    """
    질의를 검색에 최적화된 형태로 변환.

    처리 순서:
    1. 공백 정리, 특수문자 제거
    2. 한국어 형태소 분석 (Okt)
    3. 불용어 제거
    4. 키워드 추출
    5. 동의어 확장 (keyword 검색용, 선택적)
    """

    def __init__(self, synonym_expander: object | None = None) -> None:
        self._okt = Okt() if _HAS_OKT else None
        self._synonym_expander = synonym_expander
        log.info("query_preprocessor_initialized", okt_available=_HAS_OKT)

    def _clean(self, query: str) -> str:
        """공백 정리 및 불필요한 특수문자 제거."""
        # 연속 공백 제거
        cleaned = re.sub(r"\s+", " ", query.strip())
        # 검색에 방해되는 특수문자만 제거 (한글, 영문, 숫자, 일부 기호 보존)
        cleaned = re.sub(r"[^\w\s가-힣a-zA-Z0-9.,?!@#%&*()-_+=\[\]{}/<>:;\"']", "", cleaned)
        return cleaned

    def _analyze_morphemes(self, text: str) -> list[tuple[str, str]]:
        """한국어 형태소 분석 수행. Okt 미설치 시 단순 토큰화 fallback."""
        if self._okt is None:
            # Okt 미설치 시 공백+정규식 기반 단순 토큰화
            tokens = re.findall(r"[가-힣]{2,}|[a-zA-Z]{2,}|[0-9]+", text)
            return [(t, "Noun") for t in tokens]
        try:
            return self._okt.pos(text, stem=True)
        except Exception:
            log.warning("morpheme_analysis_failed", text=text[:100])
            tokens = re.findall(r"[가-힣]{2,}|[a-zA-Z]{2,}|[0-9]+", text)
            return [(t, "Noun") for t in tokens]

    def _extract_keywords(self, morphemes: list[tuple[str, str]]) -> list[str]:
        """형태소 분석 결과에서 키워드 추출."""
        keywords: list[str] = []
        for word, pos in morphemes:
            if pos in KEYWORD_POS_TAGS and word not in KOREAN_STOPWORDS and len(word) > 1:
                keywords.append(word)
        # 단일 문자 키워드만 남은 경우 원래 형태소 중 Noun을 추가
        if not keywords:
            keywords = [
                word for word, pos in morphemes
                if pos == "Noun" and word not in KOREAN_STOPWORDS
            ]
        return keywords

    async def preprocess(
        self,
        query: str,
        tenant_id: UUID | None = None,
    ) -> tuple[ProcessedQuery, SearchTraceStep]:
        """질의 전처리 수행 및 트레이스 단계 반환.

        Args:
            query: 원본 질의 텍스트
            tenant_id: 테넌트별 동의어 확장에 사용 (선택)
        """
        start = time.monotonic()

        cleaned = self._clean(query)
        morphemes = self._analyze_morphemes(cleaned)
        keywords = self._extract_keywords(morphemes)

        # 동의어 확장 (keyword 검색용)
        expanded_keywords = keywords
        if self._synonym_expander is not None and keywords:
            try:
                expanded_keywords = await self._synonym_expander.expand(
                    keywords, tenant_id=tenant_id
                )
            except Exception:
                log.warning("synonym_expansion_failed", query=query[:100], exc_info=True)
                expanded_keywords = keywords

        processed = ProcessedQuery(
            original=query,
            cleaned=cleaned,
            keywords=keywords,
            for_dense=cleaned,
            for_sparse=cleaned,
            for_keyword=expanded_keywords if expanded_keywords else [cleaned],
        )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        trace = SearchTraceStep(
            step_name="query_preprocessing",
            latency_ms=elapsed_ms,
            candidate_count=len(keywords),
            details={
                "cleaned": cleaned,
                "keywords": keywords,
                "expanded_keywords": expanded_keywords,
                "synonym_count": len(expanded_keywords) - len(keywords),
                "morpheme_count": len(morphemes),
            },
        )

        log.info(
            "query_preprocessed",
            original=query,
            keywords=keywords,
            expanded_keywords=expanded_keywords,
            latency_ms=elapsed_ms,
        )
        return processed, trace
