"""Cross-encoder 리랭커 — bge-reranker 기반 정밀 재평가.

RERANKER_URL 환경변수로 원격 GPU reranker 서비스(B200)를 호출한다.
CPU 폴백은 제거됨 — 원격 실패 시 명시적 에러를 발생시킨다.
"""

from __future__ import annotations

import asyncio
import os
import time
from functools import partial

import httpx

from src.common.config import settings
from src.common.logging import get_logger
from src.search.models import SearchHit, SearchTraceStep

log = get_logger(__name__)

_REMOTE_URL = os.environ.get("RERANKER_URL", "").strip()

# reranker title prefix 정리용 파일 확장자 집합 — 임베딩 입력(_clean_doc_title,
# embed_worker.py)과 *동일 surface form* 을 만들기 위함(코드리뷰 #1). 확장자가 붙은
# 제목("환매조건.pdf")을 그대로 넣으면 임베딩이 인덱싱한 "환매조건" 과 토큰이 어긋나
# cross-doc 변별이 약해진다. search 레이어가 pipeline.workers(embed_worker) 를 import
# 하지 않도록 함수 import 대신 동일 상수만 복제한다(도메인 키워드 아님, 구조 상수).
_DOC_EXTENSIONS = {
    ".docx", ".doc", ".pdf", ".hwp", ".hwpx",
    ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".md",
}


