"""Manifest YAML 로더 단위 테스트.

목적
----
- ``manifest/domains/*.yaml`` 모두 schema 통과 여부 검증.
- id 유일성, status 허용값, 정렬 순서 보장.
- 한 파일이 깨져도 전체 로드가 살아남는지 확인.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agent_framework.manifest.loader import (
    DOMAINS_DIR,
    ManifestLoadError,
    load_all_manifests,
    load_manifest_from_path,
)
from src.agent_framework.manifest.registry import DomainManifest


# ---------------------------------------------------------------------------
# 1. 정적 카탈로그 — 모든 yaml 이 schema 통과.
# ---------------------------------------------------------------------------


def test_all_domain_manifests_load_successfully() -> None:
    """domains/*.yaml 전부 schema 통과 + 최소 9 도메인 존재."""
    manifests = load_all_manifests()
    assert len(manifests) >= 9, (
        f"expected >=9 manifests, got {len(manifests)}: "
        f"{[m.id for m in manifests]}"
    )
    for m in manifests:
        assert isinstance(m, DomainManifest)
        assert m.id, "id must be non-empty"
        assert m.label, "label must be non-empty"
        assert m.icon, "icon must be non-empty"
        assert m.status in ("active", "available", "upcoming", "deprecated")


def test_required_domain_ids_present() -> None:
    """기획상 9 도메인 모두 카탈로그에 존재."""
    manifests = load_all_manifests()
    ids = {m.id for m in manifests}
    expected = {
        "inbox",
        "expense",
        "schedule",
        "diary",
        "knowledge",
        "agent_builder",
        "company",
        "stock_advisor",
        "restaurant_finder",
    }
    missing = expected - ids
    assert not missing, f"missing manifest ids: {missing}"


def test_domain_ids_are_unique() -> None:
    manifests = load_all_manifests()
    ids = [m.id for m in manifests]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"


def test_manifests_sorted_by_sort_order() -> None:
    manifests = load_all_manifests()
    sort_keys = [(m.sort_order, m.id) for m in manifests]
    assert sort_keys == sorted(sort_keys), "manifests not sorted"


def test_active_domains_have_endpoints() -> None:
    """active 도메인은 list_endpoint 또는 summary_endpoint 중 하나 이상 존재.

    upcoming/deprecated 는 endpoint 없어도 OK (placeholder 만 표시).
    """
    manifests = load_all_manifests()
    for m in manifests:
        if m.status == "active":
            assert m.list_endpoint or m.summary_endpoint, (
                f"active domain {m.id} must have list_endpoint or "
                "summary_endpoint"
            )


def test_no_emoji_in_labels_and_icons() -> None:
    """이모지 사용 금지 — label / icon / upcoming_message 검사."""
    manifests = load_all_manifests()
    for m in manifests:
        for field_name, value in (
            ("label", m.label),
            ("icon", m.icon),
            ("upcoming_message", m.upcoming_message or ""),
        ):
            for ch in value:
                # surrogate / emoji block 차단 — 단순 ASCII/한글/공백/구두점만 허용.
                code = ord(ch)
                assert code < 0x1F000 or code > 0x1FFFF, (
                    f"emoji codepoint U+{code:04X} in {m.id}.{field_name}"
                )


# ---------------------------------------------------------------------------
# 2. 단일 파일 파서 — 에러 케이스.
# ---------------------------------------------------------------------------


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ManifestLoadError):
        load_manifest_from_path(tmp_path / "nope.yaml")


def test_load_invalid_yaml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: x\n  bad: : :\n", encoding="utf-8")
    with pytest.raises(ManifestLoadError):
        load_manifest_from_path(bad)


def test_load_missing_required_field_raises(tmp_path: Path) -> None:
    f = tmp_path / "missing.yaml"
    f.write_text("id: x\nlabel: 라벨\nicon: mail\n", encoding="utf-8")  # status 없음
    with pytest.raises(ManifestLoadError):
        load_manifest_from_path(f)


def test_load_invalid_status_raises(tmp_path: Path) -> None:
    f = tmp_path / "bad_status.yaml"
    f.write_text(
        "id: x\nlabel: 라벨\nicon: mail\nstatus: bogus\n", encoding="utf-8"
    )
    with pytest.raises(ManifestLoadError):
        load_manifest_from_path(f)


def test_load_all_skips_broken_file_keeps_rest(tmp_path: Path) -> None:
    """한 파일 깨져도 나머지는 정상 로드."""
    good = tmp_path / "good.yaml"
    good.write_text(
        "id: good\nlabel: 정상\nicon: mail\nstatus: active\nsort_order: 5\n",
        encoding="utf-8",
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: bad\n  : : :\n", encoding="utf-8")
    out = load_all_manifests(tmp_path)
    ids = [m.id for m in out]
    assert "good" in ids
    assert "bad" not in ids


# ---------------------------------------------------------------------------
# 3. 도메인 핵심 필드 sanity — 코드 내 known component 이름과 schema 안정성.
# ---------------------------------------------------------------------------


def test_expense_manifest_has_quick_action_form_schema() -> None:
    """가계부 도메인은 지출 기록 액션이 form_schema 를 가짐 — frontend 폼 자동생성."""
    by_id = {m.id: m for m in load_all_manifests()}
    expense = by_id["expense"]
    log_action = next(
        (a for a in expense.quick_actions if a.id == "log_expense"), None
    )
    assert log_action is not None
    assert log_action.method == "POST"
    assert log_action.form_schema is not None
    props = log_action.form_schema.get("properties", {})
    assert "amount" in props
    assert "category" in props


def test_upcoming_domains_have_message() -> None:
    by_id = {m.id: m for m in load_all_manifests()}
    for did in ("company", "stock_advisor", "restaurant_finder"):
        m = by_id[did]
        assert m.status == "upcoming"
        assert m.upcoming_message, f"{did} must have upcoming_message"


def test_default_dir_is_alongside_loader() -> None:
    """DOMAINS_DIR 가 manifest/ 내 domains/ 디렉토리를 가리키는지."""
    assert DOMAINS_DIR.name == "domains"
    assert DOMAINS_DIR.parent.name == "manifest"
    assert DOMAINS_DIR.exists()


# ---------------------------------------------------------------------------
# 4. available_for_groups — 사용자 그룹 노출 필터링.
# ---------------------------------------------------------------------------


def test_all_active_domains_declare_available_for_groups() -> None:
    """active 도메인은 명시적 available_for_groups 를 가져야 — 의도치 않은 노출 방지.

    upcoming/deprecated 는 누락되어도 OK (어차피 placeholder).
    """
    manifests = load_all_manifests()
    for m in manifests:
        if m.status != "active":
            continue
        assert m.available_for_groups, (
            f"active domain {m.id} must declare available_for_groups "
            "(use [personal,company,business,sole_proprietor] for all-groups)"
        )


def test_available_for_groups_uses_known_group_names() -> None:
    """그룹 이름 오타 방지 — accounts.preferences.user_groups 와 동일 어휘."""
    allowed = {"personal", "company", "business", "sole_proprietor", "admin"}
    manifests = load_all_manifests()
    for m in manifests:
        for g in m.available_for_groups:
            assert g in allowed, f"unknown group '{g}' in {m.id}.available_for_groups"


def test_load_available_for_groups_default_empty(tmp_path: Path) -> None:
    """available_for_groups 누락 시 빈 리스트 — router 는 이를 'all groups' 로 해석."""
    f = tmp_path / "no_groups.yaml"
    f.write_text(
        "id: x\nlabel: 라벨\nicon: mail\nstatus: active\n", encoding="utf-8"
    )
    m = load_manifest_from_path(f)
    assert m.available_for_groups == []


def test_load_available_for_groups_must_be_list(tmp_path: Path) -> None:
    """문자열로 잘못 적으면 에러."""
    f = tmp_path / "bad_groups.yaml"
    f.write_text(
        "id: x\nlabel: 라벨\nicon: mail\nstatus: active\n"
        "available_for_groups: personal\n",  # list 가 아닌 string
        encoding="utf-8",
    )
    with pytest.raises(ManifestLoadError):
        load_manifest_from_path(f)


def test_load_available_for_groups_round_trip(tmp_path: Path) -> None:
    """list 로 정상 파싱 + to_dict 노출."""
    f = tmp_path / "groups.yaml"
    f.write_text(
        "id: x\nlabel: 라벨\nicon: mail\nstatus: active\n"
        "available_for_groups: [personal, company]\n",
        encoding="utf-8",
    )
    m = load_manifest_from_path(f)
    assert m.available_for_groups == ["personal", "company"]
    assert m.to_dict()["available_for_groups"] == ["personal", "company"]


def test_diary_personal_only_inbox_all_groups() -> None:
    """기획 의도 회귀 — 일기는 개인만, 메일은 모든 활성 그룹."""
    by_id = {m.id: m for m in load_all_manifests()}
    assert by_id["diary"].available_for_groups == ["personal"]
    inbox = set(by_id["inbox"].available_for_groups)
    assert {"personal", "company", "business", "sole_proprietor"} <= inbox


def test_agent_builder_admin_only() -> None:
    """에이전트 빌더는 admin 시스템 운영자 전용."""
    by_id = {m.id: m for m in load_all_manifests()}
    assert by_id["agent_builder"].available_for_groups == ["admin"]
