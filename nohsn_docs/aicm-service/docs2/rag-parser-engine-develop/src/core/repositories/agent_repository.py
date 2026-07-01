from __future__ import annotations
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.models.agent import Agent


class AgentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, *, tenant_id: UUID, created_by: UUID | None, **fields) -> Agent:
        # NOTE: created_at/updated_at 은 TimestampMixin 의 server_default 가 처리.
        agent = Agent(tenant_id=tenant_id, created_by=created_by, **fields)
        self.db.add(agent)
        await self.db.flush()
        await self.db.refresh(agent)
        return agent

    async def get(self, agent_id: UUID, *, tenant_id: UUID) -> Agent | None:
        stmt = select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_by_tenant(self, tenant_id: UUID, *, active_only: bool = True) -> list[Agent]:
        stmt = select(Agent).where(Agent.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(Agent.is_active == True)
        stmt = stmt.order_by(Agent.created_at.desc())
        return list((await self.db.execute(stmt)).scalars().all())

    async def update(self, agent_id: UUID, *, tenant_id: UUID, **patch) -> Agent | None:
        agent = await self.get(agent_id, tenant_id=tenant_id)
        if agent is None:
            return None
        for k, v in patch.items():
            if v is not None:
                setattr(agent, k, v)
        # updated_at 은 TimestampMixin 의 onupdate 가 자동 갱신.
        await self.db.flush()
        return agent

    async def soft_delete(self, agent_id: UUID, *, tenant_id: UUID) -> bool:
        agent = await self.get(agent_id, tenant_id=tenant_id)
        if agent is None:
            return False
        agent.is_active = False
        await self.db.flush()
        return True
