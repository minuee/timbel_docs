"""D24 §2 — _redis_store deprecation warning 검증.

검증:
1. _get_client 첫 진입 시 1회 DeprecationWarning emit.
2. 두 번째 호출에서는 emit 안 함 (once-flag).
3. _reset_sync 는 emit 안 함 (테스트 인프라).
"""
from __future__ import annotations

import importlib
import warnings

import pytest

from src.agent_framework.tools import _redis_store


@pytest.mark.asyncio
async def test_redis_legacy_deprecation_warning_once():
    """_get_client 첫 진입 시 DeprecationWarning, 두 번째 호출은 silent."""
    # once-flag 초기화 — 다른 테스트 영향 분리 (모듈 reload 대신 flag reset).
    _redis_store._DEPRECATION_WARNED = False

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DeprecationWarning)
        try:
            await _redis_store._get_client()
        except Exception:
            # Redis 연결 실패해도 emit 시점은 진입 직후 — 무시.
            pass

        # 첫 호출 emit 확인.
        deprecation_warns = [
            w for w in captured if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_warns) >= 1, (
            "_get_client 첫 호출 시 DeprecationWarning emit 안 됨"
        )
        msg = str(deprecation_warns[0].message)
        assert "redis legacy path" in msg
        assert "AGENT_DATA_STORE=kms" in msg
        assert "D25" in msg

        # 두 번째 호출 — emit 없음.
        captured.clear()
        try:
            await _redis_store._get_client()
        except Exception:
            pass
        deprecation_warns_2 = [
            w for w in captured if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_warns_2) == 0, (
            "_get_client 두 번째 호출 시 DeprecationWarning emit 됨 (once-flag 실패)"
        )


def test_reset_sync_does_not_emit_deprecation():
    """_reset_sync (테스트 인프라) 는 DeprecationWarning emit 안 함."""
    _redis_store._DEPRECATION_WARNED = False  # 초기화

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DeprecationWarning)
        try:
            _redis_store._reset_sync()
        except Exception:
            pass

        deprecation_warns = [
            w for w in captured if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_warns) == 0, (
            f"_reset_sync 가 DeprecationWarning emit 함: {[str(w.message) for w in deprecation_warns]}"
        )
