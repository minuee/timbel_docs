"""예약 (reservation) 도구 — Phase 1.5C P0.

Top-7 한국 SMB 산업 (restaurant_cafe / beauty / hair / health_medical /
lodging / pet / leisure_sports / travel) 의 핵심 능력. 12/19 산업이 직접
요구하는 *예약 생성·조회·변경·취소* verbs.

설계 원칙 (한국 시장 + 자비스 비전 정합):
- ``documents`` 테이블의 ``kind='reservation'`` 으로 표준 schema 저장
  (alembic migration 변경 X).
- multi-tenant 격리는 ``agent_document_store`` 가 책임 (tenant_id 직접 컬럼).
- ``reschedule`` 은 기존 row 의 시각만 update — 새 row 생성 X (audit log 는
  후속 PR 에서 추가).
- ``cancel`` 은 id-only enforcement (Phase 1.5A Task 8e 패턴) — broad mutation
  방지. 매장 운영자가 실수로 다중 row 취소하지 않게.
- ``check_availability`` 는 ``schedule.availability`` 와 동일한 overlap 검사
  로직이지만 *reservation 도메인 한정* — 기존 일정과 섞이지 않는다.

저장 schema (``documents.processing_meta.body``):
- ``title``: 예약 제목 (예약자명 / 메뉴 / 객실명).
- ``start_at``: ISO 8601 datetime — 예약 시작 시각.
- ``end_at``: ISO 8601 datetime — 예약 종료 시각.
- ``attendee_count``: 인원 수 (옵션).
- ``location``: 자리/객실/지점 (옵션).
- ``contact``: 예약자 연락처 (옵션).
- ``notes``: 특이사항 / 메모 (옵션).
- ``status``: ``confirmed`` / ``cancelled`` / ``rescheduled``.

후속 PR 예정:
- 채널 webhook (KakaoTalk Channel commerceCard 연동).
- 환불 정책 자동 적용 (기존 ``payment.refund`` 와 묶음).
- 알림톡 (SOLAPI) 자동 발송.
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any
from uuid import UUID

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools.schedule_store import _get_shared_engine

_DOCUMENT_TYPE = "reservation"


def _store_mode() -> str:
    """``AGENT_DATA_STORE`` — 기본 ``redis`` 이지만 reservation 은 multi-tenant
    필수 도메인이라 KMS only. redis 모드에서 호출되면 명확히 거부.
    """
    return os.environ.get("AGENT_DATA_STORE", "redis").lower()


def _require_tenant(args: dict[str, Any]) -> tuple[UUID | None, dict[str, Any] | None]:
    """tenant_id 추출 — 미주입 시 명시적 에러 응답."""
    tenant_id = args.get("tenant_id")
    if not tenant_id:
        return None, {
            "success": False,
            "error": "tenant_id required (reservation 은 multi-tenant 도구)",
        }
    try:
        return UUID(str(tenant_id)), None
    except (ValueError, TypeError):
        return None, {
            "success": False,
            "error": "tenant_id 형식 오류 — UUID 문자열이어야 합니다",
        }


def _parse_iso(value: Any) -> _dt.datetime | None:
    """ISO 8601 문자열 → datetime. 실패 시 None.

    LLM 이 ``2026-05-08T19:00`` 또는 ``2026-05-08T19:00:00+09:00`` 같은 다양한
    형태로 넘기므로 fromisoformat 만 시도. 실패 시 호출자가 None 처리.
    """
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    # Python 3.11+ fromisoformat 은 'Z' suffix 도 처리.
    s_normalized = s.replace("Z", "+00:00")
    try:
        return _dt.datetime.fromisoformat(s_normalized)
    except ValueError:
        return None


# ── Public tool entry points ─────────────────────────────────────────


async def create(args: dict[str, Any]) -> dict[str, Any]:
    """예약 생성.

    Args:
      - title (str, 필수): 예약 제목.
      - start_at (str ISO datetime, 필수): 시작 시각.
      - end_at (str ISO datetime, 필수): 종료 시각.
      - attendee_count (int, 옵션): 인원 수.
      - location (str, 옵션): 자리/객실/지점.
      - contact (str, 옵션): 연락처.
      - notes (str, 옵션): 메모.
      - tenant_id (UUID, 필수, auto-injected): 매장 격리.
      - account_id_hint (str, 옵션, auto-injected): 운영자 식별.

    반환: ``{id, success, summary, status='confirmed'}`` 또는 에러.
    """
    if _store_mode() != "kms":
        return {
            "success": False,
            "error": "reservation tool 은 AGENT_DATA_STORE=kms 환경에서만 동작",
        }

    tenant_id, err = _require_tenant(args)
    if err:
        return err
    assert tenant_id is not None

    title = str(args.get("title") or "").strip()
    if not title:
        return {"success": False, "error": "title 슬롯이 비어있습니다"}

    start_at = _parse_iso(args.get("start_at"))
    end_at = _parse_iso(args.get("end_at"))
    if start_at is None:
        return {"success": False, "error": "start_at (ISO datetime) 슬롯이 비어있습니다"}
    if end_at is None:
        return {"success": False, "error": "end_at (ISO datetime) 슬롯이 비어있습니다"}
    if end_at <= start_at:
        return {
            "success": False,
            "error": "end_at 은 start_at 보다 이후여야 합니다",
        }

    body: dict[str, Any] = {
        "title": title,
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "status": "confirmed",
        "kind": "reservation",
    }
    for k in ("attendee_count", "location", "contact", "notes", "account_id_hint"):
        v = args.get(k)
        if v is not None:
            body[k] = v
    body["created_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()

    doc_id = await agent_document_store.create_item(
        _get_shared_engine(),
        tenant_id,
        _DOCUMENT_TYPE,
        title=title,
        body=body,
    )
    return {
        "id": str(doc_id),
        "success": True,
        "status": "confirmed",
        "title": title,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "summary": f"예약 등록 완료 — {title} · {body['start_at']}",
    }


async def cancel(args: dict[str, Any]) -> dict[str, Any]:
    """예약 취소.

    Phase 1.5A Task 8e id-only enforcement — title/시각 등으로 broad cancel X.
    매장 운영자가 의도치 않게 여러 예약을 한꺼번에 취소하는 사고를 차단.

    Args:
      - id (UUID str, 필수): 예약 document id.
      - reason (str, 옵션): 취소 사유 (audit log 후속 PR 에서 사용).
      - tenant_id (UUID, 필수, auto-injected).

    반환: ``{success, status='cancelled', summary}``.

    취소 정책 (예: 30분 전 환불 불가) 은 SOP RAG 가 가이드 — 이 도구는 행위만.
    """
    if _store_mode() != "kms":
        return {
            "success": False,
            "error": "reservation tool 은 AGENT_DATA_STORE=kms 환경에서만 동작",
        }

    tenant_id, err = _require_tenant(args)
    if err:
        return err
    assert tenant_id is not None

    item_id = args.get("id")
    if not item_id:
        return {
            "success": False,
            "error": "id required — 어떤 예약인지 먼저 조회 후 id 로 호출하세요",
        }

    # status='cancelled' 로 patch + 메타 보존 (soft delete 가 아니라 status 전환).
    body_patch: dict[str, Any] = {
        "status": "cancelled",
        "cancelled_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    if args.get("reason"):
        body_patch["cancel_reason"] = args["reason"]

    ok = await agent_document_store.update_item(
        _get_shared_engine(),
        tenant_id,
        _DOCUMENT_TYPE,
        str(item_id),
        body_patch=body_patch,
    )
    if not ok:
        return {"success": False, "error": "not found"}
    return {
        "success": True,
        "id": str(item_id),
        "status": "cancelled",
        "summary": "예약 취소 완료",
    }


async def check_availability(args: dict[str, Any]) -> dict[str, Any]:
    """주어진 [start_at, end_at] 슬롯에 다른 active 예약과 overlap 이 있는지.

    raw 예약 정보 노출 X — yes/no 만. 매장 운영자가 안내할 수 있는 정도만.

    Args:
      - start_at (str ISO, 필수)
      - end_at (str ISO, 필수)
      - tenant_id (UUID, 필수, auto-injected).

    반환: ``{success, available: bool, summary}``.
    """
    if _store_mode() != "kms":
        return {
            "success": False,
            "error": "reservation tool 은 AGENT_DATA_STORE=kms 환경에서만 동작",
        }

    tenant_id, err = _require_tenant(args)
    if err:
        return err
    assert tenant_id is not None

    start = _parse_iso(args.get("start_at"))
    end = _parse_iso(args.get("end_at"))
    if start is None or end is None:
        return {"success": False, "error": "start_at / end_at (ISO datetime) 필요"}
    if end <= start:
        return {"success": False, "error": "end_at 은 start_at 보다 이후여야 합니다"}

    # 모든 active reservation 조회 후 메모리에서 overlap 검사.
    # documents 의 body->>'start_at' SQL 캐스팅은 schedule.availability 와
    # 동일 패턴으로 가능하지만, 본 도구는 reservation 도메인 한정 + 호출 빈도가
    # 낮아 list 후 필터가 단순·테스트 친화. (동일 매장에서 한꺼번에 수만 개
    # 예약을 검사할 일은 통상 없음 — top 7 산업의 일일 예약 수십 ~ 수백 건.)
    items = await agent_document_store.list_items(
        _get_shared_engine(),
        tenant_id,
        _DOCUMENT_TYPE,
    )
    overlap = False
    for it in items:
        if (it.get("status") or "confirmed") != "confirmed":
            continue
        it_start = _parse_iso(it.get("start_at"))
        it_end = _parse_iso(it.get("end_at"))
        if it_start is None or it_end is None:
            continue
        # half-open interval overlap: A 의 시작 < B 의 끝 and B 의 시작 < A 의 끝
        if it_start < end and start < it_end:
            overlap = True
            break

    return {
        "success": True,
        "available": not overlap,
        "summary": ("가능한 시간" if not overlap else "다른 예약과 겹치는 시간"),
    }


async def reschedule(args: dict[str, Any]) -> dict[str, Any]:
    """예약 일정 변경 — 기존 row 의 start_at / end_at 만 갱신.

    새 row 생성 X — 변경 이력은 후속 PR 의 audit log 에서 추적.

    Args:
      - id (UUID str, 필수): 예약 document id.
      - new_start_at (str ISO, 필수)
      - new_end_at (str ISO, 필수)
      - tenant_id (UUID, 필수, auto-injected).

    반환: ``{success, id, new_start_at, new_end_at, summary}``.
    """
    if _store_mode() != "kms":
        return {
            "success": False,
            "error": "reservation tool 은 AGENT_DATA_STORE=kms 환경에서만 동작",
        }

    tenant_id, err = _require_tenant(args)
    if err:
        return err
    assert tenant_id is not None

    item_id = args.get("id")
    if not item_id:
        return {"success": False, "error": "id required"}

    new_start = _parse_iso(args.get("new_start_at"))
    new_end = _parse_iso(args.get("new_end_at"))
    if new_start is None or new_end is None:
        return {
            "success": False,
            "error": "new_start_at / new_end_at (ISO datetime) 필요",
        }
    if new_end <= new_start:
        return {
            "success": False,
            "error": "new_end_at 은 new_start_at 보다 이후여야 합니다",
        }

    body_patch: dict[str, Any] = {
        "start_at": new_start.isoformat(),
        "end_at": new_end.isoformat(),
        "status": "rescheduled",
        "rescheduled_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    ok = await agent_document_store.update_item(
        _get_shared_engine(),
        tenant_id,
        _DOCUMENT_TYPE,
        str(item_id),
        body_patch=body_patch,
    )
    if not ok:
        return {"success": False, "error": "not found"}
    return {
        "success": True,
        "id": str(item_id),
        "new_start_at": body_patch["start_at"],
        "new_end_at": body_patch["end_at"],
        "summary": f"예약 일정 변경 — {body_patch['start_at']} ~ {body_patch['end_at']}",
    }
