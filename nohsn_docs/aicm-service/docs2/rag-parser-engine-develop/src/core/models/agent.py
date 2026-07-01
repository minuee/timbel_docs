"""Agent, AgentChannel, ChannelUserMapping ORM 모델 (External Agent Phase 1)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, LargeBinary, Text, UniqueConstraint, text
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import ARRAY as PgARRAY, JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.core.models.base import Base, TimestampMixin


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    guidelines_md: Mapped[str] = mapped_column(Text, nullable=False)
    primary_repo_ids: Mapped[list[UUID]] = mapped_column(
        PgARRAY(PgUUID(as_uuid=True)), nullable=False, default=list
    )
    fallback_repo_ids: Mapped[list[UUID]] = mapped_column(
        PgARRAY(PgUUID(as_uuid=True)), nullable=False, default=list
    )
    # Phase 1.5A — SOP/policy 문서를 보유한 repo IDs (Phase 1.5B SOP RAG 가 활용).
    sop_repo_ids: Mapped[list[UUID]] = mapped_column(
        PgARRAY(PgUUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    # Phase 1.5B-γ — 이 agent 가 위임 호출 가능한 sub-agent IDs (multi-agent).
    # admin kind 인 경우 default 동작은 "모든 role agent 자동 inject" 이지만
    # 명시적으로 채우면 그것만 사용. role kind 는 비어 있으면 위임 불가.
    delegate_to_agent_ids: Mapped[list[UUID]] = mapped_column(
        PgARRAY(PgUUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default="{}",
    )
    knowledge_isolation: Mapped[str] = mapped_column(Text, nullable=False, default="priority")
    allowed_tools: Mapped[list[str]] = mapped_column(PgARRAY(Text), nullable=False, default=list)
    done_when: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_mode_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 058 — admin (Locus 어시스턴트, 1 per tenant) vs role (사용자가 만드는 하부 에이전트, N 개).
    # admin 은 engine 에서 skill state machine bypass + 전체 도구 카탈로그 사용.
    # role 은 기존 동작 (skill yaml narrowing + plan_orchestrator 카테고리 7-tool subset).
    kind: Mapped[str] = mapped_column(
        Text, nullable=False, default="role", server_default="role"
    )
    template_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # 065 (Phase 1.5E) — agent 전용 repo namespace 라벨. admin kind 는 NULL —
    # 모든 repo 접근 (Layer 2 bypass). role kind 가 NULL 이면 공용 repo 만 접근.
    # 자유 문자열 — tenant 안 unique 운영자 책임. Marketplace import 시 customer
    # tenant 안 prefix 권고 (예: tenant1_baemin).
    repo_namespace: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    # 069 (Plan A v3, 2026-05-07) — 웹검색 모드. 4 enum:
    #   'off'      = KMS only (현재 기본).
    #   'separate' = KMS + web 병렬 검색, 답변에 *두 섹션* 분리해 출처 구분.
    #   'blended'  = KMS + web 결과 합쳐 reranker 통합 ranking → 단일 list.
    #   'web_only' = KMS skip, web 만.
    # default 'off' (격리 우선). admin Locus 만 'separate' (alembic 069 시드).
    web_search_mode: Mapped[str] = mapped_column(
        Text, nullable=False, default="off", server_default="off"
    )
    # 071 (옵션 Y v2, 2026-05-07) — agent 의 default 업로드 / 작성 저장 폴더.
    # NULL = 아직 자동 생성 안 됨. 첫 업로드 / 작성 시 ensure_default_folder()
    # 가 자동 생성 (library_folders.owner_agent_id = agent.id 로 표시).
    # FK ON DELETE SET NULL — 폴더 삭제 시 다음 업로드에서 자동 재생성.
    default_folder_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("library_folders.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 075 (Phase 3 #154, 2026-05-07) — agent 별 도구 scope override.
    # format: {"<tool_name>": "<scope>"} (예: {"schedule.create": "user"}).
    # 승격 금지 (Pydantic validator) — default 보다 *낮거나 같은* 등급만 허용.
    # 본 PR 에서는 *컬럼 + UI* 만. manifest enforcement 는 Phase 4 (#155).
    tool_scope_overrides: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # 080 (D70, 2026-05-11) — 봇별 cross-domain 키워드 (intent gate). nullable
    # — 기존 row 호환. None / [] 모두 안전 (intent_gate 가 통과 처리). 운영자가
    # *브랜드/서비스 고유명* 만 등록 권고 (일반어 금지).
    oos_keywords: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, server_default=text("'[]'::jsonb")
    )

    # Legacy columns — kept for router/data compatibility (Phase 1 does not write these)
    persona: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    allowed_skills: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="[]")
    allowed_repos: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="[]")
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")

    channels: Mapped[list[AgentChannel]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "knowledge_isolation IN ('strict', 'priority', 'broad')",
            name="agents_isolation_check",
        ),
        CheckConstraint(
            "kind IN ('admin', 'role')",
            name="agents_kind_check",
        ),
        # Phase 1.5B-γ — 자기 자신 위임 금지 (DB 단 안전망). 순환/depth 검증은
        # application layer.
        CheckConstraint(
            "NOT (id = ANY(delegate_to_agent_ids))",
            name="agents_no_self_delegation",
        ),
        # 069 — web_search_mode enum (off / separate / blended / web_only).
        CheckConstraint(
            "web_search_mode IN ('off','separate','blended','web_only')",
            name="ck_agents_web_search_mode",
        ),
    )


class AgentChannel(Base, TimestampMixin):
    __tablename__ = "agent_channels"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)

    agent: Mapped[Agent] = relationship(back_populates="channels")
    user_mappings: Mapped[list[ChannelUserMapping]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("kind", "external_id", name="agent_channels_kind_external_uq"),
    )


class ChannelInboundDedup(Base):
    """webhook 인바운드 멱등성 — (channel_id, idempotency_key) 합성 unique.

    Telegram update_id 등 채널이 제공하는 멱등성 키를 기록해 동일 webhook 재시도
    시 중복 처리 / 중복 응답을 차단한다 (alembic 060).
    """

    __tablename__ = "channel_inbound_dedup"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    channel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    response_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "channel_id", "idempotency_key", name="channel_inbound_dedup_uq"
        ),
    )


class ChannelUserMapping(Base):
    __tablename__ = "channel_user_mappings"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    channel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    internal_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # 059 — webhook routing 이 chat_sessions.account_id 로 직접 attribute
    # 하기 위한 accounts FK (accounts ↔ users 1:1 아닌 현 스키마 정합).
    # NULL = guest. 운영자가 admin endpoint (또는 수동 SQL) 로 채움.
    # NOTE: accounts 테이블은 ORM Model 미정의 — DB FK constraint 는 alembic
    # 059 에서 생성됨. ORM 레벨 FK 는 제거 (NoReferencedTableError 방지).
    internal_account_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=True,
    )
    # 063 (Task 8f) — chat_id binding key + group default deny.
    # private chat: chat_id == external_user_id.
    # group/supergroup/channel: chat_id = chat.id (from.id 와 다름).
    chat_id: Mapped[str] = mapped_column(Text, nullable=False)
    # group_enabled — group/supergroup/channel 응답 default deny gate.
    # admin 이 true 토글 한 mapping 만 응답 (멤버 자동응답 폭주 차단).
    # private chat 은 라우터 분기에서 무시되므로 사실상 사용 안 함.
    group_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    channel: Mapped[AgentChannel] = relationship(back_populates="user_mappings")

    __table_args__ = (
        # 063 (Task 8f) — (channel_id, chat_id, external_user_id) 합성 unique.
        UniqueConstraint(
            "channel_id", "chat_id", "external_user_id",
            name="channel_user_mappings_uq",
        ),
    )
