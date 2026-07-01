"""Account / tenant 자동 생성 + 조회.

Stage B-1 — 원안 복귀 2단계.

첫 chat 방문 (혹은 identity/register) 시점에 phone 으로 account 가 있으면 조회,
없으면 account + personal_tenant + default repositories 자동 생성.

설계 메모:
- ``accounts`` 는 agent 프레임워크의 "phone 기반 개인 유저" 식별. 기존 ``users``
  (tenant 내부 직원/관리자) 와 역할이 다름 — 둘 다 유지.
- 중복 생성 방지를 위해 TX 안에서 SELECT → INSERT 로직 사용.
- ``tenants`` 의 NOT NULL 제약 (``plan``, ``config``, ``context_config``,
  ``tenant_type``, ``is_active``) 을 모두 주입한다.
- default repositories 6개: schedules/diaries/news_subscriptions/news_reports/
  reminders/uploads. ``(tenant_id, name)`` UNIQUE 이므로 ON CONFLICT DO NOTHING.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


# personal_tenant 에 기본 생성될 repository 이름.
# Stage B-2~5 에서 각 스킬 도메인이 KMS document 로 전환될 때 타깃 repo.
DEFAULT_PERSONAL_REPOS: list[str] = [
    "schedules",
    "diaries",
    "news_subscriptions",
    "news_reports",
    "reminders",
    "uploads",
]


async def _enable_default_skills_for_personal_tenant(
    conn, tenant_id: UUID, account_id: UUID
) -> list[str]:
    """personal tenant 생성 직후 scope=personal/all + visibility=auto 스킬 전원 자동 enable.

    FS 기반 Skill 로더를 사용한다 — account 생성은 KMS 의존성 없이 동작해야 함.
    Stage B-Core-1: 엔진 런타임 연결은 B-Core-2/3 에서. 여기서는 tenant_skills
    에 row 만 정확히 insert 해 두고 나중에 SkillRegistry 가 조회.

    Returns enabled skill_id list (로깅/테스트 용도).
    """
    # 지연 import — circular import 방지 (runtime.engine 이 accounts 를 볼 수 있음).
    from src.agent_framework.runtime.engine import SKILLS_DIR
    from src.agent_framework.runtime.loader import load_all_skills

    skills = load_all_skills(SKILLS_DIR)
    to_enable: list[str] = []
    for sid, s in skills.items():
        scope = s.availability.scope
        vis = s.availability.visibility
        if scope in ("personal", "all") and vis == "auto":
            to_enable.append(sid)

    for sid in to_enable:
        await conn.execute(
            text(
                """
                INSERT INTO tenant_skills
                  (tenant_id, skill_id, enabled_by_account_id, config)
                VALUES (:tid, :sid, :aid, '{}'::jsonb)
                ON CONFLICT (tenant_id, skill_id) DO NOTHING
                """
            ),
            {"tid": tenant_id, "sid": sid, "aid": account_id},
        )
    return to_enable


@dataclass
class AccountContext:
    """세션/요청 scope 에서 account 식별에 필요한 최소 정보.

    JSON 직렬화 (SessionState) 에 넣을 때는 필드를 개별 str 로 꺼내 저장한다.
    """

    account_id: UUID
    phone: str
    name: str | None
    personal_tenant_id: UUID


_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    """Lazy singleton engine. 테스트에서는 ``DATABASE_URL`` env override 로 교체."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


