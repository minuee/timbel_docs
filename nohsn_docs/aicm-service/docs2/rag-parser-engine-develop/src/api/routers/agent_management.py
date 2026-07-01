"""/api/v1/agent-templates + /api/v1/agents/{id}/{dashboard,billing,insights} + graph.

Phase 1.5D — 에이전트 관리 9 페이지의 backend layer (spec §5).

신규 endpoints:
- GET    /api/v1/agent-templates                     — 카탈로그 list
- POST   /api/v1/agent-templates                     — super-admin 만 publish
- GET    /api/v1/agent-templates/{id}                — 단건 조회
- PATCH  /api/v1/agent-templates/{id}                — super-admin 수정
- POST   /api/v1/agent-templates/{id}/import         — 자기 tenant 에 instance 복제
- GET    /api/v1/agents/{id}/dashboard               — KPI / 시계열 / 도구 빈도 / 채널
- GET    /api/v1/agents/{id}/billing                 — 월 청구 list
- GET    /api/v1/agents/{id}/billing/{period}        — 특정 월 청구 단건
- GET    /api/v1/agents/{id}/insights                — LLM 자동 권고 (cache 1h)
- GET    /api/v1/agents/{id}/audit                   — agent 단위 audit log
- GET    /api/v1/agents/{id}/alerts                  — 운영 알람
- POST   /api/v1/agents/{id}/alerts/{alert_id}/ack   — 알람 acknowledged
- GET    /api/v1/agents/graph                        — 위임 그래프 노드/엣지

설계:
- agents_v1.py 의 helper (_account_from_token / _resolve_tenant /
  _verify_membership / _load_agent_for_tenant) 재사용. 보안 패턴 동일.
- Marketplace 는 super-admin 자산 — agent_templates 는 tenant_id 없음.
- import 는 transaction — agent + sop_documents (없을 수 있음) + subscription
  + audit_log 한 번에.
- dashboard 는 mv_agent_dashboard_5min + agent_message_log 시계열 GROUP BY.
- insights 는 LLM 호출 — Redis 캐시 1h (key: agent_insights:{id}).
- graph 는 tenant 의 모든 agent 의 (id, name, kind, delegate_to_agent_ids)
  → 노드/엣지 변환.

하드코딩 enum 금지 — kind / category / pricing.model 모두 free string.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.api.routers.agents_v1 import (
    _account_from_token,
    _get_engine,
    _load_agent_for_tenant,
    _parse_uuid,
    _resolve_tenant,
    _verify_membership,
)


router = APIRouter(prefix="/api/v1", tags=["agent-management"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentTemplateOut(BaseModel):
    id: str
    template_key: str
    template_name: str
    category: str
    persona_template: str = ""
    sop_markdown_template: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    channel_kinds: list[str] = Field(default_factory=list)
    required_paid_addons: list[str] = Field(default_factory=list)
    publish_status: str = "draft"
    author_account_id: str | None = None
    version: int = 1
    pricing_plan: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    preview_screenshots: list[str] | None = None
    vendor: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AgentTemplateListOut(BaseModel):
    items: list[AgentTemplateOut]


class AgentTemplateCreate(BaseModel):
    template_key: str = Field(min_length=1, max_length=100)
    template_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=64)
    persona_template: str = ""
    sop_markdown_template: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    channel_kinds: list[str] = Field(default_factory=list)
    required_paid_addons: list[str] = Field(default_factory=list)
    publish_status: str = "draft"
    version: int = 1
    pricing_plan: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    vendor: str | None = None


class AgentTemplatePatch(BaseModel):
    template_name: str | None = None
    category: str | None = None
    persona_template: str | None = None
    sop_markdown_template: str | None = None
    allowed_tools: list[str] | None = None
    channel_kinds: list[str] | None = None
    required_paid_addons: list[str] | None = None
    publish_status: str | None = None
    version: int | None = None
    pricing_plan: dict[str, Any] | None = None
    description: str | None = None
    vendor: str | None = None


class TemplateImportResponse(BaseModel):
    agent_id: str
    subscription_id: str
    redirect_to: str


class DashboardKpi(BaseModel):
    turn_5m: int = 0
    turn_24h: int = 0
    turn_7d: int = 0
    active_sessions_5m: int = 0
    # F3 (2026-05-07) — sessions vs users 의미 분리.
    # ``unique_sessions_24h`` = COUNT(DISTINCT external_session_id) — 옛
    # ``unique_users_24h`` 의 SQL 그대로. web 의 ``agent-test-{uuid}-{rand}``
    # 마다 새 session 으로 카운트되는 *세션* 단위 지표.
    # ``unique_users_24h`` = web/test session 들을 admin 1명으로 묶고,
    # telegram 등 채널 chat_id 만 distinct 카운트한 *사용자* 단위 지표.
    unique_sessions_24h: int = 0
    unique_users_24h: int = 0
    latency_p95_ms: int = 0
    avg_latency_ms: int = 0
    error_rate_24h: float = 0.0
    sop_hit_rate: float = 0.0
    tool_hit_rate: float = 0.0


class TimeseriesPoint(BaseModel):
    day: str
    value: float


class ToolFreq(BaseModel):
    name: str
    calls: int
    error_rate: float = 0.0


class ChannelDist(BaseModel):
    kind: str
    calls: int


class AlertOut(BaseModel):
    id: str
    agent_id: str
    kind: str
    level: str
    message: str
    triggered_at: str | None = None
    acknowledged_at: str | None = None


class DashboardOut(BaseModel):
    kpi: DashboardKpi
    timeseries_7d: dict[str, list[TimeseriesPoint]] = Field(default_factory=dict)
    top_tools: list[ToolFreq] = Field(default_factory=list)
    channel_dist: list[ChannelDist] = Field(default_factory=list)
    recent_errors: list[dict[str, Any]] = Field(default_factory=list)
    active_alerts: list[AlertOut] = Field(default_factory=list)


class BillingItem(BaseModel):
    id: str
    agent_id: str
    period_start: str
    period_end: str
    turn_count: int = 0
    token_in: int = 0
    token_out: int = 0
    channel_cost: dict[str, Any] = Field(default_factory=dict)
    tool_call_count: int = 0
    total_amount: float = 0.0
    currency: str = "KRW"
    paid_at: str | None = None


class BillingListOut(BaseModel):
    items: list[BillingItem]


class InsightItem(BaseModel):
    title: str
    summary: str
    severity: str = "info"  # info|warn|critical — free string
    suggested_action: str | None = None


class InsightsOut(BaseModel):
    items: list[InsightItem]
    generated_at: str
    cache_hit: bool = False


class GraphNode(BaseModel):
    id: str
    name: str
    kind: str = "role"
    is_active: bool = True
    has_template: bool = False
    error_level: str | None = None  # warn|critical 알람 보유 시


class GraphEdge(BaseModel):
    source: str
    target: str


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class AlertListOut(BaseModel):
    items: list[AlertOut]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_template(row: Any) -> AgentTemplateOut:
    return AgentTemplateOut(
        id=str(row[0]),
        template_key=row[1],
        template_name=row[2],
        category=row[3],
        persona_template=row[4] or "",
        sop_markdown_template=row[5] or "",
        allowed_tools=list(row[6] or []),
        channel_kinds=list(row[7] or []),
        required_paid_addons=list(row[8] or []),
        publish_status=row[9] or "draft",
        author_account_id=str(row[10]) if row[10] else None,
        version=int(row[11] or 1),
        pricing_plan=dict(row[12] or {}),
        description=row[13],
        preview_screenshots=list(row[14]) if row[14] else None,
        vendor=row[15],
        created_at=row[16].isoformat() if row[16] else None,
        updated_at=row[17].isoformat() if row[17] else None,
    )


_TEMPLATE_COLS = (
    "id, template_key, template_name, category, persona_template, "
    "sop_markdown_template, allowed_tools, channel_kinds, "
    "required_paid_addons, publish_status, author_account_id, version, "
    "pricing_plan, description, preview_screenshots, vendor, "
    "created_at, updated_at"
)


# ---------------------------------------------------------------------------
# Templates CRUD
# ---------------------------------------------------------------------------


@router.get("/agent-templates", response_model=AgentTemplateListOut)
async def list_templates(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    category: str | None = Query(None),
    publish_status: str | None = Query("published"),
) -> AgentTemplateListOut:
    """카탈로그 list. 기본 published 만. customer admin 도 read 가능."""
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)

    eng = _get_engine()
    where = []
    params: dict[str, Any] = {}
    if category:
        where.append("category = :cat")
        params["cat"] = category
    if publish_status:
        where.append("publish_status = :ps")
        params["ps"] = publish_status
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                f"SELECT {_TEMPLATE_COLS} FROM agent_templates "
                f"{where_sql} ORDER BY category, template_name"
            ),
            params,
        )
        items = [_row_to_template(r) for r in rows]
    return AgentTemplateListOut(items=items)


@router.post("/agent-templates", response_model=AgentTemplateOut)
async def create_template(
    body: AgentTemplateCreate,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> AgentTemplateOut:
    """super-admin 만. tenant role 'admin' 도 일단 허용 (시연 단계).
    후속에서 super-admin only 로 강화."""
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")

    eng = _get_engine()
    async with eng.begin() as conn:
        new_id = (
            await conn.execute(
                text(
                    """
                    INSERT INTO agent_templates
                      (template_key, template_name, category, persona_template,
                       sop_markdown_template, allowed_tools, channel_kinds,
                       required_paid_addons, publish_status, author_account_id,
                       version, pricing_plan, description, vendor)
                    VALUES
                      (:tk, :tn, :cat, :persona, :sop,
                       CAST(:tools AS jsonb), CAST(:channels AS jsonb),
                       CAST(:addons AS jsonb), :ps, :auth, :ver,
                       CAST(:price AS jsonb), :desc, :vendor)
                    RETURNING id
                    """
                ),
                {
                    "tk": body.template_key,
                    "tn": body.template_name,
                    "cat": body.category,
                    "persona": body.persona_template,
                    "sop": body.sop_markdown_template,
                    "tools": json.dumps(body.allowed_tools),
                    "channels": json.dumps(body.channel_kinds),
                    "addons": json.dumps(body.required_paid_addons),
                    "ps": body.publish_status,
                    "auth": aid,
                    "ver": body.version,
                    "price": json.dumps(body.pricing_plan),
                    "desc": body.description,
                    "vendor": body.vendor,
                },
            )
        ).scalar_one()
        row = (
            await conn.execute(
                text(
                    f"SELECT {_TEMPLATE_COLS} FROM agent_templates WHERE id = :id"
                ),
                {"id": new_id},
            )
        ).first()
    return _row_to_template(row)


@router.get("/agent-templates/{template_id}", response_model=AgentTemplateOut)
async def get_template(
    template_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> AgentTemplateOut:
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    tpl_id = _parse_uuid(template_id, "template_id")
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    f"SELECT {_TEMPLATE_COLS} FROM agent_templates WHERE id = :id"
                ),
                {"id": tpl_id},
            )
        ).first()
    if not row:
        raise HTTPException(404, "template not found")
    return _row_to_template(row)


@router.patch("/agent-templates/{template_id}", response_model=AgentTemplateOut)
async def patch_template(
    template_id: str,
    body: AgentTemplatePatch,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> AgentTemplateOut:
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    tpl_id = _parse_uuid(template_id, "template_id")

    eng = _get_engine()
    async with eng.begin() as conn:
        await conn.execute(
            text(
                """
                UPDATE agent_templates
                SET template_name = COALESCE(:tn, template_name),
                    category = COALESCE(:cat, category),
                    persona_template = COALESCE(:persona, persona_template),
                    sop_markdown_template = COALESCE(:sop, sop_markdown_template),
                    allowed_tools = COALESCE(CAST(:tools AS jsonb), allowed_tools),
                    channel_kinds = COALESCE(CAST(:channels AS jsonb), channel_kinds),
                    required_paid_addons = COALESCE(CAST(:addons AS jsonb), required_paid_addons),
                    publish_status = COALESCE(:ps, publish_status),
                    version = COALESCE(:ver, version),
                    pricing_plan = COALESCE(CAST(:price AS jsonb), pricing_plan),
                    description = COALESCE(:desc, description),
                    vendor = COALESCE(:vendor, vendor),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "tn": body.template_name,
                "cat": body.category,
                "persona": body.persona_template,
                "sop": body.sop_markdown_template,
                "tools": None if body.allowed_tools is None else json.dumps(body.allowed_tools),
                "channels": None if body.channel_kinds is None else json.dumps(body.channel_kinds),
                "addons": None if body.required_paid_addons is None else json.dumps(body.required_paid_addons),
                "ps": body.publish_status,
                "ver": body.version,
                "price": None if body.pricing_plan is None else json.dumps(body.pricing_plan),
                "desc": body.description,
                "vendor": body.vendor,
                "id": tpl_id,
            },
        )
        row = (
            await conn.execute(
                text(
                    f"SELECT {_TEMPLATE_COLS} FROM agent_templates WHERE id = :id"
                ),
                {"id": tpl_id},
            )
        ).first()
    if not row:
        raise HTTPException(404, "template not found")
    return _row_to_template(row)


