"""배송 추적 (delivery.track) 도구 — Phase 1.5C P0 추상 layer.

본 PR 범위:
- ``delivery.track`` — tracking_number 기반 documents 조회 + 상태 응답.
- 외부 carrier API (스마트택배 / CJ대한통운 / 한진 / 우체국) 호출 X — 추상 layer.
- 후속 PR 의 webhook 이 ``status`` 갱신.

산업 매트릭스 (P0 가치):
- retail / clothing / kids / restaurant_cafe (배민) / plants_flowers — 5 산업 핵심.

저장 schema (``documents.processing_meta.body``):
- ``tracking_number``: 송장번호 (검색 키, 정규화 — 공백·하이픈 제거).
- ``carrier``: 택배사 코드 (예: cj / hanjin / lotte / koreapost / sweettracker).
- ``status``: ``pending`` / ``picked_up`` / ``in_transit`` / ``out_for_delivery`` /
  ``delivered`` / ``failed``.
- ``last_updated``: 최종 갱신 시각 (ISO).
- ``eta``: 도착 예정 (ISO, 옵션).
- ``last_event``: 최근 trail event 텍스트 (옵션).

후속 PR 예정:
- 스마트택배 (smartracker.parcel) webhook 연동.
- carrier 별 status 매핑 테이블.
- 배달의민족 OpenAPI 연동 (영업 트랙 — Phase 1.9).
- ``delivery.subscribe_updates`` (배송 진행 푸시 알림).
"""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools.schedule_store import _get_shared_engine

_DOCUMENT_TYPE = "delivery_tracking"


def _store_mode() -> str:
    return os.environ.get("AGENT_DATA_STORE", "redis").lower()


def _require_tenant(args: dict[str, Any]) -> tuple[UUID | None, dict[str, Any] | None]:
    tenant_id = args.get("tenant_id")
    if not tenant_id:
        return None, {
            "success": False,
            "error": "tenant_id required (delivery.track 은 multi-tenant 도구)",
        }
    try:
        return UUID(str(tenant_id)), None
    except (ValueError, TypeError):
        return None, {
            "success": False,
            "error": "tenant_id 형식 오류 — UUID 문자열이어야 합니다",
        }


def _normalize_tracking(num: Any) -> str:
    """송장번호 정규화 — 공백·하이픈·언더스코어 제거. 매칭 일관성 확보.

    사용자 발화에서 ``1234-5678-9012`` / ``1234 5678 9012`` 등 다양하게 들어옴.
    """
    s = str(num or "").strip()
    return s.replace(" ", "").replace("-", "").replace("_", "")


# ── Public tool entry points ─────────────────────────────────────────


async def track(args: dict[str, Any]) -> dict[str, Any]:
    """배송 조회 (추상 layer).

    실 carrier API 호출 X — 본 PR 은 *내부 documents 캐시* 만 조회.
    후속 PR 의 webhook 이 status 를 실시간 갱신.

    Args:
      - tracking_number (str, 필수): 송장번호.
      - carrier (str, 옵션): 택배사 코드 (정확도 향상 + 후속 webhook 라우팅).
      - tenant_id (UUID, 필수, auto-injected).

    반환:
      매칭 1건: ``{success, tracking_number, carrier, status, last_updated, eta?, summary}``
      매칭 0건: ``{success: False, status: 'unknown', summary}`` — 후속 PR 의
        webhook 이 캐시 미스 시 carrier API 직접 조회 (이번 PR 에선 hint 만).
    """
    if _store_mode() != "kms":
        return {
            "success": False,
            "error": "delivery.track 은 AGENT_DATA_STORE=kms 환경에서만 동작",
        }

    tenant_id, err = _require_tenant(args)
    if err:
        return err
    assert tenant_id is not None

    raw_number = args.get("tracking_number")
    if not raw_number:
        return {"success": False, "error": "tracking_number 슬롯이 비어있습니다"}
    norm_number = _normalize_tracking(raw_number)
    if not norm_number:
        return {"success": False, "error": "tracking_number 가 비어있거나 유효하지 않습니다"}

    carrier_hint = args.get("carrier")

    items = await agent_document_store.list_items(
        _get_shared_engine(),
        tenant_id,
        _DOCUMENT_TYPE,
    )
    # 송장번호 정규화 후 매칭. carrier hint 가 있으면 그 carrier 만 우선.
    candidates = []
    for it in items:
        it_num = _normalize_tracking(it.get("tracking_number"))
        if it_num != norm_number:
            continue
        if carrier_hint and (it.get("carrier") or "") and (it.get("carrier") != carrier_hint):
            continue
        candidates.append(it)

    if not candidates:
        return {
            "success": False,
            "tracking_number": norm_number,
            "status": "unknown",
            "summary": (
                "내부 캐시에 해당 송장 정보가 없습니다 — 후속 PR 의 carrier "
                "webhook 이 활성화되면 외부 조회로 보강됩니다."
            ),
        }

    # 매칭 다건이면 가장 최근 갱신본 우선 (last_updated 내림차순).
    candidates.sort(key=lambda c: str(c.get("last_updated") or ""), reverse=True)
    item = candidates[0]
    status = item.get("status") or "pending"

    summary_map = {
        "pending": "배송 준비 중",
        "picked_up": "택배사 인수 완료",
        "in_transit": "운송 중",
        "out_for_delivery": "배송 출발",
        "delivered": "배송 완료",
        "failed": "배송 실패",
        "unknown": "상태 정보 없음",
    }
    label = summary_map.get(status, status)

    return {
        "success": True,
        "tracking_number": norm_number,
        "carrier": item.get("carrier"),
        "status": status,
        "last_updated": item.get("last_updated"),
        "eta": item.get("eta"),
        "last_event": item.get("last_event"),
        "summary": f"송장 {norm_number} — {label}",
    }
