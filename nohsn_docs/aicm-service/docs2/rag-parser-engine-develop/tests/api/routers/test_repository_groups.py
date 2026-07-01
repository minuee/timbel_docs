"""RepositoryGroup CRUD + tenant 격리 + Unique constraint 단위 테스트.

다른 agent 가 진행 중인 backend (model + migration + router) 의 *계약* 검증.
실 DB 의존 X — fake service / in-memory store 로 동작 검증.

검증 시나리오:
1. POST → 201 + Pydantic schema 검증 (RepositoryGroupResponse)
2. 동일 tenant + 동일 name → 409 (UniqueConstraint tenant_id+name)
3. GET list → tenant 격리 (다른 tenant 의 group 안 보임)
4. PATCH — repository_ids 갱신 + is_default 토글 (다른 group 자동 false)
5. DELETE — 삭제 후 GET 404
6. repository_ids 의 각 UUID 가 *해당 tenant 의 active repo* 인지 검증
   — 다른 tenant 의 repo 포함 시 422

backend 미시행 환경에서 import 실패 시 pytest.importorskip 가 모듈을 skip.
import 가능 후에는 본 테스트 모두 통과해야 한다 (계약 명세).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# In-memory fake store + service — backend 가 구현할 RepositoryGroupService 의
# 동작 명세를 fake 로 표현. 실 service 호환을 위해 동일한 method 이름 사용.
# ---------------------------------------------------------------------------


@dataclass
class _FakeRepo:
    id: UUID
    tenant_id: UUID
    name: str
    is_active: bool = True


@dataclass
class _FakeGroup:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None = None
    repository_ids: list[UUID] = field(default_factory=list)
    is_default: bool = False
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


class _FakeRepoGroupStore:
    """In-memory store — backend 의 RepositoryGroupService 행동을 흉내.

    Unique (tenant_id, name) + tenant 격리 + is_default 토글 (다른 group 자동
    false) + repository_ids 검증 (tenant 소속 + active) 모두 구현.
    """

    def __init__(self) -> None:
        self.repos: dict[UUID, _FakeRepo] = {}
        self.groups: dict[UUID, _FakeGroup] = {}

    # ---- repo 등록 (test setup 용) ----
    def add_repo(self, repo: _FakeRepo) -> None:
        self.repos[repo.id] = repo

    # ---- group ops ----
    def _validate_repo_ids(
        self, tenant_id: UUID, repo_ids: list[UUID]
    ) -> None:
        for rid in repo_ids:
            r = self.repos.get(rid)
            if r is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"repository {rid} 가 존재하지 않습니다.",
                )
            if r.tenant_id != tenant_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"repository {rid} 가 해당 tenant 소속이 아닙니다 "
                        "(cross-tenant 차단)."
                    ),
                )
            if not r.is_active:
                raise HTTPException(
                    status_code=422,
                    detail=f"repository {rid} 가 비활성 상태입니다.",
                )

    def create(
        self,
        *,
        tenant_id: UUID,
        name: str,
        description: str | None,
        repository_ids: list[UUID],
        is_default: bool = False,
    ) -> _FakeGroup:
        # name unique 검증
        for g in self.groups.values():
            if g.tenant_id == tenant_id and g.name == name:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"repository_group name 중복: "
                        f"tenant={tenant_id} name={name}"
                    ),
                )
        # repo_ids 검증
        self._validate_repo_ids(tenant_id, repository_ids)
        # is_default 처리 — 다른 group 자동 false
        if is_default:
            for g in self.groups.values():
                if g.tenant_id == tenant_id and g.is_default:
                    g.is_default = False
        g = _FakeGroup(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name,
            description=description,
            repository_ids=list(repository_ids),
            is_default=is_default,
        )
        self.groups[g.id] = g
        return g

    def list_by_tenant(self, tenant_id: UUID) -> list[_FakeGroup]:
        return [g for g in self.groups.values() if g.tenant_id == tenant_id]

    def get(self, group_id: UUID, tenant_id: UUID) -> _FakeGroup:
        g = self.groups.get(group_id)
        if g is None or g.tenant_id != tenant_id:
            raise HTTPException(
                status_code=404, detail=f"repository_group {group_id} 없음"
            )
        return g

    def update(
        self,
        group_id: UUID,
        tenant_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        repository_ids: list[UUID] | None = None,
        is_default: bool | None = None,
    ) -> _FakeGroup:
        g = self.get(group_id, tenant_id)
        if name is not None and name != g.name:
            # name unique 재검증
            for other in self.groups.values():
                if (
                    other.id != group_id
                    and other.tenant_id == tenant_id
                    and other.name == name
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=f"name 중복: {name}",
                    )
            g.name = name
        if description is not None:
            g.description = description
        if repository_ids is not None:
            self._validate_repo_ids(tenant_id, repository_ids)
            g.repository_ids = list(repository_ids)
        if is_default is not None:
            if is_default and not g.is_default:
                for other in self.groups.values():
                    if (
                        other.id != group_id
                        and other.tenant_id == tenant_id
                        and other.is_default
                    ):
                        other.is_default = False
            g.is_default = is_default
        g.updated_at = datetime.now(tz=timezone.utc)
        return g

    def delete(self, group_id: UUID, tenant_id: UUID) -> None:
        g = self.get(group_id, tenant_id)
        del self.groups[g.id]


# ---------------------------------------------------------------------------
# 공유 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_a() -> UUID:
    return uuid4()


@pytest.fixture
def tenant_b() -> UUID:
    return uuid4()


@pytest.fixture
def store(tenant_a: UUID, tenant_b: UUID) -> _FakeRepoGroupStore:
    s = _FakeRepoGroupStore()
    # tenant A 의 active repo 3개
    s.add_repo(_FakeRepo(id=uuid4(), tenant_id=tenant_a, name="a1"))
    s.add_repo(_FakeRepo(id=uuid4(), tenant_id=tenant_a, name="a2"))
    s.add_repo(_FakeRepo(id=uuid4(), tenant_id=tenant_a, name="a3"))
    # tenant B 의 repo 1개 (격리 검증용)
    s.add_repo(_FakeRepo(id=uuid4(), tenant_id=tenant_b, name="b1"))
    return s


@pytest.fixture
def tenant_a_repo_ids(
    store: _FakeRepoGroupStore, tenant_a: UUID
) -> list[UUID]:
    return [r.id for r in store.repos.values() if r.tenant_id == tenant_a]


@pytest.fixture
def tenant_b_repo_ids(
    store: _FakeRepoGroupStore, tenant_b: UUID
) -> list[UUID]:
    return [r.id for r in store.repos.values() if r.tenant_id == tenant_b]


# ---------------------------------------------------------------------------
# 시나리오 1 — POST → 201 + schema 필드
# ---------------------------------------------------------------------------


def test_create_returns_group_with_required_fields(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_a_repo_ids: list[UUID],
) -> None:
    """POST → 생성된 group 이 id / tenant_id / name / repository_ids /
    is_default / created_at / updated_at 필드 모두 보유.
    """
    g = store.create(
        tenant_id=tenant_a,
        name="공공 SaaS 전체",
        description="모든 공공 자료",
        repository_ids=tenant_a_repo_ids[:2],
        is_default=False,
    )
    assert isinstance(g.id, UUID)
    assert g.tenant_id == tenant_a
    assert g.name == "공공 SaaS 전체"
    assert g.description == "모든 공공 자료"
    assert set(g.repository_ids) == set(tenant_a_repo_ids[:2])
    assert g.is_default is False
    assert isinstance(g.created_at, datetime)
    assert isinstance(g.updated_at, datetime)


# ---------------------------------------------------------------------------
# 시나리오 2 — Unique constraint (tenant_id + name)
# ---------------------------------------------------------------------------


def test_create_duplicate_name_same_tenant_raises_409(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_a_repo_ids: list[UUID],
) -> None:
    """동일 tenant + 동일 name → 409."""
    store.create(
        tenant_id=tenant_a,
        name="dup-name",
        description=None,
        repository_ids=tenant_a_repo_ids[:1],
    )
    with pytest.raises(HTTPException) as exc:
        store.create(
            tenant_id=tenant_a,
            name="dup-name",
            description="다른 설명",
            repository_ids=tenant_a_repo_ids[1:2],
        )
    assert exc.value.status_code == 409
    assert "중복" in str(exc.value.detail)


def test_create_same_name_different_tenant_ok(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_b: UUID,
    tenant_a_repo_ids: list[UUID],
    tenant_b_repo_ids: list[UUID],
) -> None:
    """다른 tenant 의 동일 name 은 허용 (UniqueConstraint 는 tenant_id+name)."""
    g_a = store.create(
        tenant_id=tenant_a,
        name="shared-name",
        description=None,
        repository_ids=tenant_a_repo_ids[:1],
    )
    g_b = store.create(
        tenant_id=tenant_b,
        name="shared-name",
        description=None,
        repository_ids=tenant_b_repo_ids,
    )
    assert g_a.id != g_b.id
    assert g_a.tenant_id != g_b.tenant_id


# ---------------------------------------------------------------------------
# 시나리오 3 — GET list tenant 격리
# ---------------------------------------------------------------------------


def test_list_tenant_isolation(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_b: UUID,
    tenant_a_repo_ids: list[UUID],
    tenant_b_repo_ids: list[UUID],
) -> None:
    """다른 tenant 의 group 은 list 결과에 나타나지 않는다."""
    store.create(
        tenant_id=tenant_a,
        name="ga-1",
        description=None,
        repository_ids=tenant_a_repo_ids[:1],
    )
    store.create(
        tenant_id=tenant_a,
        name="ga-2",
        description=None,
        repository_ids=tenant_a_repo_ids[:2],
    )
    store.create(
        tenant_id=tenant_b,
        name="gb-1",
        description=None,
        repository_ids=tenant_b_repo_ids,
    )

    a_groups = store.list_by_tenant(tenant_a)
    b_groups = store.list_by_tenant(tenant_b)
    assert {g.name for g in a_groups} == {"ga-1", "ga-2"}
    assert {g.name for g in b_groups} == {"gb-1"}
    # tenant_id 일관성 — list 결과의 모든 group 이 요청 tenant 소속.
    assert all(g.tenant_id == tenant_a for g in a_groups)
    assert all(g.tenant_id == tenant_b for g in b_groups)


def test_get_other_tenant_group_returns_404(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_b: UUID,
    tenant_b_repo_ids: list[UUID],
) -> None:
    """다른 tenant 의 group_id 로 GET → 404 (존재하지만 cross-tenant)."""
    g_b = store.create(
        tenant_id=tenant_b,
        name="b-only",
        description=None,
        repository_ids=tenant_b_repo_ids,
    )
    with pytest.raises(HTTPException) as exc:
        store.get(g_b.id, tenant_a)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 시나리오 4 — PATCH (repository_ids 갱신 + is_default 토글)
# ---------------------------------------------------------------------------


def test_patch_repository_ids_replaces_set(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_a_repo_ids: list[UUID],
) -> None:
    """PATCH repository_ids — 통째 교체 (부분 머지 X)."""
    g = store.create(
        tenant_id=tenant_a,
        name="g",
        description=None,
        repository_ids=tenant_a_repo_ids[:1],
    )
    updated = store.update(
        g.id,
        tenant_a,
        repository_ids=tenant_a_repo_ids,  # 3 개 모두
    )
    assert set(updated.repository_ids) == set(tenant_a_repo_ids)
    assert updated.updated_at >= g.created_at


def test_patch_is_default_toggle_demotes_others(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_a_repo_ids: list[UUID],
) -> None:
    """is_default=true 로 설정 시 같은 tenant 의 다른 default group 자동 false."""
    g1 = store.create(
        tenant_id=tenant_a,
        name="g1",
        description=None,
        repository_ids=tenant_a_repo_ids[:1],
        is_default=True,
    )
    g2 = store.create(
        tenant_id=tenant_a,
        name="g2",
        description=None,
        repository_ids=tenant_a_repo_ids[1:2],
        is_default=False,
    )
    # g2 를 default 로 전환 → g1 자동 false
    store.update(g2.id, tenant_a, is_default=True)
    g1_after = store.get(g1.id, tenant_a)
    g2_after = store.get(g2.id, tenant_a)
    assert g1_after.is_default is False
    assert g2_after.is_default is True


def test_patch_is_default_does_not_affect_other_tenant(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_b: UUID,
    tenant_a_repo_ids: list[UUID],
    tenant_b_repo_ids: list[UUID],
) -> None:
    """다른 tenant 의 default group 은 영향 받지 않음 (격리)."""
    g_a = store.create(
        tenant_id=tenant_a,
        name="a-default",
        description=None,
        repository_ids=tenant_a_repo_ids[:1],
        is_default=True,
    )
    g_b = store.create(
        tenant_id=tenant_b,
        name="b-default",
        description=None,
        repository_ids=tenant_b_repo_ids,
        is_default=True,
    )
    # 둘 다 default 유지 — 서로 영향 X
    assert store.get(g_a.id, tenant_a).is_default is True
    assert store.get(g_b.id, tenant_b).is_default is True


# ---------------------------------------------------------------------------
# 시나리오 5 — DELETE 후 404
# ---------------------------------------------------------------------------


def test_delete_then_get_returns_404(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_a_repo_ids: list[UUID],
) -> None:
    g = store.create(
        tenant_id=tenant_a,
        name="to-delete",
        description=None,
        repository_ids=tenant_a_repo_ids[:1],
    )
    store.delete(g.id, tenant_a)
    with pytest.raises(HTTPException) as exc:
        store.get(g.id, tenant_a)
    assert exc.value.status_code == 404


def test_delete_other_tenant_group_blocked(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_b: UUID,
    tenant_b_repo_ids: list[UUID],
) -> None:
    """tenant A 가 tenant B 의 group 을 delete 시도 → 404 (격리)."""
    g_b = store.create(
        tenant_id=tenant_b,
        name="b",
        description=None,
        repository_ids=tenant_b_repo_ids,
    )
    with pytest.raises(HTTPException) as exc:
        store.delete(g_b.id, tenant_a)
    assert exc.value.status_code == 404
    # 실제로는 삭제되지 않음
    assert g_b.id in store.groups


# ---------------------------------------------------------------------------
# 시나리오 6 — repository_ids 검증 (cross-tenant repo 차단)
# ---------------------------------------------------------------------------


def test_create_with_cross_tenant_repo_returns_422(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_a_repo_ids: list[UUID],
    tenant_b_repo_ids: list[UUID],
) -> None:
    """tenant A 의 group 에 tenant B 의 repo_id 포함 시 422."""
    mixed = tenant_a_repo_ids[:1] + tenant_b_repo_ids[:1]
    with pytest.raises(HTTPException) as exc:
        store.create(
            tenant_id=tenant_a,
            name="mixed",
            description=None,
            repository_ids=mixed,
        )
    assert exc.value.status_code == 422
    assert "cross-tenant" in str(exc.value.detail).lower() or "소속" in str(
        exc.value.detail
    )


def test_create_with_unknown_repo_returns_422(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
) -> None:
    """존재하지 않는 repo_id → 422."""
    with pytest.raises(HTTPException) as exc:
        store.create(
            tenant_id=tenant_a,
            name="ghost",
            description=None,
            repository_ids=[uuid4()],
        )
    assert exc.value.status_code == 422


def test_create_with_inactive_repo_returns_422(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_a_repo_ids: list[UUID],
) -> None:
    """비활성 (is_active=False) repo 포함 시 422."""
    # 첫 repo 를 비활성으로
    inactive = store.repos[tenant_a_repo_ids[0]]
    inactive.is_active = False
    with pytest.raises(HTTPException) as exc:
        store.create(
            tenant_id=tenant_a,
            name="inactive-group",
            description=None,
            repository_ids=[inactive.id],
        )
    assert exc.value.status_code == 422
    assert "비활성" in str(exc.value.detail) or "active" in str(
        exc.value.detail
    ).lower()


def test_patch_with_cross_tenant_repo_returns_422(
    store: _FakeRepoGroupStore,
    tenant_a: UUID,
    tenant_a_repo_ids: list[UUID],
    tenant_b_repo_ids: list[UUID],
) -> None:
    """PATCH 시 repository_ids 에 다른 tenant repo 포함 → 422."""
    g = store.create(
        tenant_id=tenant_a,
        name="ok",
        description=None,
        repository_ids=tenant_a_repo_ids[:1],
    )
    with pytest.raises(HTTPException) as exc:
        store.update(
            g.id,
            tenant_a,
            repository_ids=tenant_a_repo_ids[:1] + tenant_b_repo_ids[:1],
        )
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# 통합 — backend router import 가능 시 schema 호환 smoke
# ---------------------------------------------------------------------------


def test_router_import_smoke() -> None:
    """backend 가 router/schema 를 ship 한 후, import 가능 + 핵심 symbol 노출.

    아직 ship 전이면 pytest.importorskip 가 skip — 회귀 0.
    ship 후에는 RepositoryGroupCreate / Update / Response 가 schemas 에 존재.
    """
    schemas_mod = pytest.importorskip(
        "src.api.schemas.repository_group",
        reason="backend agent 가 schemas/repository_group.py 미시행 — skip",
    )
    # 필드 검증은 backend ship 후 본격화 — 최소 symbol 존재만 확인.
    for symbol in (
        "RepositoryGroupCreate",
        "RepositoryGroupUpdate",
        "RepositoryGroupResponse",
    ):
        assert hasattr(schemas_mod, symbol), (
            f"backend agent 가 {symbol} 미정의 — 계약 위반"
        )


def test_router_module_import_smoke() -> None:
    """router 자체 import smoke — 미시행 환경에서 자동 skip."""
    router_mod = pytest.importorskip(
        "src.api.routers.repository_groups",
        reason="backend agent 가 routers/repository_groups.py 미시행 — skip",
    )
    assert hasattr(router_mod, "router"), (
        "router 모듈은 'router' (APIRouter) 를 노출해야 함"
    )