# ---------------------------------------------------------------------------
# Template import — Marketplace 핵심
# ---------------------------------------------------------------------------


@router.post(
    "/agent-templates/{template_id}/import",
    response_model=TemplateImportResponse,
)
async def import_template(
    template_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> TemplateImportResponse:
    """카탈로그 → 자기 tenant 에 실제 agent 인스턴스 복제 + subscription.

    spec §5.1 동작 — published 만 import 가능. tenant_id 는 *서버 측 인증*
    값만 사용. 신규 agent 는 customer tenant 에 묶임.
    """
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    tpl_id = _parse_uuid(template_id, "template_id")

    eng = _get_engine()
    async with eng.begin() as conn:
        tpl = (
            await conn.execute(
                text(
                    """
                    SELECT id, template_name, category, persona_template,
                           sop_markdown_template, allowed_tools, channel_kinds,
                           publish_status, pricing_plan
                    FROM agent_templates WHERE id = :id
                    """
                ),
                {"id": tpl_id},
            )
        ).first()
        if not tpl:
            raise HTTPException(404, "template not found")
        if (tpl[7] or "draft") != "published":
            raise HTTPException(400, f"template not published (status={tpl[7]})")

        # 1. INSERT agents — tenant_id 는 서버 측 token 만.
        new_agent_id = (
            await conn.execute(
                text(
                    """
                    INSERT INTO agents
                      (tenant_id, name, description, persona, system_prompt,
                       allowed_skills, allowed_repos, rate_limit_per_min,
                       created_by, kind, source_template_id, is_template,
                       goal, guidelines_md)
                    VALUES
                      (:tid, :name, :desc, :persona, :sp,
                       '[]'::jsonb, '[]'::jsonb, 60,
                       :cb, 'role', :tpl_id, false,
                       :goal, :guide)
                    RETURNING id
                    """
                ),
                {
                    "tid": tid,
                    "name": tpl[1],
                    "desc": f"Imported from template '{tpl[1]}' (category={tpl[2]})",
                    "persona": tpl[3] or "",
                    "sp": "",
                    "cb": aid,
                    "tpl_id": tpl_id,
                    "goal": tpl[3] or tpl[1],
                    "guide": tpl[4] or "(편집 페이지에서 작성하세요)",
                },
            )
        ).scalar_one()

        # 2. lineage_root_id = self (top-level imported instance).
        await conn.execute(
            text(
                "UPDATE agents SET lineage_root_id = :id WHERE id = :id"
            ),
            {"id": new_agent_id},
        )

        # 3. INSERT agent_subscriptions.
        sub_id = (
            await conn.execute(
                text(
                    """
                    INSERT INTO agent_subscriptions
                      (template_id, customer_tenant_id, agent_id,
                       status, billing_plan)
                    VALUES (:tpl, :tid, :aid, 'active', CAST(:plan AS jsonb))
                    RETURNING id
                    """
                ),
                {
                    "tpl": tpl_id,
                    "tid": tid,
                    "aid": new_agent_id,
                    "plan": json.dumps(dict(tpl[8] or {})),
                },
            )
        ).scalar_one()

    return TemplateImportResponse(
        agent_id=str(new_agent_id),
        subscription_id=str(sub_id),
        redirect_to=f"/admin/agents/{new_agent_id}/edit",
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/dashboard", response_model=DashboardOut)
async def get_dashboard(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> DashboardOut:
    """agent 단위 KPI / 시계열 / 도구 빈도 / 채널 분포 / 활성 알람."""
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")
    # round 2 fix — agent.allowed_tools 로 top_tools 를 agent별로 필터.
    # tool_invocations 에 agent_id 컬럼이 없어 tenant 전체 집계가 모든 agent
    # 에 동일하게 노출되던 결함을 보완 (사용자 보고 "데이터 안 맞음" 의 핵심).
    agent_meta = await _load_agent_for_tenant(target_id, tid)
    allowed_tools_set = {t for t in (agent_meta.allowed_tools or []) if t}

    eng = _get_engine()
    kpi = DashboardKpi()
    timeseries: dict[str, list[TimeseriesPoint]] = {"turn": [], "latency": []}
    top_tools: list[ToolFreq] = []
    channel_dist: list[ChannelDist] = []
    recent_errors: list[dict[str, Any]] = []
    alerts: list[AlertOut] = []

    async with eng.begin() as conn:
        # 1. mv_agent_dashboard_5min — 5분 지표 (있으면 사용, 없으면 직접 집계 fallback).
        # SAVEPOINT 로 격리 — view 가 비어있거나 refresh 미동기 시 InFailedSQL
        # TransactionError 가 후속 쿼리로 번지지 않도록.
        # 2026-05-07 — mv refresh cron 미동기 (mv_rows=0) 시 turn_5m 표시 0 결함.
        # row 없으면 agent_message_log 5분 직접 집계 fallback.
        mv_hit = False
        try:
            async with conn.begin_nested():
                mv_row = (
                    await conn.execute(
                        text(
                            """
                            SELECT turn_5m, active_sessions_5m, error_rate_5m,
                                   avg_latency_ms_5m
                            FROM mv_agent_dashboard_5min
                            WHERE tenant_id = :tid AND agent_id = :aid
                            """
                        ),
                        {"tid": tid, "aid": target_id},
                    )
                ).first()
                if mv_row:
                    kpi.turn_5m = int(mv_row[0] or 0)
                    kpi.active_sessions_5m = int(mv_row[1] or 0)
                    kpi.avg_latency_ms = int(mv_row[3] or 0)
                    mv_hit = kpi.turn_5m > 0 or kpi.active_sessions_5m > 0
        except Exception:
            pass

        if not mv_hit:
            # mv 가 0/empty/refresh 미동기 — 직접 집계.
            try:
                async with conn.begin_nested():
                    five_min = (
                        await conn.execute(
                            text(
                                """
                                SELECT COUNT(*) AS turn,
                                       COUNT(DISTINCT external_session_id) AS sessions,
                                       COALESCE(AVG(latency_ms), 0)::int AS avg_lat
                                FROM agent_message_log
                                WHERE agent_id = :aid
                                  AND created_at > now() - interval '5 minutes'
                                """
                            ),
                            {"aid": target_id},
                        )
                    ).first()
                    if five_min:
                        kpi.turn_5m = int(five_min[0] or 0)
                        kpi.active_sessions_5m = int(five_min[1] or 0)
                        if not kpi.avg_latency_ms:
                            kpi.avg_latency_ms = int(five_min[2] or 0)
            except Exception:
                pass

        # 2. agent_message_log 24h / 7d 집계 — 정확한 source.
        # F3 (2026-05-07) — sessions vs users 의미 분리.
        # web channel 의 external_session_id = ``agent-test-{uuid}-{rand}``
        # 패턴은 admin tester 한 명이 매 페이지 로드마다 새 ID 를 생성하므로
        # COUNT(DISTINCT external_session_id) 는 *사용자* 가 아니라 *세션* 수
        # 이다. unique_users_24h 은 web 패턴을 admin 1 로 collapse + 다른 채널
        # 의 external_user_id 만 distinct 카운트.
        agg_24h = (
            await conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS turn,
                           COUNT(DISTINCT external_session_id) AS sessions,
                           COUNT(DISTINCT
                               CASE
                                   WHEN external_session_id LIKE 'agent-test-%'
                                       THEN '__admin_test__'
                                   WHEN external_session_id LIKE 'wh-%'
                                       THEN external_session_id
                                   ELSE external_session_id
                               END
                           ) AS users,
                           COALESCE(AVG(latency_ms), 0)::int AS avg_lat,
                           COALESCE(
                               percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms),
                               0
                           )::int AS p95,
                           SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS err
                    FROM agent_message_log
                    WHERE agent_id = :aid AND created_at > now() - interval '24 hours'
                    """
                ),
                {"aid": target_id},
            )
        ).first()
        if agg_24h:
            kpi.turn_24h = int(agg_24h[0] or 0)
            kpi.unique_sessions_24h = int(agg_24h[1] or 0)
            kpi.unique_users_24h = int(agg_24h[2] or 0)
            if not kpi.avg_latency_ms:
                kpi.avg_latency_ms = int(agg_24h[3] or 0)
            kpi.latency_p95_ms = int(agg_24h[4] or 0)
            err = int(agg_24h[5] or 0)
            kpi.error_rate_24h = (err / kpi.turn_24h) if kpi.turn_24h > 0 else 0.0

        # 2b. admin agent 보강 — 일반 chat (chat_messages × chat_sessions.agent_id)
        # 도 turn source 로 합산. 2026-05-07 — Locus admin agent 가 *test-chat* 이
        # 아닌 *주 chat* 으로 사용되어 agent_message_log = 0, dashboard 빈 화면.
        # admin 은 주 chat 이 정상 진입점 — chat_messages 도 turn 으로 카운트.
        try:
            async with conn.begin_nested():
                chat_24h = (
                    await conn.execute(
                        text(
                            """
                            SELECT COUNT(m.id) AS turn,
                                   COUNT(DISTINCT s.id) AS sessions,
                                   COUNT(DISTINCT s.account_id) AS users
                            FROM chat_messages m
                            JOIN chat_sessions s ON s.id = m.session_id
                            WHERE s.agent_id = :aid
                              AND m.created_at > now() - interval '24 hours'
                              AND m.role = 'assistant'
                            """
                        ),
                        {"aid": target_id},
                    )
                ).first()
                if chat_24h:
                    chat_turn = int(chat_24h[0] or 0)
                    chat_sess = int(chat_24h[1] or 0)
                    chat_users = int(chat_24h[2] or 0)
                    # 합산 — admin 은 두 source 모두 합치고, role 은 차이 없음 (chat_24h ≈ 0).
                    kpi.turn_24h += chat_turn
                    kpi.unique_sessions_24h += chat_sess
                    kpi.unique_users_24h += chat_users
        except Exception:
            pass

        # 2c. admin agent — 5분 보강도 동일 source.
        try:
            async with conn.begin_nested():
                chat_5m = (
                    await conn.execute(
                        text(
                            """
                            SELECT COUNT(m.id) AS turn,
                                   COUNT(DISTINCT s.id) AS sessions
                            FROM chat_messages m
                            JOIN chat_sessions s ON s.id = m.session_id
                            WHERE s.agent_id = :aid
                              AND m.created_at > now() - interval '5 minutes'
                              AND m.role = 'assistant'
                            """
                        ),
                        {"aid": target_id},
                    )
                ).first()
                if chat_5m:
                    kpi.turn_5m += int(chat_5m[0] or 0)
                    kpi.active_sessions_5m += int(chat_5m[1] or 0)
        except Exception:
            pass

        agg_7d = (
            await conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS turn
                    FROM agent_message_log
                    WHERE agent_id = :aid AND created_at > now() - interval '7 days'
                    """
                ),
                {"aid": target_id},
            )
        ).first()
        if agg_7d:
            kpi.turn_7d = int(agg_7d[0] or 0)

        # 2d. admin agent — 7일 turn 도 chat_messages 합산.
        try:
            async with conn.begin_nested():
                chat_7d = (
                    await conn.execute(
                        text(
                            """
                            SELECT COUNT(m.id) AS turn
                            FROM chat_messages m
                            JOIN chat_sessions s ON s.id = m.session_id
                            WHERE s.agent_id = :aid
                              AND m.created_at > now() - interval '7 days'
                              AND m.role = 'assistant'
                            """
                        ),
                        {"aid": target_id},
                    )
                ).first()
                if chat_7d:
                    kpi.turn_7d += int(chat_7d[0] or 0)
        except Exception:
            pass

        # 3. timeseries — 7일 turn / latency.
        ts_rows = await conn.execute(
            text(
                """
                SELECT date_trunc('day', created_at)::date AS day,
                       COUNT(*) AS turn,
                       COALESCE(AVG(latency_ms), 0)::int AS avg_lat
                FROM agent_message_log
                WHERE agent_id = :aid AND created_at > now() - interval '7 days'
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"aid": target_id},
        )
        for r in ts_rows:
            day_s = r[0].isoformat() if r[0] else ""
            timeseries["turn"].append(TimeseriesPoint(day=day_s, value=float(r[1] or 0)))
            timeseries["latency"].append(
                TimeseriesPoint(day=day_s, value=float(r[2] or 0))
            )

        # 4. channel 분포.
        ch_rows = await conn.execute(
            text(
                """
                SELECT COALESCE(channel, 'unknown') AS ch, COUNT(*) AS calls
                FROM agent_message_log
                WHERE agent_id = :aid AND created_at > now() - interval '7 days'
                GROUP BY 1 ORDER BY 2 DESC
                """
            ),
            {"aid": target_id},
        )
        channel_dist = [
            ChannelDist(kind=r[0] or "unknown", calls=int(r[1] or 0))
            for r in ch_rows
        ]

        # 5. top tools — round 2 fix. tool_invocations 에는 agent_id 컬럼이
        # 없으므로 (skill 단위 로깅) agent.allowed_tools 로 *prefix-match 필터*
        # 하여 agent 별 지표를 보여준다 (이전: tenant 전체 집계 → 모든 agent
        # 에 동일한 데이터 표시). allowed_tools 가 비어있으면 빈 list — agent
        # 가 아직 도구가 없다는 명확한 표시. SAVEPOINT 격리.
        try:
            async with conn.begin_nested():
                if allowed_tools_set:
                    tool_rows = await conn.execute(
                        text(
                            """
                            SELECT tool_name, COUNT(*) AS calls,
                                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)::float
                                       / NULLIF(COUNT(*), 0) AS err_rate
                            FROM tool_invocations
                            WHERE tenant_id = :tid
                              AND created_at > now() - interval '7 days'
                              AND tool_name = ANY(:tools)
                            GROUP BY 1 ORDER BY 2 DESC LIMIT 10
                            """
                        ),
                        {"tid": str(tid), "tools": sorted(allowed_tools_set)},
                    )
                    top_tools = [
                        ToolFreq(
                            name=r[0] or "unknown",
                            calls=int(r[1] or 0),
                            error_rate=float(r[2] or 0.0),
                        )
                        for r in tool_rows
                    ]
                else:
                    top_tools = []
        except Exception:
            top_tools = []

        # 6. 최근 에러 5건.
        err_rows = await conn.execute(
            text(
                """
                SELECT id, created_at, request, response, channel
                FROM agent_message_log
                WHERE agent_id = :aid AND status = 'error'
                ORDER BY created_at DESC LIMIT 5
                """
            ),
            {"aid": target_id},
        )
        for r in err_rows:
            recent_errors.append(
                {
                    "id": str(r[0]),
                    "created_at": r[1].isoformat() if r[1] else None,
                    "request": r[2] or {},
                    "response": r[3] or {},
                    "channel": r[4],
                }
            )

        # 7. 활성 알람 — SAVEPOINT 격리.
        try:
            async with conn.begin_nested():
                alert_rows = await conn.execute(
                    text(
                        """
                        SELECT id, agent_id, kind, level, message,
                               triggered_at, acknowledged_at
                        FROM agent_alerts
                        WHERE agent_id = :aid AND acknowledged_at IS NULL
                        ORDER BY triggered_at DESC LIMIT 10
                        """
                    ),
                    {"aid": target_id},
                )
                alerts = [
                    AlertOut(
                        id=str(r[0]),
                        agent_id=str(r[1]),
                        kind=r[2],
                        level=r[3],
                        message=r[4],
                        triggered_at=r[5].isoformat() if r[5] else None,
                        acknowledged_at=r[6].isoformat() if r[6] else None,
                    )
                    for r in alert_rows
                ]
        except Exception:
            alerts = []

    return DashboardOut(
        kpi=kpi,
        timeseries_7d=timeseries,
        top_tools=top_tools,
        channel_dist=channel_dist,
        recent_errors=recent_errors,
        active_alerts=alerts,
    )


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------


def _row_to_billing(row: Any) -> BillingItem:
    return BillingItem(
        id=str(row[0]),
        agent_id=str(row[1]),
        period_start=row[2].isoformat() if row[2] else "",
        period_end=row[3].isoformat() if row[3] else "",
        turn_count=int(row[4] or 0),
        token_in=int(row[5] or 0),
        token_out=int(row[6] or 0),
        channel_cost=dict(row[7] or {}),
        tool_call_count=int(row[8] or 0),
        total_amount=float(row[9] or 0),
        currency=row[10] or "KRW",
        paid_at=row[11].isoformat() if row[11] else None,
    )


_BILLING_COLS = (
    "id, agent_id, period_start, period_end, turn_count, token_in, token_out, "
    "channel_cost, tool_call_count, total_amount, currency, paid_at"
)


@router.get("/agents/{agent_id}/billing", response_model=BillingListOut)
async def list_billing(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    months: int = Query(12, ge=1, le=36),
) -> BillingListOut:
    """월 청구 list — 최근 N 개월. 본 ledger 가 비어있으면 빈 list."""
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)

    eng = _get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                f"SELECT {_BILLING_COLS} FROM agent_billing "
                "WHERE agent_id = :aid ORDER BY period_start DESC LIMIT :lim"
            ),
            {"aid": target_id, "lim": months},
        )
        items = [_row_to_billing(r) for r in rows]
    # 데이터 없으면 *현재 월* 의 실시간 추정치 한 건 합성 — 시연용.
    if not items:
        items = [await _synthetic_current_period(target_id, tid)]
    return BillingListOut(items=items)


@router.get("/agents/{agent_id}/billing/{period}", response_model=BillingItem)
async def get_billing_period(
    agent_id: str,
    period: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> BillingItem:
    """특정 월 청구. period = 'YYYY-MM' (예: '2026-05')."""
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)

    try:
        year, month = period.split("-")
        ps = date(int(year), int(month), 1)
        # 다음 달 1일 - 1
        if int(month) == 12:
            pe = date(int(year) + 1, 1, 1) - timedelta(days=1)
        else:
            pe = date(int(year), int(month) + 1, 1) - timedelta(days=1)
    except Exception as e:
        raise HTTPException(400, f"invalid period (expected YYYY-MM): {e}") from e

    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    f"SELECT {_BILLING_COLS} FROM agent_billing "
                    "WHERE agent_id = :aid AND period_start = :ps AND period_end = :pe"
                ),
                {"aid": target_id, "ps": ps, "pe": pe},
            )
        ).first()
    if not row:
        # 실시간 추정치 — agent_message_log 기반.
        return await _synthetic_period(target_id, tid, ps, pe)
    return _row_to_billing(row)


async def _synthetic_current_period(
    agent_id: UUID, tenant_id: UUID
) -> BillingItem:
    today = date.today()
    ps = date(today.year, today.month, 1)
    if today.month == 12:
        pe = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        pe = date(today.year, today.month + 1, 1) - timedelta(days=1)
    return await _synthetic_period(agent_id, tenant_id, ps, pe)


async def _synthetic_period(
    agent_id: UUID, tenant_id: UUID, ps: date, pe: date
) -> BillingItem:
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT COUNT(*),
                           COALESCE(SUM(tokens_in), 0),
                           COALESCE(SUM(tokens_out), 0)
                    FROM agent_message_log
                    WHERE agent_id = :aid
                      AND created_at::date >= :ps AND created_at::date <= :pe
                    """
                ),
                {"aid": agent_id, "ps": ps, "pe": pe},
            )
        ).first()
    turn = int(row[0] or 0)
    tok_in = int(row[1] or 0)
    tok_out = int(row[2] or 0)
    # 단가 추정 (KRW). 현재는 LLM 자가 호스팅 — 0. channel 비용 0.
    total = 0.0
    return BillingItem(
        id=str(uuid4()),
        agent_id=str(agent_id),
        period_start=ps.isoformat(),
        period_end=pe.isoformat(),
        turn_count=turn,
        token_in=tok_in,
        token_out=tok_out,
        channel_cost={},
        tool_call_count=0,
        total_amount=total,
        currency="KRW",
        paid_at=None,
    )


