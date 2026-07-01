"""의미 중복 제거 — BGE-M3 dense_vector 코사인 유사도 기반.

SHA-256 해시는 exact-match만 가능.
이 모듈은 약간 다른 문장으로 같은 의미인 블럭을 걸러낸다.
"""

from __future__ import annotations

import math

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType

log = get_logger(__name__)

# 이 값 이상이면 중복으로 판단
_SIMILARITY_THRESHOLD = 0.95


def deduplicate_by_embedding(
    blocks: list[BlockObject],
    threshold: float = _SIMILARITY_THRESHOLD,
) -> list[BlockObject]:
    """dense_vector 기반으로 near-duplicate 블럭을 제거한다.

    - summary / heading / table / image 블럭은 보호
    - dense_vector가 없는 블럭은 그대로 유지
    - 같은 해시는 먼저 제거 (exact-dup)
    - 남은 블럭 중 코사인 ≥ threshold인 블럭 쌍에서 후행 블럭 제거
    """
    if len(blocks) <= 1:
        return blocks

    # 1) exact hash dedup
    seen_hashes: set[str] = set()
    after_exact: list[BlockObject] = []
    exact_removed = 0
    for block in blocks:
        h = block.block_hash
        if h and h in seen_hashes:
            exact_removed += 1
            continue
        if h:
            seen_hashes.add(h)
        after_exact.append(block)

    # 2) cosine near-dup (보호 타입 제외)
    _PROTECTED = {
        BlockType.SUMMARY, BlockType.TABLE, BlockType.IMAGE, BlockType.DIVIDER,
        BlockType.HEADING_1, BlockType.HEADING_2, BlockType.HEADING_3,
    }
    result: list[BlockObject] = []
    kept_vectors: list[tuple[BlockObject, list[float]]] = []
    semantic_removed = 0

    for block in after_exact:
        if block.block_type in _PROTECTED:
            result.append(block)
            continue

        if not block.dense_vector:
            result.append(block)
            continue

        # 기존 유지 블럭과 비교
        is_dup = False
        for kept_block, kept_vec in kept_vectors:
            if kept_block.block_type in _PROTECTED:
                continue
            sim = _cosine(block.dense_vector, kept_vec)
            if sim >= threshold:
                is_dup = True
                # 중복 정보를 기존 블럭 metadata에 기록
                kept_block.metadata.setdefault("duplicate_sources", []).append(
                    {
                        "block_id": str(block.id),
                        "similarity": round(sim, 3),
                    }
                )
                semantic_removed += 1
                break

        if not is_dup:
            result.append(block)
            kept_vectors.append((block, block.dense_vector))

    if exact_removed or semantic_removed:
        log.info(
            "semantic_dedup_complete",
            input=len(blocks),
            exact_removed=exact_removed,
            semantic_removed=semantic_removed,
            remaining=len(result),
            threshold=threshold,
        )

    return result


def _cosine(a: list[float], b: list[float]) -> float:
    """코사인 유사도."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
