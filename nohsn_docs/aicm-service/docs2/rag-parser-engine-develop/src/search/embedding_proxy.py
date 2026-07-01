"""임베딩 프록시 클라이언트 — 원격 Search Proxy의 /embed 엔드포인트를 호출.

API 서버가 BGE-M3 모델 없이도 벡터 검색을 수행할 수 있도록,
별도의 Search Proxy(기본 :3580)에 임베딩 생성을 위임한다.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

# 설정에서 프록시 URL을 가져온다. Settings에 없으면 환경변수 직접 참조.
_PROXY_URL: str = getattr(settings, "EMBEDDING_PROXY_URL", "http://localhost:3580")


class EmbeddingProxyClient:
    """Search Proxy를 통해 BGE-M3 임베딩을 생성하는 클라이언트.

    Search Proxy가 ``POST /embed`` 엔드포인트를 제공한다고 가정한다.
    요청: ``{"text": "..."}``
    응답: ``{"dense": [float, ...], "sparse": {token_id_str: weight, ...}}``

    프록시가 다운되면 빈 벡터를 반환하여 graceful degradation 한다.
    """

    def __init__(
        self,
        proxy_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._proxy_url = (proxy_url or _PROXY_URL).rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        log.info(
            "embedding_proxy_client_initialized",
            proxy_url=self._proxy_url,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """httpx AsyncClient를 지연 생성한다."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=self._timeout, write=10.0, pool=5.0),
                limits=httpx.Limits(
                    max_connections=30,
                    max_keepalive_connections=10,
                    keepalive_expiry=30.0,
                ),
            )
        return self._client

    async def embed(self, text: str) -> tuple[list[float], dict[int, float]]:
        """단일 텍스트를 임베딩하여 (dense, sparse) 튜플을 반환한다.

        Args:
            text: 임베딩할 텍스트

        Returns:
            (dense_vector, sparse_vector) — 프록시 실패 시 빈 벡터 반환

        Raises:
            RuntimeError: 프록시 응답 형식이 예상과 다를 때
        """
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self._proxy_url}/embed",
                json={"text": text},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

            dense: list[float] = data.get("dense", [])
            raw_sparse = data.get("sparse", {})

            # sparse 키를 int로 변환 (JSON은 문자열 키만 허용)
            sparse: dict[int, float] = {
                int(k): float(v) for k, v in raw_sparse.items()
            }

            log.debug(
                "embedding_proxy_success",
                dense_dim=len(dense),
                sparse_dim=len(sparse),
            )
            return dense, sparse

        except httpx.HTTPStatusError as exc:
            log.warning(
                "embedding_proxy_http_error",
                status_code=exc.response.status_code,
                detail=exc.response.text[:200],
            )
            raise RuntimeError(
                f"Embedding proxy HTTP error: {exc.response.status_code}"
            ) from exc

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning(
                "embedding_proxy_connection_error",
                error=str(exc),
                proxy_url=self._proxy_url,
            )
            raise RuntimeError(
                f"Embedding proxy unreachable at {self._proxy_url}: {exc}"
            ) from exc

        except Exception as exc:
            log.error(
                "embedding_proxy_unexpected_error",
                error=str(exc),
            )
            raise RuntimeError(
                f"Embedding proxy unexpected error: {exc}"
            ) from exc

    async def close(self) -> None:
        """HTTP 클라이언트를 정리한다."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


async def get_proxy_embedding_fn(
    proxy_url: str | None = None,
) -> Any:
    """프록시 기반 임베딩 함수를 반환한다.

    SearchService의 embedding_fn 파라미터에 주입 가능한
    ``async def(text: str) -> tuple[list[float], dict[int, float]]`` 형태.
    """
    client = EmbeddingProxyClient(proxy_url=proxy_url)

    async def _embed(text: str) -> tuple[list[float], dict[int, float]]:
        return await client.embed(text)

    # 클라이언트 참조를 함수에 부착 (close 호출용)
    _embed._proxy_client = client  # type: ignore[attr-defined]
    return _embed


def create_embedding_fn() -> Any:
    """임베딩 함수를 생성한다 — 프록시 우선, 로컬 fallback.

    분기 순서 (B200 원칙):
    1. ``EMBEDDING_PROXY_URL`` 설정돼 있으면 → 즉시 proxy 클라이언트 반환.
       FlagEmbedding import 시도조차 하지 않아 torch CUDA context 초기화 방지.
    2. 미설정 시에만 FlagEmbedding(로컬 BGE-M3) 시도.
    3. FlagEmbedding 도 없으면 기본 proxy URL 로 fallback.

    Returns:
        async callable: (text: str) -> (dense, sparse)
    """
    proxy_url = (getattr(settings, "EMBEDDING_PROXY_URL", "") or "").strip()

    def _make_proxy_fn(reason: str) -> Any:
        log.info("embedding_fn_source", source="proxy", proxy_url=proxy_url or _PROXY_URL, reason=reason)
        client = EmbeddingProxyClient(proxy_url=proxy_url or None)

        async def _proxy_embed(text: str) -> tuple[list[float], dict[int, float]]:
            return await client.embed(text)

        _proxy_embed._proxy_client = client  # type: ignore[attr-defined]
        return _proxy_embed

    # 1. PROXY_URL 있으면 우선 사용 (B200 원격 경로)
    if proxy_url:
        return _make_proxy_fn(reason="EMBEDDING_PROXY_URL set (B200 remote)")

    # 2. PROXY_URL 미설정 시 로컬 BGE-M3 fallback (dev/로컬 GPU 환경)
    try:
        from FlagEmbedding import BGEM3FlagModel  # noqa: F401
        from src.pipeline.embedders.bge_m3 import BGEM3Embedder

        embedder = BGEM3Embedder()
        log.info("embedding_fn_source", source="local_bge_m3")

        async def _local_embed(text: str) -> tuple[list[float], dict[int, float]]:
            result = await embedder.embed_single(text)
            return result.dense, result.sparse

        return _local_embed

    except ImportError:
        return _make_proxy_fn(reason="FlagEmbedding unavailable, default proxy")
