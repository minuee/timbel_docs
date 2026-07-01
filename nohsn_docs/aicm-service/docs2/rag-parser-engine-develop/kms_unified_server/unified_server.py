"""B200 통합 서비스 — reranker (sentence-transformers) + embedder (BGE-M3 via FlagEmbedding).

Gemma 4 는 transformers 5.x 이 필수인데, FlagEmbedding reranker 는 4.x API (prepare_for_model) 에
묶여있어 충돌. 해결: reranker 는 sentence-transformers CrossEncoder 로 교체 (modern API),
embedder 는 FlagEmbedding BGEM3FlagModel 그대로 유지 (이쪽은 transformers 5.x 호환).

기존 `host.docker.internal:7125/7130` 과 동일 응답 포맷:
    GET  /health   → {ready, reranker_loaded, embedder_loaded, sparse_head_loaded, device}
    POST /rerank   → { results: [{id, score, rank}] }
    POST /embed    → { vectors, sparse, latency_ms }
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI
from pydantic import BaseModel, Field
from rerank_batcher import RerankBatcher
from embed_batcher import EmbedBatcher


RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
DEVICE = os.environ.get("DEVICE", "cuda:0")
USE_FP16 = os.environ.get("USE_FP16", "1") != "0"

_reranker = None
_embedder = None
_lock = asyncio.Lock()
_rerank_batcher = None
_embed_batcher = None


async def _load_reranker():
    global _reranker
    if _reranker is not None:
        return
    async with _lock:
        if _reranker is not None:
            return
        # sentence-transformers CrossEncoder 는 transformers 5.x 와 호환
        from sentence_transformers import CrossEncoder
        dtype = torch.float16 if USE_FP16 else torch.float32
        _reranker = CrossEncoder(RERANKER_MODEL, device=DEVICE, model_kwargs={"torch_dtype": dtype})


async def _load_embedder():
    global _embedder
    if _embedder is not None:
        return
    async with _lock:
        if _embedder is not None:
            return
        from FlagEmbedding import BGEM3FlagModel
        _embedder = BGEM3FlagModel(EMBED_MODEL, use_fp16=USE_FP16, device=DEVICE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("PRELOAD", "0") == "1":
        await _load_reranker()
        await _load_embedder()
    global _rerank_batcher
    _rerank_batcher = RerankBatcher(
        predict_fn=lambda pairs: _reranker.predict(pairs, show_progress_bar=False),
        max_batch_pairs=int(os.environ.get("RERANK_MAX_BATCH_PAIRS", "160")),
        batch_wait_ms=int(os.environ.get("RERANK_BATCH_WAIT_MS", "8")),
        max_queue=int(os.environ.get("RERANK_MAX_QUEUE", "1000")),
    )
    _rerank_batcher.start()
    global _embed_batcher
    _embed_batcher = EmbedBatcher(
        predict_fn=lambda texts: _embedder.encode(
            texts, batch_size=16, return_dense=True, return_sparse=True
        ),
        max_batch_texts=int(os.environ.get("EMBED_MAX_BATCH_TEXTS", "32")),
        batch_wait_ms=int(os.environ.get("EMBED_BATCH_WAIT_MS", "6")),
        max_queue=int(os.environ.get("EMBED_MAX_QUEUE", "1000")),
    )
    _embed_batcher.start()
    yield


app = FastAPI(title="KMS B200 Unified Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "ready": True,
        "reranker_loaded": _reranker is not None,
        "embedder_loaded": _embedder is not None,
        "sparse_head_loaded": _embedder is not None,
        "device": DEVICE,
        "cuda_available": torch.cuda.is_available(),
    }


# ── Reranker ──────────────────────────────────────────────────────────────

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


@app.post("/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest):
    await _load_reranker()
    if not req.candidates:
        return RerankResponse(results=[], latency_ms=0, model=RERANKER_MODEL)
    if _rerank_batcher is None:
        raise RuntimeError("rerank batcher not initialized")
    t0 = time.perf_counter()
    pairs = [[req.query, c.content] for c in req.candidates]
    scores = await _rerank_batcher.submit(pairs)
    scores = [float(s) for s in scores]
    ranked = sorted(
        zip(req.candidates, scores), key=lambda x: x[1], reverse=True
    )[: req.top_k]
    results = [
        RerankResult(id=c.id, score=s, rank=i + 1)
        for i, (c, s) in enumerate(ranked)
    ]
    return RerankResponse(
        results=results,
        latency_ms=int((time.perf_counter() - t0) * 1000),
        model=RERANKER_MODEL,
    )


# ── Embedder (dense + sparse) ─────────────────────────────────────────────
#
# 호환성 필수: 기존 KMS API (src/search/embedding_proxy.py) 는 `{"text": "..."}` 단일
# 문자열 포맷 + `{"dense":[...], "sparse":{"token_str": weight}}` 응답을 기대.
# 새 KMS-Plus 경로는 `{"texts":[...]}` 배치 포맷 사용.
# 하나의 /embed 엔드포인트가 둘 다 수용.


@app.post("/embed")
async def embed(payload: dict):
    """양방향 호환 embed:
    - Legacy: {"text": "단일"} → {"dense":[...], "sparse":{"token_str":weight}}
    - Batch:  {"texts":["..."], "return_dense":bool, "return_sparse":bool}
              → {"dense":[[...]], "sparse":[{"indices":[], "values":[]}], "latency_ms":int, "model":str}
    """
    await _load_embedder()
    t0 = time.perf_counter()

    # 포맷 감지
    is_legacy = "text" in payload and "texts" not in payload
    if is_legacy:
        text = str(payload.get("text") or "")
        if not text:
            return {"dense": [], "sparse": {}}
        if _embed_batcher is None:
            raise RuntimeError("embed batcher not initialized")
        dense_vec, lw = await _embed_batcher.submit(text)
        single_dense = (
            dense_vec.tolist() if hasattr(dense_vec, "tolist")
            else (list(dense_vec) if dense_vec is not None else [])
        )
        single_sparse = {str(k): float(v) for k, v in (lw or {}).items()}
        return {"dense": single_dense, "sparse": single_sparse}
    else:
        texts = list(payload.get("texts") or [])
        return_dense = bool(payload.get("return_dense", True))
        return_sparse = bool(payload.get("return_sparse", True))
        if not texts:
            return {
                "dense": [],
                "sparse": [],
                "latency_ms": 0,
                "model": EMBED_MODEL,
            }

    batch_size = int(payload.get("batch_size", 16))

    def _encode():
        return _embedder.encode(
            texts,
            batch_size=batch_size,
            return_dense=return_dense,
            return_sparse=return_sparse,
        )

    out = await asyncio.to_thread(_encode)

    # 공통 추출
    dense_list: list[list[float]] | None = None
    if return_dense and "dense_vecs" in out:
        dense_list = [
            (v.tolist() if hasattr(v, "tolist") else list(v))
            for v in out["dense_vecs"]
        ]

    if is_legacy:
        # 단일 응답 — dense: 1차원, sparse: dict[str, float]
        single_dense = dense_list[0] if dense_list else []
        single_sparse_dict: dict[str, float] = {}
        if return_sparse and "lexical_weights" in out and out["lexical_weights"]:
            lw = out["lexical_weights"][0]
            single_sparse_dict = {str(k): float(v) for k, v in lw.items()}
        return {
            "dense": single_dense,
            "sparse": single_sparse_dict,
        }

    # 배치 응답 — 기존 EmbedResponse 포맷 유지
    sparse_list: list[dict] | None = None
    if return_sparse and "lexical_weights" in out:
        sparse_list = []
        for lw in out["lexical_weights"]:
            sparse_list.append({
                "indices": [int(k) for k in lw.keys()],
                "values": [float(v) for v in lw.values()],
            })
    return {
        "dense": dense_list,
        "sparse": sparse_list,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "model": EMBED_MODEL,
    }
