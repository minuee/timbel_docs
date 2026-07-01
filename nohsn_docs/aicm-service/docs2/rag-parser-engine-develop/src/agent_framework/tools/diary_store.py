"""일기장 저장소 — Redis (legacy) / KMS documents (Stage B-3) dual backend.

env ``AGENT_DATA_STORE`` 로 백엔드 선택:
- ``redis`` (기본, 하위호환) — 기존 ``_redis_store`` 리스트에 JSON entry 저장.
- ``kms``               — KMS ``documents`` 테이블에 한 entry = 한 document.

KMS 경로는 tenant 격리를 위해 ``tenant_id`` (UUID string) 를 args 에서 요구한다.
Engine 의 ``_resolve_args`` 가 ``$personal_tenant_id`` 치환을 제공.

search 는 ``agent_document_store.list_items_filtered`` 로 위임 —
body.emotion equality + body.text substring + 최신순 정렬.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from typing import Any
from uuid import UUID

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools import _redis_store as rs
from src.agent_framework.tools.schedule_store import _get_shared_engine

_CATEGORY = "diary"
_DOCUMENT_TYPE = "agent_diary"


def _store_mode() -> str:
    """``AGENT_DATA_STORE`` 환경 변수 읽기 (redis | kms). 기본 redis."""
    return os.environ.get("AGENT_DATA_STORE", "redis").lower()


def _owner_agent_uuid(args: dict[str, Any]) -> UUID | None:
    """D23 §1 (2026-05-08) — args["agent_id"] → UUID. 빈 값 / 비-UUID → None."""
    raw = args.get("agent_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _resolve_null_owner_arg(args: dict[str, Any]) -> Any:
    """D23 §7 — engine sentinel 만 storage 로 forward."""
    sentinel = args.get("_admin_null_owner_sentinel")
    if sentinel is agent_document_store.ADMIN_NULL_OWNER_OK:
        return agent_document_store.ADMIN_NULL_OWNER_OK
    return False


def _reset() -> None:
    """하위 호환 sync 인터페이스 — conftest async fixture 가 실제 flush."""
    rs._reset_sync()


# ── Idempotency helper (PR-E1 — schedule_store 패턴 확산) ──────────────


def _dedup_signature(date: Any, text: Any) -> str:
    """``(date, text 첫 120자)`` 정규화 해시. 같은 날짜에 동일 본문 entry 중복 차단."""
    norm_date = str(date or "").strip()
    norm_text = str(text or "").strip().lower()[:120]
    raw = f"{norm_date}|{norm_text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _duplicate_response(existing_id: str) -> dict[str, Any]:
    return {
        "id": existing_id,
        "success": True,
        "duplicate": True,
        "summary": "이미 기록된 일기입니다",
    }


# ── Public tool entry points ─────────────────────────────────────────


async def save(args: dict[str, Any]) -> dict[str, Any]:
    """일기 저장.

    KMS 모드에서는 ``tenant_id`` (UUID string) 를 args 에서 받는다. Redis 모드는
    기존 ``phone`` scope 를 유지.

    PR-E1 — ``(scope, date, text)`` 동일 시 silent skip + duplicate 플래그.

    date 기본값 (2026-04-28) — slot_filler 가 entry_date 를 못 채워 None 으로
    오면 오늘 날짜로 fallback. 사용자가 명시 안 하면 작성일 = 오늘 이라는
    자연스러운 기본값.
    """
    import datetime as _dt
    if not args.get("date"):
        args = dict(args)
        args["date"] = _dt.date.today().isoformat()
    sig = _dedup_signature(args.get("date"), args.get("entry_text"))

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {
                "success": False,
                "error": "tenant_id required when AGENT_DATA_STORE=kms",
            }
        scope_group = args.get("scope_group") or "personal"
        owner_agent_uuid = _owner_agent_uuid(args)
        try:
            existing = await agent_document_store.list_items(
                _get_shared_engine(),
                UUID(str(tenant_id)),
                _DOCUMENT_TYPE,
                scope_group=scope_group,
                owner_agent_id=owner_agent_uuid,
            )
        except Exception:
            existing = []
        for it in existing:
            if _dedup_signature(it.get("date"), it.get("text")) == sig:
                return _duplicate_response(str(it.get("id", "")))

        date = args.get("date")
        title = f"{date} 일기" if date else "일기"
        try:
            doc_id = await agent_document_store.create_item(
                _get_shared_engine(),
                UUID(str(tenant_id)),
                _DOCUMENT_TYPE,
                title=title,
                body={
                    "text": args["entry_text"],
                    "emotion": args.get("emotion"),
                    "date": date,
                },
                scope_group=scope_group,
                owner_agent_id=owner_agent_uuid,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        return {
            "id": str(doc_id),
            "success": True,
            "scope_group": scope_group,
            "owner_agent_id": str(owner_agent_uuid) if owner_agent_uuid else None,
        }

    # DEPRECATED (D24 §2, 2026-05-08) — agent 격리 X.
    # AGENT_DATA_STORE=kms 권장. 후속 제거 plan: D25.
    # redis (legacy)
    phone = args["phone"]
    try:
        existing = await rs.list_items(_CATEGORY, phone)
    except Exception:
        existing = []
    for it in existing:
        if _dedup_signature(it.get("date"), it.get("text")) == sig:
            return _duplicate_response(str(it.get("id", "")))

    entry = {
        "id": str(uuid.uuid4()),
        "date": args.get("date"),
        "text": args["entry_text"],
        "emotion": args.get("emotion"),
    }
    await rs.rpush_item(_CATEGORY, phone, entry)
    return {"id": entry["id"], "success": True}


async def update(args: dict[str, Any]) -> dict[str, Any]:
    """일기 수정 — id + 변경 필드 (entry_text / emotion / date). redis/kms 양쪽."""
    item_id = args.get("id")
    if not item_id:
        return {"success": False, "error": "id required"}
    tenant_id = args.get("tenant_id")
    if _store_mode() != "kms":
        phone = args.get("phone")
        if not phone:
            return {"success": False, "error": "phone required (redis mode)"}
        items = await rs.list_items(_CATEGORY, phone)
        new_items = []
        found = False
        for it in items:
            if str(it.get("id")) == str(item_id):
                merged = {**it}
                if args.get("entry_text") is not None:
                    merged["text"] = args["entry_text"]
                if args.get("emotion") is not None:
                    merged["emotion"] = args["emotion"]
                if args.get("date") is not None:
                    merged["date"] = args["date"]
                new_items.append(merged)
                found = True
            else:
                new_items.append(it)
        if not found:
            return {"success": False, "error": "not found"}
        await rs.replace_items(_CATEGORY, phone, new_items)
        return {"success": True}

    if not tenant_id:
        return {"success": False, "error": "tenant_id required (kms mode)"}
    body_patch: dict[str, Any] = {}
    if args.get("entry_text") is not None:
        body_patch["text"] = args["entry_text"]
    if args.get("emotion") is not None:
        body_patch["emotion"] = args["emotion"]
    if args.get("date") is not None:
        body_patch["date"] = args["date"]
    new_title = (
        f"{args['date']} 일기" if args.get("date") else None
    )
    owner_agent_uuid = _owner_agent_uuid(args)
    ok = await agent_document_store.update_item(
        _get_shared_engine(),
        UUID(str(tenant_id)),
        _DOCUMENT_TYPE,
        str(item_id),
        title=new_title,
        body_patch=body_patch or None,
        owner_agent_id=owner_agent_uuid,
    )
    if not ok:
        return {"success": False, "error": "not found"}
    return {"success": True}


async def search(args: dict[str, Any]) -> dict[str, Any]:
    """일기 검색 — query substring (body.text) + emotion equality, 최신순."""
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {
                "hits": [],
                "error": "tenant_id required when AGENT_DATA_STORE=kms",
            }
        top_k = int(args.get("top_k", 10))
        body_equals: dict[str, Any] | None = None
        emo = args.get("emotion")
        if emo:
            body_equals = {"emotion": emo}
        body_text_contains: tuple[str, str] | None = None
        q = args.get("query")
        if q:
            body_text_contains = ("text", str(q))
        owner_agent_uuid = _owner_agent_uuid(args)
        include_null_arg = _resolve_null_owner_arg(args)
        items = await agent_document_store.list_items_filtered(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            body_equals=body_equals,
            body_text_contains=body_text_contains,
            order_desc=True,
            limit=top_k,
            scope_group=args.get("scope_group"),
            owner_agent_id=owner_agent_uuid,
            include_null_owner=include_null_arg,
        )
        return {"hits": items}

    # DEPRECATED (D24 §2, 2026-05-08) — agent 격리 X.
    # AGENT_DATA_STORE=kms 권장. 후속 제거 plan: D25.
    # redis (legacy)
    phone = args["phone"]
    q = (args.get("query") or "").lower()
    emo = args.get("emotion")
    top_k = int(args.get("top_k", 10))
    entries = await rs.list_items(_CATEGORY, phone)
    hits = [
        e for e in entries
        if (q in e["text"].lower() if q else True)
        and (e.get("emotion") == emo if emo else True)
    ]
    # 최신 (삽입 순서 역순) 우선
    hits = list(reversed(hits))[:top_k]
    return {"hits": hits}


async def delete(args: dict[str, Any]) -> dict[str, Any]:
    """data_api.delete_diary 전용 — phone + id 로 일기 삭제 (KMS 모드는 soft delete)."""
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"success": False, "error": "tenant_id required when AGENT_DATA_STORE=kms"}
        owner_agent_uuid = _owner_agent_uuid(args)
        ok = await agent_document_store.delete_item(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            args["id"],
            owner_agent_id=owner_agent_uuid,
        )
        return {"success": ok}

    ok = await rs.remove_by_id(_CATEGORY, args["phone"], args["id"])
    return {"success": ok}
