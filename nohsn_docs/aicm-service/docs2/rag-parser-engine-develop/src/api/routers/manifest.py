"""GET /api/v1/manifest — frontend schema-driven UI 카탈로그 + 사용자 정보.

P0.2 추가: GET /api/v1/manifest/skill_examples — 활성화된 skill 들의
trigger_examples 를 카테고리별로 그룹핑해 반환. frontend-v3 의 onboarding /
chat empty-state / HelpPopover 가 사용.

설계
----
- ``manifest/domains/*.yaml`` 디렉토리를 정적 카탈로그로 사용. 신규 도메인 추가 시
  YAML 한 파일만 추가하면 frontend 가 manifest 를 fetch 해 sidebar / dashboard
  자동 렌더.
- ``user`` 블록은 ``accounts`` 테이블에서 display_name + preferences 를 fetch.
- ``user_enabled`` — 모든 active 도메인은 default true. 향후
  ``user_domain_settings`` 테이블이 도입되면 거기 값 우선.
- 인증은 ``account_settings`` / ``auth_v2`` 와 동일한 Bearer JWT 패턴.

응답 스키마 (예시)::

    {
      "user": {
        "user_id": "...",
        "display_name": "...",
        "preferences": {...}
      },
      "domains": [
        {
          "id": "inbox",
          "label": "받은 편지함",
          "icon": "mail",
          "status": "active",
          "list_endpoint": "/api/v1/inbox",
          "summary_endpoint": "/api/v1/inbox/summary",
          "detail_endpoint": "/api/v1/inbox/{id}",
          "list_columns": [...],
          "summary_widgets": [...],
          "quick_actions": [...],
          "chat_intents": [...],
          "card_renderer": "InboxSummaryCard",
          "upcoming_message": null,
          "user_enabled": true,
          "sort_order": 10
        },
        ...
      ],
      "version": "1"
    }
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# KMS-only image (.dockerignore drops src/agent_framework) - lazy guard so module load
# succeeds. endpoint 가 호출되어 load_all_manifests() 가 None 이면 그때 명확히 실패.
try:
    from src.agent_framework.manifest.loader import load_all_manifests
except ModuleNotFoundError:
    load_all_manifests = None  # type: ignore[assignment]
from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/manifest", tags=["Manifest"])


# ---------------------------------------------------------------------------
# DB engine — account_settings.py / auth_v2.py 와 동일 패턴 (lazy singleton).
# ---------------------------------------------------------------------------
_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


async def _reset_engine_for_tests() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


# ---------------------------------------------------------------------------
# Auth helper — account_settings.py 와 동일.
# ---------------------------------------------------------------------------


def _account_id_from_bearer(authorization: str) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "empty token")
    try:
        payload = decode_token(token)
    except InvalidToken as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    if payload.get("type") not in (None, "access"):
        raise HTTPException(401, "not an access token")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "token missing subject")
    return str(sub)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


# 모든 사용자 그룹 — admin 은 시스템 운영자 (모든 도메인 무조건 노출).
ALL_USER_GROUPS: tuple[str, ...] = (
    "personal",
    "company",
    "business",
    "sole_proprietor",
)


def _is_visible_for_user(
    available_for_groups: list[str],
    user_groups: list[str],
) -> bool:
    """도메인이 사용자에게 노출되는지 판정.

    규칙:
    - admin 그룹 사용자는 무조건 노출 (시스템 운영자 풀 액세스).
    - manifest 의 ``available_for_groups`` 가 비어있으면 모든 그룹에 노출
      (legacy / 보수적 default — yaml 명시 안 한 도메인은 전사 노출).
    - 사용자 ``user_groups`` 가 비어있으면 personal-only 가정. 이전 구현은
      "모든 active 그룹" 으로 fallback 해 unsigned 계정에도 회사/사업자
      도메인이 보였음 — codex 검토 (2026-04-28) 기반 보수적 fallback 으로
      변경. 시드 누락 계정도 personal 외 도메인 보면 안 됨.
    - 그 외에는 양쪽 교집합 1개 이상.
    """
    if "admin" in user_groups:
        return True
    if not available_for_groups:
        return True
    if not user_groups:
        # 시드 누락 계정 — personal-only 만 허용 (안전한 fallback).
        user_groups = ["personal"]
    return any(g in user_groups for g in available_for_groups)


@router.get("")
async def get_manifest(authorization: str = Header(...)) -> dict[str, Any]:
    """현재 사용자 + 도메인 카탈로그 반환 (사용자 그룹 필터링 적용)."""
    account_id = _account_id_from_bearer(authorization)

    # accounts 테이블에서 display_name + preferences fetch.
    # tenants 멤버십도 함께 — 사용자가 속한 모든 tenant 노출 (개인/회사/사업).
    eng = _get_engine()
    display_name: str | None = None
    preferences: dict[str, Any] = {}
    tenant_memberships: list[dict[str, Any]] = []

    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT display_name, preferences FROM accounts "
                    "WHERE id = :aid LIMIT 1"
                ),
                {"aid": account_id},
            )
        ).first()
        if row is not None:
            display_name, raw_prefs = row
            preferences = dict(raw_prefs or {})

    # tenant 멤버십 — account_tenants 가 있으면 M:N, 없으면 personal_tenant_id fallback.
    # 테이블 미존재 시 transaction 이 abort 되므로 별도 connection 으로 시도/폴백.
    has_account_tenants = False
    async with eng.connect() as conn:
        reg = (
            await conn.execute(
                text("SELECT to_regclass('public.account_tenants') AS t")
            )
        ).scalar()
        has_account_tenants = reg is not None

    if has_account_tenants:
        async with eng.connect() as conn:
            mem_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT t.id::text AS tenant_id, t.name, t.slug,
                               t.tenant_type, at.role, at.scope_group
                          FROM account_tenants at
                          JOIN tenants t ON t.id = at.tenant_id
                         WHERE at.account_id = :aid
                           AND at.is_active = TRUE
                           AND t.is_active = TRUE
                         ORDER BY at.scope_group, t.name
                        """
                    ),
                    {"aid": account_id},
                )
            ).all()
            for mr in mem_rows:
                tenant_memberships.append(
                    {
                        "tenant_id": mr[0],
                        "name": mr[1],
                        "slug": mr[2],
                        "tenant_type": mr[3],
                        "role": mr[4],
                        "scope_group": mr[5],
                    }
                )

    if not tenant_memberships:
        # legacy fallback — accounts.personal_tenant_id 만 노출.
        async with eng.connect() as conn:
            personal_row = (
                await conn.execute(
                    text(
                        """
                        SELECT t.id::text, t.name, t.slug, t.tenant_type
                          FROM accounts a
                          JOIN tenants t ON t.id = a.personal_tenant_id
                         WHERE a.id = :aid
                           AND t.is_active = TRUE
                        """
                    ),
                    {"aid": account_id},
                )
            ).first()
            if personal_row is not None:
                tenant_memberships.append(
                    {
                        "tenant_id": personal_row[0],
                        "name": personal_row[1],
                        "slug": personal_row[2],
                        "tenant_type": personal_row[3],
                        "role": "owner",
                        "scope_group": "personal",
                    }
                )

    # YAML 카탈로그 로드.
    catalog = load_all_manifests()

    # 사용자 그룹 추출 — preferences.user_groups (없으면 빈 리스트).
    raw_user_groups = preferences.get("user_groups")
    user_groups: list[str] = (
        [str(g) for g in raw_user_groups]
        if isinstance(raw_user_groups, list)
        else []
    )

    # 도메인 필터링 + user_enabled 채우기.
    domains_payload: list[dict[str, Any]] = []
    filtered_count = 0
    for m in catalog:
        if not _is_visible_for_user(m.available_for_groups, user_groups):
            filtered_count += 1
            continue
        d = m.to_dict()
        if m.status == "active":
            d["user_enabled"] = True
        else:
            # available / upcoming / deprecated 모두 사용자 활성 false.
            d["user_enabled"] = False
        domains_payload.append(d)

    log.info(
        "manifest_served",
        account_id=account_id,
        domain_count=len(domains_payload),
        filtered_count=filtered_count,
        user_groups=user_groups,
        tenant_count=len(tenant_memberships),
    )

    return {
        "user": {
            "user_id": account_id,
            "display_name": display_name,
            "preferences": preferences,
            "user_groups": user_groups,
        },
        "tenants": tenant_memberships,
        "domains": domains_payload,
        "version": "1",
    }