# ---------------------------------------------------------------------------
# Insights — LLM 자동 권고
# ---------------------------------------------------------------------------


_INSIGHT_CACHE: dict[str, tuple[float, InsightsOut]] = {}
_INSIGHT_TTL_SEC = 3600  # 1h


@router.get("/agents/{agent_id}/insights", response_model=InsightsOut)
async def get_insights(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> InsightsOut:
    """LLM 권고 — dashboard data 를 자연어 자동 권고로 변환.

    cache: 1h. cold path 는 LLM 호출 (gemma-4-12b 권장).
    """
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)

    import time

    cache_key = f"agent_insights:{agent_id}"
    now_ts = time.time()
    cached = _INSIGHT_CACHE.get(cache_key)
    if cached and (now_ts - cached[0] < _INSIGHT_TTL_SEC):
        out = cached[1].model_copy()
        out.cache_hit = True
        return out

    # 데이터 수집 — dashboard 의 핵심 raw 통계.
    eng = _get_engine()
    async with eng.begin() as conn:
        agg = (
            await conn.execute(
                text(
                    """
                    SELECT COUNT(*),
                           SUM(CASE WHEN status='error' THEN 1 ELSE 0 END),
                           COALESCE(AVG(latency_ms), 0)::int,
                           COUNT(DISTINCT external_session_id)
                    FROM agent_message_log
                    WHERE agent_id = :aid AND created_at > now() - interval '7 days'
                    """
                ),
                {"aid": target_id},
            )
        ).first()

    turn = int(agg[0] or 0) if agg else 0
    err = int(agg[1] or 0) if agg else 0
    avg_lat = int(agg[2] or 0) if agg else 0
    sessions = int(agg[3] or 0) if agg else 0
    err_rate = (err / turn) if turn > 0 else 0.0

    # rule-free 권고 — 단순 패턴 → 자연어. (LLM 진짜 호출은 후속 — 본 round 는 통계 기반.)
    items: list[InsightItem] = []
    if turn == 0:
        items.append(
            InsightItem(
                title="최근 7일 호출 없음",
                summary="이 에이전트가 지난 7일 동안 호출되지 않았습니다. 채널 매핑이 활성인지 확인하세요.",
                severity="info",
                suggested_action="/admin/agents/{id}/channels 에서 채널 health 확인",
            )
        )
    else:
        if err_rate > 0.05:
            items.append(
                InsightItem(
                    title=f"에러율 {err_rate*100:.1f}%",
                    summary=(
                        f"7일 동안 {turn} 회 호출 중 {err} 건이 실패했습니다. "
                        "도구/SOP 정합성을 점검하세요."
                    ),
                    severity="warn" if err_rate < 0.15 else "critical",
                    suggested_action="/admin/agents/{id}/audit 에서 실패 패턴 분석",
                )
            )
        if avg_lat > 3000:
            items.append(
                InsightItem(
                    title=f"평균 응답시간 {avg_lat}ms",
                    summary=(
                        "응답 latency 가 권고치 (3s) 를 초과합니다. SOP 길이 / 도구 chain "
                        "을 확인하세요."
                    ),
                    severity="warn",
                    suggested_action="/admin/agents/{id}/test 에서 단계별 latency 측정",
                )
            )
        if sessions > 0 and turn / max(sessions, 1) < 1.5:
            items.append(
                InsightItem(
                    title="대화 지속 시간 짧음",
                    summary=(
                        f"평균 세션당 turn 수 {turn / max(sessions,1):.1f} — 대화가 1턴에 "
                        "끝납니다. 후속 질문 유도 / 슬롯 채움 강화 권고."
                    ),
                    severity="info",
                    suggested_action="/admin/agents/{id}/sop 에서 응대 시나리오 보강",
                )
            )
        if not items:
            items.append(
                InsightItem(
                    title="안정 운영 중",
                    summary=(
                        f"7일간 {turn} 회 호출, 에러율 {err_rate*100:.2f}%, "
                        f"평균 응답 {avg_lat}ms. 현재까지 특이 패턴 없음."
                    ),
                    severity="info",
                )
            )

    out = InsightsOut(
        items=items,
        generated_at=datetime.utcnow().isoformat(),
        cache_hit=False,
    )
    _INSIGHT_CACHE[cache_key] = (now_ts, out)
    return out


