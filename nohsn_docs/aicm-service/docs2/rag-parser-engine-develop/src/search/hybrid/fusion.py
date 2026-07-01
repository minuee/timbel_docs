"""RRF (Reciprocal Rank Fusion) 스코어 통합."""

from __future__ import annotations

import time

from src.common.constants import (
    DEFAULT_DENSE_WEIGHT,
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_RRF_K,
    DEFAULT_SPARSE_WEIGHT,
)
from src.common.logging import get_logger
from src.search.models import SearchConfig, SearchHit, SearchTraceStep

log = get_logger(__name__)


class RRFFusion:
    """
    여러 검색 소스의 결과를 하나의 순위로 통합.

    RRF 공식: score(d) = Sigma weight_i / (k + rank_i(d))
    - k = 60 (표준값, 순위 간 차이를 완화)
    - rank_i(d) = i번째 검색 소스에서 문서 d의 순위 (1-based)
    """

    def __init__(self, k: int = DEFAULT_RRF_K) -> None:
        self.k = k

    def fuse(
        self,
        search_results: dict[str, list[SearchHit]],
        weights: dict[str, float] | None = None,
        config: SearchConfig | None = None,
    ) -> tuple[list[SearchHit], SearchTraceStep]:
        """
        RRF 스코어 통합 수행.

        가중치 우선순위: weights 파라미터 > config > 기본값
        """
        start = time.monotonic()

        # 가중치 결정
        resolved_weights = self._resolve_weights(weights, config)

        # 청크별 RRF 스코어 합산
        chunk_scores: dict[str, float] = {}
        chunk_data: dict[str, SearchHit] = {}

        for source, hits in search_results.items():
            w = resolved_weights.get(source, 1.0)
            for rank, hit in enumerate(hits):
                rrf_score = w * (1.0 / (self.k + rank + 1))
                chunk_id = str(hit.chunk_id)

                if chunk_id not in chunk_scores:
                    chunk_scores[chunk_id] = 0.0
                    chunk_data[chunk_id] = hit
                else:
                    # 기존 hit의 스코어를 병합
                    existing = chunk_data[chunk_id]
                    if hit.dense_score is not None and existing.dense_score is None:
                        existing.dense_score = hit.dense_score
                    if hit.sparse_score is not None and existing.sparse_score is None:
                        existing.sparse_score = hit.sparse_score
                    if hit.keyword_score is not None and existing.keyword_score is None:
                        existing.keyword_score = hit.keyword_score

                chunk_scores[chunk_id] += rrf_score

        # 스코어 순 정렬
        sorted_ids = sorted(chunk_scores, key=lambda x: chunk_scores[x], reverse=True)

        results: list[SearchHit] = []
        for cid in sorted_ids:
            hit = chunk_data[cid]
            hit.fused_score = chunk_scores[cid]
            results.append(hit)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        trace = SearchTraceStep(
            step_name="rrf_fusion",
            latency_ms=elapsed_ms,
            candidate_count=len(results),
            details={
                "weights": resolved_weights,
                "rrf_k": self.k,
                "source_counts": {s: len(h) for s, h in search_results.items()},
                "top_fused_scores": [
                    round(results[i].fused_score, 6) for i in range(min(5, len(results)))
                ],
            },
        )

        log.info(
            "rrf_fusion_completed",
            total_candidates=len(results),
            weights=resolved_weights,
            latency_ms=elapsed_ms,
        )
        return results, trace

    @staticmethod
    def _resolve_weights(
        weights: dict[str, float] | None,
        config: SearchConfig | None,
    ) -> dict[str, float]:
        """가중치 결정. 우선순위: API 요청 > config > 기본값."""
        default = {
            "dense": DEFAULT_DENSE_WEIGHT,
            "sparse": DEFAULT_SPARSE_WEIGHT,
            "keyword": DEFAULT_KEYWORD_WEIGHT,
        }

        if config:
            default = {
                "dense": config.dense_weight,
                "sparse": config.sparse_weight,
                "keyword": config.keyword_weight,
            }

        if weights:
            # API 요청 가중치로 오버라이드 (부분 오버라이드 허용)
            return {k: weights.get(k, default[k]) for k in default}

        return default
