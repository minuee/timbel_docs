"""Reminder 기록용 저장소 — Redis (legacy) / KMS documents (Stage B-5) dual backend.

env ``AGENT_DATA_STORE`` 로 백엔드 선택:
- ``redis`` (기본) — 전역 list 에 JSON entry append. ``list_recent`` 는 모든 예약 반환.
- ``kms``         — tenant 별 ``agent_reminder`` document 로 저장. ``list_recent`` 는
  cross-tenant 전역 조회 (관리자/스케줄러 전용).

PII: phone 은 structured body 에 저장되지만 로그에는 남기지 않는다 (기존 mock 동일).

P11-18 (2026-04-29) — recurrence 지원:
- 단발: ``at`` (ISO 8601 datetime) — 한 번만 발사 후 done.
- 주기: ``recurrence`` (단순 명세 — RRULE 풀 파서 X)
    * ``daily_at: "HH:MM"`` — 매일 그 시각
    * ``weekly_at: {day: "mon"|"tue"|..., time: "HH:MM"}``
    * ``every_n_days: {n: int, time: "HH:MM"}``
- ``next_at`` — 워커가 다음 발사 시각 계산 후 stamp. 발사 직후 다음 occurrence 로 업데이트.
- ``last_fired_at`` — 마지막 발사 시각.
- ``status`` — active | paused | done. user "혈압약 알람 그만" → paused.

워커 (``src/pipeline/workers/reminder_worker.py``) 가 1분 주기로
``next_at <= now AND status='active'`` reminder 를 가져와 fire (feed_event 발행).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
from typing import Any
from uuid import UUID

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools import _redis_store as rs
from src.agent_framework.tools.schedule_store import _get_shared_engine
from src.common.logging import get_logger

log = get_logger(__name__)

_CATEGORY = "reminder"
_DOCUMENT_TYPE = "agent_reminder"


_DAY_MAP = {
    "mon": 0, "monday": 0, "월": 0, "월요일": 0,
    "tue": 1, "tuesday": 1, "화": 1, "화요일": 1,
    "wed": 2, "wednesday": 2, "수": 2, "수요일": 2,
    "thu": 3, "thursday": 3, "목": 3, "목요일": 3,
    "fri": 4, "friday": 4, "금": 4, "금요일": 4,
    "sat": 5, "saturday": 5, "토": 5, "토요일": 5,
    "sun": 6, "sunday": 6, "일": 6, "일요일": 6,
}


def _local_tz() -> _dt.tzinfo:
    """KMS_LOCAL_TZ env (default Asia/Seoul) 반환. zoneinfo 실패시 +09 offset."""
    name = os.environ.get("KMS_LOCAL_TZ", "Asia/Seoul")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        return _dt.timezone(_dt.timedelta(hours=9))


def _local_now() -> _dt.datetime:
    """현재 시각 — local tz aware."""
    return _dt.datetime.now(_local_tz())


def _parse_hhmm(s: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(s or "").strip())
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh, mm


def compute_next_occurrence(
    recurrence: dict | None,
    *,
    now: _dt.datetime | None = None,
    last_fired_at: str | None = None,
) -> str | None:
    """recurrence 명세로 다음 발사 시각 ISO datetime 반환.

    - daily_at: "HH:MM" → 오늘 또는 내일 그 시각.
    - weekly_at: {day, time} → 이번 주 또는 다음 주 그 요일 그 시각.
    - every_n_days: {n, time} → last_fired_at 기준 +n일 그 시각.

    인자 ``now`` 는 테스트 주입용. None 이면 datetime.now (system tz).
    """
    if not recurrence or not isinstance(recurrence, dict):
        return None
    if now is None:
        now = _local_now()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_local_tz())
    if "daily_at" in recurrence:
        hhmm = _parse_hhmm(recurrence["daily_at"])
        if not hhmm:
            return None
        hh, mm = hhmm
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= now:
            candidate += _dt.timedelta(days=1)
        return candidate.isoformat(timespec="seconds")
    if "weekly_at" in recurrence:
        spec = recurrence["weekly_at"] or {}
        day_key = str(spec.get("day", "")).strip().lower()
        target_dow = _DAY_MAP.get(day_key)
        hhmm = _parse_hhmm(spec.get("time"))
        if target_dow is None or not hhmm:
            return None
        hh, mm = hhmm
        days_ahead = (target_dow - now.weekday()) % 7
        candidate = (now + _dt.timedelta(days=days_ahead)).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += _dt.timedelta(days=7)
        return candidate.isoformat(timespec="seconds")
    if "every_n_days" in recurrence:
        spec = recurrence["every_n_days"] or {}
        n = int(spec.get("n", 1))
        if n < 1:
            return None
        hhmm = _parse_hhmm(spec.get("time"))
        if not hhmm:
            return None
        hh, mm = hhmm
        if last_fired_at:
            try:
                base = _dt.datetime.fromisoformat(last_fired_at)
            except ValueError:
                base = now
        else:
            base = now
        candidate = (base + _dt.timedelta(days=n)).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += _dt.timedelta(days=n)
        return candidate.isoformat(timespec="seconds")
    return None


# ── Idempotency helper (PR-E1 — schedule_store 패턴 확산) ──────────────


def _dedup_signature(at: Any, template: Any) -> str:
    """``(at, template)`` 정규화 해시 — 같은 시각 동일 메시지 reminder 중복 차단."""
    norm_at = str(at or "").strip()
    norm_tpl = str(template or "").strip().lower()[:120]
    raw = f"{norm_at}|{norm_tpl}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _build_schedule_summary(
    title: str, recurrence: dict | None, next_at: str | None,
) -> str:
    """P11-19e — 신규 등록 시 모든 recurrence 종류 (daily/weekly/every_n_days/단발)
    summary 명시. 이전엔 daily_at 만 처리, weekly/every_n_days 는 generic
    fallback 으로 처리되어 사용자에게 주기 정보 누락.
    """
    if recurrence and "daily_at" in recurrence:
        return (
            f"{title} 알람을 매일 {recurrence['daily_at']} 에 등록했습니다 "
            f"(다음 발사: {next_at})"
        )
    if recurrence and "weekly_at" in recurrence:
        wa = recurrence["weekly_at"] or {}
        return (
            f"{title} 알람을 매주 {wa.get('day','')} {wa.get('time','')} 에 "
            f"등록했습니다 (다음 발사: {next_at})"
        )
    if recurrence and "every_n_days" in recurrence:
        ed = recurrence["every_n_days"] or {}
        n = ed.get("n", "")
        t = ed.get("time", "")
        return (
            f"{title} 알람을 {n}일마다 {t} 에 등록했습니다 "
            f"(다음 발사: {next_at})"
        )
    return f"{title} 알람을 등록했습니다 (예정: {next_at})"


def _duplicate_response(at: Any, *, title: str | None = None, recurrence: dict | None = None) -> dict[str, Any]:
    """P11-19e — duplicate 시 정보 echo. 사용자가 "이미 등록되어 있고 *어떤* 알람인지"
    바로 알 수 있게. 이전 ('이미 예약된 리마인더입니다' 한 줄) 은 정보 부족."""
    parts = []
    if title:
        parts.append(title)
    if recurrence and isinstance(recurrence, dict):
        if "daily_at" in recurrence:
            parts.append(f"매일 {recurrence['daily_at']}")
        elif "weekly_at" in recurrence:
            wa = recurrence["weekly_at"] or {}
            parts.append(f"매주 {wa.get('day','')} {wa.get('time','')}".strip())
        elif "every_n_days" in recurrence:
            ed = recurrence["every_n_days"] or {}
            parts.append(f"{ed.get('n','')}일마다 {ed.get('time','')}".strip())
    if at and not recurrence:
        parts.append(str(at))
    detail = " · ".join(p for p in parts if p)
    summary = (
        f"{detail} 알람은 이미 등록되어 있습니다."
        if detail
        else "이미 예약된 리마인더입니다."
    )
    return {
        "success": True,
        "at": at,
        "duplicate": True,
        "summary": summary,
    }


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


async def list_recent() -> list[dict[str, Any]]:
    """최근 등록된 reminder 들 (테스트/관리 UI 용).

    KMS 모드는 tenant 경계를 넘는 조회 — 관리자/스케줄러 경로 전용. 실제 prod
    UX 에서 일반 사용자 호출하는 경로가 생기면 tenant 필터 추가한 별도 함수를
    써야 한다.
    """
    if _store_mode() == "kms":
        items = await agent_document_store.list_items_global_doctype(
            _get_shared_engine(),
            _DOCUMENT_TYPE,
            order_desc=False,
        )
        return items

    return await rs.list_global(_CATEGORY)


def _coerce_recurrence(args: dict[str, Any]) -> dict | None:
    """flat args (recurrence_kind/time/weekday/every_n) → 통일 recurrence dict.

    medication_tracker.yaml 는 flat slot 으로 전달, plan_orchestrator 는 nested
    `recurrence` dict 로 전달 가능. 양쪽 다 받아 통일된 형태로 정규화.
    """
    if isinstance(args.get("recurrence"), dict):
        return args["recurrence"]
    kind = (args.get("recurrence_kind") or "").strip().lower()
    time_str = (args.get("time") or "").strip()
    if not kind or not time_str:
        return None
    if kind == "daily":
        return {"daily_at": time_str}
    if kind == "weekly":
        wd = args.get("weekday") or args.get("day") or ""
        return {"weekly_at": {"day": wd, "time": time_str}}
    if kind == "every_n_days":
        try:
            n = int(args.get("every_n") or 0)
        except (TypeError, ValueError):
            n = 0
        if n < 1:
            return None
        return {"every_n_days": {"n": n, "time": time_str}}
    return None


async def schedule(args: dict[str, Any]) -> dict[str, Any]:
    """reminder 를 예약 (단발 또는 주기). 워커가 next_at 도달 시 fire.

    Args:
      - title: 사용자에게 보일 제목 (예: "혈압약 복용")
      - template: 알람 본문 (template 또는 message). title 미지정 시 fallback.
      - at: ISO datetime — 단발 reminder. recurrence 와 동시 사용 X.
      - recurrence: dict — 주기 명세. ``compute_next_occurrence`` 참조.
        * ``{daily_at: "08:00"}``
        * ``{weekly_at: {day: "mon", time: "09:00"}}``
        * ``{every_n_days: {n: 2, time: "20:00"}}``
      - 또는 flat: ``recurrence_kind`` (daily|weekly|every_n_days) +
        ``time`` (HH:MM) + ``weekday`` (weekly) + ``every_n`` (every_n_days)
      - channel: "sms" | "in_app" | "email" (default: in_app)
      - phone, tenant_id, scope_group: 식별
      - status: "active" (default) — paused/done 은 별도 update API.

    P11-18: recurrence 가 있으면 next_at 자동 계산, last_fired_at=null 로 시작.
    워커가 발사 후 last_fired_at update + next_at 재계산.
    """
    title = (args.get("title") or args.get("template") or "리마인더").strip()
    recurrence = _coerce_recurrence(args)
    at = args.get("at")
    template = args.get("template") or title

    # next_at 결정 — recurrence 있으면 계산, 없으면 at 사용.
    if recurrence:
        next_at = compute_next_occurrence(recurrence)
        if not next_at:
            return {
                "success": False,
                "error": f"invalid recurrence spec: {recurrence}",
            }
    elif at:
        next_at = at
    else:
        return {"success": False, "error": "either 'at' or 'recurrence' required"}

    # dedup 시그니처는 (next_at + template + recurrence) 로 — 동일 일정 중복 차단.
    sig = _dedup_signature(
        f"{next_at}|{recurrence or ''}", template
    )

    body = {
        "title": title,
        "template": template,
        "channel": args.get("channel", "in_app"),
        "phone": args.get("phone"),
        "at": at,
        "recurrence": recurrence,
        "next_at": next_at,
        "last_fired_at": None,
        "fire_count": 0,
        "status": "active",
    }

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
            it_body = it.get("body") if isinstance(it, dict) else None
            ref = it_body if isinstance(it_body, dict) else it
            comp = _dedup_signature(
                f"{ref.get('next_at')}|{ref.get('recurrence') or ''}",
                ref.get("template"),
            )
            if comp == sig:
                return _duplicate_response(
                    ref.get("next_at"),
                    title=ref.get("title") or ref.get("template"),
                    recurrence=ref.get("recurrence"),
                )

        try:
            doc_id = await agent_document_store.create_item(
                _get_shared_engine(),
                UUID(str(tenant_id)),
                _DOCUMENT_TYPE,
                title=f"{title} ({next_at})",
                body=body,
                scope_group=scope_group,
                owner_agent_id=owner_agent_uuid,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        log.info(
            "reminder_scheduled",
            id=str(doc_id),
            next_at=next_at,
            title=title,
            recurrence=recurrence,
            backend="kms",
        )
        summary = _build_schedule_summary(title, recurrence, next_at)
        return {
            "success": True,
            "id": str(doc_id),
            "next_at": next_at,
            "recurrence": recurrence,
            "summary": summary,
        }

    # DEPRECATED (D24 §2, 2026-05-08) — agent 격리 X.
    # AGENT_DATA_STORE=kms 권장. 후속 제거 plan: D25.
    # redis (legacy) — 전역 리스트
    try:
        existing = await rs.list_global(_CATEGORY)
    except Exception:
        existing = []
    for it in existing:
        comp = _dedup_signature(
            f"{it.get('next_at')}|{it.get('recurrence') or ''}",
            it.get("template"),
        )
        if comp == sig:
            return _duplicate_response(
                it.get("next_at"),
                title=it.get("title") or it.get("template"),
                recurrence=it.get("recurrence"),
            )

    import uuid as _uuid

    entry = {"id": str(_uuid.uuid4()), **body}
    await rs.rpush_global(_CATEGORY, entry)
    log.info(
        "reminder_scheduled",
        id=entry["id"],
        next_at=next_at,
        title=title,
        recurrence=recurrence,
        backend="redis",
    )
    summary = (
        f"{title} 알람을 매일 {recurrence['daily_at']} 에 등록했습니다 "
        f"(다음 발사: {next_at})"
        if recurrence and "daily_at" in recurrence
        else f"{title} 알람을 등록했습니다 (예정: {next_at})"
    )
    return {
        "success": True,
        "id": entry["id"],
        "next_at": next_at,
        "recurrence": recurrence,
        "summary": summary,
    }


async def list_for_user(args: dict[str, Any]) -> dict[str, Any]:
    """tenant 의 *내* 알람 리스트 (active + paused). 사용자 발화 '내 알람 보여줘' 류.

    KMS 모드: tenant_id scoped — 다른 tenant 의 reminder 안 보임.
    redis 모드: phone scope (현재는 전역 — 후속 PR 에서 phone 필터).

    반환: {success, items: [{id, title, recurrence, next_at, status}], summary}
    """
    items_raw: list[dict[str, Any]]
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {
                "success": False,
                "items": [],
                "error": "tenant_id required when AGENT_DATA_STORE=kms",
            }
        owner_agent_uuid = _owner_agent_uuid(args)
        include_null_arg = _resolve_null_owner_arg(args)
        items_raw = await agent_document_store.list_items(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            owner_agent_id=owner_agent_uuid,
            include_null_owner=include_null_arg,
        )
    else:
        items_raw = await rs.list_global(_CATEGORY)

    items: list[dict[str, Any]] = []
    for it in items_raw:
        body = it.get("body") if isinstance(it, dict) and "body" in it else it
        ref = body if isinstance(body, dict) else it
        if ref.get("status") == "done":
            continue  # 끝난 단발 reminder 는 제외
        rec = ref.get("recurrence") or {}
        kind_label = "단발"
        if "daily_at" in rec:
            kind_label = f"매일 {rec['daily_at']}"
        elif "weekly_at" in rec:
            wa = rec["weekly_at"] or {}
            kind_label = f"매주 {wa.get('day')} {wa.get('time')}"
        elif "every_n_days" in rec:
            ed = rec["every_n_days"] or {}
            kind_label = f"{ed.get('n')}일마다 {ed.get('time')}"
        items.append(
            {
                "id": str(it.get("id") or ref.get("id") or ""),
                "title": ref.get("title") or ref.get("template") or "(제목 없음)",
                "recurrence_label": kind_label,
                "next_at": ref.get("next_at"),
                "status": ref.get("status", "active"),
            }
        )

    if items:
        lines = [
            f"- {it['title']}: {it['recurrence_label']} (다음: {it['next_at']})"
            for it in items
        ]
        summary = "현재 등록된 알람:\n" + "\n".join(lines)
    else:
        summary = "등록된 알람이 없습니다."

    return {"success": True, "items": items, "summary": summary, "count": len(items)}


async def cancel(args: dict[str, Any]) -> dict[str, Any]:
    """알람 해제 — id 또는 title 매칭 후 status='paused' 또는 'done'.

    args: {id?, title?, tenant_id?, action: "pause"|"cancel"}
    """
    target_id = args.get("id")
    target_title = (args.get("title") or "").strip().lower()
    action = args.get("action", "pause")
    new_status = "paused" if action == "pause" else "done"

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"success": False, "error": "tenant_id required"}
        owner_agent_uuid = _owner_agent_uuid(args)
        items = await agent_document_store.list_items(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            owner_agent_id=owner_agent_uuid,
        )
        match = None
        for it in items:
            body = it.get("body") if isinstance(it, dict) else None
            ref = body if isinstance(body, dict) else it
            if target_id and str(it.get("id")) == str(target_id):
                match = it
                break
            if target_title and target_title in (ref.get("title") or "").lower():
                match = it
                break
        if not match:
            return {"success": False, "error": "not_found"}
        await agent_document_store.update_item(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            str(match.get("id")),
            body_patch={"status": new_status},
            owner_agent_id=owner_agent_uuid,
        )
        return {
            "success": True,
            "id": str(match.get("id")),
            "summary": (
                f"{(match.get('body') or {}).get('title') or '알람'} 을 "
                f"{'일시정지' if action == 'pause' else '취소'} 했습니다."
            ),
        }

    items = await rs.list_global(_CATEGORY)
    new_items = []
    found = None
    for it in items:
        if target_id and str(it.get("id")) == str(target_id):
            it["status"] = new_status
            found = it
        elif target_title and target_title in (it.get("title") or "").lower():
            it["status"] = new_status
            found = it
        new_items.append(it)
    if not found:
        return {"success": False, "error": "not_found"}
    await rs.replace_global(_CATEGORY, new_items)
    return {
        "success": True,
        "id": found.get("id"),
        "summary": (
            f"{found.get('title') or '알람'} 을 "
            f"{'일시정지' if action == 'pause' else '취소'} 했습니다."
        ),
    }


async def list_active(tenant_id: str | None = None) -> list[dict[str, Any]]:
    """status='active' reminder 만 반환. 워커가 폴링용으로 호출.

    KMS 모드는 cross-tenant (워커 전용). redis 모드는 전역.
    """
    if _store_mode() == "kms":
        items = await agent_document_store.list_items_global_doctype(
            _get_shared_engine(),
            _DOCUMENT_TYPE,
            order_desc=False,
        )
    else:
        items = await rs.list_global(_CATEGORY)
    out = []
    for it in items:
        body = it.get("body") if isinstance(it, dict) else None
        ref = body if isinstance(body, dict) else it
        if ref.get("status", "active") == "active":
            out.append(it)
    return out


async def mark_fired(
    reminder_id: str,
    *,
    tenant_id: str | None = None,
    new_next_at: str | None = None,
    new_last_fired_at: str | None = None,
    new_status: str | None = None,
) -> bool:
    """워커가 reminder 발사 후 호출 — last_fired_at, next_at, status 업데이트."""
    patch: dict[str, Any] = {}
    if new_next_at is not None:
        patch["next_at"] = new_next_at
    if new_last_fired_at is not None:
        patch["last_fired_at"] = new_last_fired_at
    if new_status is not None:
        patch["status"] = new_status

    if _store_mode() == "kms":
        if not tenant_id:
            return False
        ok = await agent_document_store.update_item(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            reminder_id,
            body_patch=patch,
        )
        return bool(ok)

    # redis: list 전체 읽고 해당 id 만 patch — 효율 중요하면 hash 로 마이그레이션.
    items = await rs.list_global(_CATEGORY)
    new_items = []
    found = False
    for it in items:
        if str(it.get("id")) == str(reminder_id):
            for k, v in patch.items():
                it[k] = v
            it["fire_count"] = int(it.get("fire_count") or 0) + (
                1 if new_last_fired_at is not None else 0
            )
            new_items.append(it)
            found = True
        else:
            new_items.append(it)
    if not found:
        return False
    await rs.replace_global(_CATEGORY, new_items)
    return True