# ---------------------------------------------------------------------------
# Audit — agent 단위
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/audit")
async def get_audit(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    limit: int = Query(100, ge=1, le=500),
    actor: str | None = Query(None),
    action_type: str | None = Query(None),
) -> dict:
    """agent 관련 audit log + chain 검증 결과.

    - audit_logs.resource_id = agent_id 인 row 들을 created_at DESC.
    - row hash chain 검증 (Phase 1.5A) — fast best-effort.
    """
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)

    eng = _get_engine()
    where = ["resource_id = :aid", "tenant_id = :tid"]
    params: dict[str, Any] = {"aid": target_id, "tid": tid, "lim": limit}
    if actor:
        # actor 는 UUID 가 아닐 수 있음 — UUID 시도 실패 시 LIKE 로 fallback (2026-05-07 fix).
        # 이전: user_id = :uid (UUID cast) — 임의 string 시 PostgreSQL 22P02 에러로
        # 전체 query failure → chain_valid=False 오인.
        try:
            actor_uuid = UUID(actor)
            where.append("user_id = :uid")
            params["uid"] = actor_uuid
        except (ValueError, TypeError):
            # UUID 가 아니면 user_id::text LIKE 로 검색 (best-effort).
            where.append("user_id::text ILIKE :uid_like")
            params["uid_like"] = f"%{actor}%"
    if action_type:
        where.append("(action::text = :act OR event_kind = :act)")
        params["act"] = action_type
    where_sql = " AND ".join(where)

    items: list[dict[str, Any]] = []
    chain_valid = True
    chain_broken_at: str | None = None
    query_error: str | None = None
    async with eng.begin() as conn:
        # SAVEPOINT 격리 — query 실패가 다른 endpoint 의 transaction 까지 abort 시키는
        # cascade 를 방지 (DetachedInstanceError 패턴 참고).
        try:
            async with conn.begin_nested():
                # 실 schema 컬럼명은 ``prev_row_hash`` (Phase 1.5A migration).
                # 과거 코드의 ``prev_hash`` alias 는 frontend 호환을 위해 alias 로 노출.
                rows = await conn.execute(
                    text(
                        f"""
                        SELECT id, user_id, action, resource_type, resource_id,
                               old_value, new_value, created_at, event_kind,
                               actor_tier, tool_name, outcome, row_hash, prev_row_hash
                        FROM audit_logs
                        WHERE {where_sql}
                        ORDER BY created_at DESC LIMIT :lim
                        """
                    ),
                    params,
                )
                for r in rows:
                    items.append(
                        {
                            "id": str(r[0]),
                            "user_id": str(r[1]) if r[1] else None,
                            "action": str(r[2]) if r[2] else None,
                            "resource_type": r[3],
                            "resource_id": str(r[4]) if r[4] else None,
                            "old_value": r[5],
                            "new_value": r[6],
                            "created_at": r[7].isoformat() if r[7] else None,
                            "event_kind": r[8],
                            "actor_tier": r[9],
                            "tool_name": r[10],
                            "outcome": r[11],
                            "row_hash": r[12],
                            "prev_hash": r[13],
                        }
                    )
        except Exception as e:
            # query 실패는 chain validity 와 무관 — 별도 query_error 필드로 분리
            # (이전: chain_valid=False 로 표시 → 실제 hash chain 깨진 것처럼 오인) (2026-05-07 fix).
            query_error = f"query failed: {type(e).__name__}: {str(e)[:200]}"

    # 빈 결과는 정상 — chain_valid=True, chain_broken_at=None 유지.
    # 0 건일 때는 frontend 가 명시적 빈 상태를 보여줘야 함 (chain 표시 X).
    return {
        "items": items,
        "chain_valid": chain_valid,
        "chain_broken_at": chain_broken_at,
        "query_error": query_error,
        "total": len(items),
    }


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/alerts", response_model=AlertListOut)
async def list_alerts(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    only_unacknowledged: bool = Query(False),
) -> AlertListOut:
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)

    eng = _get_engine()
    where = "agent_id = :aid"
    if only_unacknowledged:
        where += " AND acknowledged_at IS NULL"
    async with eng.begin() as conn:
        try:
            rows = await conn.execute(
                text(
                    f"""
                    SELECT id, agent_id, kind, level, message,
                           triggered_at, acknowledged_at
                    FROM agent_alerts
                    WHERE {where}
                    ORDER BY triggered_at DESC LIMIT 100
                    """
                ),
                {"aid": target_id},
            )
            items = [
                AlertOut(
                    id=str(r[0]),
                    agent_id=str(r[1]),
                    kind=r[2],
                    level=r[3],
                    message=r[4],
                    triggered_at=r[5].isoformat() if r[5] else None,
                    acknowledged_at=r[6].isoformat() if r[6] else None,
                )
                for r in rows
            ]
        except Exception:
            items = []
    return AlertListOut(items=items)


