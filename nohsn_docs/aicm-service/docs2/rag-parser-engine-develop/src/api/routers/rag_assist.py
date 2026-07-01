"""외부 웹프론트 상담 보조 SSE 엔드포인트.

POST /api/v1/rag/assist-stream
- 입력: query, conversation_history (최근 2턴 강제 truncate), repository_id
- 내부: intent gate → hybrid Top5 → distill → LLM stream
- SSE 이벤트: intent → sources → distilled → token → done

설계: docs/superpowers/specs/2026-04-17-rag-assist-stream-design.md
"""

from __future__ import annotations

import asyncio
import json
import re as _re
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id, get_current_user_id
from src.api.metrics import (
    ASSIST_STREAM_CONCURRENT,
    ASSIST_STREAM_REQUESTS,
    ASSIST_STREAM_STAGE_DURATION,
    ASSIST_STREAM_TOKENS,
)
from src.api.schemas.rag import AssistStreamRequest
from src.common.config import settings
from src.common.logging import get_logger
from src.core.database import get_db

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# table-aware retrieval slot 헬퍼
# ---------------------------------------------------------------------------


def _needs_table_slot(hits: list) -> bool:
    """retrieval 결과에 table 계열 block 이 0개면 True — table-aware 보강 필요.

    group-by aggregation 질문 ("지자체의 메일 X개") 에서 키워드 밀도 높은 짧은
    사례 chunk 가 긴 table chunk 를 밀어내는 구조적 문제 보정.
    """
    if not hits:
        return False
    for h in hits:
        bt = (getattr(h, "block_type", "") or "").lower()
        if "table" in bt:
            return False
    return True


