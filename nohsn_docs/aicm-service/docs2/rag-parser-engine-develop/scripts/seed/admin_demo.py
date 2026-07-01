"""Admin demo 계정 + 13개 demo 계정의 cross-tenant memberships seed.

실행:
    docker exec -e PYTHONPATH=/app kms-api python scripts/seed/admin_demo.py
    # 기본 dry-run. --execute 로 실제 적용.

목적:
    1) ``demo-admin@kms-plus.io`` (password: ``password123``) 생성. 본인 personal
       tenant 의 ``owner``. 추가로 4개 조직 (Timbel/KB/신한/삼성) + 개인 (송하나)
       의 personal tenant 5개에 ``admin`` 멤버십을 받음 → 전 조직 데이터 풀가.
    2) 13개 demo 계정의 cross-tenant 멤버십을 advertised role 대로 부여.
       예) dh.lee@kbfin.com 은 본인 personal 의 owner + jm.kim 의 personal
       (= KB workspace) 의 viewer.
       이로써 admin 이 아닌 demo 계정도 "조직 워크스페이스" 컨텍스트에서
       역할 제한 (viewer/editor/admin) UI 확인 가능.

idempotent: 모든 INSERT 는 ON CONFLICT / 선조회 후 skip.
"""
from __future__ import annotations

import argparse
import asyncio
import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from src.api.auth.jwt_utils import hash_password
from src.api.routers.auth_v2 import _create_account_with_email
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


# ── Constants ──────────────────────────────────────────────────────


ADMIN_EMAIL = "demo-admin@kms-plus.io"
ADMIN_PASSWORD = "password123"  # noqa: S105 — demo seed
ADMIN_NAME = "Admin Demo"

# org owner email → workspace label (로그용)
ORG_OWNERS: dict[str, str] = {
    "ricky@timbel.ai": "Timbel",
    "jm.kim@kbfin.com": "KB금융",
    "sw.han@shinhan.com": "신한금융",
    "hyunwoo.kang@samsung.com": "삼성전자",
    "hana.song@gmail.com": "개인 (송하나)",
}


@dataclass
class CrossMembership:
    """advertised role 그대로 owner_email 의 personal tenant 에 멤버 등록."""

    member_email: str
    owner_email: str
    role: str  # owner / admin / editor / viewer / member


# DemoAccountSelect 의 advertised role 과 일치.
CROSS_MEMBERSHIPS: list[CrossMembership] = [
    # KB — jm.kim 이 owner 격, 나머지는 advertised role.
    CrossMembership("jm.kim@kbfin.com", "jm.kim@kbfin.com", "owner"),
    CrossMembership("soyeon.park@kbfin.com", "jm.kim@kbfin.com", "editor"),
    CrossMembership("dh.lee@kbfin.com", "jm.kim@kbfin.com", "viewer"),
    CrossMembership("yuri.jung@kbfin.com", "jm.kim@kbfin.com", "viewer"),
    CrossMembership("minjae.choi@kbfin.com", "jm.kim@kbfin.com", "viewer"),
    # 신한 — sw.han 이 owner 격.
    CrossMembership("sw.han@shinhan.com", "sw.han@shinhan.com", "owner"),
    CrossMembership("jihye.oh@shinhan.com", "sw.han@shinhan.com", "editor"),
    CrossMembership("taeyang.seo@shinhan.com", "sw.han@shinhan.com", "viewer"),
    # 삼성 — hyunwoo.kang 이 owner 격.
    CrossMembership("hyunwoo.kang@samsung.com", "hyunwoo.kang@samsung.com", "owner"),
    CrossMembership("minji.yoon@samsung.com", "hyunwoo.kang@samsung.com", "editor"),
    CrossMembership("junho.lim@samsung.com", "hyunwoo.kang@samsung.com", "viewer"),
]


# ── Plan ───────────────────────────────────────────────────────────


@dataclass
class Plan:
    admin_created: bool = False
    admin_existed: bool = False
    admin_memberships_added: int = 0
    admin_memberships_skipped: int = 0
    cross_memberships_added: int = 0
    cross_memberships_skipped: int = 0
    missing_accounts: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    def line(self, msg: str) -> None:
        self.log.append(msg)

    def summary(self) -> str:
        return (
            f"admin={'created' if self.admin_created else 'existed'} "
            f"admin_memberships +{self.admin_memberships_added} "
            f"(skip {self.admin_memberships_skipped}) "
            f"cross_memberships +{self.cross_memberships_added} "
            f"(skip {self.cross_memberships_skipped}) "
            f"missing={len(self.missing_accounts)}"
        )


# ── DB helpers ─────────────────────────────────────────────────────


async def _lookup_account(
    conn: AsyncConnection, *, email: str
) -> tuple[UUID, UUID] | None:
    r = (
        await conn.execute(
            text(
                "SELECT id, personal_tenant_id FROM accounts "
                "WHERE email = :e AND is_active = true"
            ),
            {"e": email},
        )
    ).first()
    if not r:
        return None
    return r[0], r[1]


async def _ensure_admin(
    conn: AsyncConnection,
) -> tuple[UUID, UUID, bool]:
    """Returns (account_id, personal_tenant_id, created)."""
    existing = await _lookup_account(conn, email=ADMIN_EMAIL)
    if existing:
        return existing[0], existing[1], False
    pwd_hash = hash_password(ADMIN_PASSWORD)
    account_id, tenant_id = await _create_account_with_email(
        conn, email=ADMIN_EMAIL, password_hash=pwd_hash, name=ADMIN_NAME
    )
    return account_id, tenant_id, True


