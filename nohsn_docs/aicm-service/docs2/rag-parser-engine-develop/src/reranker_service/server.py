"""GPU reranker sidecar — serves bge-reranker-base via FastAPI.

Runs inside a container that already has torch+cuda+FlagEmbedding installed
(re-uses the pipeline-worker image). kms-api calls this over HTTP instead of
loading a local CPU reranker model.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

MODEL_NAME = os.environ.get("RERANKER_MODEL", "BAAI/bge-reranker-base")
DEVICE = os.environ.get("RERANKER_DEVICE", "cuda")
USE_FP16 = os.environ.get("RERANKER_FP16", "1") != "0"

app = FastAPI(title="KMS Reranker", version="1.0.0")

_reranker_lock = asyncio.Lock()
_reranker = None
_ready = False


class RerankPair(BaseModel):
    id: str
    content: str


class RerankRequest(BaseModel):
    query: str
    candidates: list[RerankPair] = Field(default_factory=list)
    top_k: int = 10


class RerankResult(BaseModel):
    id: str
    score: float
    rank: int


class RerankResponse(BaseModel):
    results: list[RerankResult]
    latency_ms: int
    model: str


async def _ensure_loaded() -> None:
    global _reranker, _ready
    if _ready:
        return
    async with _reranker_lock:
        if _ready:
            return
        from FlagEmbedding import FlagReranker

        loop = asyncio.get_running_loop()

        def _load() -> Any:
            r = FlagReranker(MODEL_NAME, use_fp16=USE_FP16, device=DEVICE)
            r.compute_score([("warmup", "document")], normalize=True)
            return r

        _reranker = await loop.run_in_executor(None, _load)
        _ready = True


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ready": _ready,
        "model": MODEL_NAME,
        "device": DEVICE,
    }


@app.post("/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest) -> RerankResponse:
    await _ensure_loaded()
    start = time.monotonic()

    if not req.candidates:
        return RerankResponse(results=[], latency_ms=0, model=MODEL_NAME)

    pairs = [(req.query, c.content) for c in req.candidates]
    loop = asyncio.get_running_loop()
    scores = await loop.run_in_executor(
        None, lambda: _reranker.compute_score(pairs, normalize=True)
    )
    if isinstance(scores, (int, float)):
        scores = [float(scores)]

    scored = [
        (req.candidates[i].id, max(0.0, min(1.0, float(s))))
        for i, s in enumerate(scores)
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[: req.top_k]

    results = [
        RerankResult(id=item_id, score=score, rank=rank + 1)
        for rank, (item_id, score) in enumerate(top)
    ]
    latency_ms = int((time.monotonic() - start) * 1000)
    return RerankResponse(results=results, latency_ms=latency_ms, model=MODEL_NAME)


# ── Embedding endpoint (BGE-M3, GPU) ──
_embedder = None
_embedder_lock = asyncio.Lock()
_embedder_ready = False


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    dense: list[float]
    sparse: dict[str, float]
    latency_ms: int


async def _ensure_embedder() -> None:
    global _embedder, _embedder_ready
    if _embedder_ready:
        return
    async with _embedder_lock:
        if _embedder_ready:
            return
        from FlagEmbedding import BGEM3FlagModel

        loop = asyncio.get_running_loop()

        def _load():
            m = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True, device=DEVICE)
            return m

        _embedder = await loop.run_in_executor(None, _load)
        _embedder_ready = True


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest) -> EmbedResponse:
    await _ensure_embedder()
    start = time.monotonic()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _embedder.encode(
            [req.text], return_dense=True, return_sparse=True, return_colbert_vecs=False
        ),
    )
    dense = result["dense_vecs"][0].tolist()
    raw_sparse = result["lexical_weights"][0]
    sparse = {str(int(k)): float(v) for k, v in raw_sparse.items()}
    latency_ms = int((time.monotonic() - start) * 1000)
    return EmbedResponse(dense=dense, sparse=sparse, latency_ms=latency_ms)


@app.on_event("startup")
async def _startup() -> None:
    asyncio.create_task(_ensure_loaded())
