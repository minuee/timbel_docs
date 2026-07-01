"""KMS-Plus 데이터 API — 프런트 사이드 패널 (일정/일기/뉴스) 용 CRUD.

/agent/chat 으로 생성된 데이터를 UI 에서 조회·편집·삭제. 채팅 없이 직접 추가도 지원.
v1 은 mock 저장소 (메모리) 를 그대로 노출. Phase 2 에서 Postgres 로 교체.

Stage B-2/B-3/B-4: schedule·diary·news 는 ``AGENT_DATA_STORE=kms`` 시 KMS documents
경로를 탄다. 이 REST 라우터는 phone 만 받으므로 KMS 모드에서는 account →
personal_tenant_id 를 내부에서 resolve 해 store 에 같이 넘긴다.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.agent_framework.tools import schedule_store, diary_store, news_store

router = APIRouter(prefix="/agent/data", tags=["agent-data"])


async def _resolve_personal_tenant_for_kms(phone: str) -> str | None:
    """KMS 모드일 때만 phone → personal_tenant_id 조회.

    Redis 모드에서는 None 반환해 phone scope 만 사용하던 기존 경로 유지.
    """
    if os.environ.get("AGENT_DATA_STORE", "redis").lower() != "kms":
        return None
    # 지연 import — Redis-only 배포에서 DB 의존성을 import-time 에 끌지 않도록.
    from src.agent_framework.core.accounts import get_or_create_account

    ctx = await get_or_create_account(phone=phone)
    return str(ctx.personal_tenant_id)


# ── 일정 ──────────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    phone: str
    title: str
    when: str
    recurrence: str | None = None


@router.get("/schedules")
async def list_schedules(phone: str = Query(..., description="전화번호로 스코프")):
    args: dict = {"phone": phone}
    tid = await _resolve_personal_tenant_for_kms(phone)
    if tid:
        args["tenant_id"] = tid
    return await schedule_store.list_all(args)


@router.post("/schedules")
async def create_schedule(body: ScheduleCreate):
    args = body.model_dump()
    tid = await _resolve_personal_tenant_for_kms(body.phone)
    if tid:
        args["tenant_id"] = tid
    return await schedule_store.create(args)


@router.delete("/schedules/{sid}")
async def delete_schedule(sid: str, phone: str = Query(...)):
    args: dict = {"phone": phone, "id": sid}
    tid = await _resolve_personal_tenant_for_kms(phone)
    if tid:
        args["tenant_id"] = tid
    return await schedule_store.delete(args)


# ── 일기 ──────────────────────────────────────────────────────────────

class DiaryCreate(BaseModel):
    phone: str
    entry_text: str
    emotion: str | None = None
    date: str | None = None


@router.get("/diaries")
async def list_diaries(
    phone: str = Query(...),
    emotion: str | None = None,
    query: str = "",
    top_k: int = 50,
):
    args: dict = {
        "phone": phone,
        "query": query,
        "emotion": emotion,
        "top_k": top_k,
    }
    tid = await _resolve_personal_tenant_for_kms(phone)
    if tid:
        args["tenant_id"] = tid
    return await diary_store.search(args)


@router.post("/diaries")
async def create_diary(body: DiaryCreate):
    args = body.model_dump()
    tid = await _resolve_personal_tenant_for_kms(body.phone)
    if tid:
        args["tenant_id"] = tid
    return await diary_store.save(args)


@router.delete("/diaries/{did}")
async def delete_diary(did: str, phone: str = Query(...)):
    args: dict = {"phone": phone, "id": did}
    tid = await _resolve_personal_tenant_for_kms(phone)
    if tid:
        args["tenant_id"] = tid
    r = await diary_store.delete(args)
    if not r.get("success"):
        raise HTTPException(404, f"diary {did} not found for phone")
    return r


# ── 뉴스 ──────────────────────────────────────────────────────────────

class NewsSubscribe(BaseModel):
    phone: str
    topic: str


@router.get("/news")
async def get_news_config(phone: str = Query(...)):
    """구독 설정 + 최근 보고서 모음."""
    args_sub: dict = {"phone": phone}
    args_rep: dict = {"phone": phone}
    tid = await _resolve_personal_tenant_for_kms(phone)
    if tid:
        args_sub["tenant_id"] = tid
        args_rep["tenant_id"] = tid
    sub = (await news_store.list_subscriptions(args_sub))["subscription"]
    reports = (await news_store.list_recent_reports(args_rep))["reports"]
    return {"subscription": sub, "recent_reports": reports}


@router.post("/news/subscriptions")
async def add_news_subscription(body: NewsSubscribe):
    args = body.model_dump()
    tid = await _resolve_personal_tenant_for_kms(body.phone)
    if tid:
        args["tenant_id"] = tid
    return await news_store.add_subscription(args)


@router.delete("/news/subscriptions")
async def remove_news_subscription(body: NewsSubscribe):
    args = body.model_dump()
    tid = await _resolve_personal_tenant_for_kms(body.phone)
    if tid:
        args["tenant_id"] = tid
    return await news_store.remove_subscription(args)
