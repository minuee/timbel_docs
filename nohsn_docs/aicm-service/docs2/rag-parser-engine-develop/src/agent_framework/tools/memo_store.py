"""메모/할일 저장소 — 캐주얼 캡처 + 마감 관리.

자비스 비전 — 사용자가 일상 중 흘리는 짧은 의무·약속 발화 ("아 맞다 내일까지
보고서 제출해야 돼. 2시 마감") 를 자동 캡처해 deadline + alarm + status
관리. schedule (캘린더 약속) 도 reminder (반복 알람) 도 아닌 *capture+todo*
도메인.

env ``AGENT_DATA_STORE``:
- ``redis`` (default) — phone-scoped 리스트.
- ``kms``               — agent_documents (tenant_id scoped, document_type=agent_memo).

Schema:
- id (UUID)
- title (str) — 핵심 명사구 ("보고서 제출", "약 복용", "선물 사기")
- note (str | None) — 부연 설명
- deadline_at (str ISO datetime | None) — 마감 시각
- alarm_at (str ISO datetime | None) — 알람 시각 (deadline 보다 일찍 권장)
- status (active | done | cancelled)
- raw_utterance (str) — 사용자 원 발화 (디버깅·재해석용)
- created_at (ISO)
- completed_at (ISO | None)

Idempotency: (scope, title 정규화, deadline_at) 동일 시 silent skip.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import uuid
from typing import Any
from uuid import UUID

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools import _redis_store as rs
from src.agent_framework.tools.schedule_store import _get_shared_engine

_CATEGORY = "memo"
_DOCUMENT_TYPE = "agent_memo"


def _store_mode() -> str:
    return os.environ.get("AGENT_DATA_STORE", "redis").lower()


def _reset() -> None:
    rs._reset_sync()


def _norm_title(t: Any) -> str:
    return str(t or "").strip().lower()


def _dedup_signature(title: Any, deadline_at: Any) -> str:
    raw = f"{_norm_title(title)}|{str(deadline_at or '')[:16]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _duplicate_response(existing_id: str, title: str | None, deadline_at: str | None) -> dict[str, Any]:
    detail_parts = []
    if title:
        detail_parts.append(title)
    if deadline_at:
        detail_parts.append(f"마감 {deadline_at}")
    detail = " · ".join(detail_parts)
    return {
        "id": existing_id,
        "success": True,
        "duplicate": True,
        "title": title,
        "deadline_at": deadline_at,
        "summary": (
            f"이미 기록된 메모입니다 — {detail}" if detail else "이미 기록된 메모입니다"
        ),
    }


# ── Public tool entry points ─────────────────────────────────────────


def _owner_agent_uuid(args: dict[str, Any]) -> UUID | None:
    """args["agent_id"] → UUID. 빈 값 / 비-UUID 는 None (legacy / admin 경로).

    D23 §1 (2026-05-08) — engine 의 _resolve_args_with_defaults 가 server-side
    inject. LLM payload 의 agent_id 도 같은 슬롯이지만 engine 이 항상 server
    값으로 덮어쓰는 책임 — 본 store 는 받은 값을 신뢰.
    """
    raw = args.get("agent_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _resolve_null_owner_arg(args: dict[str, Any]) -> Any:
    """D23 §7 — store caller 가 storage 로 전달할 include_null_owner 값.

    engine 이 admin 검증 후 _admin_null_owner_sentinel 에 ADMIN_NULL_OWNER_OK
    를 set 한 경우만 sentinel 전달. 그 외 — False (격리 default).
    bool True 직접 전달 금지 (storage layer 가 ValueError 거부).
    """
    sentinel = args.get("_admin_null_owner_sentinel")
    if sentinel is agent_document_store.ADMIN_NULL_OWNER_OK:
        return agent_document_store.ADMIN_NULL_OWNER_OK
    return False


async def create(args: dict[str, Any]) -> dict[str, Any]:
    """메모/할 일 저장.

    Args:
      - title (str, 필수): 핵심 명사구.
      - note (str, 옵션): 부연.
      - deadline_at (str ISO datetime, 옵션): 마감 시각.
      - alarm_at (str ISO datetime, 옵션): 알람 시각.
      - raw_utterance (str, 옵션): 원 발화.
      - tenant_id 또는 phone (engine 자동 주입).
      - agent_id (D23 §1): owner_agent_id 격리. engine 자동 주입 (server-side).

    반환: {id, success, duplicate?, summary}
    """
    title = str(args.get("title") or "").strip()
    if not title:
        return {"success": False, "error": "title 슬롯이 비어있습니다"}
    note = (args.get("note") or None)
    deadline_at = (args.get("deadline_at") or None)
    alarm_at = (args.get("alarm_at") or None)
    raw_utt = (args.get("raw_utterance") or None)
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
    owner_agent_uuid = _owner_agent_uuid(args)

    sig = _dedup_signature(title, deadline_at)
    body = {
        "title": title,
        "note": note,
        "deadline_at": deadline_at,
        "alarm_at": alarm_at,
        "status": "active",
        "raw_utterance": raw_utt,
        "created_at": now_iso,
        "completed_at": None,
    }

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"success": False, "error": "tenant_id required when AGENT_DATA_STORE=kms"}
        scope_group = args.get("scope_group") or "personal"
        try:
            # D23 §1 — dedup 검색도 동일 owner 안에서만.
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
            it_body = it.get("body") if isinstance(it, dict) and "body" in it else it
            if (
                _dedup_signature(it_body.get("title"), it_body.get("deadline_at")) == sig
                and (it_body.get("status") or "active") == "active"
            ):
                return _duplicate_response(str(it.get("id", "")), title=title, deadline_at=deadline_at)
        try:
            doc_id = await agent_document_store.create_item(
                _get_shared_engine(),
                UUID(str(tenant_id)),
                _DOCUMENT_TYPE,
                title=title,
                body=body,
                scope_group=scope_group,
                owner_agent_id=owner_agent_uuid,
            )
        except ValueError as exc:
            # cross-tenant agent_id 차단 (storage 검증 실패).
            return {"success": False, "error": str(exc)}
        return {
            "id": str(doc_id),
            "success": True,
            "scope_group": scope_group,
            "title": title,
            "deadline_at": deadline_at,
            "owner_agent_id": str(owner_agent_uuid) if owner_agent_uuid else None,
            "summary": _build_create_summary(title, deadline_at, alarm_at),
        }

    phone = args.get("phone")
    if not phone:
        return {"success": False, "error": "phone required when AGENT_DATA_STORE=redis"}
    try:
        existing = await rs.list_items(_CATEGORY, phone)
    except Exception:
        existing = []
    for it in existing:
        if (
            _dedup_signature(it.get("title"), it.get("deadline_at")) == sig
            and (it.get("status") or "active") == "active"
        ):
            return _duplicate_response(str(it.get("id", "")), title=title, deadline_at=deadline_at)
    item = {"id": str(uuid.uuid4()), **body}
    await rs.rpush_item(_CATEGORY, phone, item)
    return {
        "id": item["id"],
        "success": True,
        "title": title,
        "deadline_at": deadline_at,
        "summary": _build_create_summary(title, deadline_at, alarm_at),
    }


def _build_create_summary(title: str, deadline_at: str | None, alarm_at: str | None) -> str:
    parts = [f"메모 기록: {title}"]
    if deadline_at:
        parts.append(f"마감 {deadline_at}")
    if alarm_at and alarm_at != deadline_at:
        parts.append(f"알람 {alarm_at}")
    return " · ".join(parts)


async def list_all(args: dict[str, Any]) -> dict[str, Any]:
    """메모 전체 / 상태별 조회.

    D23 §1 — agent_id 격리 + admin sentinel.
    """
    status_filter = args.get("status")  # active / done / None
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"items": [], "error": "tenant_id required when AGENT_DATA_STORE=kms"}
        scope_group = args.get("scope_group")
        owner_agent_uuid = _owner_agent_uuid(args)
        include_null_arg = _resolve_null_owner_arg(args)
        items_raw = await agent_document_store.list_items(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            scope_group=scope_group,
            owner_agent_id=owner_agent_uuid,
            include_null_owner=include_null_arg,
        )
        # body 펼쳐서 평탄화
        flat = []
        for it in items_raw:
            body = it.get("body") if isinstance(it, dict) and "body" in it else it
            row = {**body, "id": it.get("id")} if isinstance(body, dict) else dict(it)
            flat.append(row)
        items = flat
    else:
        phone = args.get("phone")
        if not phone:
            return {"items": [], "error": "phone required when AGENT_DATA_STORE=redis"}
        items = await rs.list_items(_CATEGORY, phone)

    if status_filter:
        items = [it for it in items if (it.get("status") or "active") == status_filter]
    # deadline_at 오름차순 (None 은 뒤로), 없으면 created_at desc
    items.sort(
        key=lambda it: (
            it.get("deadline_at") is None,
            it.get("deadline_at") or "",
            -(_safe_iso_to_ts(it.get("created_at"))),
        )
    )
    return {"items": items}


def _safe_iso_to_ts(v: Any) -> float:
    try:
        return _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


async def update(args: dict[str, Any]) -> dict[str, Any]:
    """메모 수정 — id + 변경 필드 (title / note / deadline_at / alarm_at / status)."""
    item_id = args.get("id")
    if not item_id:
        return {"success": False, "error": "id required"}
    patch_keys = ("title", "note", "deadline_at", "alarm_at", "status")
    body_patch = {k: args[k] for k in patch_keys if args.get(k) is not None}
    if (args.get("status") or "") == "done":
        body_patch["completed_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"success": False, "error": "tenant_id required (kms mode)"}
        owner_agent_uuid = _owner_agent_uuid(args)
        ok = await agent_document_store.update_item(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            str(item_id),
            body_patch=body_patch or None,
            owner_agent_id=owner_agent_uuid,
        )
        return {"success": bool(ok)}

    phone = args.get("phone")
    if not phone:
        return {"success": False, "error": "phone required (redis mode)"}
    items = await rs.list_items(_CATEGORY, phone)
    new_items, found = [], False
    for it in items:
        if str(it.get("id")) == str(item_id):
            new_items.append({**it, **body_patch})
            found = True
        else:
            new_items.append(it)
    if not found:
        return {"success": False, "error": "not found"}
    await rs.replace_items(_CATEGORY, phone, new_items)
    return {"success": True}


async def delete(args: dict[str, Any]) -> dict[str, Any]:
    """메모 삭제 (id 단건)."""
    item_id = args.get("id")
    if not item_id:
        return {"success": False, "error": "id required"}
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"success": False, "error": "tenant_id required (kms mode)"}
        owner_agent_uuid = _owner_agent_uuid(args)
        ok = await agent_document_store.delete_item(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            str(item_id),
            owner_agent_id=owner_agent_uuid,
        )
        return {"success": bool(ok)}
    phone = args.get("phone")
    if not phone:
        return {"success": False, "error": "phone required (redis mode)"}
    ok = await rs.remove_by_id(_CATEGORY, phone, str(item_id))
    return {"success": bool(ok)}


async def complete(args: dict[str, Any]) -> dict[str, Any]:
    """메모 완료 처리 — status='done' 으로 마킹."""
    return await update({**args, "status": "done"})
