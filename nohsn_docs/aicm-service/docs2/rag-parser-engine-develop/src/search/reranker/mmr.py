"""MMR (Maximum Marginal Relevance) 리랭킹 -- 검색 결과의 다양성 확보.

같은 문서의 블럭이 Top-K를 독점하는 것을 방지한다.
관련성과 다양성 사이의 균형을 lambda_param으로 조절:
- lambda=1.0: 관련성만 (기존 정렬과 동일)
- lambda=0.0: 다양성만 (이미 선택된 것과 최대한 다른 것 우선)
- lambda=0.7: 추천 기본값
"""

from __future__ import annotations

from src.search.models import SearchHit


def mmr_rerank(
    results: list[SearchHit],
    lambda_param: float = 0.7,
    top_k: int = 10,
    max_per_document: int = 3,
) -> list[SearchHit]:
    """MMR 알고리즘으로 결과를 리랭킹한다.

    Args:
        results: 원본 검색 결과 (점수 내림차순 정렬 가정)
        lambda_param: 관련성 vs 다양성 비율 (0=다양성 최대, 1=관련성 최대)
        top_k: 반환할 최대 결과 수
        max_per_document: 같은 문서에서 최대 포함 수

    Returns:
        다양성이 확보된 리랭킹 결과
    """
    if not results:
        return results

    selected: list[SearchHit] = []
    remaining = list(results)

    # 첫 번째는 최고 점수 그대로
    selected.append(remaining.pop(0))

    while remaining and len(selected) < top_k:
        best_score = -float("inf")
        best_idx = 0

        for i, candidate in enumerate(remaining):
            # 관련성 점수
            relevance = candidate.fused_score or candidate.dense_score or 0.0

            # 다양성 페널티: 이미 선택된 것과의 최대 유사도
            max_sim = 0.0
            for sel in selected:
                sim = _content_similarity(candidate.content, sel.content)
                # 같은 문서면 추가 페널티
                if candidate.document_id == sel.document_id:
                    sim = max(sim, 0.5)
                max_sim = max(max_sim, sim)

            # MMR 점수 = lambda * relevance - (1 - lambda) * max_similarity
            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim

            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i

        # 같은 문서 개수 체크
        candidate = remaining[best_idx]
        doc_count = sum(1 for s in selected if s.document_id == candidate.document_id)
        if doc_count < max_per_document:
            selected.append(remaining.pop(best_idx))
        else:
            remaining.pop(best_idx)  # 제한 초과 → 스킵

    return selected


def _content_similarity(text1: str, text2: str) -> float:
    """간단한 자카드 유사도 (단어 기반).

    임베딩 유사도 대신 사용하는 경량 대안.
    정확하진 않지만 O(1) 메모리로 빠르게 동작한다.
    """
    words1 = set(text1.split())
    words2 = set(text2.split())
    if not words1 or not words2:
        return 0.0
    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union)
