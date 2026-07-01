"""검색 scope multi-repo resolve 단위 테스트.

POST /api/v1/search 의 scope 필드 4 시나리오 + 기존 호환 + empty resolve.

scope 동작 명세:
| scope         | resolve 로직                                                |
| ------------- | ----------------------------------------------------------- |
| default       | tenant 의 is_default group → 없으면 tenant_all              |
| tenant_all    | tenant 의 모든 active repo (exclude_repository_ids 제외)    |
| specified     | repository_ids 만                                           |
| group         | repository_group_id 의 group.repository_ids                 |

기존 호환:
- repository_id (단수) → 기존 단일 검색 그대로 작동 (scope 미지정)
- scope 미지정 + repository_ids 단독 → 기존 multi-repo 호환 path

Empty resolve:
- scope=specified 인데 repository_ids 가 None/[] → 빈 결과 + warning log

실 검색 service 의존 X — resolve 단계만 단위 검증 (fake repo store).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest


# ---------------------------------------------------------------------------
# Fake repo store + scope resolver (backend 가 ship 할 helper 의 명세)
# ---------------------------------------------------------------------------


@dataclass
class _Repo:
    id: UUID
    tenant_id: UUID
    is_active: bool = True


@dataclass
class _Group:
    id: UUID
    tenant_id: UUID
    name: str
    repository_ids: list[UUID]
    is_default: bool = False


class _FakeStore:
    """tenant 별 repo + group in-memory store."""

    def __init__(self) -> None:
        self.repos: dict[UUID, _Repo] = {}
        self.groups: dict[UUID, _Group] = {}

    def add_repo(self, repo: _Repo) -> None:
        self.repos[repo.id] = repo

    def add_group(self, group: _Group) -> None:
        self.groups[group.id] = group

    def tenant_active_repo_ids(self, tenant_id: UUID) -> list[UUID]:
        return [
            r.id
            for r in self.repos.values()
            if r.tenant_id == tenant_id and r.is_active
        ]

    def tenant_default_group(self, tenant_id: UUID) -> _Group | None:
        for g in self.groups.values():
            if g.tenant_id == tenant_id and g.is_default:
                return g
        return None

    def get_group(self, group_id: UUID) -> _Group | None:
        return self.groups.get(group_id)


def resolve_search_scope(
    *,
    store: _FakeStore,
    tenant_id: UUID,
    scope: str | None,
    repository_id: UUID | None,
    repository_ids: list[UUID] | None,
    repository_group_id: UUID | None,
    exclude_repository_ids: list[UUID] | None,
    logger: logging.Logger | None = None,
) -> list[UUID]:
    """검색 scope → 실제 검색할 repo_ids 리스트로 변환.

    이 helper 는 backend 가 search.py 에 ship 할 *resolve 로직의 명세*.
    backend 의 실 helper 이름은 다를 수 있지만, 본 동작이 검증된다.

    Returns:
        검색 대상 repo_ids — 빈 리스트면 호출자가 empty 결과 반환.
    """
    log = logger or logging.getLogger(__name__)
    exclude = set(exclude_repository_ids or [])

    # 기존 호환 — scope 미지정 + repository_id 단독.
    if scope is None and repository_id is not None:
        return [repository_id]

    # 기존 호환 — scope 미지정 + repository_ids 단독.
    if scope is None and repository_ids:
        return [rid for rid in repository_ids if rid not in exclude]

    if scope == "specified":
        if not repository_ids:
            log.warning(
                "search_scope_specified_empty",
                extra={"tenant_id": str(tenant_id)},
            )
            return []
        return [rid for rid in repository_ids if rid not in exclude]

    if scope == "group":
        if repository_group_id is None:
            log.warning(
                "search_scope_group_missing_id",
                extra={"tenant_id": str(tenant_id)},
            )
            return []
        g = store.get_group(repository_group_id)
        if g is None or g.tenant_id != tenant_id:
            log.warning(
                "search_scope_group_not_found",
                extra={
                    "tenant_id": str(tenant_id),
                    "group_id": str(repository_group_id),
                },
            )
            return []
        return [rid for rid in g.repository_ids if rid not in exclude]

    if scope == "tenant_all":
        return [
            rid
            for rid in store.tenant_active_repo_ids(tenant_id)
            if rid not in exclude
        ]

    if scope == "default":
        g = store.tenant_default_group(tenant_id)
        if g is not None:
            return [rid for rid in g.repository_ids if rid not in exclude]
        # default group 없음 → tenant_all 폴백
        return [
            rid
            for rid in store.tenant_active_repo_ids(tenant_id)
            if rid not in exclude
        ]

    # scope 도 없고 repository_id/ids 도 없음 → 기존 동작 (tenant_all 자동 X) —
    # search service 가 자체 처리하도록 빈 리스트 반환 안 함, None 처리 위해
    # 빈 리스트 반환 시 호출자는 "필터 없음" 으로 해석할 수도 있음. 본 helper 는
    # 명시적 scope 의 *resolved repo_ids* 만 다룬다.
    return []


# ---------------------------------------------------------------------------
# Fixtures — tenant + repos + groups 시드
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_id() -> UUID:
    return uuid4()


@pytest.fixture
def other_tenant() -> UUID:
    return uuid4()


@pytest.fixture
def setup(
    tenant_id: UUID, other_tenant: UUID
) -> tuple[_FakeStore, list[UUID], UUID, UUID]:
    """tenant 에 3 active repo + 1 inactive repo + group A (repo[0,1]) + group B (repo[0]).

    Returns:
        (store, all_active_repo_ids, group_a_id, group_b_id)
    """
    store = _FakeStore()
    repo_ids = [uuid4(), uuid4(), uuid4()]
    for rid in repo_ids:
        store.add_repo(_Repo(id=rid, tenant_id=tenant_id, is_active=True))
    inactive_id = uuid4()
    store.add_repo(_Repo(id=inactive_id, tenant_id=tenant_id, is_active=False))
    # 다른 tenant 의 repo — tenant_all 결과에 나타나면 안 됨
    other_rid = uuid4()
    store.add_repo(_Repo(id=other_rid, tenant_id=other_tenant, is_active=True))

    group_a = _Group(
        id=uuid4(),
        tenant_id=tenant_id,
        name="A",
        repository_ids=[repo_ids[0], repo_ids[1]],
        is_default=False,
    )
    group_b = _Group(
        id=uuid4(),
        tenant_id=tenant_id,
        name="B",
        repository_ids=[repo_ids[0]],
        is_default=False,
    )
    store.add_group(group_a)
    store.add_group(group_b)
    return store, repo_ids, group_a.id, group_b.id


# ---------------------------------------------------------------------------
# 시나리오 1 — scope=specified + repository_ids
# ---------------------------------------------------------------------------


def test_scope_specified_returns_only_listed_repos(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID], tenant_id: UUID
) -> None:
    store, repo_ids, _, _ = setup
    out = resolve_search_scope(
        store=store,
        tenant_id=tenant_id,
        scope="specified",
        repository_id=None,
        repository_ids=[repo_ids[0], repo_ids[2]],
        repository_group_id=None,
        exclude_repository_ids=None,
    )
    assert set(out) == {repo_ids[0], repo_ids[2]}


# ---------------------------------------------------------------------------
# 시나리오 2 — scope=group + repository_group_id
# ---------------------------------------------------------------------------


def test_scope_group_resolves_to_group_repos(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID], tenant_id: UUID
) -> None:
    store, repo_ids, group_a_id, _ = setup
    out = resolve_search_scope(
        store=store,
        tenant_id=tenant_id,
        scope="group",
        repository_id=None,
        repository_ids=None,
        repository_group_id=group_a_id,
        exclude_repository_ids=None,
    )
    assert set(out) == {repo_ids[0], repo_ids[1]}


def test_scope_group_other_tenant_group_id_empty(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID],
    tenant_id: UUID,
    other_tenant: UUID,
) -> None:
    """다른 tenant 의 group_id 로 호출 시 빈 결과 + warning."""
    store, _, _, _ = setup
    # other_tenant 의 group 추가
    other_group = _Group(
        id=uuid4(),
        tenant_id=other_tenant,
        name="cross",
        repository_ids=[uuid4()],
    )
    store.add_group(other_group)

    out = resolve_search_scope(
        store=store,
        tenant_id=tenant_id,
        scope="group",
        repository_id=None,
        repository_ids=None,
        repository_group_id=other_group.id,
        exclude_repository_ids=None,
    )
    assert out == []


# ---------------------------------------------------------------------------
# 시나리오 3 — scope=tenant_all + exclude_repository_ids
# ---------------------------------------------------------------------------


def test_scope_tenant_all_includes_only_active_repos(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID], tenant_id: UUID
) -> None:
    store, repo_ids, _, _ = setup
    out = resolve_search_scope(
        store=store,
        tenant_id=tenant_id,
        scope="tenant_all",
        repository_id=None,
        repository_ids=None,
        repository_group_id=None,
        exclude_repository_ids=None,
    )
    # 3 active repo 모두 포함, inactive + 다른 tenant 미포함.
    assert set(out) == set(repo_ids)


def test_scope_tenant_all_with_exclude(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID], tenant_id: UUID
) -> None:
    """exclude_repository_ids 에 명시된 repo 제외."""
    store, repo_ids, _, _ = setup
    out = resolve_search_scope(
        store=store,
        tenant_id=tenant_id,
        scope="tenant_all",
        repository_id=None,
        repository_ids=None,
        repository_group_id=None,
        exclude_repository_ids=[repo_ids[0]],
    )
    assert repo_ids[0] not in out
    assert set(out) == {repo_ids[1], repo_ids[2]}


# ---------------------------------------------------------------------------
# 시나리오 4 — scope=default 분기
# ---------------------------------------------------------------------------


def test_scope_default_with_default_group_uses_group(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID], tenant_id: UUID
) -> None:
    """tenant 에 default group 있음 → 그 group 의 repos."""
    store, repo_ids, group_a_id, _ = setup
    # group A 를 default 로 설정
    store.groups[group_a_id].is_default = True

    out = resolve_search_scope(
        store=store,
        tenant_id=tenant_id,
        scope="default",
        repository_id=None,
        repository_ids=None,
        repository_group_id=None,
        exclude_repository_ids=None,
    )
    assert set(out) == {repo_ids[0], repo_ids[1]}


def test_scope_default_without_default_group_falls_back_to_tenant_all(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID], tenant_id: UUID
) -> None:
    """default group 없음 → tenant_all (모든 active repo)."""
    store, repo_ids, _, _ = setup
    # 둘 다 is_default=False — default group 없는 상태.

    out = resolve_search_scope(
        store=store,
        tenant_id=tenant_id,
        scope="default",
        repository_id=None,
        repository_ids=None,
        repository_group_id=None,
        exclude_repository_ids=None,
    )
    assert set(out) == set(repo_ids)


# ---------------------------------------------------------------------------
# 기존 호환 — repository_id (단수) 그대로 작동
# ---------------------------------------------------------------------------


def test_legacy_repository_id_single_passthrough(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID], tenant_id: UUID
) -> None:
    """scope 미지정 + repository_id 단수 → 그대로 단일 repo 반환."""
    store, repo_ids, _, _ = setup
    out = resolve_search_scope(
        store=store,
        tenant_id=tenant_id,
        scope=None,
        repository_id=repo_ids[2],
        repository_ids=None,
        repository_group_id=None,
        exclude_repository_ids=None,
    )
    assert out == [repo_ids[2]]


def test_legacy_repository_ids_multi_passthrough(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID], tenant_id: UUID
) -> None:
    """scope 미지정 + repository_ids 복수 → 그대로 반환 (기존 multi-repo 호환)."""
    store, repo_ids, _, _ = setup
    out = resolve_search_scope(
        store=store,
        tenant_id=tenant_id,
        scope=None,
        repository_id=None,
        repository_ids=[repo_ids[0], repo_ids[1]],
        repository_group_id=None,
        exclude_repository_ids=None,
    )
    assert set(out) == {repo_ids[0], repo_ids[1]}


# ---------------------------------------------------------------------------
# Empty resolve — scope=specified 인데 repo 미지정 → 빈 결과 + warning
# ---------------------------------------------------------------------------


def test_scope_specified_empty_returns_empty_with_warning(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID],
    tenant_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """scope=specified 인데 repository_ids 빈 값 → 빈 결과 + warning."""
    store, _, _, _ = setup
    with caplog.at_level(logging.WARNING):
        out = resolve_search_scope(
            store=store,
            tenant_id=tenant_id,
            scope="specified",
            repository_id=None,
            repository_ids=None,
            repository_group_id=None,
            exclude_repository_ids=None,
        )
    assert out == []
    # warning 발생 검증 (메시지 명세는 backend 가 미세 조정 가능)
    assert any(
        "specified" in rec.message.lower() or "empty" in rec.message.lower()
        for rec in caplog.records
    )


def test_scope_group_missing_id_empty(
    setup: tuple[_FakeStore, list[UUID], UUID, UUID],
    tenant_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """scope=group 인데 repository_group_id 미지정 → 빈 결과 + warning."""
    store, _, _, _ = setup
    with caplog.at_level(logging.WARNING):
        out = resolve_search_scope(
            store=store,
            tenant_id=tenant_id,
            scope="group",
            repository_id=None,
            repository_ids=None,
            repository_group_id=None,
            exclude_repository_ids=None,
        )
    assert out == []
    assert any("group" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# 통합 — backend 가 SearchRequest 에 scope 필드 추가 시 schema 호환 smoke
# ---------------------------------------------------------------------------


def test_search_request_schema_has_scope_fields() -> None:
    """backend ship 후, SearchRequest 가 scope/repository_group_id/
    exclude_repository_ids 필드 노출.

    미시행 환경에서는 skip (importorskip).
    """
    schemas_mod = pytest.importorskip(
        "src.api.schemas.search",
        reason="search schema 모듈 미존재 — 환경 문제 (skip)",
    )
    SearchRequest = getattr(schemas_mod, "SearchRequest", None)
    assert SearchRequest is not None, "SearchRequest 가 미정의"

    fields = SearchRequest.model_fields
    # backend 가 ship 한 경우만 본격 검증. 미시행이면 skip.
    if "scope" not in fields:
        pytest.skip(
            "backend agent 가 SearchRequest.scope 필드 미추가 — skip"
        )
    # 신규 필드 모두 존재 검증
    for fname in ("scope", "repository_group_id", "exclude_repository_ids"):
        assert fname in fields, (
            f"backend ship 됐지만 {fname} 누락 — 계약 위반"
        )