# ---------------------------------------------------------------------------
# SSE 직렬화 헬퍼
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict) -> bytes:
    """Server-Sent Events 프레임 한 개."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# 테넌트별 동시 요청 제한 (process-local Semaphore)
# ---------------------------------------------------------------------------

_TENANT_SEMAPHORES: dict[str, asyncio.Semaphore] = {}
_TENANT_SEM_LOCK = asyncio.Lock()


async def _get_tenant_semaphore(tenant_id: UUID) -> asyncio.Semaphore:
    """테넌트별 asyncio.Semaphore 를 lazy 생성해서 반환."""
    key = str(tenant_id)
    async with _TENANT_SEM_LOCK:
        sem = _TENANT_SEMAPHORES.get(key)
        if sem is None:
            sem = asyncio.Semaphore(settings.ASSIST_MAX_CONCURRENT_PER_TENANT)
            _TENANT_SEMAPHORES[key] = sem
        return sem


# ---------------------------------------------------------------------------
# 히스토리 truncate (서버 강제)
# ---------------------------------------------------------------------------


def _truncate_history(history: list) -> list[dict]:
    """conversation_history 를 최근 3턴(6메시지)으로 자른다.

    한 "턴" = user + assistant 쌍. LLMQueryRewriter 가 내부에서 ``[-6:]`` 로
    3턴까지 활용 — 그 만큼은 손실 없이 통과시켜야 history 활용도 극대화
    (2026-05-08 사용자 절칙: "검색 파이프라인의 자연어 query 생성/리라이팅을 활용").
    role dict 형태로 반환 (intent classifier 와 LLM 입력 포맷).

    GPT-5 Phase 1.6 사후 검증 verdict (NO-GO 사유):
    - per-message char cap 부재 — 6 메시지 모두 매우 길 경우 prompt 한도
      (8192/16384) 초과 위험. tool_calling_loop 의 1000 char cap 과 정합.
    - PII 마스킹은 본 layer 책임 X (search 파이프라인 자체에 분리 가드).
    """
    if not history:
        return []
    tail = history[-6:]  # 최근 6메시지 (3턴) — LLMQueryRewriter [-6:] 와 정합

    # GPT-5 NO-GO §1 fix — per-message 1000 char cap (tool_calling_loop align).
    # 6 메시지 × 1000 char ≈ 2.5k tokens 한국어 — 31B prompt 한도 안 안전 margin.
    out: list[dict] = []
    for t in tail:
        content = t.content or ""
        if len(content) > 1000:
            content = content[:1000].rstrip() + "..."
        out.append({"role": t.role, "content": content})

    logger.info(
        "assist_truncated_history_for_llm",
        in_len=len(history),
        out_len=len(out),
        capped=sum(1 for t in tail if len((t.content or "")) > 1000),
    )
    return out


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.post(
    "/assist-stream",
    summary="RAG 상담 보조 스트리밍 (외부 웹프론트 전용 SSE)",
    description=(
        "외부 웹프론트(상담사 보조 UI 등)를 위한 잠금형 SSE endpoint. "
        "내부에서 top_k=5, mode=hybrid, intent_gate=on, with_answer=on 등 대부분 "
        "파라미터가 잠겨 있어 일관된 품질을 보장한다.\n\n"
        "**이벤트 순서**: `intent` → `sources` → `distilled` → `token` × N → `done`. "
        "에러 시: `event: error` (stage/code/message) 후 종료.\n\n"
        "**동시 호출 제한**: tenant 단위 세마포어 (`ASSIST_MAX_CONCURRENT_PER_TENANT`). "
        "초과 시 429."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE 스트림 (text/event-stream)",
            "content": {
                "text/event-stream": {
                    "example": (
                        "event: intent\ndata: {\"search\": true}\n\n"
                        "event: sources\ndata: {\"sources\": [...]}\n\n"
                        "event: token\ndata: {\"delta\": \"...\"}\n\n"
                        "event: done\ndata: {\"latency_ms\": 2104}\n\n"
                    )
                }
            },
        },
        429: {"description": "tenant 동시 호출 한도 초과"},
    },
)
async def assist_stream(
    body: AssistStreamRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """SSE 스트림으로 상담 보조 답변 생성.

    이벤트: intent → sources → distilled → token × N → done.
    에러 시: event: error (stage, code, message) 후 종료.
    """
    # 동시 요청 상한 체크 (SSE 시작 전 — 초과 시 429 로 즉시 거절)
    sem = await _get_tenant_semaphore(tenant_id)
    if sem.locked():
        raise HTTPException(
            status_code=429,
            detail=f"Too many concurrent assist-stream requests for tenant (limit={settings.ASSIST_MAX_CONCURRENT_PER_TENANT})",
        )
    await sem.acquire()

    # 메트릭: concurrent gauge 증가
    ASSIST_STREAM_CONCURRENT.labels(tenant_id=str(tenant_id)).inc()

    history = _truncate_history(body.conversation_history)

    # tenant slug 사전 조회 (병렬 dispatch 전에 db 세션 단독 사용 — 병렬 task 가 동시에
    # 같은 AsyncSession 을 사용하면 SQLAlchemy "concurrent operation" 에러 발생)
    _preresolved_slug = str(tenant_id)
    try:
        from sqlalchemy import text as _text
        _r = await db.execute(_text("SELECT slug FROM tenants WHERE id = :tid"), {"tid": str(tenant_id)})
        _row = _r.fetchone()
        if _row:
            _preresolved_slug = _row[0]
    except Exception as _slug_exc:
        logger.warning("assist_stream_tenant_slug_lookup_failed", error=str(_slug_exc))

    async def event_generator():
        start = time.monotonic()
        search_task: asyncio.Task | None = None

        async def _do_search() -> tuple[list, int, dict, dict]:
            """Service 획득 + request build + execute 를 감싼 coroutine.

            intent gate 와 병렬로 실행되어 TTFS (sources 이벤트 도착) 를 단축한다.
            tenant_slug 은 엔드포인트 진입 시점에 이미 조회해 둔 `_preresolved_slug` 를
            closure 로 참조해서 db 세션 동시 사용을 피한다.
            반환: (hits, search_self_latency_ms, query_analysis, decomposed_dict).
            service_unavailable 은 RuntimeError 로 전파.
            """
            from src.api.routers.rag import _build_search_weights
            from src.search.factory import create_search_service
            from src.search.models import SearchRequest as _InternalSearchRequest

            try:
                _svc = await create_search_service(profile="assist")
            except Exception:
                _svc = None
            if _svc is None:
                raise RuntimeError("service_unavailable")

            _req = _InternalSearchRequest(
                query=body.query,
                repository_id=body.repository_id,
                tenant_id=tenant_id,
                category_ids=body.category_ids,
                top_k=5,
                search_mode="hybrid",
                rerank=True,
                include_content=True,
                weights=_build_search_weights(None),
                # 대화 이력을 검색에도 전달 — intent gate 에만 쓰지 않고 쿼리 재구성 용도.
                conversation_history=history,
                # LLMQueryRewriter.reformulate_for_search 를 활성화.
                # 대화 문맥에서 대명사/생략을 풀어 effective_query 를 만든다.
                enable_llm_rewrite=True,
                # HyDE 는 assist-stream 에선 비활성: rewrite 가 이미 쿼리를 구체화하므로
                # 가상답변 생성이 중복 이득. LLM 호출 1회 (+400ms cold) 와 추가 dense
                # 검색 1회 (+10ms) 를 제거. 다른 엔드포인트(/search, /rag/answer) 에선
                # default True 유지 — 다양한 쿼리 형태에 대한 보험.
                use_hyde=False,
            )
            _s = time.monotonic()
            _hits, _trace, _latency, _decomposed, _analysis = await _svc._execute_with_split(request=_req, tenant_slug=_preresolved_slug)

            # table-aware slot — table 계열 hit 이 0개면 table 한정 검색 1회 추가.
            # score 조작 없음 — 별도 검색 결과를 slot 으로 merge (메모리 절칙
            # feedback_use_kms_search_api: reranker 가 ranking 결정).
            if _needs_table_slot(_hits):
                try:
                    _table_req = _InternalSearchRequest(
                        query=body.query,
                        repository_id=body.repository_id,
                        tenant_id=tenant_id,
                        category_ids=body.category_ids,
                        top_k=2,
                        search_mode="hybrid",
                        rerank=True,
                        include_content=True,
                        weights=_build_search_weights(None),
                        conversation_history=history,
                        enable_llm_rewrite=True,
                        use_hyde=False,
                        block_types=["table"],
                    )
                    _t_hits, _, _, _, _ = await _svc._execute_pipeline(
                        request=_table_req, tenant_slug=_preresolved_slug
                    )
                    _seen = {str(getattr(h, "chunk_id", "")) for h in _hits}
                    for th in _t_hits:
                        if str(getattr(th, "chunk_id", "")) not in _seen:
                            _hits.append(th)
                except Exception as _t_exc:  # noqa: BLE001 — 보강 실패는 치명 X
                    logger.warning("assist_table_slot_failed", error=str(_t_exc))

            return _hits, int((time.monotonic() - _s) * 1000), _analysis, _decomposed

        try:
            # intent gate 와 search 를 병렬로 dispatch (일상 대화면 search cancel)
            search_task = asyncio.create_task(_do_search())

            # 1. Intent gate — 일상 대화면 검색 스킵
            #    이력 없음: 원본 쿼리로 intent 판정 (단일턴 불만/감정 정확 분류)
            #    이력 있음: reformulate 먼저 → 확장 쿼리로 intent 판정 (짧은 쿼리 오분류 방지)
            #              단, has_specific_target=false면 검색 스킵 (범주 추측만으로는 검색 무의미)
            intent_search = True
            intent_reason = ""
            intent_ms = 0
            intent_skipped = False
            intent_query = body.query
            _has_specific_target = True
            if history:
                try:
                    from src.api.routers.rag import _get_search_service
                    _svc = await _get_search_service()
                    if _svc and hasattr(_svc, "_llm_query_rewriter") and _svc._llm_query_rewriter:
                        intent_query, _has_specific_target = (
                            await _svc._llm_query_rewriter.reformulate_for_search(
                                body.query, conversation_history=history,
                            )
                        )
                except Exception as rewrite_exc:
                    logger.warning("assist_intent_rewrite_failed", error=str(rewrite_exc))
            try:
                from src.search.intent_classifier import IntentResult, classify_intent, log_intent_decision
                from src.core.models.repository import Repository

                domain_description = None
                try:
                    repo = await db.get(Repository, body.repository_id)
                    if repo and repo.description:
                        domain_description = repo.description
                except Exception:
                    pass

                _query_rewritten = intent_query != body.query
                intent_result = await asyncio.wait_for(
                    classify_intent(intent_query, None, domain_description),
                    timeout=settings.ASSIST_INTENT_TIMEOUT_MS / 1000,
                )
                if _query_rewritten:
                    logger.info(
                        "assist_intent_rewrite_applied",
                        original=body.query[:80],
                        rewritten=intent_query[:80],
                        has_specific_target=_has_specific_target,
                    )
                # reformulate가 구체적 대상을 특정하지 못한 경우 검색 스킵
                if not _has_specific_target and intent_result.search:
                    logger.info(
                        "assist_intent_override_no_target",
                        original=body.query[:80],
                        rewritten=intent_query[:80],
                    )
                    intent_result = IntentResult(
                        search=False,
                        reason="대화 이력에 구체적 대상 없음 — 검색 불가",
                        latency_ms=intent_result.latency_ms,
                        model_used=intent_result.model_used,
                    )
                await log_intent_decision(
                    db=db,
                    query=body.query,
                    conversation_history=history or None,
                    result=intent_result,
                    tenant_id=tenant_id,
                )
                intent_search = intent_result.search
                intent_reason = intent_result.reason
                intent_ms = intent_result.latency_ms
                intent_skipped = not intent_result.search
            except asyncio.TimeoutError:
                logger.warning("assist_stream_intent_timeout", query_len=len(body.query))
                intent_reason = "classifier_timeout"
            except Exception as exc:  # NOTE: CancelledError 는 BaseException 상속이라 잡히지 않음 (cancel 전파됨)
                logger.warning("assist_stream_intent_failed", error=str(exc))
                intent_reason = "classifier_unavailable"

            yield _sse("intent", {
                "search": intent_search,
                "reason": intent_reason,
                "latency_ms": intent_ms,
                "skipped": intent_skipped,
            })

            # 일상 대화 → 검색/LLM 스킵, 안내 문구만 내려보내고 종료
            if not intent_search:
                # 병렬로 이미 dispatch 한 search task 는 즉시 cancel (리소스 낭비 방지)
                if search_task is not None and not search_task.done():
                    search_task.cancel()
                    try:
                        await search_task
                    except (asyncio.CancelledError, Exception):
                        pass
                yield _sse("sources", {"sources": [], "confidence": 0.0, "search_latency_ms": 0, "total_candidates": 0})
                yield _sse("token", {"text": "일상 대화입니다."})
                elapsed = int((time.monotonic() - start) * 1000)
                # 메트릭/로그
                try:
                    ASSIST_STREAM_REQUESTS.labels(status="ok", stage_fail="none").inc()
                    if intent_ms and intent_ms > 0:
                        ASSIST_STREAM_STAGE_DURATION.labels(stage="intent").observe(intent_ms / 1000)
                except Exception:
                    logger.exception("assist_stream_metrics_update_failed")
                logger.info(
                    "assist_stream_completed",
                    tenant_id=str(tenant_id),
                    repository_id=str(body.repository_id),
                    user_id=str(user_id) if user_id else None,
                    query_len=len(body.query),
                    history_turns=len(history) // 2,
                    intent_search=False,
                    intent_ms=intent_ms,
                    total_ms=elapsed,
                    status="ok_intent_skipped",
                )
                yield _sse("done", {
                    "model_used": None,
                    "confidence": 0.0,
                    "token_usage": {"context_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    "latency_ms": elapsed,
                    "stages": {"intent": intent_ms},
                })
                return

            # 2. Hybrid 검색 — 이미 intent 와 병렬로 dispatch 된 search_task 결과 수확
            total_candidates = 0
            query_analysis = {}
            decomposed_dict = {}
            try:
                hits, search_ms, query_analysis, decomposed_dict = await asyncio.wait_for(
                    search_task,
                    timeout=settings.ASSIST_SEARCH_TIMEOUT_MS / 1000,
                )
                total_candidates = len(hits)

                # Intent gate 가 검색을 skip 한 경우엔 이 블럭에 도달 안 함 (위에서 return).
                # 여기 오면 search 가 돌았으므로 분해 결과를 UI로 노출.
                yield _sse("query_analysis", {
                    "original_query": body.query,
                    "rewritten_query": query_analysis["rewritten_query"],
                    "keywords": query_analysis["keywords"],
                    "decomposed": decomposed_dict or {},
                })
            except asyncio.TimeoutError:
                try:
                    ASSIST_STREAM_REQUESTS.labels(status="error", stage_fail="search").inc()
                except Exception:
                    pass
                logger.info(
                    "assist_stream_completed",
                    tenant_id=str(tenant_id),
                    repository_id=str(body.repository_id),
                    query_len=len(body.query),
                    status="error",
                    stage_fail="search",
                    error_message="검색 시간 초과",
                    total_ms=int((time.monotonic() - start) * 1000),
                )
                yield _sse("error", {"stage": "search", "code": "timeout", "message": "검색 시간 초과"})
                return
            except RuntimeError as exc:
                # _do_search 내부의 service_unavailable 전파
                if str(exc) == "service_unavailable":
                    try:
                        ASSIST_STREAM_REQUESTS.labels(status="error", stage_fail="search").inc()
                    except Exception:
                        pass
                    logger.info(
                        "assist_stream_completed",
                        tenant_id=str(tenant_id),
                        repository_id=str(body.repository_id),
                        query_len=len(body.query),
                        status="error",
                        stage_fail="search",
                        error_message="검색 서비스를 사용할 수 없습니다.",
                        total_ms=int((time.monotonic() - start) * 1000),
                    )
                    yield _sse("error", {"stage": "search", "code": "service_unavailable", "message": "검색 서비스를 사용할 수 없습니다."})
                    return
                raise
            except Exception as exc:  # NOTE: CancelledError 는 BaseException 상속이라 잡히지 않음 (cancel 전파됨)
                logger.error("assist_stream_search_failed", error=str(exc))
                try:
                    ASSIST_STREAM_REQUESTS.labels(status="error", stage_fail="search").inc()
                except Exception:
                    pass
                logger.info(
                    "assist_stream_completed",
                    tenant_id=str(tenant_id),
                    repository_id=str(body.repository_id),
                    query_len=len(body.query),
                    status="error",
                    stage_fail="search",
                    error_message=str(exc),
                    total_ms=int((time.monotonic() - start) * 1000),
                )
                yield _sse("error", {"stage": "search", "code": "search_error", "message": str(exc)})
                return

            # sources 페이로드 — 원문 content 그대로 (스펙 § 4)
            sources_payload = []
            for rank, h in enumerate(hits, 1):
                sl = getattr(h, "source_location", None)
                if sl is not None and hasattr(sl, "model_dump"):
                    sl_dict = sl.model_dump()
                elif isinstance(sl, dict):
                    sl_dict = sl
                else:
                    sl_dict = {}
                page_info = None
                if sl_dict:
                    if sl_dict.get("page_range"):
                        pr = sl_dict["page_range"]
                        page_info = f"p.{pr[0]}-{pr[1]}"
                    elif sl_dict.get("page_number"):
                        page_info = f"p.{sl_dict['page_number']}"
                _meta = getattr(h, "metadata", {}) or {}
                _has_position = (
                    sl_dict.get("start_char_offset") is not None
                    or sl_dict.get("page_number") is not None
                )
                _highlightable = (
                    not _meta.get("generated", False)
                    and bool(sl_dict.get("file_url"))
                    and _has_position
                )
                sources_payload.append({
                    "ref_num": rank,
                    "document_id": str(h.document_id),
                    "chunk_id": str(h.chunk_id),
                    "document_title": getattr(h, "document_title", "") or "",
                    "section_title": getattr(h, "section_title", None),
                    "content": h.content or "",
                    "score": round(getattr(h, "score", 0.0), 4),
                    "token_count": len(h.content or "") // 4,
                    "page_info": page_info,
                    "source_location": sl_dict,
                    "highlightable": _highlightable,
                })
            confidence = round(getattr(hits[0], "score", 0.0), 4) if hits else 0.0
            yield _sse("sources", {
                "sources": sources_payload,
                "confidence": confidence,
                "search_latency_ms": search_ms,
                "total_candidates": total_candidates,
            })

            # 검색 결과 0개 → 안내 후 종료
            if not hits:
                yield _sse("token", {"text": "참고자료를 찾지 못했습니다."})
                elapsed = int((time.monotonic() - start) * 1000)
                try:
                    ASSIST_STREAM_REQUESTS.labels(status="ok", stage_fail="none").inc()
                    if intent_ms and intent_ms > 0:
                        ASSIST_STREAM_STAGE_DURATION.labels(stage="intent").observe(intent_ms / 1000)
                    if search_ms and search_ms > 0:
                        ASSIST_STREAM_STAGE_DURATION.labels(stage="search").observe(search_ms / 1000)
                except Exception:
                    logger.exception("assist_stream_metrics_update_failed")
                logger.info(
                    "assist_stream_completed",
                    tenant_id=str(tenant_id),
                    repository_id=str(body.repository_id),
                    user_id=str(user_id) if user_id else None,
                    query_len=len(body.query),
                    history_turns=len(history) // 2,
                    intent_search=True,
                    intent_ms=intent_ms,
                    sources_count=0,
                    search_ms=search_ms,
                    confidence=0.0,
                    total_ms=elapsed,
                    status="ok_no_sources",
                )
                yield _sse("done", {
                    "model_used": None,
                    "confidence": 0.0,
                    "token_usage": {"context_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    "latency_ms": elapsed,
                    "stages": {"intent": intent_ms, "search": search_ms},
                })
                return

            # 3. 컨텍스트 조립 (기존 헬퍼 재사용)
            from src.api.routers.rag import _assemble_rag_context, _distill_context, _count_tokens

            context, sources_for_distill, context_tokens = await _assemble_rag_context(
                hits=hits,
                max_context_tokens=6000,
                compress=True,
                db=db,
            )
            # distill 에 넘길 full content dict (ref_num → 원문)
            full_contents = {rank: (hits[rank - 1].content or "") for rank in range(1, len(hits) + 1)}

            # 4. Distill (옵션 — body.enable_distill 이 False 면 스킵. soft timeout, 실패해도 LLM 진행)
            # 자동 스킵 기준: context 가 충분히 작으면 distill 이득 ≤ latency 비용.
            # answer LLM 이 직접 작은 context 처리하면 되므로 distill ~1000ms 절약.
            # 임계값은 "작은 context" 기준 (대략 2~3개 짧은 Q&A 블럭 분량).
            DISTILL_AUTO_SKIP_TOKENS = 800
            distill_start = time.monotonic()
            distilled = None
            distill_ms = 0
            auto_skip_short_ctx = (
                body.enable_distill and context_tokens < DISTILL_AUTO_SKIP_TOKENS
            )
            if body.enable_distill and not auto_skip_short_ctx:
                try:
                    distilled, _distill_tokens, distill_ms = await asyncio.wait_for(
                        _distill_context(query=body.query, candidates=sources_for_distill, full_contents=full_contents),
                        timeout=settings.ASSIST_DISTILL_TIMEOUT_MS / 1000,
                    )
                except asyncio.TimeoutError:
                    logger.warning("assist_stream_distill_timeout")
                    distill_ms = settings.ASSIST_DISTILL_TIMEOUT_MS
                except Exception as exc:  # NOTE: CancelledError 는 BaseException 상속이라 잡히지 않음 (cancel 전파됨)
                    logger.warning("assist_stream_distill_failed", error=str(exc))
            elif auto_skip_short_ctx:
                logger.info(
                    "assist_stream_distill_auto_skipped_short_context",
                    context_tokens=context_tokens,
                    threshold=DISTILL_AUTO_SKIP_TOKENS,
                )
            else:
                logger.info("assist_stream_distill_skipped_by_request")

            if distilled is not None:
                yield _sse("distilled", {
                    "selected_refs": distilled.selected_refs,
                    "summary": distilled.summary,
                    "rationale": distilled.rationale,
                    "latency_ms": distill_ms,
                })

            # 5. LLM 답변 스트리밍
            system_prompt = (
                "당신은 지식관리 플랫폼의 상담 보조 AI 입니다.\n"
                "참고자료에 [1], [2] 등의 번호가 부여되어 있습니다.\n"
                "답변 내에서 해당 내용의 근거를 인라인 인용 마커 [1], [2] 등으로 표시하세요.\n"
                "\n"
                "답변 방법:\n"
                "1. 참고자료가 **명시적으로 말하는 사실**을 먼저 파악한다.\n"
                "2. 사용자 질문이 그 사실에 의해 **직접 답이 되는지, 아니면 그 사실을 적용/계산/비교해야 답이 나오는지** 판단한다.\n"
                "3. 적용이 필요하면 사실과 질문 조건(시점·금액·상태 등)을 연결해 결론을 도출한다.\n"
                "   예: 사용자의 가정 시점이 그 규정의 기준에 부합하는지 따져 '예/아니요' 를 판단, 수치 질문이면 규정에 대입해 계산.\n"
                "4. 참고자료의 어떤 사실을 끌어다 써도 질문에 답할 수 없을 때만 '참고자료에 명시되어 있지 않습니다' 로 답한다.\n"
                "\n"
                "어조 규칙 (반드시 준수):\n"
                "- '틀렸습니다', '잘못 알고 계십니다', '맞지 않습니다' 등 사용자를 직접 부정하는 표현을 절대 사용하지 마세요.\n"
                "- 사용자의 추측이 사실과 다를 때는 '아닙니다, …입니다' 또는 '정확히는 …입니다' 처럼 올바른 정보를 바로 안내하세요.\n"
                "\n"
                "작성 규칙:\n"
                "- 참고자료에 없는 사실을 새로 만들지 마세요.\n"
                "- 간결하게. 같은 사실을 다른 표현으로 반복하지 말 것.\n"
                "- 질문이 Yes/No 형이면 결론을 먼저 제시한 뒤 근거 사실을 한 문장으로 덧붙이세요.\n"
                "- 수치/절차/규정을 말할 때 그 **대상의 정확한 명칭** (예: '잔고증명서 발급', '주식거래', 'NXT 매매') 을 반드시 함께 명시하라. "
                "사용자 쿼리가 포괄적이어도 참고자료는 특정 종류만 다루는 경우가 많으므로 주체를 생략하지 말 것.\n"
                "- 사용자 질문이 **포괄적**(예: 단지 '증명서', '수수료')이고 참고자료에는 **그 중 특정 종류 정보만** 있으면, "
                "해당 특정 종류에 한정된 답변임을 명시하고 말미에 `(다른 종류의 [대상]에 대한 정보는 참고자료에 없습니다)` "
                "또는 `(어떤 [대상]을 말씀하시는지 확인이 필요합니다)` 를 한 줄 덧붙인다."
            )
            # distill 성공 시 summary 를 컨텍스트에 덧붙여 LLM 입력 정제.
            # 단, distill 이 selected_refs 없이 부정 요약만 뱉는 경우 (예: "정보 없음")
            # 그대로 answer LLM 에 주입하면 원본 context 에 답이 있어도 "없다" 로 이끌림.
            # → selected_refs 가 비어있으면 summary 무시하고 raw context 만 사용.
            effective_context = context
            if distilled and distilled.summary and distilled.selected_refs:
                effective_context = f"{context}\n\n## 정제 요약\n{distilled.summary}"
            elif distilled and not distilled.selected_refs:
                logger.info(
                    "assist_stream_distill_empty_selection_fallback",
                    summary_preview=(distilled.summary or "")[:80],
                )

            history_block = ""
            if history:
                parts = [f"[{'사용자' if t['role'] == 'user' else 'AI'}] {t['content']}" for t in history]
                history_block = "\n\n## 이전 대화\n" + "\n".join(parts)

            # 쿼리 리라이팅 결과(rewritten_query)가 원본과 다르면 복원된 의도를 함께 전달.
            # 그렇지 않으면 LLM 이 history 를 못 끌어써 원본 쿼리의 표면 의미대로만 답하는
            # 문제 발생 (예: history="잔고 증명 말인데요" + "수수료 얼마?" 의 실제 의도는
            # 잔고증명서 발급 수수료인데, 원본 쿼리만 보면 거래수수료로 오해).
            rewritten_query = (query_analysis or {}).get("rewritten_query") or body.query
            if rewritten_query.strip() != body.query.strip():
                question_block = (
                    f"## 질문\n\n{rewritten_query}\n\n"
                    f"(사용자 원 발화: \"{body.query}\" — 이전 대화 문맥을 반영해 복원)"
                )
            else:
                question_block = f"## 질문\n\n{body.query}"

            user_prompt = f"## 참고자료\n\n{effective_context}{history_block}\n\n{question_block}"

            prompt_tokens = _count_tokens(system_prompt) + _count_tokens(user_prompt)
            completion_tokens = 0
            model_used = None
            full_answer = ""

            gen_start = time.monotonic()
            try:
                from src.common.llm.base import LLMRequest, LLMStreamChunk, LLMTask
                from src.common.llm.router import llm_router

                req = LLMRequest(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=settings.ASSIST_MAX_ANSWER_TOKENS,
                    temperature=0.2,
                )

                first_token_deadline = gen_start + settings.ASSIST_GEN_FIRST_TOKEN_TIMEOUT_MS / 1000
                total_deadline = gen_start + settings.ASSIST_GEN_TOTAL_TIMEOUT_MS / 1000
                got_first_token = False

                # assist 전용 B200 분기
                _assist_vllm = settings.ASSIST_VLLM_URL
                if _assist_vllm:
                    _assist_model = settings.ASSIST_VLLM_MODEL or getattr(settings, "VLLM_MODEL", "gemma-4-31b")

                    async def _assist_stream():
                        from openai import AsyncOpenAI
                        _aclient = AsyncOpenAI(
                            base_url=_assist_vllm,
                            api_key=getattr(settings, "VLLM_API_KEY", "") or "not-needed",
                            timeout=120.0,
                        )
                        messages = []
                        if req.system_prompt:
                            messages.append({"role": "system", "content": req.system_prompt})
                        messages.append({"role": "user", "content": req.prompt})
                        stream = await _aclient.chat.completions.create(
                            model=_assist_model,
                            messages=messages,
                            max_tokens=req.max_tokens,
                            temperature=req.temperature,
                            stream=True,
                        )
                        async for c in stream:
                            delta = c.choices[0].delta if c.choices else None
                            yield LLMStreamChunk(
                                text=(delta.content or "") if delta else "",
                                model=c.model or _assist_model,
                                finish_reason=c.choices[0].finish_reason if c.choices else None,
                            )

                    _gen = _assist_stream()
                else:
                    _gen = llm_router.route_stream(task=LLMTask.RAG_GENERATION, request=req)

                async for chunk in _gen:
                    now = time.monotonic()
                    if not got_first_token:
                        if now > first_token_deadline:
                            try:
                                ASSIST_STREAM_REQUESTS.labels(status="error", stage_fail="generate").inc()
                            except Exception:
                                pass
                            logger.info(
                                "assist_stream_completed",
                                tenant_id=str(tenant_id),
                                repository_id=str(body.repository_id),
                                query_len=len(body.query),
                                status="error",
                                stage_fail="generate",
                                error_message="LLM first-token timeout",
                                total_ms=int((time.monotonic() - start) * 1000),
                            )
                            yield _sse("error", {"stage": "generate", "code": "ttft_timeout", "message": "LLM first-token timeout"})
                            return
                        got_first_token = True
                    if now > total_deadline:
                        try:
                            ASSIST_STREAM_REQUESTS.labels(status="error", stage_fail="generate").inc()
                        except Exception:
                            pass
                        logger.info(
                            "assist_stream_completed",
                            tenant_id=str(tenant_id),
                            repository_id=str(body.repository_id),
                            query_len=len(body.query),
                            status="error",
                            stage_fail="generate",
                            error_message="LLM total timeout",
                            total_ms=int((time.monotonic() - start) * 1000),
                        )
                        yield _sse("error", {"stage": "generate", "code": "total_timeout", "message": "LLM total timeout"})
                        return
                    text = getattr(chunk, "text", "") or ""
                    mdl = getattr(chunk, "model", None)
                    if mdl:
                        model_used = mdl
                    if text:
                        yield _sse("token", {"text": text})
                        full_answer += text
            except asyncio.CancelledError:
                logger.info("assist_stream_llm_cancelled")
                raise
            except Exception as exc:  # NOTE: CancelledError 는 BaseException 상속이라 잡히지 않음 (cancel 전파됨)
                logger.error("assist_stream_generate_failed", error=str(exc))
                try:
                    ASSIST_STREAM_REQUESTS.labels(status="error", stage_fail="generate").inc()
                except Exception:
                    pass
                logger.info(
                    "assist_stream_completed",
                    tenant_id=str(tenant_id),
                    repository_id=str(body.repository_id),
                    query_len=len(body.query),
                    status="error",
                    stage_fail="generate",
                    error_message=str(exc),
                    total_ms=int((time.monotonic() - start) * 1000),
                )
                yield _sse("error", {"stage": "generate", "code": "llm_error", "message": str(exc)})
                return

            gen_ms = int((time.monotonic() - gen_start) * 1000)
            completion_tokens = _count_tokens(full_answer)

            elapsed = int((time.monotonic() - start) * 1000)
            # Prometheus 메트릭 업데이트
            try:
                ASSIST_STREAM_REQUESTS.labels(status="ok", stage_fail="none").inc()
                for _stage_name, _ms in (
                    ("intent", intent_ms),
                    ("search", search_ms),
                    ("distill", distill_ms),
                    ("generate", gen_ms),
                ):
                    if _ms and _ms > 0:
                        ASSIST_STREAM_STAGE_DURATION.labels(stage=_stage_name).observe(_ms / 1000)
                if context_tokens:
                    ASSIST_STREAM_TOKENS.labels(kind="context").inc(context_tokens)
                if completion_tokens:
                    ASSIST_STREAM_TOKENS.labels(kind="completion").inc(completion_tokens)
            except Exception:
                logger.exception("assist_stream_metrics_update_failed")

            # 구조화 로그 (요청당 1건)
            logger.info(
                "assist_stream_completed",
                tenant_id=str(tenant_id),
                repository_id=str(body.repository_id),
                user_id=str(user_id) if user_id else None,
                query_len=len(body.query),
                history_turns=len(history) // 2,
                intent_search=intent_search,
                intent_ms=intent_ms,
                sources_count=len(sources_payload) if sources_payload else 0,
                search_ms=search_ms,
                confidence=confidence,
                distill_ok=distilled is not None,
                distill_ms=distill_ms,
                gen_tokens=completion_tokens,
                gen_ms=gen_ms,
                model=model_used,
                total_ms=elapsed,
                status="ok",
            )

            _cited = sorted({
                int(d)
                for m in _re.findall(r"(?<![A-Za-z])\[([\d,\s]+)\]", full_answer)
                for d in m.split(",")
                if d.strip().isdigit()
            })

            yield _sse("done", {
                "model_used": model_used,
                "confidence": confidence,
                "cited_refs": _cited,
                "token_usage": {
                    "context_tokens": context_tokens,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
                "latency_ms": elapsed,
                "stages": {
                    "intent": intent_ms,
                    "search": search_ms,
                    "distill": distill_ms,
                    "generate": gen_ms,
                },
            })
        except asyncio.CancelledError:
            logger.info(
                "assist_stream_client_disconnected",
                tenant_id=str(tenant_id),
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
            raise  # FastAPI 의 StreamingResponse 가 cancel 을 전파하도록 재raise
        except Exception as exc:
            # 예기치 못한 runtime 오류 — 마지막 안전망 (각 단계 내부 try/except 에서 못 잡은 경우)
            logger.exception("assist_stream_unhandled_error", error=str(exc))
            try:
                yield _sse("error", {"stage": "unknown", "code": "internal_error", "message": str(exc)})
            except Exception:
                pass
            return
        finally:
            # 병렬 dispatch 된 search_task 안전망 cancel (예외/조기 return 등 모든 경로)
            if search_task is not None and not search_task.done():
                search_task.cancel()
                try:
                    await search_task
                except (asyncio.CancelledError, Exception):
                    pass
            # 슬롯 반납 + 메트릭 감소 (cancel / 정상 / 에러 모든 경로에서 호출)
            try:
                sem.release()
            except Exception:
                pass
            try:
                ASSIST_STREAM_CONCURRENT.labels(tenant_id=str(tenant_id)).dec()
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
