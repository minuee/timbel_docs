"""서브쿼리 결과 라운드로빈 병합 — 각 의도(서브쿼리)의 대표성을 top_k에 보장."""
from __future__ import annotations


def _key(hit):
    blk = getattr(hit, "block_id", None) or getattr(hit, "chunk_id", None)
    return (getattr(hit, "document_id", None), blk)


def round_robin_merge(hit_lists: list[list], top_k: int) -> list:
    """각 서브쿼리 결과 리스트에서 순번대로 인터리브, 중복(첫 등장 유지) 제거, top_k 절단."""
    merged: list = []
    seen: set = set()
    if not hit_lists:
        return merged
    max_len = max((len(h) for h in hit_lists), default=0)
    for rank in range(max_len):
        for lst in hit_lists:
            if rank >= len(lst):
                continue
            hit = lst[rank]
            k = _key(hit)
            if k in seen:
                continue
            seen.add(k)
            merged.append(hit)
            if len(merged) >= top_k:
                return merged
    return merged
