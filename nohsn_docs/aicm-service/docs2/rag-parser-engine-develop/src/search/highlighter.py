"""검색 결과 하이라이팅 — 키워드 매칭 부분을 <mark> 태그로 감싸기."""

from __future__ import annotations

import re

from src.common.logging import get_logger
from src.search.models import SearchHit

log = get_logger(__name__)


class SearchHighlighter:
    """
    검색 결과 콘텐츠에 하이라이팅 적용.

    - ES keyword 결과: ES highlight 응답을 활용
    - Dense/Sparse 결과: 질의 키워드 기반 후처리 하이라이팅
    - 매칭 부분을 <mark> 태그로 감싸 반환
    """

    HIGHLIGHT_TAG_OPEN = "<mark>"
    HIGHLIGHT_TAG_CLOSE = "</mark>"

    def highlight_hits(
        self,
        hits: list[SearchHit],
        keywords: list[str],
    ) -> list[SearchHit]:
        """
        검색 결과 리스트에 하이라이팅 적용.

        Args:
            hits: 검색 결과 리스트
            keywords: 질의에서 추출한 키워드

        Returns:
            highlighted_content가 metadata에 추가된 SearchHit 리스트
        """
        for hit in hits:
            highlighted = self._highlight_single(hit, keywords)
            hit.metadata["highlighted_content"] = highlighted

        return hits

    def _highlight_single(self, hit: SearchHit, keywords: list[str]) -> str:
        """단일 SearchHit에 하이라이팅 적용."""
        # ES highlight가 이미 있으면 사용
        es_highlight = hit.metadata.get("highlight", {})
        if es_highlight and "content" in es_highlight:
            # ES highlight는 <em>...</em> 형태 -> <mark>...</mark>로 변환
            fragments = es_highlight["content"]
            if isinstance(fragments, list) and fragments:
                highlighted_text = " ... ".join(fragments)
                highlighted_text = highlighted_text.replace("<em>", self.HIGHLIGHT_TAG_OPEN)
                highlighted_text = highlighted_text.replace("</em>", self.HIGHLIGHT_TAG_CLOSE)
                return highlighted_text

        # 키워드 기반 후처리 하이라이팅
        return self._keyword_highlight(hit.content, keywords)

    def _keyword_highlight(self, content: str, keywords: list[str]) -> str:
        """키워드 기반 후처리 하이라이팅."""
        if not keywords or not content:
            return content

        # 긴 키워드 우선 매칭 (짧은 키워드가 긴 키워드의 일부를 먼저 감싸지 않도록)
        sorted_keywords = sorted(keywords, key=len, reverse=True)

        # 유효한 키워드만 필터링 (1글자 이상)
        valid_keywords = [kw for kw in sorted_keywords if len(kw) >= 1]
        if not valid_keywords:
            return content

        # 모든 키워드를 OR로 묶은 정규식 패턴
        escaped = [re.escape(kw) for kw in valid_keywords]
        pattern = "|".join(escaped)

        try:
            highlighted = re.sub(
                f"({pattern})",
                f"{self.HIGHLIGHT_TAG_OPEN}\\1{self.HIGHLIGHT_TAG_CLOSE}",
                content,
                flags=re.IGNORECASE,
            )
            return highlighted
        except re.error:
            log.warning("highlight_regex_error", keywords=keywords[:5])
            return content


def highlight_text(text: str, keywords: list[str]) -> str:
    """단순 텍스트 하이라이팅 유틸리티 함수."""
    highlighter = SearchHighlighter()
    return highlighter._keyword_highlight(text, keywords)
