"""검색 프록시 패스스루 — API 서버를 통해 BGE-M3 검색 프록시에 접근.

외부에서 :3500 포트로만 접속 가능한 경우, 이 엔드포인트를 통해
내부 검색 프록시(:3581)의 기능을 사용할 수 있다.
"""

import asyncio

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Search Proxy"])

PROXY_URL = getattr(settings, "EMBEDDING_PROXY_URL", "http://localhost:3581")

# 동시 요청 제한 (백프레셔)
_MAX_CONCURRENT_PROXY = 20
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PROXY)

# 공유 커넥션 풀 (스레드 안전 초기화)
_shared_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    """공유 httpx.AsyncClient를 반환한다. Lock으로 동시 초기화 경합을 방지."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        return _shared_client
    async with _client_lock:
        if _shared_client is not None and not _shared_client.is_closed:
            return _shared_client
        _shared_client = httpx.AsyncClient(
            base_url=PROXY_URL,
            timeout=httpx.Timeout(
                connect=5.0,
                read=60.0,      # RAG answer 등 긴 응답 대비 60초
                write=10.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=50,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
        )
    return _shared_client


async def close_proxy_client() -> None:
    """앱 종료 시 공유 클라이언트를 정리한다. lifespan에서 호출."""
    global _shared_client
    async with _client_lock:
        if _shared_client is not None and not _shared_client.is_closed:
            await _shared_client.aclose()
            _shared_client = None
            logger.info("search_proxy_client_closed")


async def _proxy(path: str, request: Request) -> JSONResponse:
    """내부 검색 프록시로 요청을 전달."""
    # 백프레셔: 가용 슬롯이 없으면 즉시 503
    if _semaphore._value == 0:
        return JSONResponse(
            content={"error": "검색 프록시 과부하. 잠시 후 재시도하세요."},
            status_code=503,
        )

    async with _semaphore:
        try:
            body = await request.body()
            client = await _get_client()
            resp = await client.post(
                path,
                content=body,
                headers={"Content-Type": "application/json"},
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
        except httpx.TimeoutException as e:
            logger.warning("search_proxy_timeout", path=path, error=str(e))
            return JSONResponse(
                content={"error": f"검색 프록시 타임아웃: {e}"},
                status_code=504,
            )
        except httpx.ConnectError as e:
            logger.error("search_proxy_connect_error", path=path, error=str(e))
            return JSONResponse(
                content={"error": f"검색 프록시 연결 실패: {e}"},
                status_code=502,
            )
        except Exception as e:
            logger.error("search_proxy_error", path=path, error=str(e))
            return JSONResponse(
                content={"error": f"검색 프록시 오류: {str(e)}"},
                status_code=502,
            )


async def _proxy_get(path: str, timeout: float = 10.0) -> JSONResponse:
    """GET 요청 프록시."""
    try:
        client = await _get_client()
        resp = await client.get(path, timeout=timeout)
        return JSONResponse(content=resp.json())
    except httpx.TimeoutException:
        return JSONResponse(content={"error": "타임아웃"}, status_code=504)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.post("/proxy/search")
async def proxy_search(request: Request):
    """Knowledge Search 프록시."""
    return await _proxy("/search", request)


@router.post("/proxy/rag/retrieve")
async def proxy_rag_retrieve(request: Request):
    """RAG Retrieve 프록시."""
    return await _proxy("/rag/retrieve", request)


@router.post("/proxy/rag/answer")
async def proxy_rag_answer(request: Request):
    """RAG Answer 프록시."""
    return await _proxy("/rag/answer", request)


@router.post("/proxy/embed")
async def proxy_embed(request: Request):
    """임베딩 프록시."""
    return await _proxy("/embed", request)


@router.get("/proxy/collections")
async def proxy_collections():
    """컬렉션 목록 프록시."""
    return await _proxy_get("/collections")


@router.get("/proxy/health")
async def proxy_health():
    """검색 프록시 헬스체크."""
    return await _proxy_get("/health", timeout=5.0)


@router.post("/proxy/analyze")
async def proxy_analyze(request: Request):
    """AI 문서 분석 프록시."""
    return await _proxy("/analyze", request)


@router.post("/proxy/duplicate-check")
async def proxy_duplicate_check(request: Request):
    """문서 중복 검사 프록시."""
    return await _proxy("/duplicate-check", request)


@router.get("/proxy/doc-info")
async def proxy_doc_info(request: Request):
    """문서 정보 프록시. 검색 프록시의 /doc-info 엔드포인트로 전달."""
    # 쿼리 파라미터를 포함하여 전달
    query_string = str(request.query_params)
    path = f"/doc-info?{query_string}" if query_string else "/doc-info"
    return await _proxy_get(path)