async def _reset_engine_for_tests() -> None:
    """테스트 전용 — DATABASE_URL 변경 후 engine 재구성 필요할 때 호출."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_or_create_account(
    phone: str, name: str | None = None
) -> AccountContext:
    """phone 기준 account 조회. 없으면 account + personal_tenant + default repos 생성.

    idempotent — 재호출은 기존 row 를 그대로 반환.
    name 갱신은 하지 않는다 (명시적 update API 로 분리 예정).
    """
    eng = _get_engine()
    async with eng.begin() as conn:
        # 1. 기존 account 조회
        existing = (
            await conn.execute(
                text(
                    "SELECT id, name, personal_tenant_id FROM accounts "
                    "WHERE phone = :phone"
                ),
                {"phone": phone},
            )
        ).first()
        if existing:
            return AccountContext(
                account_id=existing[0],
                phone=phone,
                name=existing[1],
                personal_tenant_id=existing[2],
            )

        # 2. personal_tenant 생성
        tenant_name = (name or phone) + " 개인"
        tenant_slug = f"personal_{phone.replace('-', '').replace(' ', '')}"
        tr = await conn.execute(
            text(
                """
                INSERT INTO tenants
                  (id, slug, name, tenant_type, plan, config, context_config, is_active)
                VALUES
                  (gen_random_uuid(), :slug, :name, 'personal', 'free',
                   '{}'::jsonb, '{}'::jsonb, true)
                RETURNING id
                """
            ),
            {"slug": tenant_slug, "name": tenant_name},
        )
        tenant_id: UUID = tr.scalar_one()

        # 3. account 생성
        ar = await conn.execute(
            text(
                """
                INSERT INTO accounts (id, phone, name, personal_tenant_id)
                VALUES (gen_random_uuid(), :phone, :name, :tenant_id)
                RETURNING id
                """
            ),
            {"phone": phone, "name": name, "tenant_id": tenant_id},
        )
        account_id: UUID = ar.scalar_one()

        # 4. membership (owner)
        await conn.execute(
            text(
                """
                INSERT INTO tenant_memberships (id, account_id, tenant_id, role)
                VALUES (gen_random_uuid(), :aid, :tid, 'owner')
                """
            ),
            {"aid": account_id, "tid": tenant_id},
        )

        # 5. default repositories (search_mode/config/display/llm_config NOT NULL 채움)
        for repo_name in DEFAULT_PERSONAL_REPOS:
            await conn.execute(
                text(
                    """
                    INSERT INTO repositories
                      (id, tenant_id, name, description,
                       config, search_mode, display_config, llm_config, is_active)
                    VALUES
                      (gen_random_uuid(), :tid, :name, :desc,
                       '{}'::jsonb, 'simple', '{}'::jsonb, '{}'::jsonb, true)
                    ON CONFLICT ON CONSTRAINT uq_repositories_tenant_name DO NOTHING
                    """
                ),
                {
                    "tid": tenant_id,
                    "name": repo_name,
                    "desc": f"Agent framework default repo: {repo_name}",
                },
            )

        # 6. default skills (scope=personal/all + visibility=auto)
        enabled_skills = await _enable_default_skills_for_personal_tenant(
            conn, tenant_id=tenant_id, account_id=account_id
        )

        log.info(
            "account_created",
            phone_hash=hash(phone) & 0xFFFF,
            account_id=str(account_id),
            tenant_id=str(tenant_id),
            default_repos=len(DEFAULT_PERSONAL_REPOS),
            default_skills=len(enabled_skills),
        )

    return AccountContext(
        account_id=account_id,
        phone=phone,
        name=name,
        personal_tenant_id=tenant_id,
    )


async def get_account_by_phone(phone: str) -> AccountContext | None:
    """읽기 전용 조회 (생성 안 함)."""
    eng = _get_engine()
    async with eng.begin() as conn:
        r = (
            await conn.execute(
                text(
                    "SELECT id, name, personal_tenant_id FROM accounts "
                    "WHERE phone = :phone"
                ),
                {"phone": phone},
            )
        ).first()
        if not r:
            return None
        return AccountContext(
            account_id=r[0],
            phone=phone,
            name=r[1],
            personal_tenant_id=r[2],
        )


async def list_tenant_memberships(account_id: UUID) -> list[dict]:
    """account 가 속한 tenant 목록 (business tenants 포함)."""
    eng = _get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT t.id, t.slug, t.name, t.tenant_type, m.role
                FROM tenant_memberships m
                JOIN tenants t ON m.tenant_id = t.id
                WHERE m.account_id = :aid
                ORDER BY t.tenant_type DESC, t.name
                """
            ),
            {"aid": account_id},
        )
        return [
            {
                "tenant_id": r[0],
                "slug": r[1],
                "name": r[2],
                "type": r[3],
                "role": r[4],
            }
            for r in rows
        ]
