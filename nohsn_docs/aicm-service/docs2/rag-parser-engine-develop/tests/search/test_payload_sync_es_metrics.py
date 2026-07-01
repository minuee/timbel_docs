"""D31d Phase 3 §3 (#212) — ES 색인 retry/failure counter unit tests.

검증:
- classify_es_error 4 분기 매핑 (timeout/conflict/connection/other).
- _es_set_document_status retry/failure inc.
- _es_set_document_title retry/failure inc.
- sync_search_excluded ES retry/failure inc.
- 비파괴: retry 와 failure counter 가 *동일 attempt 에서 중복 inc 되지 않음*.
- false positive: 1 회 시도 성공 시 counter 변화 0.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from src.common.metrics import (
    KMS_ES_INDEX_FAILURE_TOTAL,
    KMS_ES_INDEX_RETRY_TOTAL,
    classify_es_error,
)


def _read_retry(reason: str) -> float:
    return KMS_ES_INDEX_RETRY_TOTAL.labels(reason=reason)._value.get()


def _read_failure(reason: str) -> float:
    return KMS_ES_INDEX_FAILURE_TOTAL.labels(reason=reason)._value.get()


# ---------------------------------------------------------------------------
# classify_es_error 4 분기
# ---------------------------------------------------------------------------


def test_classify_es_error_timeout_by_class_name() -> None:
    """클래스명에 'timeout' 포함 → timeout."""

    class CustomTimeoutError(Exception):
        pass

    assert classify_es_error(CustomTimeoutError("read timeout")) == "timeout"


def test_classify_es_error_timeout_by_asyncio() -> None:
    """asyncio.TimeoutError → timeout."""
    assert classify_es_error(asyncio.TimeoutError()) == "timeout"


def test_classify_es_error_conflict_by_status_code() -> None:
    """exc.status_code = 409 → conflict."""

    class ApiError(Exception):
        def __init__(self, msg: str) -> None:
            super().__init__(msg)
            self.status_code = 409

    assert classify_es_error(ApiError("version conflict")) == "conflict"


def test_classify_es_error_conflict_by_status_attr() -> None:
    """exc.status = 409 → conflict (대안 속성)."""

    class ApiError(Exception):
        def __init__(self, msg: str) -> None:
            super().__init__(msg)
            self.status = 409

    assert classify_es_error(ApiError("conflict")) == "conflict"


def test_classify_es_error_conflict_by_class_name() -> None:
    """클래스명에 'Conflict' 포함 → conflict."""

    class ConflictErrorCustom(Exception):
        pass

    assert classify_es_error(ConflictErrorCustom("v_conflict")) == "conflict"


def test_classify_es_error_connection_by_class_name() -> None:
    """클래스명에 'Connection' 포함 → connection."""

    class CustomConnectionError(Exception):
        pass

    assert classify_es_error(CustomConnectionError("refused")) == "connection"


def test_classify_es_error_connection_refused() -> None:
    """ConnectionRefusedError → connection."""
    assert classify_es_error(ConnectionRefusedError("refused")) == "connection"


def test_classify_es_error_other_default() -> None:
    """기타 → other."""
    assert classify_es_error(RuntimeError("unknown")) == "other"
    assert classify_es_error(ValueError("bad")) == "other"


# ---------------------------------------------------------------------------
# _es_set_document_status retry/failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_es_set_document_status_all_fail_retry_then_failure() -> None:
    """3 attempt 모두 실패 — retry inc 2 (attempts 1, 2), failure inc 1 (attempt 3 = 최종).

    GPT-5 §3 verdict: 최종 attempt 는 retry 가 아닌 failure 로만 카운트.
    """
    from src.search import payload_sync

    # 클래스명에 timeout/conflict/connection 포함 X → reason="other".
    class GenericFault(Exception):
        pass

    before_retry = _read_retry("other")
    before_failure = _read_failure("other")

    async def _raise_always(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise GenericFault("boom")

    with patch.object(
        payload_sync,
        "_es_set_document_status_once",
        side_effect=_raise_always,
    ):
        # asyncio.sleep 도 mock 으로 빠르게 통과.
        with patch.object(payload_sync.asyncio, "sleep", return_value=None):
            result = await payload_sync._es_set_document_status(
                "ricky-personal",
                "00000000-0000-0000-0000-000000000000",
                "active",
            )

    assert result == (0, "GenericFault: boom")  # 비파괴 — 기존 반환 유지.

    after_retry = _read_retry("other")
    after_failure = _read_failure("other")

    # 3 attempts: 1+2 = retry, 3 = failure.
    assert after_retry == before_retry + 2.0
    assert after_failure == before_failure + 1.0


@pytest.mark.asyncio
async def test_es_set_document_status_first_success_no_inc() -> None:
    """첫 시도 성공 — retry 와 failure counter 모두 변화 0."""
    from src.search import payload_sync

    before_retry = _read_retry("other")
    before_failure = _read_failure("other")

    async def _ok(*_args, **_kwargs) -> int:  # type: ignore[no-untyped-def]
        return 5

    with patch.object(
        payload_sync,
        "_es_set_document_status_once",
        side_effect=_ok,
    ):
        result = await payload_sync._es_set_document_status(
            "ricky-personal",
            "11111111-1111-1111-1111-111111111111",
            "active",
        )

    assert result == (5, "")

    after_retry = _read_retry("other")
    after_failure = _read_failure("other")
    assert after_retry == before_retry
    assert after_failure == before_failure


@pytest.mark.asyncio
async def test_es_set_document_status_recover_on_2nd_attempt() -> None:
    """1 fail + 2 success — retry +1, failure +0."""
    from src.search import payload_sync

    before_retry = _read_retry("connection")
    before_failure = _read_failure("connection")

    call_count = {"n": 0}

    async def _fail_then_ok(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionRefusedError("refused")
        return 3

    with patch.object(
        payload_sync,
        "_es_set_document_status_once",
        side_effect=_fail_then_ok,
    ):
        with patch.object(payload_sync.asyncio, "sleep", return_value=None):
            result = await payload_sync._es_set_document_status(
                "ricky-personal",
                "22222222-2222-2222-2222-222222222222",
                "active",
            )

    assert result == (3, "")

    after_retry = _read_retry("connection")
    after_failure = _read_failure("connection")
    assert after_retry == before_retry + 1.0
    assert after_failure == before_failure


# ---------------------------------------------------------------------------
# _es_set_document_title retry/failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_es_set_document_title_all_fail_timeout_classify() -> None:
    """asyncio.TimeoutError → reason=timeout 로 분류 + retry/failure inc."""
    from src.search import payload_sync

    before_retry = _read_retry("timeout")
    before_failure = _read_failure("timeout")

    async def _raise_timeout(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise asyncio.TimeoutError()

    with patch.object(
        payload_sync,
        "_es_set_document_title_once",
        side_effect=_raise_timeout,
    ):
        with patch.object(payload_sync.asyncio, "sleep", return_value=None):
            await payload_sync._es_set_document_title(
                "ricky-personal",
                "33333333-3333-3333-3333-333333333333",
                "new-title",
            )

    after_retry = _read_retry("timeout")
    after_failure = _read_failure("timeout")
    assert after_retry == before_retry + 2.0
    assert after_failure == before_failure + 1.0


# ---------------------------------------------------------------------------
# sync_search_excluded ES 파트
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_search_excluded_es_all_fail_conflict() -> None:
    """ES 3 attempt 모두 conflict 실패 — retry 2 + failure 1, reason=conflict."""
    from src.search import payload_sync

    before_retry = _read_retry("conflict")
    before_failure = _read_failure("conflict")

    class _Conflict(Exception):
        def __init__(self) -> None:
            super().__init__("v_conflict")
            self.status_code = 409

    async def _raise_conflict(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise _Conflict()

    async def _qdrant_ok(*_args, **_kwargs) -> int:  # type: ignore[no-untyped-def]
        return 1

    class _StubResult:
        def fetchone(self):  # type: ignore[no-untyped-def]
            return ("ricky-personal",)

    class _StubSession:
        async def execute(self, *_args, **_kwargs) -> _StubResult:
            return _StubResult()

    with patch.object(
        payload_sync,
        "_es_set_search_excluded_once",
        side_effect=_raise_conflict,
    ), patch.object(
        payload_sync,
        "_qdrant_set_search_excluded_once",
        side_effect=_qdrant_ok,
    ):
        with patch.object(payload_sync.asyncio, "sleep", return_value=None):
            result = await payload_sync.sync_search_excluded(
                "44444444-4444-4444-4444-444444444444",
                excluded=True,
                db=_StubSession(),  # type: ignore[arg-type]
            )

    # 비파괴: 기존 dict 반환 유지.
    assert result["qdrant"] == 1
    assert result["es"] == 0

    after_retry = _read_retry("conflict")
    after_failure = _read_failure("conflict")
    assert after_retry == before_retry + 2.0
    assert after_failure == before_failure + 1.0


# ---------------------------------------------------------------------------
# metric 정의
# ---------------------------------------------------------------------------


def test_kms_es_index_metric_definitions() -> None:
    """metric 이름 + label 정의."""
    assert KMS_ES_INDEX_RETRY_TOTAL._name == "kms_es_index_retry"
    assert KMS_ES_INDEX_FAILURE_TOTAL._name == "kms_es_index_failure"
    assert KMS_ES_INDEX_RETRY_TOTAL._labelnames == ("reason",)
    assert KMS_ES_INDEX_FAILURE_TOTAL._labelnames == ("reason",)
