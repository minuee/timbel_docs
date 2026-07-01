"""TableLayerSelector -- 쿼리 의도에 따라 최적의 테이블 레이어를 선택.

Knowledge Search(사람용)에서는 표의 3개 레이어(Row NL, Markdown Group, Summary)를
모두 반환하지만, RAG Retrieval(LLM용)에서는 토큰 낭비를 방지하기 위해
쿼리 의도에 가장 적합한 레이어만 선택적으로 반환한다.

의도 분류:
- cell_lookup: 특정 셀 값 조회 → Row NL 레이어 선호
- comparison: 비교/목록 조회 → Markdown Group 레이어 선호
- aggregation: 집계/요약 조회 → Summary 레이어 선호
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Sequence

from pydantic import BaseModel, Field

from src.common.logging import get_logger
from src.search.models import SearchHit

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 의도(Intent) 정의
# ---------------------------------------------------------------------------

class TableQueryIntent(str, Enum):
    """표 관련 쿼리 의도 유형."""

    CELL_LOOKUP = "cell_lookup"
    COMPARISON = "comparison"
    AGGREGATION = "aggregation"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# 의도별 선호 레이어 매핑
# ---------------------------------------------------------------------------

_INTENT_TO_PREFERRED_LAYERS: dict[TableQueryIntent, list[str]] = {
    TableQueryIntent.CELL_LOOKUP: ["row_nl", "table_markdown", "table_summary"],
    TableQueryIntent.COMPARISON: ["table_markdown", "row_nl", "table_summary"],
    TableQueryIntent.AGGREGATION: ["table_summary", "table_markdown", "row_nl"],
    TableQueryIntent.UNKNOWN: ["table_markdown", "row_nl", "table_summary"],
}

# ---------------------------------------------------------------------------
# 한국어 키워드 패턴 (의도 감지용)
# ---------------------------------------------------------------------------

# Cell lookup: 특정 값을 찾는 질의
_CELL_LOOKUP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"얼마", re.IGNORECASE),
    re.compile(r"몇\s*(개|원|건|명|%|퍼센트)", re.IGNORECASE),
    re.compile(r"단가", re.IGNORECASE),
    re.compile(r"가격", re.IGNORECASE),
    re.compile(r"무엇", re.IGNORECASE),
    re.compile(r"뭐", re.IGNORECASE),
    re.compile(r"어떤\s*값", re.IGNORECASE),
    re.compile(r"몇\s*호", re.IGNORECASE),
    re.compile(r"규격\s*(은|이)", re.IGNORECASE),
    re.compile(r"(what|how\s*much|price)", re.IGNORECASE),
]

# Comparison: 비교, 목록 조회
_COMPARISON_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"비교", re.IGNORECASE),
    re.compile(r"차이", re.IGNORECASE),
    re.compile(r"종류", re.IGNORECASE),
    re.compile(r"목록", re.IGNORECASE),
    re.compile(r"리스트", re.IGNORECASE),
    re.compile(r"전부|모두|모든", re.IGNORECASE),
    re.compile(r"나열", re.IGNORECASE),
    re.compile(r"어떤\s*것들", re.IGNORECASE),
    re.compile(r"(compare|list|difference)", re.IGNORECASE),
]

# Aggregation: 집계, 요약
_AGGREGATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"가장", re.IGNORECASE),
    re.compile(r"최대", re.IGNORECASE),
    re.compile(r"최소", re.IGNORECASE),
    re.compile(r"평균", re.IGNORECASE),
    re.compile(r"총\s*(합|계|액)", re.IGNORECASE),
    re.compile(r"합계", re.IGNORECASE),
    re.compile(r"전체\s*(요약|개요|합)", re.IGNORECASE),
    re.compile(r"몇\s*종|몇\s*가지", re.IGNORECASE),
    re.compile(r"요약", re.IGNORECASE),
    re.compile(r"(max|min|average|total|sum|overview)", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# 레이어 식별자
# ---------------------------------------------------------------------------

TABLE_LAYERS: frozenset[str] = frozenset({"row_nl", "table_markdown", "table_summary"})


def _is_table_chunk(hit: SearchHit) -> bool:
    """SearchHit이 표 청크인지 확인."""
    layer = hit.metadata.get("layer", "")
    return layer in TABLE_LAYERS


def _count_tokens(text: str) -> int:
    """간이 토큰 수 추정 (한국어 기준 ~3.5자/토큰, 영문 ~4자/토큰)."""
    if not text:
        return 0
    korean_chars = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
    total_chars = len(text)
    if total_chars == 0:
        return 0
    korean_ratio = korean_chars / total_chars
    avg_chars_per_token = 3.5 * korean_ratio + 4.0 * (1 - korean_ratio)
    return max(1, int(total_chars / avg_chars_per_token))


# ---------------------------------------------------------------------------
# IntentScore -- 의도 감지 결과
# ---------------------------------------------------------------------------

class IntentScore(BaseModel):
    """의도 감지 점수."""

    intent: TableQueryIntent
    score: float = Field(default=0.0, ge=0.0)
    matched_keywords: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# TableLayerSelector 본체
# ---------------------------------------------------------------------------

class TableLayerSelector:
    """쿼리 의도에 따라 최적의 테이블 레이어를 선택.

    RAG Retrieval에서 사용. 3개 레이어를 모두 보내는 대신,
    쿼리 의도에 가장 적합한 레이어만 필터링하여 토큰을 절약한다.

    Knowledge Search에서는 이 클래스를 사용하지 않고
    모든 레이어를 그대로 반환한다.
    """

    def select_layer(
        self,
        query: str,
        table_chunks: list[SearchHit],
        *,
        max_context_tokens: int = 2000,
    ) -> list[SearchHit]:
        """쿼리 의도 기반으로 표 청크를 필터링.

        Parameters
        ----------
        query : str
            사용자 질의
        table_chunks : list[SearchHit]
            표 관련 검색 결과 (다양한 레이어 혼재)
        max_context_tokens : int
            토큰 예산

        Returns
        -------
        list[SearchHit]
            의도에 맞는 최적 레이어의 청크만 필터링된 리스트
        """
        if not table_chunks:
            return []

        # 표 청크와 비표 청크를 분리
        table_hits: list[SearchHit] = []
        non_table_hits: list[SearchHit] = []
        for chunk in table_chunks:
            if _is_table_chunk(chunk):
                table_hits.append(chunk)
            else:
                non_table_hits.append(chunk)

        if not table_hits:
            return table_chunks

        # 1. 쿼리 의도 감지
        intent = self._detect_intent(query)

        # 2. 의도에 맞는 레이어 우선순위 결정
        preferred_layers = _INTENT_TO_PREFERRED_LAYERS[intent]

        # 3. 표별로 그룹핑 (document_id, table_index)
        table_groups: dict[tuple[str, int | None], list[SearchHit]] = {}
        for hit in table_hits:
            doc_id = str(hit.document_id)
            table_idx = hit.source_location.table_index
            if table_idx is None:
                table_idx = hit.metadata.get("table_index")
            key = (doc_id, table_idx)
            table_groups.setdefault(key, []).append(hit)

        # 4. 각 표 그룹에서 선호 레이어만 선택
        selected: list[SearchHit] = []
        token_budget = max_context_tokens

        # 비표 청크 토큰 먼저 계산
        for hit in non_table_hits:
            token_budget -= _count_tokens(hit.content)

        for _table_key, group_hits in table_groups.items():
            layer_map: dict[str, list[SearchHit]] = {}
            for hit in group_hits:
                layer = hit.metadata.get("layer", "unknown")
                layer_map.setdefault(layer, []).append(hit)

            # 선호 레이어 순으로 선택 시도
            chosen = False
            for preferred in preferred_layers:
                if preferred in layer_map:
                    for hit in layer_map[preferred]:
                        tokens = _count_tokens(hit.content)
                        if token_budget - tokens >= 0:
                            selected.append(hit)
                            token_budget -= tokens
                            chosen = True
                    if chosen:
                        break

            # 모든 선호 레이어가 예산 초과면 가장 짧은 걸 하나라도 넣기
            if not chosen:
                all_hits_sorted = sorted(
                    group_hits, key=lambda h: _count_tokens(h.content)
                )
                for hit in all_hits_sorted:
                    tokens = _count_tokens(hit.content)
                    if token_budget - tokens >= 0:
                        selected.append(hit)
                        token_budget -= tokens
                        break

        log.info(
            "table_layer_selected",
            query=query[:100],
            intent=intent.value,
            input_table_chunks=len(table_hits),
            selected_chunks=len(selected),
            remaining_tokens=token_budget,
        )

        # 비표 청크 + 선택된 표 청크 합산
        return non_table_hits + selected

    def _detect_intent(self, query: str) -> TableQueryIntent:
        """쿼리에서 표 관련 의도를 감지.

        각 의도 카테고리의 키워드 패턴 매칭 횟수로 스코어를 산출하고,
        가장 높은 스코어의 의도를 반환한다.

        Parameters
        ----------
        query : str
            사용자 질의

        Returns
        -------
        TableQueryIntent
            감지된 의도
        """
        scores = self._compute_intent_scores(query)

        # 최고 스코어 의도 선택
        best = max(scores, key=lambda s: s.score)

        if best.score == 0.0:
            return TableQueryIntent.UNKNOWN

        return best.intent

    def _compute_intent_scores(self, query: str) -> list[IntentScore]:
        """각 의도 카테고리의 매칭 점수를 계산.

        Parameters
        ----------
        query : str
            사용자 질의

        Returns
        -------
        list[IntentScore]
            의도별 점수 리스트
        """
        results: list[IntentScore] = []

        for intent_type, patterns in [
            (TableQueryIntent.CELL_LOOKUP, _CELL_LOOKUP_PATTERNS),
            (TableQueryIntent.COMPARISON, _COMPARISON_PATTERNS),
            (TableQueryIntent.AGGREGATION, _AGGREGATION_PATTERNS),
        ]:
            matched: list[str] = []
            for pattern in patterns:
                if pattern.search(query):
                    matched.append(pattern.pattern)

            results.append(
                IntentScore(
                    intent=intent_type,
                    score=float(len(matched)),
                    matched_keywords=matched,
                )
            )

        return results

    def detect_intent(self, query: str) -> TableQueryIntent:
        """공개 인터페이스: 쿼리 의도 감지.

        Parameters
        ----------
        query : str
            사용자 질의

        Returns
        -------
        TableQueryIntent
            감지된 의도 (cell_lookup / comparison / aggregation / unknown)
        """
        return self._detect_intent(query)