async def _ensure_membership(
    conn: AsyncConnection, *, account_id: UUID, tenant_id: UUID, role: str
) -> bool:
    """ON CONFLICT-safe insert. Returns True if inserted, False if existed."""
    existing = (
        await conn.execute(
            text(
                "SELECT id, role FROM tenant_memberships "
                "WHERE account_id = :aid AND tenant_id = :tid LIMIT 1"
            ),
            {"aid": account_id, "tid": tenant_id},
        )
    ).first()
    if existing:
        # 같은 멤버십 존재 — role 이 다르면 update (admin 격상 가능).
        if existing[1] != role:
            # owner 는 절대 강등하지 않는다 — owner 로 이미 들어가 있는데
            # cross_membership 에서 admin 으로 잡혀있어도 owner 유지.
            if existing[1] == "owner":
                return False
            await conn.execute(
                text(
                    "UPDATE tenant_memberships SET role = :r "
                    "WHERE id = :mid"
                ),
                {"r": role, "mid": existing[0]},
            )
            return True
        return False
    await conn.execute(
        text(
            """
            INSERT INTO tenant_memberships (id, account_id, tenant_id, role)
            VALUES (gen_random_uuid(), :aid, :tid, :r)
            """
        ),
        {"aid": account_id, "tid": tenant_id, "r": role},
    )
    return True


# ── Orchestration ──────────────────────────────────────────────────


async def run_seed(*, execute: bool) -> Plan:
    plan = Plan()
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)

    try:
        # 1) admin 계정 확보
        async with engine.begin() as conn:
            if not execute:
                # dry-run: 계정 존재 여부만 확인.
                existing = await _lookup_account(conn, email=ADMIN_EMAIL)
                if existing:
                    plan.admin_existed = True
                    plan.line(f"[dry] admin already exists: {ADMIN_EMAIL}")
                    admin_account_id, admin_tenant_id = existing
                else:
                    plan.line(f"[dry] would CREATE admin: {ADMIN_EMAIL}")
                    admin_account_id, admin_tenant_id = None, None  # type: ignore[assignment]
            else:
                admin_account_id, admin_tenant_id, created = await _ensure_admin(conn)
                if created:
                    plan.admin_created = True
                    plan.line(f"[seed] CREATED admin: {ADMIN_EMAIL} → tenant {admin_tenant_id}")
                else:
                    plan.admin_existed = True
                    plan.line(f"[seed] admin already exists: {ADMIN_EMAIL}")

        # 2) admin → 조직 5개 personal_tenant 에 admin 멤버십 추가
        for owner_email, label in ORG_OWNERS.items():
            async with engine.begin() as conn:
                owner = await _lookup_account(conn, email=owner_email)
                if not owner:
                    plan.missing_accounts.append(owner_email)
                    plan.line(f"[MISS] org owner not found: {owner_email}")
                    continue
                owner_account_id, owner_tenant_id = owner

                if not execute:
                    plan.line(
                        f"[dry] admin → {label} ({owner_email}) "
                        f"tenant={owner_tenant_id} role=admin"
                    )
                    continue

                if admin_account_id is None:
                    continue
                inserted = await _ensure_membership(
                    conn,
                    account_id=admin_account_id,
                    tenant_id=owner_tenant_id,
                    role="admin",
                )
                if inserted:
                    plan.admin_memberships_added += 1
                    plan.line(f"[seed] admin →+ {label} ({owner_email}) admin")
                else:
                    plan.admin_memberships_skipped += 1

        # 3) cross-membership: 13개 계정 → 조직 owner 의 personal_tenant
        for cm in CROSS_MEMBERSHIPS:
            async with engine.begin() as conn:
                member = await _lookup_account(conn, email=cm.member_email)
                if not member:
                    plan.missing_accounts.append(cm.member_email)
                    plan.line(f"[MISS] member not found: {cm.member_email}")
                    continue
                owner = await _lookup_account(conn, email=cm.owner_email)
                if not owner:
                    plan.missing_accounts.append(cm.owner_email)
                    plan.line(f"[MISS] owner not found: {cm.owner_email}")
                    continue
                member_account_id, _ = member
                _, owner_tenant_id = owner

                if not execute:
                    plan.line(
                        f"[dry] {cm.member_email} → owner-tenant of "
                        f"{cm.owner_email} role={cm.role}"
                    )
                    continue

                inserted = await _ensure_membership(
                    conn,
                    account_id=member_account_id,
                    tenant_id=owner_tenant_id,
                    role=cm.role,
                )
                if inserted:
                    plan.cross_memberships_added += 1
                    plan.line(
                        f"[seed] {cm.member_email} →+ {cm.owner_email}'s tenant ({cm.role})"
                    )
                else:
                    plan.cross_memberships_skipped += 1
    finally:
        await engine.dispose()

    return plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute", action="store_true", help="실제 DB 변경 (기본 dry-run)"
    )
    args = parser.parse_args()

    plan = asyncio.run(run_seed(execute=args.execute))
    prefix = "[seed]" if args.execute else "[dry]"
    print(f"{prefix} {plan.summary()}")
    if plan.missing_accounts:
        # dedupe
        miss = sorted(set(plan.missing_accounts))
        print(f"  MISSING: {miss}")
    for line in plan.log[:80]:
        print(f"  {line}")
    if len(plan.log) > 80:
        print(f"  ... +{len(plan.log) - 80} more")
    if not args.execute:
        print("Run with --execute to apply.")


if __name__ == "__main__":
    # `re` import for symmetry with auth_v2 helper internals (not strictly needed here).
    _ = re
    main()
