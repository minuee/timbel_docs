"""Circuit Breaker 패턴 구현 — 외부 서비스 장애 격리.

상태 전이:
    CLOSED  --(failure_threshold 연속 실패)--> OPEN
    OPEN    --(recovery_timeout 경과)-------> HALF_OPEN
    HALF_OPEN --(half_open_max_calls 성공)---> CLOSED
    HALF_OPEN --(1회 실패)-------------------> OPEN
"""

from __future__ import annotations

import asyncio
import enum
import functools
import time
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from src.common.logging import get_logger

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])

# ---------------------------------------------------------------------------
# Global registry — 이름으로 CircuitBreaker 인스턴스를 공유
# ---------------------------------------------------------------------------
_registry: dict[str, CircuitBreaker] = {}


def get_breaker(name: str) -> CircuitBreaker | None:
    """등록된 CircuitBreaker 조회."""
    return _registry.get(name)


def all_breakers() -> dict[str, CircuitBreaker]:
    """등록된 모든 CircuitBreaker 반환 (메트릭 수집용)."""
    return dict(_registry)


class CircuitState(str, enum.Enum):
    """Circuit breaker 상태."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """Circuit breaker가 OPEN 상태일 때 발생하는 예외."""

    def __init__(self, name: str, remaining_seconds: float) -> None:
        self.name = name
        self.remaining_seconds = remaining_seconds
        super().__init__(
            f"CircuitBreaker '{name}' is OPEN. "
            f"Retry after {remaining_seconds:.1f}s."
        )


class CircuitBreaker:
    """비동기 Circuit Breaker.

    Args:
        name: 식별 이름 (예: "webhook_dispatch", "sharepoint_sync")
        failure_threshold: OPEN 전환까지 허용하는 연속 실패 횟수
        recovery_timeout: OPEN → HALF_OPEN 전환까지 대기 시간(초)
        half_open_max_calls: HALF_OPEN에서 CLOSED 전환에 필요한 연속 성공 횟수
        excluded_exceptions: circuit breaker가 무시할 예외 타입 목록
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        excluded_exceptions: tuple[type[Exception], ...] = (),
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.excluded_exceptions = excluded_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_success_count = 0
        self._state_change_count = 0
        self._last_failure_time: float = 0.0
        self._lock = asyncio.Lock()

        # 메트릭
        self.total_failures = 0
        self.total_successes = 0

        # 글로벌 레지스트리에 등록
        _registry[name] = self

    # ------------------------------------------------------------------
    # 공개 속성
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """현재 상태 (OPEN 상태에서 timeout이 지나면 자동 HALF_OPEN)."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        """현재 연속 실패 횟수."""
        return self._failure_count

    @property
    def success_count(self) -> int:
        """현재 연속 성공 횟수."""
        return self._success_count

    @property
    def state_change_count(self) -> int:
        """상태 전환 총 횟수 (메트릭)."""
        return self._state_change_count

    # ------------------------------------------------------------------
    # 핵심 로직
    # ------------------------------------------------------------------

    async def call(self, func: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any) -> Any:
        """Circuit breaker를 통해 비동기 함수를 호출한다."""
        await self._before_call()
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            if isinstance(exc, self.excluded_exceptions):
                # 제외된 예외는 성공으로 취급
                await self._on_success()
                raise
            await self._on_failure()
            raise
        else:
            await self._on_success()
            return result

    async def _before_call(self) -> None:
        """호출 전 상태 확인."""
        async with self._lock:
            current = self.state

            if current == CircuitState.OPEN:
                remaining = self.recovery_timeout - (time.monotonic() - self._last_failure_time)
                log.warning(
                    "circuit_breaker_rejected",
                    name=self.name,
                    remaining_seconds=round(remaining, 1),
                )
                raise CircuitBreakerOpen(self.name, max(0.0, remaining))

            if current == CircuitState.HALF_OPEN:
                # HALF_OPEN 상태로 실제 전환 (OPEN → HALF_OPEN 자동 감지)
                if self._state == CircuitState.OPEN:
                    self._transition_to(CircuitState.HALF_OPEN)

    async def _on_success(self) -> None:
        """호출 성공 시 상태 갱신."""
        async with self._lock:
            self.total_successes += 1
            self._success_count += 1
            self._failure_count = 0

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_success_count += 1
                if self._half_open_success_count >= self.half_open_max_calls:
                    self._transition_to(CircuitState.CLOSED)

    async def _on_failure(self) -> None:
        """호출 실패 시 상태 갱신."""
        async with self._lock:
            self.total_failures += 1
            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # HALF_OPEN에서 1회 실패 → 즉시 OPEN
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """상태 전환 (lock 내부에서 호출)."""
        old_state = self._state
        self._state = new_state
        self._state_change_count += 1

        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._half_open_success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_success_count = 0
        elif new_state == CircuitState.OPEN:
            self._half_open_success_count = 0

        log.info(
            "circuit_breaker_state_change",
            name=self.name,
            from_state=old_state,
            to_state=new_state,
            failure_count=self._failure_count,
        )

    # ------------------------------------------------------------------
    # 수동 리셋
    # ------------------------------------------------------------------

    async def reset(self) -> None:
        """수동으로 CLOSED 상태로 리셋."""
        async with self._lock:
            self._transition_to(CircuitState.CLOSED)


# ---------------------------------------------------------------------------
# 데코레이터
# ---------------------------------------------------------------------------


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    half_open_max_calls: int = 3,
    excluded_exceptions: tuple[type[Exception], ...] = (),
) -> Callable[[F], F]:
    """Circuit breaker 데코레이터.

    같은 이름으로 여러 함수에 적용하면 동일한 CircuitBreaker 인스턴스를 공유한다.

    사용 예::

        @circuit_breaker("webhook_dispatch")
        async def send_webhook(url: str, payload: dict) -> None:
            ...
    """

    def decorator(func: F) -> F:
        # 동일 이름이면 기존 인스턴스 재사용
        breaker = _registry.get(name)
        if breaker is None:
            breaker = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                half_open_max_calls=half_open_max_calls,
                excluded_exceptions=excluded_exceptions,
            )

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await breaker.call(func, *args, **kwargs)

        # 데코레이터에 breaker 인스턴스를 노출 (테스트/디버깅용)
        wrapper.breaker = breaker  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
