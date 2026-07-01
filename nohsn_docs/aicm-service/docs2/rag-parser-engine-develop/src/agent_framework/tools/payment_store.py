"""결제 환불 (payment.refund) 도구 — Phase 1.5C P0 추상 layer.

본 PR 범위:
- args validation + ``documents.kind='refund_request'`` row 저장.
- status 'pending' 으로 시작 — 후속 PR 의 PG webhook (Toss / 카카오페이 /
  네이버페이) 가 'completed' / 'failed' 로 전환.
- 외부 API 호출 X (이번 PR 은 추상 layer — *후속 PR 에서 실 PG 연동*).

설계 원칙:
- ``payment.charge`` 는 P2 보류 — chatbot 안에서 직접 결제 = 사기 위험 +
  채널 정책 위반 (Q3 권고).
- ``payment.refund`` 만 P0 — 사용자가 명시적으로 환불 요구 시 *기록만*
  남기고 운영자가 PG 콘솔에서 승인하거나, 후속 PR 의 webhook 이 자동 처리.
- multi-tenant 격리 + audit trail (요청 시각·요청자·사유) 필수.

저장 schema (``documents.processing_meta.body``):
- ``order_id``: 외부 주문 식별자 (PG 의 paymentKey 또는 자체 주문번호).
- ``amount``: 환불 금액 (정수 원).
- ``reason``: 환불 사유 (옵션).
- ``status``: ``pending`` / ``completed`` / ``failed`` / ``cancelled``.
- ``requested_at``: 요청 시각 (ISO).
- ``account_id_hint``: 운영자/사용자 식별 (옵션, auto-injected).

후속 PR 예정:
- Toss / 카카오페이 / 네이버페이 webhook 연동.
- 부분 환불 (partial=True) flag.
- 환불 영수증 PDF 자동 생성 (cert.issue_pdf 와 묶음).
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any
from uuid import UUID

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools.schedule_store import _get_shared_engine

_DOCUMENT_TYPE = "refund_request"


def _store_mode() -> str:
    return os.environ.get("AGENT_DATA_STORE", "redis").lower()


def _require_tenant(args: dict[str, Any]) -> tuple[UUID | None, dict[str, Any] | None]:
    tenant_id = args.get("tenant_id")
    if not tenant_id:
        return None, {
            "success": False,
            "error": "tenant_id required (payment.refund 은 multi-tenant 도구)",
        }
    try:
        return UUID(str(tenant_id)), None
    except (ValueError, TypeError):
        return None, {
            "success": False,
            "error": "tenant_id 형식 오류 — UUID 문자열이어야 합니다",
        }


def _parse_amount(value: Any) -> int | None:
    """amount → int. ``"15000"`` / ``15000`` / ``15000.0`` 모두 처리.

    음수 / 0 은 거부 — 환불은 양의 정수 원화.
    """
    if value is None:
        return None
    try:
        # 부동 소수점 들어오면 round 후 int.
        amount = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return amount


# ── Public tool entry points ─────────────────────────────────────────


async def refund(args: dict[str, Any]) -> dict[str, Any]:
    """환불 요청 기록 (추상 layer).

    실 PG 호출 X — 본 PR 은 *환불 의향* 을 documents 에 기록만 한다.
    후속 PR 의 webhook (`tosspayments.refund` 등) 이 status 를 'completed'
    또는 'failed' 로 전환.

    Args:
      - order_id (str, 필수): 외부 주문 식별자.
      - amount (int, 필수): 환불 금액 (원).
      - reason (str, 옵션): 환불 사유.
      - tenant_id (UUID, 필수, auto-injected).

    반환: ``{id, success, status='pending', order_id, amount, summary}``.
    """
    if _store_mode() != "kms":
        return {
            "success": False,
            "error": "payment.refund 은 AGENT_DATA_STORE=kms 환경에서만 동작",
        }

    tenant_id, err = _require_tenant(args)
    if err:
        return err
    assert tenant_id is not None

    order_id = str(args.get("order_id") or "").strip()
    if not order_id:
        return {"success": False, "error": "order_id 슬롯이 비어있습니다"}

    amount = _parse_amount(args.get("amount"))
    if amount is None:
        return {
            "success": False,
            "error": "amount 슬롯이 비어있거나 양의 정수 (원) 가 아닙니다",
        }

    reason = (args.get("reason") or None)
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
    body: dict[str, Any] = {
        "kind": "refund_request",
        "order_id": order_id,
        "amount": amount,
        "reason": reason,
        "status": "pending",
        "requested_at": now_iso,
    }
    if args.get("account_id_hint") is not None:
        body["account_id_hint"] = args["account_id_hint"]

    title = f"환불요청 {order_id} ({amount:,}원)"
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
        "status": "pending",
        "order_id": order_id,
        "amount": amount,
        "summary": (
            f"환불 요청 접수 — 주문 {order_id} · {amount:,}원 (PG 처리 대기)"
        ),
    }
