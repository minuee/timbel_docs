"""tenant 별 활성 스킬 조회 — engine 이 매 턴 available labels 얻는 데 사용.

account_id 기준: personal_tenant + membership business_tenants 모두 합쳐서
``tenant_skills`` 로 enabled 된 스킬 id 집합 반환.

반환한 skill_id 로 실제 ``Skill`` 객체는 별도 loader (fs/kms) 에서 조회.

Stage B-Core-1: 데이터 레이어만. engine 런타임 연결은 B-Core-2/3.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.agent_framework.runtime.schema import Skill
from src.common.logging import get_logger

log = get_logger(__name__)


class SkillRegistry:
    """account → enabled Skill 필터.

    Parameters
    ----------
    engine : AsyncEngine
        SQLAlchemy async engine (kms_pipeline).
    all_skills : dict[str, Skill]
        fs/kms 로 로드된 전역 스킬 dict. registry 는 이 중에서 필터만 한다.
        엔진이 주입 시점에 ``load_all_skills(SKILLS_DIR)`` 또는 KMS 로더 결과를 넘긴다.
    """

    def __init__(self, engine: AsyncEngine, all_skills: dict[str, Skill]):
        self.engine = engine
        self.all_skills = all_skills

    async def list_enabled_skill_ids_for_account(self, account_id: UUID) -> list[str]:
        """account 의 모든 membership tenant 에서 enabled 된 skill_id 합집합."""
        async with self.engine.begin() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT DISTINCT ts.skill_id
                    FROM tenant_skills ts
                    JOIN tenant_memberships m ON m.tenant_id = ts.tenant_id
                    WHERE m.account_id = :aid
                    """
                ),
                {"aid": account_id},
            )
            return [r[0] for r in rows]

    async def list_available_skills_for_account(
        self, account_id: UUID
    ) -> list[Skill]:
        """account 가 접근 가능한 ``Skill`` 객체 리스트.

        tenant_skills 에 enabled 되어 있지만 all_skills 에 없으면 (fs/kms 로드 실패
        또는 이름 불일치) 경고 로그와 함께 skip.
        """
        enabled_ids = await self.list_enabled_skill_ids_for_account(account_id)
        result: list[Skill] = []
        for sid in enabled_ids:
            s = self.all_skills.get(sid)
            if s is not None:
                result.append(s)
            else:
                log.warning(
                    "skill_enabled_but_not_loaded",
                    skill_id=sid,
                    hint="tenant_skills 에는 있는데 fs/kms 로드 실패 또는 이름 불일치",
                )
        return result

    async def _get_tenant_type(self, tenant_id: UUID) -> str | None:
        """tenants.tenant_type 조회. None 이면 미상."""
        try:
            async with self.engine.begin() as conn:
                row = (
                    await conn.execute(
                        text("SELECT tenant_type FROM tenants WHERE id = :tid"),
                        {"tid": tenant_id},
                    )
                ).first()
            return row[0] if row else None
        except Exception as e:  # noqa: BLE001
            log.warning("tenant_type_lookup_failed", tid=str(tenant_id), error=str(e))
            return None

    async def list_available_labels_for_account(
        self,
        account_id: UUID,
        *,
        active_tenant_id: UUID | None = None,
    ) -> list[str]:
        """engine intent classifier 에 넘길 후보 intent 라벨 집합.

        모드별 분기 (2026-04-28 사용자 결정):
        - **대화모드** (active tenant_type = ``personal``): visibility=auto skill
          은 tenant_skills opt-in 무관 자동 노출. 사용자가 일상 발화에서
          일정·가계부·주식 등 personal 도구를 모두 즉시 사용 가능.
        - **에이전트/상담사 모드** (active tenant_type = ``company``/``corporate``):
          strict — tenant_skills 에 *명시적 enable* 된 skill 만 후보. 주식·
          일정처럼 personal 도구가 상담사 워크플로에 끼어들지 않게 차단.
          에이전트 정의는 진짜 커스텀.

        active_tenant_id 미주입 시 (legacy 호출) 옛 PR-J 동작 유지 — auto bypass.
        """
        # 옛 PR-J 우회는 active_tenant_id 가 personal 일 때 OR 미주입일 때만.
        bypass_auto = True
        if active_tenant_id is not None:
            ttype = await self._get_tenant_type(active_tenant_id)
            if ttype and ttype.lower() not in ("personal",):
                bypass_auto = False

        if bypass_auto:
            skills = await self.list_available_skills_for_account(account_id)
            seen_ids = {s.meta.id for s in skills}
            for s in self.all_skills.values():
                if s.meta.id in seen_ids:
                    continue
                visibility = getattr(getattr(s, "availability", None), "visibility", "")
                if str(visibility).lower() == "auto":
                    skills.append(s)
                    seen_ids.add(s.meta.id)
            return sorted({t.intent for s in skills for t in s.triggers})

        # strict mode — 활성 tenant 의 tenant_skills row 에 등록된 것만.
        async with self.engine.begin() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT skill_id
                      FROM tenant_skills
                     WHERE tenant_id = :tid
                    """
                ),
                {"tid": active_tenant_id},
            )
            enabled_ids = [r[0] for r in rows]
        skills_strict = []
        for sid in enabled_ids:
            s = self.all_skills.get(sid)
            if s is None:
                continue
            # business_only / scope=all 만 허용. personal 만 적용 가능한 skill 은
            # 에이전트 모드에서 노출 안 함.
            scope = str(getattr(getattr(s, "availability", None), "scope", "all")).lower()
            if scope == "personal":
                continue
            skills_strict.append(s)
        return sorted({t.intent for s in skills_strict for t in s.triggers})

    async def enable_skill(
        self,
        tenant_id: UUID,
        skill_id: str,
        by_account_id: UUID | None = None,
    ) -> None:
        """명시적 opt-in (business_only 스킬 등). tenant 단위 enablement."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO tenant_skills
                      (tenant_id, skill_id, enabled_by_account_id, config)
                    VALUES (:tid, :sid, :aid, '{}'::jsonb)
                    ON CONFLICT (tenant_id, skill_id) DO NOTHING
                    """
                ),
                {"tid": tenant_id, "sid": skill_id, "aid": by_account_id},
            )

    async def disable_skill(self, tenant_id: UUID, skill_id: str) -> None:
        """tenant 에서 해당 skill 비활성 (행 삭제)."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM tenant_skills "
                    "WHERE tenant_id = :tid AND skill_id = :sid"
                ),
                {"tid": tenant_id, "sid": skill_id},
            )
