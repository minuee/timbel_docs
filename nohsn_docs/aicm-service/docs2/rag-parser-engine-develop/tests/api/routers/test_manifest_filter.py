"""Manifest router — 사용자 그룹 필터링 단위 테스트.

router 의 ``_is_visible_for_user`` 헬퍼만 직접 검증. DB 통합 테스트는 별도.
"""
from __future__ import annotations

from src.api.routers.manifest import _is_visible_for_user


# ---------------------------------------------------------------------------
# admin 사용자 — 모든 도메인 노출.
# ---------------------------------------------------------------------------


def test_admin_sees_all_domains() -> None:
    assert _is_visible_for_user(["personal"], ["admin"]) is True
    assert _is_visible_for_user(["admin"], ["admin"]) is True
    # admin 외 그룹도 함께 보유 — 어차피 풀 액세스.
    assert _is_visible_for_user(["personal"], ["admin", "company"]) is True


# ---------------------------------------------------------------------------
# 빈 available_for_groups — 모든 그룹 노출 (legacy default).
# ---------------------------------------------------------------------------


def test_empty_available_for_groups_visible_to_all() -> None:
    assert _is_visible_for_user([], ["personal"]) is True
    assert _is_visible_for_user([], ["company"]) is True
    assert _is_visible_for_user([], []) is True


# ---------------------------------------------------------------------------
# 빈 user_groups — legacy 시드 사용자, 모든 active 그룹 가정.
# ---------------------------------------------------------------------------


def test_legacy_user_no_groups_sees_personal_only() -> None:
    """user_groups 가 비어있는 옛 시드 계정 — 보수적 fallback (personal-only).

    codex 검토(2026-04-28): 미시드 계정도 회사/사업자 도메인이 보이면 안 됨.
    """
    assert _is_visible_for_user(["personal"], []) is True
    # personal 외 그룹은 가려져야 함 — 시드 누락 계정 보호.
    assert _is_visible_for_user(["company"], []) is False
    assert _is_visible_for_user(["business"], []) is False
    assert _is_visible_for_user(["sole_proprietor"], []) is False
    assert _is_visible_for_user(["admin"], []) is False


# ---------------------------------------------------------------------------
# 교집합 — 그룹 매칭.
# ---------------------------------------------------------------------------


def test_personal_user_sees_personal_domain() -> None:
    assert _is_visible_for_user(["personal"], ["personal"]) is True


def test_personal_user_does_not_see_company_only_domain() -> None:
    assert _is_visible_for_user(["company"], ["personal"]) is False


def test_personal_user_does_not_see_admin_only_domain() -> None:
    assert _is_visible_for_user(["admin"], ["personal"]) is False


def test_overlap_one_group_enough() -> None:
    """다중 그룹 사용자 — 한 도메인이라도 매칭하면 노출."""
    assert (
        _is_visible_for_user(
            ["company", "business"], ["personal", "company"]
        )
        is True
    )


def test_no_overlap_hidden() -> None:
    assert (
        _is_visible_for_user(
            ["company", "business"], ["personal", "sole_proprietor"]
        )
        is False
    )


# ---------------------------------------------------------------------------
# 시드된 Ricky 케이스 — 모든 그룹 보유.
# ---------------------------------------------------------------------------


def test_ricky_full_groups_sees_everything() -> None:
    """Ricky preferences.user_groups = 전 그룹 — 모든 도메인 노출."""
    ricky = ["admin", "personal", "company", "business", "sole_proprietor"]
    # admin 포함 → 무조건 true
    assert _is_visible_for_user(["personal"], ricky) is True
    assert _is_visible_for_user(["company"], ricky) is True
    assert _is_visible_for_user(["admin"], ricky) is True
    assert _is_visible_for_user([], ricky) is True


# ---------------------------------------------------------------------------
# 1인 사업자 — personal + sole_proprietor 만 노출.
# ---------------------------------------------------------------------------


def test_sole_proprietor_only_groups() -> None:
    user_groups = ["sole_proprietor"]
    assert (
        _is_visible_for_user(["personal", "sole_proprietor"], user_groups)
        is True
    )
    assert (
        _is_visible_for_user(["personal"], user_groups) is False
    )  # personal 만 노출인 도메인 (예: 일기) 은 안 보임
    assert _is_visible_for_user(["company"], user_groups) is False