# ---------------------------------------------------------------------------
# /manifest/skill_examples — frontend-v3 P0.2.
# ---------------------------------------------------------------------------


# 카테고리별 cap. 사례 enum 가 아니라 일반 패턴 — yaml 의 tenant_scope 값을
# 그대로 카테고리 키로 사용. 새 scope 가 yaml 에 등장하면 자동으로 새 카테고리
# 가 생긴다 (하드코드 X).
_PER_SKILL_LIMIT = 8
_PER_CATEGORY_LIMIT = 30
_TOTAL_LIMIT = 200
# tenant_scope 값이 비어있는 skill 의 fallback 카테고리.
_DEFAULT_CATEGORY = "general"


def _skill_categories(skill: Any) -> list[str]:
    """skill yaml 에서 카테고리 키 추출. tenant_scope 값을 그대로 사용.

    빈 리스트 / "*" 만 있으면 [_DEFAULT_CATEGORY]. 여러 scope 면 여러 카테고리에
    중복 노출 (사용자에게는 그룹별 시각으로 선택 폭이 넓어지는 효과).
    """
    role = getattr(skill, "role", None)
    if role is None:
        return [_DEFAULT_CATEGORY]
    scopes = list(getattr(role, "tenant_scope", []) or [])
    cats = [s for s in scopes if s and s != "*"]
    return cats if cats else [_DEFAULT_CATEGORY]


