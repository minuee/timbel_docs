"""D23 §7 — admin null-owner sentinel 단위 테스트 (GPT-5 phase 0 R4 GO).

include_null_owner 의 strict contract:
- False → False (격리, default)
- ADMIN_NULL_OWNER_OK (sentinel identity) → True (NULL bucket 노출, admin only)
- 일반 bool True → ValueError (admin enforcement 우회 차단)
- 그 외 truthy → ValueError
"""
from __future__ import annotations

import pytest

from src.agent_framework.storage import agent_document_store as ads


def test_resolve_default_false() -> None:
    assert ads._resolve_include_null_owner(False) is False


def test_resolve_none_false() -> None:
    assert ads._resolve_include_null_owner(None) is False


def test_resolve_sentinel_true() -> None:
    """ADMIN_NULL_OWNER_OK identity → True."""
    assert ads._resolve_include_null_owner(ads.ADMIN_NULL_OWNER_OK) is True


def test_resolve_bool_true_rejected() -> None:
    """일반 bool True 는 admin enforcement 우회 차단."""
    with pytest.raises(ValueError, match="admin 전용"):
        ads._resolve_include_null_owner(True)


def test_resolve_string_yes_rejected() -> None:
    """string 'yes' / 1 같은 truthy 도 sentinel 만 허용."""
    with pytest.raises(ValueError):
        ads._resolve_include_null_owner("yes")


def test_resolve_int_one_rejected() -> None:
    with pytest.raises(ValueError):
        ads._resolve_include_null_owner(1)


def test_sentinel_singleton() -> None:
    """ADMIN_NULL_OWNER_OK 는 모듈 수준 단일 인스턴스 — identity 비교."""
    s1 = ads.ADMIN_NULL_OWNER_OK
    s2 = ads.ADMIN_NULL_OWNER_OK
    assert s1 is s2


def test_sentinel_repr() -> None:
    """디버깅 보조 — 명확한 repr."""
    assert repr(ads.ADMIN_NULL_OWNER_OK) == "ADMIN_NULL_OWNER_OK"


def test_sentinel_truthy() -> None:
    """admin path 에서 ``if include_null_owner`` 같은 truthy 검사 호환."""
    assert bool(ads.ADMIN_NULL_OWNER_OK) is True


def test_new_instance_not_accepted() -> None:
    """새 _AdminNullOwnerOk 인스턴스는 identity 가 다르므로 차단되어야 한다.

    (외부에서 _AdminNullOwnerOk 를 import 해 만들 가능성은 낮지만 — 보안 보장).
    """
    new_instance = ads._AdminNullOwnerOk()
    # 실제 비교는 ``is`` identity 만 — sentinel 모듈 수준만 통과.
    # 새 인스턴스는 identity 다름 → 일반 truthy 처리 → ValueError.
    with pytest.raises(ValueError):
        ads._resolve_include_null_owner(new_instance)