class CrossEncoderReranker:
    """
    상위 후보를 Cross-encoder로 정밀 재평가.

    - 모델: bge-reranker-v2-m3
    - 입력: (query, chunk_content) 쌍
    - 출력: relevance score (0.0 ~ 1.0)
    - 적용 대상: RRF 통합 후 Top-N -> 최종 Top-K
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        remote_url: str | None = None,
    ) -> None:
        self._model_name = model_name or settings.RERANKER_MODEL
        self._device = device or settings.RERANKER_DEVICE
        self._reranker = None
        self._initialized = False
        self._remote_url = remote_url or _REMOTE_URL
        self._http: httpx.AsyncClient | None = None
        if self._remote_url:
            log.info("cross_encoder_remote_mode", url=self._remote_url)

    def _ensure_initialized(self) -> None:
        """모델을 지연 로딩."""
        if self._initialized:
            return
        try:
            from FlagEmbedding import FlagReranker

            self._reranker = FlagReranker(
                self._model_name,
                use_fp16=True,
                device=self._device,
            )
            self._initialized = True
            log.info(
                "cross_encoder_initialized",
                model=self._model_name,
                device=self._device,
            )
        except Exception:
            log.exception("cross_encoder_init_failed", model=self._model_name)
            raise

    def _compute_scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        """동기 스코어 계산 (CPU/GPU 바운드)."""
        self._ensure_initialized()
        raw_scores = self._reranker.compute_score(pairs, normalize=True)
        # compute_score는 단일 쌍이면 float, 여러 쌍이면 list[float] 반환
        if isinstance(raw_scores, (int, float)):
            raw_scores = [float(raw_scores)]
        return [self._normalize_score(s) for s in raw_scores]

    @staticmethod
    def _rerank_text(hit: SearchHit) -> str:
        """reranker 입력 텍스트 — document_title(+section)을 content 앞에 붙인다.

        cross-encoder 에 content 만 보내면 *동일 구조의 타 문서 블럭*(예: 펀드별
        "환매수수료" 표)을 구분 못 해 질의가 특정 문서를 지목해도 cross-doc 오순위가
        발생한다(reranker 가 문서명을 못 봄). 임베딩 _embedding_text_with_context 및
        llm_reranker 와 동일하게 문서/섹션 컨텍스트를 prefix 로 주입해 변별을 살린다.
        section_title 은 QNA 블럭의 질문이기도 해 답변 content 의 rerank 정확도도 높인다.
        """
        title = (hit.document_title or "").strip()
        # 파일 확장자 제거 — 임베딩 입력(_clean_doc_title)과 surface form 일치(코드리뷰 #1).
        _root, _ext = os.path.splitext(title)
        if _ext.lower() in _DOC_EXTENSIONS:
            title = _root.strip()
        section = (hit.section_title or "").strip()
        content = hit.content or ""
        if title and section:
            return f"{title} > {section}\n{content}"
        if title:
            return f"{title}\n{content}"
        return content

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._http

    async def _remote_score(
        self,
        query: str,
        candidates: list[SearchHit],
    ) -> list[float]:
        """원격 reranker 서비스 호출. 원본 후보 순서대로 스코어 리스트 반환."""
        client = await self._get_http()
        payload = {
            "query": query,
            "candidates": [
                {"id": str(i), "content": self._rerank_text(hit)}
                for i, hit in enumerate(candidates)
            ],
            "top_k": len(candidates),
        }
        resp = await client.post(self._remote_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        # 결과를 원본 index 순서로 재정렬
        score_by_id: dict[str, float] = {
            r["id"]: float(r["score"]) for r in data.get("results", [])
        }
        return [
            self._normalize_score(score_by_id.get(str(i), 0.0))
            for i in range(len(candidates))
        ]

    @staticmethod
    def _normalize_score(score: float) -> float:
        """BGE reranker v2-m3 raw logit 을 sigmoid 로 [0, 1] 정규화.

        원격 reranker 서비스(B200) 가 반환하는 score 는 모델의 raw logit 이며
        음수 범위가 대부분 (예: -0.66 = relevant, -11.0 = irrelevant).
        이전 구현의 `max(0, min(1, score))` 는 모든 음수를 0 으로 clip 해버려
        rerank_score 가 전부 0 이 되고 정렬 구분이 불가능했음.
        sigmoid 를 써서 logit 을 확률로 변환하면 상대 순서가 보존된다:
          -0.66 → sigmoid ≈ 0.34
          -11.0 → sigmoid ≈ 1.7e-5
        """
        import math
        s = float(score)
        # 안정성: 매우 큰 값에서 overflow 방지
        if s >= 0:
            return 1.0 / (1.0 + math.exp(-s))
        exp_s = math.exp(s)
        return exp_s / (1.0 + exp_s)

    async def rerank(
        self,
        query: str,
        candidates: list[SearchHit],
        top_k: int = 5,
    ) -> tuple[list[SearchHit], SearchTraceStep]:
        """
        리랭킹 수행.

        CPU/GPU 바운드 작업을 스레드풀에서 실행하여 이벤트 루프 블로킹 방지.
        """
        start = time.monotonic()

        if not candidates:
            trace = SearchTraceStep(
                step_name="reranking",
                latency_ms=0,
                candidate_count=0,
                details={"skipped": True, "reason": "no candidates"},
            )
            return [], trace

        # 원격 GPU reranker 경로. 실패 시 검색이 죽지 않도록 융합순서로 폴백.
        try:
            if not self._remote_url:
                raise RuntimeError("RERANKER_URL 미설정")
            scores = await self._remote_score(query, candidates)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "rerank_failed_fusion_fallback",
                error=str(exc),
                candidate_count=len(candidates),
            )
            result = candidates[:top_k]
            trace = SearchTraceStep(
                step_name="reranking",
                latency_ms=int((time.monotonic() - start) * 1000),
                candidate_count=len(result),
                details={"fallback": "fusion_order", "error": str(exc)},
            )
            return result, trace

        # 스코어 할당
        for hit, score in zip(candidates, scores):
            hit.rerank_score = score

        # 리랭크 스코어 기준 내림차순 정렬
        candidates.sort(key=lambda x: x.rerank_score or 0.0, reverse=True)
        result = candidates[:top_k]

        elapsed_ms = int((time.monotonic() - start) * 1000)
        trace = SearchTraceStep(
            step_name="reranking",
            latency_ms=elapsed_ms,
            candidate_count=len(result),
            details={
                "input_count": len(candidates),
                "output_count": len(result),
                "model": self._model_name,
                "top_rerank_scores": [
                    round(h.rerank_score, 4) for h in result[:5] if h.rerank_score is not None
                ],
            },
        )

        log.info(
            "reranking_completed",
            input_count=len(candidates),
            output_count=len(result),
            latency_ms=elapsed_ms,
        )
        return result, trace
