"""SemHash-style pre-filter (델타 #7). NVIDIA SemDeDup 패턴.

Stage 2a: cosine vs candidate corpus, threshold + topk 축소.
Stage 2b: caller 가 reranker 로 최종 축소 (BGE reranker v2-m3).
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass
class Candidate:
    doc_id: str
    embedding: np.ndarray
    title: str
    snippet: str | None = None


class SemHashPreFilter:
    def __init__(
        self,
        stage2a_threshold: float = 0.55,
        stage2a_topk: int = 50,
        small_corpus_bypass: int = 30,
    ):
        self.threshold = stage2a_threshold
        self.topk = stage2a_topk
        self.small_bypass = small_corpus_bypass

    def stage2a_filter(
        self, new_embedding: np.ndarray, corpus: list[Candidate],
    ) -> list[Candidate]:
        if len(corpus) < self.small_bypass:
            return corpus
        M = np.stack([c.embedding for c in corpus])
        new = new_embedding / (np.linalg.norm(new_embedding) + 1e-12)
        sims = M @ new
        hits = [(i, float(s)) for i, s in enumerate(sims) if s >= self.threshold]
        hits.sort(key=lambda x: -x[1])
        top = hits[: self.topk]
        return [corpus[i] for i, _ in top]
