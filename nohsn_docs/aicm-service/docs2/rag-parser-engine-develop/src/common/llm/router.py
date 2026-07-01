"""LLM 라우터 — vLLM (Gemma 4) OpenAI-compatible 엔드포인트 + GB10 DGX Spark 폴백 체인.

Primary (B200) 장애 시 VLLM_FALLBACKS 환경 변수로 지정한 엔드포인트로 순차 폴백.
각 엔드포인트는 독립된 circuit breaker 키 (`vllm:<label>`) 를 사용하므로
한 엔드포인트의 open 상태가 다른 엔드포인트를 차단하지 않는다.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import httpx
import redis.asyncio as aioredis

from src.common.config import settings
from src.common.exceptions import LLMRoutingError
from src.common.llm.base import (
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    LLMTask,
    LLMVisionRequest,
)
from src.common.llm.circuit_breaker import circuit_breaker
from src.common.llm.fallbacks import EndpointSpec, parse_fallbacks
from src.common.llm.metrics import (
    record_fallback_served,
    record_request,
    set_circuit_open,
)
from src.common.llm.qwen_client import QwenLLMClient
from src.common.logging import get_logger

log = get_logger(__name__)

# 재시도 설정 (원인 고려 backoff 강화 — vLLM 재시작/crash 시 ~1분 정도 필요)
MAX_RETRIES = 4
RETRY_BACKOFF_TIMES = (1.0, 3.0, 8.0, 20.0)

# 느린 LLM 호출 추적 임계(ms). 이 시간 이상 걸린 호출은 llm_slow_call 로 로깅하여
# B200/vLLM 부하로 인한 처리속도 편차 디버깅에 사용. settings 로 오버라이드 가능.
LLM_SLOW_CALL_MS = getattr(settings, "LLM_SLOW_CALL_MS", 5000)

# 전역 동시성 가드: vLLM max_num_seqs=4 를 초과하지 않도록 프로세스 내 세마포어.
# pipeline-worker 의 모든 enricher/stage + api 의 classifier/distill 이 공유.
# vLLM 큐 오버플로우/OOM 방지 핵심 가드.
_VLLM_MAX_CONCURRENT = 4
_vllm_semaphore: asyncio.Semaphore | None = None


def _get_vllm_semaphore() -> asyncio.Semaphore:
    """현재 이벤트 루프에 바인드된 세마포어 지연 생성."""
    global _vllm_semaphore
    if _vllm_semaphore is None:
        _vllm_semaphore = asyncio.Semaphore(_VLLM_MAX_CONCURRENT)
    return _vllm_semaphore


# Redis 통계 키
_STATS_KEY = "kms:llm_stats:{provider}:{task}:{outcome}"
_STATS_TTL_SECONDS = 86400 * 7


def _is_retryable_error(exc: Exception) -> bool:
    """재시도 가능한 에러인지 판별."""
    if isinstance(exc, (TimeoutError, ConnectionError, OSError, asyncio.TimeoutError)):
        return True
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True

    status_code = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status_code is not None:
        if status_code in (401, 403, 400):
            return False
        if status_code == 429 or 500 <= status_code < 600:
            return True

    retryable_names = {
        "RateLimitError", "InternalServerError", "APIConnectionError",
        "APITimeoutError", "ServiceUnavailableError",
    }
    if type(exc).__name__ in retryable_names:
        return True
    return True  # 알 수 없는 에러는 보수적으로 retryable


class LLMRouter:
    """vLLM 엔드포인트 체인 라우터 (OpenAI API 호환).

    primary (settings.VLLM_URL) 로 먼저 시도하고, 실패 시 VLLM_FALLBACKS 순서로 폴백.
    각 엔드포인트는 독립된 circuit breaker 키 (`vllm:<label>`) 를 사용한다.
    """

    def __init__(self) -> None:
        self._endpoints: list[tuple[EndpointSpec, QwenLLMClient]] = []
        self._redis: aioredis.Redis | None = None
        self._init_endpoints()

    def _init_endpoints(self) -> None:
        # Primary
        if settings.VLLM_URL:
            primary_spec = EndpointSpec("primary", settings.VLLM_URL, settings.VLLM_MODEL)
            primary_client = QwenLLMClient(label="primary")
            self._endpoints.append((primary_spec, primary_client))
            log.info(
                "llm_client_initialized",
                provider="vllm",
                label="primary",
                model=settings.VLLM_MODEL,
                url=settings.VLLM_URL,
            )

        # Fallbacks
        raw = (settings.VLLM_FALLBACKS or "").strip()
        if raw and raw.lower() != "auto":
            # JSON 형식일 가능성 — 파싱 실패 시 경고 로그
            import json as _json
            try:
                _json.loads(raw)
            except _json.JSONDecodeError as exc:
                log.warning(
                    "llm_fallbacks_parse_error",
                    error=str(exc),
                    raw_prefix=raw[:80],
                )

        fallbacks = parse_fallbacks(settings.VLLM_FALLBACKS)
        for spec in fallbacks:
            client = QwenLLMClient(url=spec.url, model=spec.model, label=spec.label)
            self._endpoints.append((spec, client))
            log.info(
                "llm_fallback_client_initialized",
                provider="vllm",
                label=spec.label,
                model=spec.model,
                url=spec.url,
            )

    async def _get_redis(self) -> aioredis.Redis | None:
        if self._redis is None:
            try:
                self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            except Exception:
                return None
        return self._redis

    async def _record_stats(self, task: str, success: bool) -> None:
        try:
            r = await self._get_redis()
            if r is None:
                return
            outcome = "success" if success else "fail"
            key = _STATS_KEY.format(provider="vllm", task=task, outcome=outcome)
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, _STATS_TTL_SECONDS)
            await pipe.execute()
        except Exception:
            pass

    async def route(
        self,
        task: LLMTask,
        request: LLMRequest,
        config_override: dict | None = None,
    ) -> LLMResponse:
        """LLM 요청 라우팅 + 엔드포인트 체인 폴백 + 재시도 + circuit 가드."""
        if not self._endpoints:
            raise LLMRoutingError(task=task.value, errors={"vllm": "no endpoints configured"})

        last_error: Exception | None = None
        errors: dict[str, str] = {}

        for spec, client in self._endpoints:
            provider_key = f"vllm:{spec.label}"
            if await circuit_breaker.is_open(provider_key):
                set_circuit_open(spec.label, True)
                log.warning(
                    "llm_endpoint_circuit_open",
                    task=task.value,
                    label=spec.label,
                )
                errors[spec.label] = "circuit open"
                continue
            set_circuit_open(spec.label, False)

            semaphore = _get_vllm_semaphore()
            async with semaphore:
                endpoint_started = time.perf_counter()
                for attempt in range(1 + MAX_RETRIES):
                    try:
                        response = await client.generate(request)
                        duration = time.perf_counter() - endpoint_started
                        await self._record_stats(f"{task.value}:{spec.label}", success=True)
                        await circuit_breaker.record_success(provider_key)
                        record_request(spec.label, "success", duration)
                        _duration_ms = int(duration * 1000)
                        if _duration_ms >= LLM_SLOW_CALL_MS:
                            log.warning(
                                "llm_slow_call",
                                task=task.value,
                                label=spec.label,
                                duration_ms=_duration_ms,
                                attempt=attempt + 1,
                            )
                        if spec.label != "primary":
                            record_fallback_served(spec.label)
                            log.warning(
                                "llm_fallback_served",
                                task=task.value,
                                label=spec.label,
                            )
                        return response
                    except Exception as e:
                        last_error = e
                        if not _is_retryable_error(e):
                            # 명확한 클라이언트 에러 — 이 엔드포인트 포기하고 다음으로
                            log.warning(
                                "llm_endpoint_non_retryable",
                                task=task.value,
                                label=spec.label,
                                error=str(e),
                            )
                            errors[spec.label] = str(e)
                            break
                        if attempt < MAX_RETRIES:
                            backoff = RETRY_BACKOFF_TIMES[
                                min(attempt, len(RETRY_BACKOFF_TIMES) - 1)
                            ]
                            log.warning(
                                "llm_retry",
                                label=spec.label,
                                attempt=attempt + 1,
                                backoff=backoff,
                                error=str(e),
                            )
                            await asyncio.sleep(backoff)
                # 이 엔드포인트 retry 모두 소진 → 통계/circuit fail 기록 후 다음 시도
                duration = time.perf_counter() - endpoint_started
                await self._record_stats(f"{task.value}:{spec.label}", success=False)
                await circuit_breaker.record_failure(provider_key)
                record_request(spec.label, "fail", duration)
                errors.setdefault(spec.label, "all retries exhausted")
                log.warning(
                    "llm_endpoint_exhausted",
                    task=task.value,
                    label=spec.label,
                )

        # 모든 엔드포인트 실패
        raise LLMRoutingError(
            task=task.value,
            errors={"vllm": "all endpoints exhausted", **errors},
        ) from last_error

    async def route_stream(
        self,
        task: LLMTask,
        request: LLMRequest,
        config_override: dict | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """스트리밍 LLM 요청 + 엔드포인트 체인 폴백.

        첫 chunk 전 실패 → 다음 엔드포인트 시도.
        첫 chunk 후 실패 → 부분 응답 보존을 위해 LLMRoutingError 즉시 전파 (폴백 없음).
        """
        if not self._endpoints:
            raise LLMRoutingError(task=task.value, errors={"vllm": "no endpoints configured"})

        last_error: Exception | None = None
        for spec, client in self._endpoints:
            provider_key = f"vllm:{spec.label}"
            if await circuit_breaker.is_open(provider_key):
                set_circuit_open(spec.label, True)
                log.warning(
                    "llm_endpoint_circuit_open",
                    task=task.value,
                    label=spec.label,
                    stream=True,
                )
                continue
            set_circuit_open(spec.label, False)

            first_chunk_received = False
            endpoint_started = time.perf_counter()
            try:
                async for chunk in client.generate_stream(request):
                    first_chunk_received = True
                    yield chunk
                # 정상 종료
                duration = time.perf_counter() - endpoint_started
                await self._record_stats(f"{task.value}:{spec.label}", success=True)
                await circuit_breaker.record_success(provider_key)
                record_request(spec.label, "success", duration)
                if spec.label != "primary":
                    record_fallback_served(spec.label)
                    log.warning(
                        "llm_fallback_served_stream",
                        task=task.value,
                        label=spec.label,
                    )
                return
            except Exception as e:
                last_error = e
                duration = time.perf_counter() - endpoint_started
                await self._record_stats(f"{task.value}:{spec.label}", success=False)
                await circuit_breaker.record_failure(provider_key)
                record_request(spec.label, "fail", duration)
                if first_chunk_received:
                    # 중간 실패 → 이미 부분 응답이 consumer 로 흘러감. 폴백/재시도 금지.
                    log.warning(
                        "llm_stream_endpoint_failed_after_first_chunk",
                        task=task.value,
                        label=spec.label,
                        error=str(e),
                    )
                    raise LLMRoutingError(
                        task=task.value,
                        errors={"vllm": str(e)},
                    ) from e
                # 첫 chunk 전 실패 → 다음 엔드포인트 시도
                log.warning(
                    "llm_stream_endpoint_failed_before_first_chunk",
                    task=task.value,
                    label=spec.label,
                    error=str(e),
                )
                continue

        raise LLMRoutingError(
            task=task.value,
            errors={"vllm": "all endpoints exhausted"},
        ) from last_error

    async def route_vision(
        self,
        task: LLMTask,
        request: LLMVisionRequest,
        config_override: dict | None = None,
    ) -> LLMResponse:
        """비전 요청 라우팅 + 엔드포인트 체인 폴백 + 재시도 + circuit 가드."""
        if not self._endpoints:
            raise LLMRoutingError(task=task.value, errors={"vllm": "no endpoints configured"})

        last_error: Exception | None = None
        errors: dict[str, str] = {}

        for spec, client in self._endpoints:
            provider_key = f"vllm:{spec.label}"
            if await circuit_breaker.is_open(provider_key):
                set_circuit_open(spec.label, True)
                log.warning(
                    "llm_endpoint_circuit_open",
                    task=task.value,
                    label=spec.label,
                    vision=True,
                )
                errors[spec.label] = "circuit open"
                continue
            set_circuit_open(spec.label, False)

            semaphore = _get_vllm_semaphore()
            async with semaphore:
                endpoint_started = time.perf_counter()
                for attempt in range(1 + MAX_RETRIES):
                    try:
                        response = await client.generate_vision(request)
                        duration = time.perf_counter() - endpoint_started
                        await self._record_stats(f"{task.value}:{spec.label}", success=True)
                        await circuit_breaker.record_success(provider_key)
                        record_request(spec.label, "success", duration)
                        if spec.label != "primary":
                            record_fallback_served(spec.label)
                            log.warning(
                                "llm_fallback_served_vision",
                                task=task.value,
                                label=spec.label,
                            )
                        return response
                    except Exception as e:
                        last_error = e
                        if not _is_retryable_error(e):
                            log.warning(
                                "llm_endpoint_non_retryable",
                                task=task.value,
                                label=spec.label,
                                vision=True,
                                error=str(e),
                            )
                            errors[spec.label] = str(e)
                            break
                        if attempt < MAX_RETRIES:
                            backoff = RETRY_BACKOFF_TIMES[
                                min(attempt, len(RETRY_BACKOFF_TIMES) - 1)
                            ]
                            log.warning(
                                "llm_vision_retry",
                                label=spec.label,
                                attempt=attempt + 1,
                                backoff=backoff,
                                error=str(e),
                            )
                            await asyncio.sleep(backoff)
                duration = time.perf_counter() - endpoint_started
                await self._record_stats(f"{task.value}:{spec.label}", success=False)
                await circuit_breaker.record_failure(provider_key)
                record_request(spec.label, "fail", duration)
                errors.setdefault(spec.label, "all retries exhausted")
                log.warning(
                    "llm_endpoint_exhausted",
                    task=task.value,
                    label=spec.label,
                    vision=True,
                )

        raise LLMRoutingError(
            task=task.value,
            errors={"vllm": "all endpoints exhausted", **errors},
        ) from last_error

    async def get_provider_stats(self) -> dict:
        """엔드포인트별 circuit/통계 반환."""
        result: dict = {"providers": {}, "endpoints": {}}
        # Per-endpoint stats
        for spec, _client in self._endpoints:
            provider_key = f"vllm:{spec.label}"
            cb_status = await circuit_breaker.get_status(provider_key)
            # Gauge 동기화 — get_provider_stats 호출 시점 기준
            set_circuit_open(spec.label, cb_status.get("state") == "open")
            tasks_stats: dict = {}
            try:
                r = await self._get_redis()
                if r is not None:
                    for task in LLMTask:
                        s_key = _STATS_KEY.format(
                            provider="vllm",
                            task=f"{task.value}:{spec.label}",
                            outcome="success",
                        )
                        f_key = _STATS_KEY.format(
                            provider="vllm",
                            task=f"{task.value}:{spec.label}",
                            outcome="fail",
                        )
                        s_str, f_str = await asyncio.gather(r.get(s_key), r.get(f_key))
                        sc, fc = int(s_str or 0), int(f_str or 0)
                        total = sc + fc
                        if total > 0:
                            tasks_stats[task.value] = {
                                "success": sc,
                                "fail": fc,
                                "success_rate": round(sc / total, 3),
                            }
            except Exception:
                pass
            result["endpoints"][spec.label] = {
                "url": spec.url,
                "model": spec.model,
                "circuit_breaker": cb_status,
                "tasks": tasks_stats,
            }

        # Legacy top-level summary — 첫 엔드포인트 (primary) 기준
        if self._endpoints:
            primary_label = self._endpoints[0][0].label
            result["providers"]["vllm"] = {
                "configured": True,
                "circuit_breaker": result["endpoints"][primary_label]["circuit_breaker"],
                "tasks": result["endpoints"][primary_label]["tasks"],
            }
        else:
            result["providers"]["vllm"] = {
                "configured": False,
                "circuit_breaker": {"state": "closed", "fail_count": 0, "opened_at": None},
                "tasks": {},
            }
        return result


# 싱글턴
llm_router = LLMRouter()
