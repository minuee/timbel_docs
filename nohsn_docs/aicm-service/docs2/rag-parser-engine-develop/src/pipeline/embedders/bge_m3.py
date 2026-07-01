"""BGE-M3 임베더 -- Dense (1024d) + Sparse 벡터 동시 생성.

specs/02 5.1 구현.

D56 §A PR-A: `EMBEDDING_PROXY_URL` 환경변수 설정 시 외부 B200 사이드카
(`:7130/embed`) HTTP 호출로 위임. proxy 미설정 시 로컬 FlagEmbedding fallback (dev).

Redis 기반 임베딩 캐시를 내장하여 동일 텍스트 재연산을 방지한다.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import weakref
from typing import Any, Optional

import httpx
import redis.asyncio as aioredis
from pydantic import BaseModel, Field

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 임베딩 캐시 상수
# ---------------------------------------------------------------------------
_EMBED_CACHE_PREFIX = "aicm:embed:bge-m3"
_EMBED_CACHE_TTL = 30 * 24 * 3600  # 30일
_MIN_TEXT_LENGTH_FOR_CACHE = 10  # 이보다 짧은 텍스트는 캐시 스킵

# ---------------------------------------------------------------------------
# proxy 호출 상수 (D56 §A PR-A)
# ---------------------------------------------------------------------------
_PROXY_DEFAULT_CONCURRENCY = 16  # GPT-5 권고: 초기 16, 관측 후 8~32 튜닝
_PROXY_DEFAULT_TIMEOUT_READ = 20.0  # ingest read timeout (s)
_PROXY_DEFAULT_TIMEOUT_CONNECT = 3.0
_PROXY_MAX_RETRIES = 3
_PROXY_BACKOFF_BASE_MS = 100


class EmbeddingResult(BaseModel):
    """단일 텍스트의 임베딩 결과."""

    dense: list[float] = Field(default_factory=list)  # 1024d
    sparse: dict[int, float] = Field(default_factory=dict)  # {token_id: weight}


class EmbeddingCache:
    """Redis 기반 임베딩 캐시.

    캐시 키: ``aicm:embed:bge-m3:{sha256(text)}``
    캐시 값: gzip 압축된 JSON ``{dense: [...], sparse: {...}}``
    TTL: 30일. 10자 미만 텍스트는 캐시하지 않는다.
    캐시 실패는 조용히 무시하여 실제 연산을 차단하지 않는다.
    """

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._redis = redis_client
        self.hit_count: int = 0
        self.miss_count: int = 0

    async def _get_redis(self) -> aioredis.Redis:
        """지연 초기화된 Redis 클라이언트 반환."""
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
        return self._redis

    @staticmethod
    def _cache_key(text: str) -> str:
        """텍스트의 SHA-256 해시 기반 캐시 키."""
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{_EMBED_CACHE_PREFIX}:{text_hash}"

    @staticmethod
    def _should_cache(text: str) -> bool:
        """캐시 대상 여부 판단. 너무 짧은 텍스트는 스킵."""
        return len(text) >= _MIN_TEXT_LENGTH_FOR_CACHE

    async def get(self, text: str) -> EmbeddingResult | None:
        """캐시에서 임베딩 결과 조회. 미스 시 None."""
        if not self._should_cache(text):
            self.miss_count += 1
            return None
        try:
            redis = await self._get_redis()
            raw = await redis.get(self._cache_key(text))
            if raw is None:
                self.miss_count += 1
                return None
            decompressed = gzip.decompress(raw)
            data = json.loads(decompressed)
            self.hit_count += 1
            log.debug("embedding_cache_hit", text_len=len(text))
            # D56 §A: sparse key 명시 int 캐스팅 (JSON 직렬화로 str 키 저장됨)
            sparse = {int(k): float(v) for k, v in data["sparse"].items()}
            return EmbeddingResult(dense=data["dense"], sparse=sparse)
        except Exception:
            log.warning("embedding_cache_get_failed", exc_info=True)
            self.miss_count += 1
            return None

    async def set(self, text: str, result: EmbeddingResult) -> None:
        """임베딩 결과를 캐시에 저장. gzip 압축 후 Redis 저장."""
        if not self._should_cache(text):
            return
        try:
            redis = await self._get_redis()
            data = json.dumps(
                {"dense": result.dense, "sparse": result.sparse},
                ensure_ascii=False,
            )
            compressed = gzip.compress(data.encode("utf-8"), compresslevel=6)
            await redis.set(self._cache_key(text), compressed, ex=_EMBED_CACHE_TTL)
            log.debug("embedding_cache_set", text_len=len(text))
        except Exception:
            log.warning("embedding_cache_set_failed", exc_info=True)

    async def get_batch(self, texts: list[str]) -> dict[int, EmbeddingResult]:
        """배치 조회. 인덱스 -> EmbeddingResult 매핑 반환 (캐시 히트만)."""
        cached: dict[int, EmbeddingResult] = {}
        if not texts:
            return cached
        try:
            redis = await self._get_redis()
            keys = [self._cache_key(t) for t in texts]
            raws = await redis.mget(keys)
            for i, raw in enumerate(raws):
                if not self._should_cache(texts[i]):
                    self.miss_count += 1
                    continue
                if raw is None:
                    self.miss_count += 1
                    continue
                try:
                    decompressed = gzip.decompress(raw)
                    data = json.loads(decompressed)
                    # D56 §A: sparse key 명시 int 캐스팅
                    sparse = {int(k): float(v) for k, v in data["sparse"].items()}
                    cached[i] = EmbeddingResult(dense=data["dense"], sparse=sparse)
                    self.hit_count += 1
                except Exception:
                    self.miss_count += 1
        except Exception:
            log.warning("embedding_cache_batch_get_failed", exc_info=True)
            # 전체 미스 처리
            self.miss_count += len(texts) - len(cached)
        return cached

    async def set_batch(self, texts: list[str], results: list[EmbeddingResult]) -> None:
        """배치 저장. 파이프라인으로 일괄 저장."""
        if not texts or not results:
            return
        try:
            redis = await self._get_redis()
            pipe = redis.pipeline()
            for text, result in zip(texts, results):
                if not self._should_cache(text):
                    continue
                data = json.dumps(
                    {"dense": result.dense, "sparse": result.sparse},
                    ensure_ascii=False,
                )
                compressed = gzip.compress(data.encode("utf-8"), compresslevel=6)
                pipe.set(self._cache_key(text), compressed, ex=_EMBED_CACHE_TTL)
            await pipe.execute()
        except Exception:
            log.warning("embedding_cache_batch_set_failed", exc_info=True)

    @property
    def hit_rate(self) -> float:
        """캐시 적중률."""
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else 0.0

    def reset_stats(self) -> None:
        """통계 초기화."""
        self.hit_count = 0
        self.miss_count = 0


class BGEM3Embedder:
    """BGE-M3 임베더. Dense + Sparse 벡터를 하나의 모델로 동시 생성한다.

    D56 §A PR-A 분기:
    - `EMBEDDING_PROXY_URL` 설정 시 → 외부 B200 사이드카 `:7130/embed` HTTP 호출.
      FlagEmbedding import 도 하지 않아 워커 메모리 회수 (-2 GiB/워커).
      proxy 도달성 실패 = hard fail (RuntimeError) — 의도된 메모리 회수 보호.
    - 미설정 시 → 기존 로컬 FlagEmbedding (dev/로컬 GPU).

    Redis 기반 임베딩 캐시로 동일 텍스트 재연산을 자동 방지한다.
    """

    def __init__(
        self,
        model_name: str = "",
        device: str = "",
        use_fp16: bool = True,
        max_length: int = 512,
        embedding_cache: EmbeddingCache | None = None,
    ) -> None:
        self._model_name = model_name or settings.EMBEDDING_MODEL
        self._device = device or settings.EMBEDDING_DEVICE
        self._use_fp16 = use_fp16
        self._max_length = max_length
        self._model: Optional[Any] = None
        self._cache = embedding_cache or EmbeddingCache()

        # D56 §A: proxy 우선 사용 결정 — 환경변수 유무로만 토글 (GPT-5 권고).
        proxy_url = (getattr(settings, "EMBEDDING_PROXY_URL", "") or "").strip()
        self._proxy_url: str = proxy_url.rstrip("/")
        self._use_proxy: bool = bool(self._proxy_url)
        # 이벤트 루프별 클라이언트/세마포어 캐시 (GPT-5 권고: race 회피)
        # WeakKeyDictionary: 루프 객체 자체 키 → 루프 GC 시 자동 소거 (id 재사용 위험 0)
        self._http_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()
        self._proxy_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()
        # 동시성 / 타임아웃은 env override 허용 (하드코딩 금지 절칙)
        self._proxy_concurrency = int(
            os.environ.get("EMBEDDING_PROXY_CONCURRENCY", _PROXY_DEFAULT_CONCURRENCY)
        )
        self._proxy_timeout_read = float(
            os.environ.get("EMBEDDING_PROXY_TIMEOUT_READ", _PROXY_DEFAULT_TIMEOUT_READ)
        )

        if self._use_proxy:
            log.info(
                "bge_m3_proxy_mode",
                proxy_url=self._proxy_url,
                concurrency=self._proxy_concurrency,
                timeout_read=self._proxy_timeout_read,
                reason="EMBEDDING_PROXY_URL set — FlagEmbedding 로드 건너뜀",
            )
            # proxy 모드에서는 device/fp16 의미 없음 (proxy 가 결정)
            return

        # GPU 사용 불가 시 CPU 폴백 (로컬 모드 한정)
        if self._device == "cuda":
            try:
                import torch

                if not torch.cuda.is_available():
                    self._device = "cpu"
                    self._use_fp16 = False  # CPU 에서는 fp16 비활성화
                    log.warning(
                        "cuda_not_available_using_cpu",
                        original_device="cuda",
                        fallback_device="cpu",
                    )
            except ImportError:
                self._device = "cpu"
                self._use_fp16 = False
                log.warning(
                    "torch_not_installed_using_cpu",
                    fallback_device="cpu",
                )

    # ------------------------------------------------------------------
    # proxy HTTP 호출 (D56 §A PR-A)
    # ------------------------------------------------------------------
    async def _get_http_client(self) -> httpx.AsyncClient:
        """proxy 호출용 httpx.AsyncClient — 이벤트 루프별 캐시 (race 회피).

        GPT-5 post v2 권고: 루프 객체 자체 키 + WeakKeyDictionary 사용.
        - 루프 객체 동일성으로 충돌/재사용 위험 제거 (id() 재사용 위험 0)
        - 루프 GC 시 엔트리 자동 제거 → 메모리 누수 0
        """
        loop = asyncio.get_running_loop()
        existing = self._http_clients.get(loop)
        if existing is not None and not existing.is_closed:
            return existing
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=_PROXY_DEFAULT_TIMEOUT_CONNECT,
                read=self._proxy_timeout_read,
                write=10.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=64,
                max_keepalive_connections=32,
                keepalive_expiry=60.0,
            ),
        )
        self._http_clients[loop] = client
        return client

    def _get_semaphore(self) -> asyncio.Semaphore:
        """동시 호출 제한 세마포어 — 이벤트 루프별 lazy 생성 (race 회피).

        GPT-5 post v2 권고: WeakKeyDictionary 로 루프 객체 키 + 자동 소거.
        """
        loop = asyncio.get_running_loop()
        sem = self._proxy_semaphores.get(loop)
        if sem is None:
            sem = asyncio.Semaphore(self._proxy_concurrency)
            self._proxy_semaphores[loop] = sem
        return sem

    async def _embed_via_proxy_one(self, text: str) -> EmbeddingResult:
        """proxy `/embed` 단일 텍스트 호출 (재시도 + sparse int 캐스팅).

        Raises:
            RuntimeError: proxy 도달 불가 또는 retry exhausted (hard fail).
        """
        client = await self._get_http_client()
        url = f"{self._proxy_url}/embed"
        sem = self._get_semaphore()
        last_exc: Exception | None = None

        for attempt in range(_PROXY_MAX_RETRIES + 1):
            try:
                async with sem:
                    resp = await client.post(url, json={"text": text})
                # 429 + 모든 5xx (>=500) 재시도 — GPT-5 post v1 권고
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = RuntimeError(
                        f"proxy retryable status {resp.status_code}"
                    )
                    # 마지막 시도에서는 sleep 생략 (불필요 대기 방지)
                    if attempt >= _PROXY_MAX_RETRIES:
                        break
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            await asyncio.sleep(float(retry_after))
                        except ValueError:
                            await asyncio.sleep(
                                _PROXY_BACKOFF_BASE_MS / 1000.0 * (2 ** attempt)
                            )
                    else:
                        await asyncio.sleep(
                            _PROXY_BACKOFF_BASE_MS / 1000.0 * (2 ** attempt)
                        )
                    continue
                resp.raise_for_status()
                data = resp.json()
                dense = [float(x) for x in data.get("dense", [])]
                raw_sparse = data.get("sparse", {})
                sparse = {int(k): float(v) for k, v in raw_sparse.items()}
                return EmbeddingResult(dense=dense, sparse=sparse)

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt >= _PROXY_MAX_RETRIES:
                    break
                await asyncio.sleep(
                    _PROXY_BACKOFF_BASE_MS / 1000.0 * (2 ** attempt)
                )
                continue
            except httpx.HTTPStatusError as exc:
                # 4xx (429 제외) — 즉시 실패. 5xx 는 위 status_code 분기로 처리되므로
                # raise_for_status 가 5xx 로 도달하지 않음.
                raise RuntimeError(
                    f"embedding proxy HTTP error: {exc.response.status_code}"
                ) from exc
            except Exception as exc:
                last_exc = exc
                break

        log.error(
            "embedding_proxy_exhausted",
            proxy_url=self._proxy_url,
            attempts=_PROXY_MAX_RETRIES + 1,
            error=str(last_exc),
        )
        raise RuntimeError(
            f"embedding proxy unreachable after {_PROXY_MAX_RETRIES + 1} attempts: "
            f"{last_exc}"
        ) from last_exc

    async def _embed_via_proxy_batch(
        self, texts: list[str]
    ) -> list[EmbeddingResult]:
        """N 텍스트를 asyncio.gather 로 병렬 proxy 호출 (Semaphore 로 동시성 제한)."""
        if not texts:
            return []
        coros = [self._embed_via_proxy_one(t) for t in texts]
        return await asyncio.gather(*coros)

    def _ensure_model(self) -> Any:
        """모델을 지연 로드한다. proxy 모드에서는 호출되지 않음."""
        if self._use_proxy:
            # GPT-5 권고: proxy 모드에서는 모델 import / 로드 금지.
            raise RuntimeError(
                "BGEM3Embedder._ensure_model called in proxy mode — "
                "should not happen. EMBEDDING_PROXY_URL is set; "
                "use _embed_via_proxy_* instead."
            )
        if self._model is not None:
            return self._model

        log.info(
            "bge_m3_model_loading",
            model=self._model_name,
            device=self._device,
            fp16=self._use_fp16,
            msg="모델 다운로드/로드 시작 (최초 실행 시 수 분 소요될 수 있음)",
        )

        try:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(
                self._model_name,
                use_fp16=self._use_fp16,
                device=self._device,
            )
            log.info(
                "bge_m3_model_loaded",
                model=self._model_name,
                device=self._device,
                fp16=self._use_fp16,
            )
        except ImportError:
            log.error("FlagEmbedding 패키지가 필요합니다: pip install FlagEmbedding")
            raise
        return self._model

    @property
    def cache(self) -> EmbeddingCache:
        """임베딩 캐시 인스턴스 접근."""
        return self._cache

    async def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 0,
    ) -> list[EmbeddingResult]:
        """텍스트 배치를 임베딩한다.

        캐시 히트된 텍스트는 모델 연산을 건너뛰고,
        캐시 미스 텍스트만 모델로 임베딩한 후 캐시에 저장한다.
        """
        if not texts:
            return []

        # 캐시에서 일괄 조회
        cached_map = await self._cache.get_batch(texts)

        # 캐시 미스 텍스트 수집
        miss_indices = [i for i in range(len(texts)) if i not in cached_map]

        if miss_indices:
            miss_texts = [texts[i] for i in miss_indices]
            bs = batch_size or settings.EMBEDDING_BATCH_SIZE

            if self._use_proxy:
                # D56 §A: 외부 proxy 병렬 호출 (Semaphore 로 동시성 제한)
                miss_results = await self._embed_via_proxy_batch(miss_texts)
            else:
                miss_results = await asyncio.to_thread(
                    self._embed_sync, miss_texts, bs
                )

            # 캐시 저장 및 결과 매핑
            for idx, result in zip(miss_indices, miss_results):
                cached_map[idx] = result

            # 캐시에 비동기 저장 (fire-and-forget)
            try:
                await self._cache.set_batch(miss_texts, miss_results)
            except Exception:
                log.warning("embed_batch_cache_store_failed", exc_info=True)

            log.info(
                "embed_batch_completed",
                total=len(texts),
                cache_hits=len(texts) - len(miss_indices),
                cache_misses=len(miss_indices),
                mode="proxy" if self._use_proxy else "local",
            )
        else:
            log.info(
                "embed_batch_all_cached",
                total=len(texts),
            )

        # 원래 순서대로 결과 조립
        return [cached_map[i] for i in range(len(texts))]

    def _embed_sync(self, texts: list[str], batch_size: int) -> list[EmbeddingResult]:
        model = self._ensure_model()
        outputs = model.encode(
            texts,
            batch_size=batch_size,
            max_length=self._max_length,
            return_dense=True,
            return_sparse=True,
        )

        results: list[EmbeddingResult] = []
        dense_vecs = outputs["dense_vecs"]
        sparse_weights = outputs["lexical_weights"]

        for i in range(len(texts)):
            dense = dense_vecs[i].tolist()
            sparse = self._convert_sparse(sparse_weights[i])
            results.append(EmbeddingResult(dense=dense, sparse=sparse))

        return results

    @staticmethod
    def _convert_sparse(lexical_weight: Any) -> dict[int, float]:
        """FlagEmbedding sparse 출력 -> {token_id: weight} dict."""
        result: dict[int, float] = {}
        if isinstance(lexical_weight, dict):
            for k, v in lexical_weight.items():
                result[int(k)] = float(v)
        return result

    async def embed_single(self, text: str) -> EmbeddingResult:
        """단일 텍스트 임베딩 편의 메서드. 캐시 우선 조회."""
        # 단일 텍스트는 직접 캐시 조회로 mget 오버헤드 회피
        cached = await self._cache.get(text)
        if cached is not None:
            return cached

        if self._use_proxy:
            # D56 §A: 외부 proxy 호출 (단일)
            result = await self._embed_via_proxy_one(text)
        else:
            results = await asyncio.to_thread(self._embed_sync, [text], 1)
            result = results[0]

        # 캐시 저장
        try:
            await self._cache.set(text, result)
        except Exception:
            log.warning("embed_single_cache_store_failed", exc_info=True)

        return result

    async def aclose(self) -> None:
        """proxy 모드 HTTP 클라이언트 정리 — 현재 루프 클라이언트 우선 종료.

        GPT-5 post v2 권고: 다른 루프의 client 를 현재 루프에서 close 하는 건
        unsafe — 현재 루프 자원만 확실히 await close. WeakKeyDictionary 가
        과거 루프 엔트리를 자연 소거.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            current = self._http_clients.get(loop)
            if current is not None and not current.is_closed:
                try:
                    await current.aclose()
                except Exception:
                    pass
                # WeakKeyDictionary 는 __setitem__ 만 허용 — pop 가능
                try:
                    del self._http_clients[loop]
                except KeyError:
                    pass
            try:
                del self._proxy_semaphores[loop]
            except KeyError:
                pass
