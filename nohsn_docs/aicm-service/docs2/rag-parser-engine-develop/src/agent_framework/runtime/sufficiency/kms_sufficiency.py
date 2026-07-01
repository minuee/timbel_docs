"""KMS 검색 결과의 sufficiency feature 추출 — 2026-05-06 spec § 4.3 B.

GPT-5.5 권고: BGE-M3 raw score 절대값 기반 threshold 금지. answer compose
LLM 이 metadata 로 받아 sufficiency 판정. 이 모듈은 *feature 추출* 만
담당 — 판정/분기 로직은 post-demo dispatcher 통합 시점에 추가.

pre-demo: 어디서도 import 안 됨 (kms_rag.py 변경 X 보장). 단위 테스트만.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class KmsHit:
    score: float           # sigmoid 정규화된 reranker 점수 (0..1)
    title: str
    snippet: str
    source: str            # kms_chunk / agent_data / ...


@dataclass
class KmsFeatures:
    top_score: float | None = None
    second_score: float | None = None
    rank_gap: float | None = None
    top_titles: list[str] = field(default_factory=list)
    snippet_lengths: list[int] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)
    n_hits: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "top_score": self.top_score,
            "second_score": self.second_score,
            "rank_gap": self.rank_gap,
            "top_titles": self.top_titles,
            "snippet_lengths": self.snippet_lengths,
            "source_types": self.source_types,
            "n_hits": self.n_hits,
        }


# 임시 threshold heuristic — Stage 3 에서 LLM judge 로 교체 예정.
# 본 값은 BGE-M3 sigmoid 정규화된 score (0-1) 기준.
KMS_SCORE_THRESHOLD = 0.7   # top hit 의 최소 점수
KMS_GAP_THRESHOLD = 0.15    # 1위와 2위 사이 의미 있는 격차


def is_sufficient(features: KmsFeatures) -> bool:
    """KMS 검색 결과가 sufficient 한지 threshold heuristic 으로 판정.

    LLM judge 로 교체 예정 (Stage 3).
    """
    if features.n_hits < 1 or features.top_score is None:
        return False
    if features.top_score <= KMS_SCORE_THRESHOLD:
        return False
    if features.rank_gap is None:
        # 단일 hit — top_score 만 보고 통과
        return True
    return features.rank_gap > KMS_GAP_THRESHOLD


def extract_kms_features(hits: list[KmsHit]) -> KmsFeatures:
    """KMS hits 에서 sufficiency 판정에 쓸 feature 추출. 부수효과 없음."""
    if not hits:
        return KmsFeatures()
    sorted_hits = sorted(hits, key=lambda h: h.score, reverse=True)
    top = sorted_hits[0]
    second = sorted_hits[1] if len(sorted_hits) >= 2 else None
    return KmsFeatures(
        top_score=top.score,
        second_score=second.score if second else None,
        rank_gap=(top.score - second.score) if second else None,
        top_titles=[h.title for h in sorted_hits[:3]],
        snippet_lengths=[len(h.snippet) for h in sorted_hits[:3]],
        source_types=[h.source for h in sorted_hits[:3]],
        n_hits=len(sorted_hits),
    )
