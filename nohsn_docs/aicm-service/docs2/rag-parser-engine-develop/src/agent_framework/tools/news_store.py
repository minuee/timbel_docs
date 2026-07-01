"""뉴스 구독·보고서 저장소 — Redis (legacy) / KMS documents (Stage B-4) dual backend.

env ``AGENT_DATA_STORE`` 로 백엔드 선택:
- ``redis`` (기본, 하위호환) — 기존 ``_redis_store`` hash/list 에 JSON 저장.
- ``kms``               — KMS ``documents`` 테이블에서 구독 = ``agent_news_sub``,
  보고서 = ``agent_news_report`` 타입 document.

KMS 경로는 tenant 격리를 위해 ``tenant_id`` (UUID string) 를 args 에서 요구한다.
Engine 의 ``_resolve_args`` 가 ``$personal_tenant_id`` 치환을 제공.

- scheduled trigger 가 호출하는 ``list_subscribers`` 는 cross-tenant — KMS 모드에서는
  ``agent_document_store.list_tenants_with_doctype("agent_news_sub")`` 로 distinct tenant
  목록을 얻고, 호출측 (engine._fire_scheduled_skill) 이 phone 이 아닌 tenant_id 를
  루프 scope 로 쓴다.
"""
from __future__ import annotations

import datetime
import os
from typing import Any
from uuid import UUID

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools import _redis_store as rs
from src.agent_framework.tools.schedule_store import _get_shared_engine

_SUB_CATEGORY = "news_sub"
_REPORT_CATEGORY = "news_reports"
_DEFAULT_SUB: dict[str, Any] = {"topics": [], "channel": "web"}

_DOCUMENT_TYPE_SUB = "agent_news_sub"
_DOCUMENT_TYPE_REPORT = "agent_news_report"


def _store_mode() -> str:
    """``AGENT_DATA_STORE`` 환경 변수 읽기 (redis | kms). 기본 redis."""
    return os.environ.get("AGENT_DATA_STORE", "redis").lower()


def _reset() -> None:
    """하위 호환 sync 인터페이스 — conftest async fixture 가 실제 flush."""
    rs._reset_sync()


# ── Public tool entry points ─────────────────────────────────────────


async def add_subscription(args: dict[str, Any]) -> dict[str, Any]:
    """구독 주제 추가.

    KMS 모드에서는 topic 을 한 document 로 저장 (중복 topic 은 생성 skip).
    Redis 모드는 기존 hash 안의 topics 리스트에 append.
    """
    topic = args["topic"]

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {
                "success": False,
                "topics": [],
                "error": "tenant_id required when AGENT_DATA_STORE=kms",
            }
        eng = _get_shared_engine()
        tid = UUID(str(tenant_id))
        # 중복 topic 체크 — body.topic equality 로 existing doc 조회.
        existing = await agent_document_store.list_items_filtered(
            eng,
            tid,
            _DOCUMENT_TYPE_SUB,
            body_equals={"topic": topic},
        )
        was_duplicate = bool(existing)
        if not existing:
            await agent_document_store.create_item(
                eng,
                tid,
                _DOCUMENT_TYPE_SUB,
                title=f"구독: {topic}",
                body={
                    "topic": topic,
                    "channel": "web",
                    "added_at": datetime.datetime.utcnow().isoformat(timespec="seconds"),
                },
            )
        # 반환은 현재 구독 topic 전체
        all_items = await agent_document_store.list_items(eng, tid, _DOCUMENT_TYPE_SUB)
        topics = [i.get("topic") for i in all_items if i.get("topic")]
        # PR-E1 — duplicate 명시. tool_result summary 가 사용자에게 즉시 노출.
        resp: dict[str, Any] = {"success": True, "topics": topics}
        if was_duplicate:
            resp["duplicate"] = True
            resp["summary"] = "이미 구독 중인 주제입니다"
        return resp

    # DEPRECATED (D24 §2, 2026-05-08) — agent 격리 X.
    # AGENT_DATA_STORE=kms 권장. 후속 제거 plan: D25.
    # redis (legacy)
    phone = args["phone"]
    sub = await rs.hash_get(_SUB_CATEGORY, phone)
    if not sub:
        sub = dict(_DEFAULT_SUB)
    topics = list(sub.get("topics") or [])
    was_duplicate = topic in topics
    if not was_duplicate:
        topics.append(topic)
    sub["topics"] = topics
    sub.setdefault("channel", "web")
    await rs.hash_set(_SUB_CATEGORY, phone, sub)
    resp = {"success": True, "topics": list(topics)}
    if was_duplicate:
        resp["duplicate"] = True
        resp["summary"] = "이미 구독 중인 주제입니다"
    return resp


async def remove_subscription(args: dict[str, Any]) -> dict[str, Any]:
    """구독 주제 제거. KMS 모드는 soft delete."""
    topic = args["topic"]

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {
                "success": False,
                "topics": [],
                "error": "tenant_id required when AGENT_DATA_STORE=kms",
            }
        eng = _get_shared_engine()
        tid = UUID(str(tenant_id))
        # 해당 topic 의 existing doc 을 찾아 delete_item.
        matched = await agent_document_store.list_items_filtered(
            eng,
            tid,
            _DOCUMENT_TYPE_SUB,
            body_equals={"topic": topic},
        )
        for doc in matched:
            await agent_document_store.delete_item(
                eng, tid, _DOCUMENT_TYPE_SUB, doc["id"]
            )
        remaining = await agent_document_store.list_items(eng, tid, _DOCUMENT_TYPE_SUB)
        topics = [i.get("topic") for i in remaining if i.get("topic")]
        return {"success": True, "topics": topics}

    # redis
    phone = args["phone"]
    sub = await rs.hash_get(_SUB_CATEGORY, phone)
    if not sub:
        return {"success": True, "topics": []}
    topics = list(sub.get("topics") or [])
    if topic in topics:
        topics.remove(topic)
    sub["topics"] = topics
    await rs.hash_set(_SUB_CATEGORY, phone, sub)
    return {"success": True, "topics": list(topics)}


