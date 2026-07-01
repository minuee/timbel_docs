"""RepositoryGroup E2E 통합 테스트 (staging 환경 대상).

staging Locus-KMS (port 5201 default) 가 가동 중일 때만 실행.
``LUCAS_KMS_BASE_URL`` 환경 변수 미설정 시 자동 skip.

시나리오:
1. 2 repo 생성 → group A (repo1+repo2) + group B (repo1) 생성
2. group A 를 default 로 설정
3. group A.is_default=true, group B.is_default=false 검증
4. POST /api/v1/search { scope: "default" } → group A 의 chunk 반환
5. POST /api/v1/search { scope: "group", repository_group_id: B } → group B 만
6. DELETE group A → 남은 group B 가 default 로 자동 promote 되는지 (선택 확인)

requires_db marker — pytest -m requires_db 일 때만 수집.
"""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import pytest


pytestmark = pytest.mark.requires_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base_url() -> str:
    """staging Locus-KMS base URL.

    환경변수 ``LUCAS_KMS_BASE_URL`` 우선, 미설정 시 staging default (5201).
    실제 staging 미가동이면 health check 단에서 skip.
    """
    return os.environ.get("LUCAS_KMS_BASE_URL", "http://localhost:5201")


@pytest.fixture(scope="module")
def tenant_id() -> str:
    """staging 기본 tenant. .env.staging 의 default tenant."""
    return os.environ.get(
        "LUCAS_KMS_TENANT_ID", "00000000-0000-0000-0000-000000000001"
    )


@pytest.fixture(scope="module")
def http_client(base_url: str):
    """staging Locus-KMS 가 떠 있어야 의미 있는 테스트. health check + skip."""
    httpx = pytest.importorskip("httpx", reason="httpx 미설치")
    client = httpx.Client(base_url=base_url, timeout=30.0)
    try:
        r = client.get("/health")
        if r.status_code != 200:
            pytest.skip(f"staging Locus-KMS unhealthy ({r.status_code})")
    except Exception as exc:
        pytest.skip(f"staging Locus-KMS unreachable: {exc}")
    yield client
    client.close()


@pytest.fixture
def seeded_repos(http_client, tenant_id: str) -> list[str]:
    """테스트 전용 repo 2 개 생성. teardown 시 비활성화."""
    import uuid

    created: list[str] = []
    suffix = uuid.uuid4().hex[:8]
    for n in (1, 2):
        r = http_client.post(
            f"/api/v1/tenants/{tenant_id}/repositories",
            json={
                "name": f"e2e-repo-{n}-{suffix}",
                "description": f"e2e repo {n} for repository_groups test",
            },
        )
        assert r.status_code == 201, f"repo {n} 생성 실패: {r.text}"
        created.append(r.json()["data"]["id"])

    yield created

    # teardown — 모든 repo soft delete
    for rid in created:
        try:
            http_client.delete(f"/api/v1/repositories/{rid}")
        except Exception:
            pass