def _user_scopes_from_groups(user_groups: list[str]) -> set[str]:
    """user_groups 를 skill tenant_scope 매칭용 set 으로 변환.

    admin 은 manifest 와 동일하게 모든 카테고리 풀 접근 (특수 마커 ``*``).
    """
    if "admin" in user_groups:
        return {"*"}
    return set(user_groups) if user_groups else set()


# P0.2 hardening (codex 2차) — role hierarchy. schema_v2.SkillRole.role_min 의
# 값은 ``viewer < member < editor < admin < owner``. 코드베이스 단일 정의이므로
# 여기서 인덱스로 비교 (사례 enum 가 아니라 일반 패턴).
_ROLE_HIERARCHY: tuple[str, ...] = ("viewer", "member", "editor", "admin", "owner")


def _role_rank(role: str | None) -> int:
    """role hierarchy index. 알 수 없는 값은 ``viewer`` (최소) 로 취급."""
    if not role:
        return 0
    try:
        return _ROLE_HIERARCHY.index(role)
    except ValueError:
        return 0


def _skill_visible_to_user(
    skill: Any,
    user_scopes: set[str],
    account_role: str | None = None,
) -> bool:
    """tenant_scope ∩ user_scopes 통과 + ``role_min`` 통과 시에만 노출.

    P0.2 hardening (codex P2-7):
        - ``role.role_min`` 도 검사. ``account_role`` 이 hierarchy 상
          role_min 이상이어야 함. account_role 이 None 이면 ``viewer``.
        - ``admin`` 사용자 (``user_scopes == {"*"}``) 는 role_min 도 우회.

    빈 tenant_scope (제약 없음) 는 모두에게 노출. ``*`` 사용자는 무조건 노출.
    """
    if "*" in user_scopes:
        return True
    role = getattr(skill, "role", None)
    if role is None:
        return True
    scopes = list(getattr(role, "tenant_scope", []) or [])
    role_min = getattr(role, "role_min", "viewer") or "viewer"
    # role_min 통과 검사. 사용자 role 이 role_min 보다 낮으면 노출 X.
    if _role_rank(account_role) < _role_rank(role_min):
        return False
    if not scopes:
        return True
    if "*" in scopes:
        return True
    if not user_scopes:
        # 시드 누락 계정 — personal-only 로 보수적 fallback (manifest 와 일치).
        user_scopes = {"personal"}
    return any(s in user_scopes for s in scopes)


