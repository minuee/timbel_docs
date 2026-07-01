"""Semantic block merger — block 단위 의미 그룹핑.

D31b (#208) — canonical 위치. 옛 위치 (`scripts/seed/semantic_block_merger.py`)
는 thin compatibility re-export 만 유지. `src/pipeline/full_pipeline.py` +
`src/pipeline/chunkers/type_aware_chunker.py` 의 src→scripts 의존 0 달성 (D31b
v3 fix A).

#116 의 미완 부분 (1:1 blocks→chunks) 보완.
사용자 명시 (2026-05-07):
    "자료 KMS 등록 파이프라인은 시간이 걸려도 좋으니 잘 정제해서 저장 해두는게
     중요한거야. 그건 시간 절감 말고 효율 및 검색 품질에 집중 하도록 해"

문제:
    기존 reseed_5_agents_kms_pipeline.py 는 chunker = "block_per_chunk":
    - block 한 개 → chunk 한 개 (1:1)
    - 짧은 항목 (예: heading 한 줄, 한 두 문장 paragraph) 까지 모두 chunk
    - BGE-M3 임베딩 score 가 분산 → KMS hit 0~2 건 (cutoff 0.5)

해결:
    SemanticBlockMerger 가 *인접* block 들을 의미 단위로 묶어서 더 큰 chunk 로
    만든다. 알고리즘:

    1. 같은 heading_* 아래의 paragraph/table/image_ref block 은 한 cluster.
    2. cluster 내부에서 인접 block 의 *KSS 문장 임베딩 cosine 유사도* 가
       threshold 이상이면 같은 chunk 로 병합.
    3. heading_1/heading_2 boundary 는 *항상* 새 cluster 시작.
    4. min_chars / max_chars 제약 적용 — 너무 작은 cluster 는 인접 cluster 에
       흡수, 너무 큰 chunk 는 강제 split.

특징:
    - block.id 는 보존 (blocks 테이블 그대로) — *chunks 테이블만 변경*.
    - chunks.metadata 에 source_block_ids[] 추가 → 검색 hit 시 어느 block 들이
      포함됐는지 trace 가능.
    - chunks.metadata.cluster_id (uuid) 로 같은 의미 그룹 mark.
    - 외부 모델 없이도 동작 (TF-IDF fallback) — KSS 가 없으면 줄 단위 fallback.

검증:
    pytest scripts/seed/test_semantic_block_merger.py 또는 직접 실행:
        python -m scripts.seed.semantic_block_merger --demo
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import numpy as np

# D31a (#206 v5 fix 3) — DTO canonical 은 src.pipeline.models.chunking.
from src.pipeline.models.chunking import InputBlock, MergedChunk

# ── 임계값 ────────────────────────────────────────────────────────────────

# cosine 유사도 임계값 — 이상이면 *병합*, 미만이면 *분할*.
# 0.18 은 한국어 콜센터 자료 기준 — 짧은 paragraph 도 충분히 묶이는 수준.
DEFAULT_SIMILARITY_THRESHOLD = 0.18

# chunk 사이즈 제약 (문자 단위, 토큰 ≈ chars/2 가정).
DEFAULT_MIN_CHARS = 200
DEFAULT_MAX_CHARS = 1800
DEFAULT_OVERLAP = 80

# heading boundary — heading_1, heading_2 만 boundary. heading_3 은 계속 묶임.
HARD_BOUNDARY_TYPES = frozenset({"heading_1", "heading_2"})

# 단독 chunk 화 — table 은 큰 단위 그대로 검색 노출 (분할 시 정보 손실).
ATOMIC_TYPES = frozenset({"table", "image_ref"})


# ── 임베딩 (TF-IDF fallback) ──────────────────────────────────────────────


def _tokenize_korean(text: str) -> list[str]:
    """한국어 + 영문 단순 토큰화 — TF-IDF 용 경량 함수.

    * 공백/구두점 분리.
    * 1자 이하 토큰 제외 (한국어 조사 노이즈 감소).
    """
    import re

    # 한글/영문/숫자만 남김
    cleaned = re.sub(r"[^\w가-힣]+", " ", text)
    tokens = [t for t in cleaned.split() if len(t) >= 2]
    return tokens


def _tfidf_matrix(texts: list[str]) -> np.ndarray:
    """텍스트 목록 → TF-IDF 정규화 matrix.

    KSS 가 없거나 BGE-M3 호출이 비싸므로 가벼운 TF-IDF 로 대체.
    embedding 의 *상대* 유사도만 보면 되므로 충분.
    """
    if not texts:
        return np.zeros((0, 0))

    # 어휘 + DF
    vocab: dict[str, int] = {}
    df: dict[str, int] = {}
    tokenized: list[list[str]] = []
    for text in texts:
        tokens = _tokenize_korean(text)
        tokenized.append(tokens)
        seen = set(tokens)
        for tok in seen:
            df[tok] = df.get(tok, 0) + 1
            if tok not in vocab:
                vocab[tok] = len(vocab)

    if not vocab:
        return np.zeros((len(texts), 1))

    n_docs = len(texts)
    matrix = np.zeros((n_docs, len(vocab)), dtype=np.float32)
    for i, tokens in enumerate(tokenized):
        if not tokens:
            continue
        # TF
        tf: dict[int, int] = {}
        for tok in tokens:
            j = vocab[tok]
            tf[j] = tf.get(j, 0) + 1
        for j, c in tf.items():
            tf_val = c / len(tokens)
            idf_val = float(np.log((1 + n_docs) / (1 + df.get(_inverse_lookup(vocab, j), 1))) + 1.0)
            matrix[i, j] = tf_val * idf_val

    # L2 정규화
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


# vocab idx → token 역참조 — 작은 문서에선 무시 가능한 비용.
def _inverse_lookup(vocab: dict[str, int], idx: int) -> str:
    for tok, j in vocab.items():
        if j == idx:
            return tok
    return ""


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return 0.0
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ── 메인 merger ───────────────────────────────────────────────────────────


@dataclass
class SemanticBlockMerger:
    """블록 → 의미 단위 chunk 병합기.

    Args:
        similarity_threshold: 이상이면 인접 block 병합. 한국어 콜센터 자료
            기준 0.18 권장.
        min_chars / max_chars: chunk 크기 제약.
        overlap: 강제 split 시 인접 chunk 의 char overlap.
    """

    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    min_chars: int = DEFAULT_MIN_CHARS
    max_chars: int = DEFAULT_MAX_CHARS
    overlap: int = DEFAULT_OVERLAP

    def merge(self, blocks: list[InputBlock]) -> list[MergedChunk]:
        """block 목록 → 의미 단위 병합된 chunk 목록.

        steps:
            1. heading_1/heading_2 / atomic 경계로 cluster split
            2. cluster 안에서 인접 block 임베딩 유사도 < threshold 면 split
            3. min_chars 미만 chunk → 인접 chunk 와 병합
            4. max_chars 초과 chunk → 강제 split (paragraph/문장 boundary 우선)
        """
        if not blocks:
            return []

        # 1) 경계 분할 — atomic 은 단독 cluster, heading_1/2 는 새 cluster 시작
        clusters: list[list[InputBlock]] = []
        cur: list[InputBlock] = []
        for b in blocks:
            if b.block_type in ATOMIC_TYPES:
                if cur:
                    clusters.append(cur)
                    cur = []
                clusters.append([b])
                continue
            if b.block_type in HARD_BOUNDARY_TYPES and cur:
                clusters.append(cur)
                cur = []
            cur.append(b)
        if cur:
            clusters.append(cur)

        # 2) cluster 안에서 유사도 split → 잠정 chunk 그룹
        groups: list[list[InputBlock]] = []
        for cluster in clusters:
            if len(cluster) <= 1:
                groups.append(cluster)
                continue
            if any(b.block_type in ATOMIC_TYPES for b in cluster):
                # atomic 단독 cluster — 그대로
                groups.append(cluster)
                continue
            # block 본문 임베딩 → 인접 유사도
            texts = [b.content for b in cluster]
            mat = _tfidf_matrix(texts)
            sub: list[InputBlock] = [cluster[0]]
            for i in range(1, len(cluster)):
                sim = _cosine(mat[i - 1], mat[i]) if mat.size else 1.0
                # heading_3 직후 paragraph 는 *항상* 같은 그룹으로 끌어당김 (구조 신호 우선)
                attract = (
                    cluster[i - 1].block_type == "heading_3"
                    or cluster[i].block_type.startswith("heading_")
                )
                if sim >= self.similarity_threshold or attract:
                    sub.append(cluster[i])
                else:
                    groups.append(sub)
                    sub = [cluster[i]]
            if sub:
                groups.append(sub)

        # 3) 작은 그룹 흡수 — min_chars 미만 → 직전 또는 직후 그룹과 병합.
        # heading_1 단독 cluster (도큐멘트 제목 등) 는 hard boundary 라 step 1
        # 에서 격리됐는데, content 가 너무 작으면 검색 score 가 떨어지므로
        # *직후* 그룹과 병합 — 컨텍스트 보존.
        merged: list[list[InputBlock]] = []
        i = 0
        while i < len(groups):
            g = groups[i]
            text_len = sum(len(b.content) for b in g)
            atomic = any(b.block_type in ATOMIC_TYPES for b in g)
            if not atomic and text_len < self.min_chars:
                # 우선 직전과 병합 시도
                if merged:
                    prev_atomic = any(b.block_type in ATOMIC_TYPES for b in merged[-1])
                    prev_len = sum(len(b.content) for b in merged[-1])
                    # 직전 그룹이 비-atomic 이고 합쳐도 max 안 넘으면 흡수
                    if not prev_atomic and prev_len + text_len <= self.max_chars:
                        merged[-1].extend(g)
                        i += 1
                        continue
                # 그렇지 않으면 직후와 병합 시도
                if i + 1 < len(groups):
                    nxt = groups[i + 1]
                    next_atomic = any(b.block_type in ATOMIC_TYPES for b in nxt)
                    next_len = sum(len(b.content) for b in nxt)
                    if not next_atomic and text_len + next_len <= self.max_chars:
                        merged.append(g + nxt)
                        i += 2
                        continue
            merged.append(g)
            i += 1

        # 4) 그룹 → MergedChunk 생성 (max_chars 초과 시 split)
        chunks: list[MergedChunk] = []
        for group in merged:
            cluster_id = uuid4()
            text = self._join_blocks(group)
            if len(text) <= self.max_chars:
                chunks.append(self._make_chunk(text, group, cluster_id, len(chunks)))
                continue
            # 강제 split — paragraph boundary 우선
            for piece, piece_blocks in self._force_split(text, group):
                chunks.append(
                    self._make_chunk(piece, piece_blocks, cluster_id, len(chunks))
                )

        # chunk_index 재정렬
        for i, c in enumerate(chunks):
            c.chunk_index = i
        return chunks

    @staticmethod
    def _join_blocks(blocks: list[InputBlock]) -> str:
        """block 본문을 묶어 chunk text 로 만든다.

        heading_* 는 그대로 첫 줄로 남기고 paragraph 는 본문 이어붙임.
        의미 보존을 위해 줄바꿈 포함.
        """
        parts: list[str] = []
        for b in blocks:
            content = b.content.strip()
            if not content:
                continue
            parts.append(content)
        return "\n\n".join(parts)

    def _make_chunk(
        self,
        text: str,
        source_blocks: list[InputBlock],
        cluster_id: UUID,
        chunk_index: int,
    ) -> MergedChunk:
        # D31a (#206 v5 §2.4) — neutral helper 사용 (metadata 풀세트 inject).
        from src.pipeline.processing.merged_chunk_builder import build_merged_chunk
        return build_merged_chunk(
            text=text,
            source_blocks=source_blocks,
            cluster_id=cluster_id,
            chunk_index=chunk_index,
        )

    def _force_split(
        self, text: str, source_blocks: list[InputBlock]
    ) -> list[tuple[str, list[InputBlock]]]:
        """max_chars 초과 chunk 강제 split.

        먼저 paragraph boundary, 다음 줄바꿈, 다음 마침표 순으로 분할.
        block attribution 은 *근사* — split 된 모든 piece 가 동일 source_block_ids
        를 공유 (fine-grained char-offset tracking 은 여기서는 생략, blocks
        테이블이 이미 단위 보존).
        """
        out: list[tuple[str, list[InputBlock]]] = []
        remaining = text
        while len(remaining) > self.max_chars:
            cut = self.max_chars
            for sep in ("\n\n", "\n", ". ", "! ", "? ", " "):
                pos = remaining.rfind(sep, self.min_chars, cut)
                if pos > 0:
                    cut = pos + len(sep)
                    break
            piece = remaining[:cut].strip()
            if piece:
                out.append((piece, source_blocks))
            # 오버랩 적용
            ov_start = max(0, cut - self.overlap)
            remaining = remaining[ov_start:]
        if remaining.strip():
            out.append((remaining.strip(), source_blocks))
        return out


# ── 검증 helper ───────────────────────────────────────────────────────────


def stats_for(blocks: list[InputBlock], chunks: list[MergedChunk]) -> dict[str, Any]:
    """병합 결과 요약 — 비율 + 평균 사이즈."""
    if not blocks:
        return {"blocks": 0, "chunks": 0, "ratio": 0.0, "avg_chunk_chars": 0}
    total_chunk_chars = sum(c.char_count for c in chunks)
    return {
        "blocks": len(blocks),
        "chunks": len(chunks),
        "ratio": round(len(chunks) / max(1, len(blocks)), 3),
        "avg_chunk_chars": round(total_chunk_chars / max(1, len(chunks)), 1),
        "min_chunk_chars": min((c.char_count for c in chunks), default=0),
        "max_chunk_chars": max((c.char_count for c in chunks), default=0),
        "block_types_per_chunk": [len(set(c.block_types)) for c in chunks][:10],
    }


# ── 데모 (작업 확인용) ───────────────────────────────────────────────────


def _demo() -> None:
    """수동 검증 — 샘플 block 으로 merger 동작 확인."""
    sample = [
        InputBlock(uuid4(), "heading_1", "배달 중 주문 취소 절차", 0),
        InputBlock(uuid4(), "heading_2", "사전 확인", 1),
        InputBlock(uuid4(), "paragraph", "고객의 주문 ID를 확인합니다.", 2),
        InputBlock(uuid4(), "paragraph", "배달원 위치를 확인합니다.", 3),
        InputBlock(uuid4(), "heading_2", "취소 처리", 4),
        InputBlock(
            uuid4(),
            "paragraph",
            "주문 취소 사유를 청취합니다. 배달 중 단계라도 사유에 따라 환불 가능합니다.",
            5,
        ),
        InputBlock(
            uuid4(),
            "paragraph",
            "환불 처리는 결제 수단별로 다릅니다. 카드는 즉시, 계좌이체는 영업일 3일.",
            6,
        ),
    ]
    merger = SemanticBlockMerger()
    chunks = merger.merge(sample)
    print(f"blocks={len(sample)} chunks={len(chunks)}")
    for c in chunks:
        print(
            f"  chunk[{c.chunk_index}] cluster={str(c.cluster_id)[:8]} "
            f"types={c.block_types} chars={c.char_count}"
        )
        print(f"    {c.content[:120]}")


__all__ = [
    "SemanticBlockMerger",
    "InputBlock",
    "MergedChunk",
    "stats_for",
    "DEFAULT_SIMILARITY_THRESHOLD",
    "DEFAULT_MIN_CHARS",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_OVERLAP",
    "HARD_BOUNDARY_TYPES",
    "ATOMIC_TYPES",
]


if __name__ == "__main__":
    import sys

    if "--demo" in sys.argv:
        _demo()