@pytest.fixture
def seeded_groups(http_client, tenant_id: str, seeded_repos: list[str]):
    """group A (repo[0]+repo[1]) + group B (repo[0]) 생성. teardown 시 삭제."""
    import uuid

    suffix = uuid.uuid4().hex[:8]
    created: list[str] = []

    # group A
    r_a = http_client.post(
        f"/api/v1/tenants/{tenant_id}/repository-groups",
        json={
            "name": f"e2e-group-A-{suffix}",
            "description": "두 repo 묶음",
            "repository_ids": seeded_repos,
            "is_default": False,
        },
    )
    # backend 가 router ship 전이면 404 → skip
    if r_a.status_code == 404:
        pytest.skip(
            "POST /tenants/{tid}/repository-groups 404 — backend agent "
            "router 미시행 (예상). backend ship 후 재실행."
        )
    assert r_a.status_code == 201, f"group A 생성 실패: {r_a.text}"
    group_a_id = r_a.json()["data"]["id"]
    created.append(group_a_id)

    # group B
    r_b = http_client.post(
        f"/api/v1/tenants/{tenant_id}/repository-groups",
        json={
            "name": f"e2e-group-B-{suffix}",
            "description": "단일 repo",
            "repository_ids": seeded_repos[:1],
            "is_default": False,
        },
    )
    assert r_b.status_code == 201, f"group B 생성 실패: {r_b.text}"
    group_b_id = r_b.json()["data"]["id"]
    created.append(group_b_id)

    yield {"a": group_a_id, "b": group_b_id}

    # teardown — 남은 group 삭제
    for gid in created:
        try:
            http_client.delete(f"/api/v1/repository-groups/{gid}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Scenario tests
# ---------------------------------------------------------------------------


def test_set_default_promotes_one_demotes_others(
    http_client, tenant_id: str, seeded_groups: dict[str, str]
) -> None:
    """group A 를 default 로 설정 → A.is_default=true, B.is_default=false 검증."""
    a, b = seeded_groups["a"], seeded_groups["b"]

    r = http_client.post(f"/api/v1/repository-groups/{a}/set-default")
    assert r.status_code in (200, 204), f"set-default 실패: {r.text}"

    # list 로 두 group 의 is_default 검증
    r_list = http_client.get(
        f"/api/v1/tenants/{tenant_id}/repository-groups"
    )
    assert r_list.status_code == 200
    items = r_list.json()["data"]["items"]
    by_id = {item["id"]: item for item in items}
    assert by_id[a]["is_default"] is True
    assert by_id[b]["is_default"] is False


def test_search_scope_default_uses_default_group(
    http_client,
    tenant_id: str,
    seeded_groups: dict[str, str],
    seeded_repos: list[str],
) -> None:
    """default group 설정 후 scope='default' 검색 → group A 의 repo 만 대상."""
    a = seeded_groups["a"]
    http_client.post(f"/api/v1/repository-groups/{a}/set-default")

    r = http_client.post(
        "/api/v1/search",
        json={
            "query": "e2e test query — repository group scope",
            "scope": "default",
            "top_k": 5,
            "enable_intent_gate": False,
        },
        headers={"X-Tenant-Id": tenant_id},
    )
    # backend 가 scope 필드 미지원이면 422 → skip
    if r.status_code == 422 and "scope" in r.text.lower():
        pytest.skip("search router 가 scope 필드 미지원 — backend ship 후 재실행")
    assert r.status_code == 200, f"search 실패: {r.text}"
    # 결과 repo_id 가 seeded_repos 안에 있어야 함 (group A 가 두 repo 모두 포함).
    results = r.json()["data"].get("results", [])
    for hit in results:
        rid = hit.get("repository_id")
        if rid is not None:
            assert rid in seeded_repos, (
                f"scope=default 결과에 group A 외 repo 포함: {rid}"
            )


def test_search_scope_group_b_restricts_to_repo1(
    http_client,
    tenant_id: str,
    seeded_groups: dict[str, str],
    seeded_repos: list[str],
) -> None:
    """scope='group' + repository_group_id=B → group B 의 repo (= seeded_repos[0]) 만."""
    b = seeded_groups["b"]

    r = http_client.post(
        "/api/v1/search",
        json={
            "query": "e2e test query — group B",
            "scope": "group",
            "repository_group_id": b,
            "top_k": 5,
            "enable_intent_gate": False,
        },
        headers={"X-Tenant-Id": tenant_id},
    )
    if r.status_code == 422 and "scope" in r.text.lower():
        pytest.skip("search router 가 scope 필드 미지원 — backend ship 후 재실행")
    assert r.status_code == 200, f"search 실패: {r.text}"
    results = r.json()["data"].get("results", [])
    for hit in results:
        rid = hit.get("repository_id")
        if rid is not None:
            assert rid == seeded_repos[0], (
                f"scope=group(B) 결과에 group B 외 repo 포함: {rid}"
            )


def test_delete_default_group_optional_auto_promote(
    http_client, tenant_id: str, seeded_groups: dict[str, str]
) -> None:
    """default group 삭제 후 남은 group 이 자동 default 로 promote 되는지.

    *선택 동작* — backend 가 auto-promote 미구현 시 단순히 default 가 None 이
    되어도 OK. 본 테스트는 시나리오 검증만 (양쪽 path 허용).
    """
    a, b = seeded_groups["a"], seeded_groups["b"]
    http_client.post(f"/api/v1/repository-groups/{a}/set-default")
    # group A 삭제
    r_del = http_client.delete(f"/api/v1/repository-groups/{a}")
    assert r_del.status_code in (200, 204), f"delete 실패: {r_del.text}"

    # 남은 group B 의 is_default 상태 확인
    r_list = http_client.get(
        f"/api/v1/tenants/{tenant_id}/repository-groups"
    )
    assert r_list.status_code == 200
    items = r_list.json()["data"]["items"]
    # backend 가 auto-promote 구현 시 B.is_default=True, 미구현 시 False — 둘 다 OK.
    b_item = next((i for i in items if i["id"] == b), None)
    assert b_item is not None, "group B 가 list 에 없음"
    assert isinstance(b_item["is_default"], bool)


def test_cross_tenant_group_id_in_search_returns_empty_or_404(
    http_client, tenant_id: str, seeded_groups: dict[str, str]
) -> None:
    """가짜 group_id (존재 안 함) 로 검색 → 빈 결과 또는 404 (양쪽 허용).

    실제 cross-tenant group_id 는 staging 에 다른 tenant 가 없으므로
    not-found UUID 로 대체 검증.
    """
    import uuid

    fake_group_id = str(uuid.uuid4())
    r = http_client.post(
        "/api/v1/search",
        json={
            "query": "cross-tenant group test",
            "scope": "group",
            "repository_group_id": fake_group_id,
            "top_k": 5,
            "enable_intent_gate": False,
        },
        headers={"X-Tenant-Id": tenant_id},
    )
    if r.status_code == 422 and "scope" in r.text.lower():
        pytest.skip("search router 가 scope 필드 미지원")
    # 200 (빈 결과) 또는 404 (group not found) 모두 허용 — backend 정책.
    assert r.status_code in (200, 404), f"unexpected: {r.status_code} {r.text}"
    if r.status_code == 200:
        results = r.json()["data"].get("results", [])
        # 빈 결과여야 함 (존재하지 않는 group)
        assert results == [], (
            "존재하지 않는 group_id 인데 결과가 나옴 — security issue 가능"
        )