async def _resolve_account_role(
    eng: AsyncEngine, account_id: str, x_tenant_id: str | None
) -> str | None:
    """현재 (account, tenant) 의 ``tenant_memberships.role`` 반환.

    - x_tenant_id 가 없으면 ``personal_tenant_id`` 로 resolve.
    - 멤버십 row 없음 → None (role_min 검사에서 viewer 취급).
    - account 가 ``preferences.user_groups`` 에 'admin' 이면 ``admin`` 반환
      (role_min 통과 보장 — manifest 와 일관).
    """
    # admin 그룹은 무조건 'admin' role 로 간주 — _skill_visible_to_user 가
    # ``*`` user_scopes 일 때 통과시키지만, 명시적으로 role_min 도 통과.
    async with eng.connect() as conn:
        prefs_row = (
            await conn.execute(
                text(
                    "SELECT preferences FROM accounts WHERE id = :aid LIMIT 1"
                ),
                {"aid": account_id},
            )
        ).first()
    if prefs_row is not None:
        raw_prefs = prefs_row[0] or {}
        if isinstance(raw_prefs, str):
            try:
                raw_prefs = json.loads(raw_prefs)
            except Exception:
                raw_prefs = {}
        if isinstance(raw_prefs, dict):
            ug = raw_prefs.get("user_groups") or []
            if isinstance(ug, list) and "admin" in ug:
                return "admin"

    # tenant 별 멤버십 role.
    tid_str: str | None = None
    if x_tenant_id and x_tenant_id.strip():
        tid_str = x_tenant_id.strip()
    else:
        async with eng.connect() as conn:
            r = (
                await conn.execute(
                    text(
                        "SELECT personal_tenant_id FROM accounts "
                        "WHERE id = :aid LIMIT 1"
                    ),
                    {"aid": account_id},
                )
            ).first()
            if r and r[0]:
                tid_str = str(r[0])
    if not tid_str:
        return None
    async with eng.connect() as conn:
        r = (
            await conn.execute(
                text(
                    "SELECT role FROM tenant_memberships "
                    "WHERE account_id = :aid AND tenant_id = :tid LIMIT 1"
                ),
                {"aid": account_id, "tid": tid_str},
            )
        ).first()
    if not r:
        return None
    return str(r[0] or "").lower() or None


@router.get("/skill_examples")
async def get_skill_examples(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """활성 skill 의 trigger_examples 를 tenant_scope 별 카테고리로 그룹핑.

    응답::

        {
          "categories": {
            "personal":  [{"skill_id": "daily_journal", "text": "오늘 일기 써줘."}, ...],
            "company":   [...],
            ...
          }
        }

    - 사용자 ``preferences.user_groups`` 와 skill ``role.tenant_scope`` 의 교집합
      만 노출.
    - per-skill cap = ``_PER_SKILL_LIMIT`` (8).
    - per-category cap = ``_PER_CATEGORY_LIMIT`` (30).
    - total cap = ``_TOTAL_LIMIT`` (200).
    """
    account_id = _account_id_from_bearer(authorization)

    eng = _get_engine()
    user_groups: list[str] = []
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT preferences FROM accounts WHERE id = :aid LIMIT 1"
                ),
                {"aid": account_id},
            )
        ).first()
        if row is not None:
            raw_prefs = row[0] or {}
            if isinstance(raw_prefs, dict):
                raw_groups = raw_prefs.get("user_groups")
                if isinstance(raw_groups, list):
                    user_groups = [str(g) for g in raw_groups]

    user_scopes = _user_scopes_from_groups(user_groups)

    # P0.2 hardening (codex P2-7) — role_min 검사를 위해 active tenant 의
    # tenant_memberships.role 을 함께 resolve. admin user_groups 는 'admin'
    # 으로 간주 (manifest 와 일관).
    account_role = await _resolve_account_role(eng, account_id, x_tenant_id)

    # SkillV2 카탈로그 로드. engine 의 SKILLS_V2_DIR 와 동일 경로.
    from src.agent_framework.runtime.engine import SKILLS_V2_DIR
    from src.agent_framework.skills.schema_v2 import load_all_v2

    skills_map = load_all_v2(SKILLS_V2_DIR)

    categories: dict[str, list[dict[str, str]]] = {}
    total = 0
    # 정렬 — 결과 안정성을 위해 skill name 사전순.
    for name in sorted(skills_map.keys()):
        if total >= _TOTAL_LIMIT:
            break
        skill = skills_map[name]
        if not _skill_visible_to_user(skill, user_scopes, account_role):
            continue
        examples = list(getattr(skill, "trigger_examples", []) or [])[
            :_PER_SKILL_LIMIT
        ]
        if not examples:
            continue
        for cat in _skill_categories(skill):
            bucket = categories.setdefault(cat, [])
            if len(bucket) >= _PER_CATEGORY_LIMIT:
                continue
            for ex in examples:
                if len(bucket) >= _PER_CATEGORY_LIMIT:
                    break
                if total >= _TOTAL_LIMIT:
                    break
                bucket.append({"skill_id": name, "text": str(ex)})
                total += 1
            if total >= _TOTAL_LIMIT:
                break
    log.info(
        "manifest_skill_examples_served",
        account_id=account_id,
        category_count=len(categories),
        total=total,
    )
    return {"categories": categories}