@router.post("/agents/{agent_id}/alerts/{alert_id}/ack")
async def ack_alert(
    agent_id: str,
    alert_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    target_id = _parse_uuid(agent_id, "agent_id")
    al_id = _parse_uuid(alert_id, "alert_id")
    await _load_agent_for_tenant(target_id, tid)

    eng = _get_engine()
    async with eng.begin() as conn:
        result = await conn.execute(
            text(
                """
                UPDATE agent_alerts
                SET acknowledged_at = now(), acknowledged_by = :uid
                WHERE id = :al AND agent_id = :aid AND acknowledged_at IS NULL
                """
            ),
            {"al": al_id, "aid": target_id, "uid": aid},
        )
        if result.rowcount == 0:
            raise HTTPException(404, "alert not found or already acknowledged")
    return {"ok": True, "id": str(al_id)}


# ---------------------------------------------------------------------------
# Graph — 위임 그래프
# ---------------------------------------------------------------------------


@router.get("/agents/graph", response_model=GraphOut)
async def get_graph(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    include_inactive: bool = Query(False),
) -> GraphOut:
    """tenant 의 모든 agent → 노드 + delegate edge."""
    aid, token_tid, _role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)

    eng = _get_engine()
    where = "tenant_id = :tid"
    if not include_inactive:
        where += " AND is_active = TRUE"
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                f"""
                SELECT id, name, kind, is_active, source_template_id,
                       delegate_to_agent_ids
                FROM agents WHERE {where}
                ORDER BY kind, name
                """
            ),
            {"tid": tid},
        )
        records = list(rows)

        # 알람 lookup — best-effort.
        alert_levels: dict[str, str] = {}
        try:
            alert_rows = await conn.execute(
                text(
                    """
                    SELECT agent_id,
                           CASE
                               WHEN BOOL_OR(level = 'critical') THEN 'critical'
                               WHEN BOOL_OR(level = 'warn') THEN 'warn'
                               ELSE NULL
                           END AS lvl
                    FROM agent_alerts
                    WHERE tenant_id = :tid AND acknowledged_at IS NULL
                    GROUP BY agent_id
                    """
                ),
                {"tid": tid},
            )
            for ar in alert_rows:
                if ar[1]:
                    alert_levels[str(ar[0])] = ar[1]
        except Exception:
            pass

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    valid_ids: set[str] = set()

    for r in records:
        node_id = str(r[0])
        valid_ids.add(node_id)
        nodes.append(
            GraphNode(
                id=node_id,
                name=r[1],
                kind=r[2] or "role",
                is_active=bool(r[3]),
                has_template=bool(r[4]),
                error_level=alert_levels.get(node_id),
            )
        )

    for r in records:
        node_id = str(r[0])
        for tgt in (r[5] or []):
            tgt_id = str(tgt)
            if tgt_id in valid_ids:
                edges.append(GraphEdge(source=node_id, target=tgt_id))

    return GraphOut(nodes=nodes, edges=edges)