async def list_subscriptions(args: dict[str, Any]) -> dict[str, Any]:
    """현재 구독 상태 조회 — mock 과 동일 shape: ``{"subscription": {topics, channel}}``."""
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {
                "subscription": dict(_DEFAULT_SUB),
                "error": "tenant_id required when AGENT_DATA_STORE=kms",
            }
        eng = _get_shared_engine()
        tid = UUID(str(tenant_id))
        items = await agent_document_store.list_items(eng, tid, _DOCUMENT_TYPE_SUB)
        topics = [i.get("topic") for i in items if i.get("topic")]
        # channel 은 첫 doc 의 값 (모두 동일 channel 가정); 없으면 기본 web.
        channel = "web"
        for i in items:
            if i.get("channel"):
                channel = i["channel"]
                break
        return {"subscription": {"topics": topics, "channel": channel}}

    # redis
    phone = args["phone"]
    sub = await rs.hash_get(_SUB_CATEGORY, phone)
    if not sub:
        sub = dict(_DEFAULT_SUB)
    return {"subscription": sub}


async def fetch_and_summarize(args: dict[str, Any]) -> dict[str, Any]:
    """scheduled trigger 가 호출. 실제로는 news API 호출 + LLM 요약이지만
    v1 mock 은 구독 주제 echo + 가상 요약.

    생성된 요약은 KMS 모드에서 ``agent_news_report`` document 로 저장되고
    Redis 모드에서는 기존 list 로 push.
    """
    today = args.get("today") or datetime.date.today().isoformat()

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {
                "summary": "tenant_id required when AGENT_DATA_STORE=kms",
                "topics": [],
                "error": "tenant_id required when AGENT_DATA_STORE=kms",
            }
        eng = _get_shared_engine()
        tid = UUID(str(tenant_id))
        items = await agent_document_store.list_items(eng, tid, _DOCUMENT_TYPE_SUB)
        topics = [i.get("topic") for i in items if i.get("topic")]
        summary = (
            f"오늘 {', '.join(topics)} 관련 주요 이슈 3건 발생."
            if topics
            else "구독 주제가 설정되지 않았습니다. 'AI 스타트업 뉴스 구독' 같이 말씀해 주세요."
        )
        # topics 가 하나면 해당 topic, 여러 개면 첫 topic 을 title 에 대표.
        title_topic = topics[0] if topics else "구독없음"
        await agent_document_store.create_item(
            eng,
            tid,
            _DOCUMENT_TYPE_REPORT,
            title=f"{today} {title_topic} 요약",
            body={"date": today, "summary": summary, "topics": list(topics)},
        )
        return {"summary": summary, "topics": list(topics)}

    # redis
    phone = args["phone"]
    sub = await rs.hash_get(_SUB_CATEGORY, phone)
    topics = list((sub or {}).get("topics") or [])
    summary = (
        f"오늘 {', '.join(topics)} 관련 주요 이슈 3건 발생."
        if topics
        else "구독 주제가 설정되지 않았습니다. 'AI 스타트업 뉴스 구독' 같이 말씀해 주세요."
    )
    report = {"date": today, "summary": summary, "topics": list(topics)}
    await rs.rpush_item(_REPORT_CATEGORY, phone, report)
    return {"summary": summary, "topics": list(topics)}


async def list_recent_reports(args: dict[str, Any]) -> dict[str, Any]:
    """최근 요약 리포트 — 최신 10건.

    KMS 모드는 ``list_items_filtered(order_desc=True, limit=10)``.
    Redis 모드는 기존 list 전체 (append 순, 호출측이 reverse 필요).
    """
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {
                "reports": [],
                "error": "tenant_id required when AGENT_DATA_STORE=kms",
            }
        eng = _get_shared_engine()
        tid = UUID(str(tenant_id))
        items = await agent_document_store.list_items_filtered(
            eng,
            tid,
            _DOCUMENT_TYPE_REPORT,
            order_desc=True,
            limit=10,
        )
        return {"reports": items}

    # redis
    phone = args["phone"]
    reports = await rs.list_items(_REPORT_CATEGORY, phone)
    return {"reports": reports}


async def list_subscribers() -> list[str]:
    """모든 구독자 scope key 목록 — scheduled trigger 가 fan-out 할 때 사용.

    Redis 모드: phone 목록.
    KMS 모드: ``agent_news_sub`` 를 하나라도 가진 tenant_id 목록 (string). 엔진은
    모드에 따라 phone vs tenant_id 를 구분하지 않고 이 값을 scope key 로 루프 돌린다.
    """
    if _store_mode() == "kms":
        tenants = await agent_document_store.list_tenants_with_doctype(
            _get_shared_engine(), _DOCUMENT_TYPE_SUB
        )
        return [str(t) for t in tenants]

    client = await rs._get_client()
    prefix = f"agent_mock:{_SUB_CATEGORY}:"
    phones: list[str] = []
    async for key in client.scan_iter(match=f"{prefix}*"):
        phones.append(key[len(prefix):])
    return phones
