"""재고 (inventory) 도구 — Phase 1.5C P0 read-only.

본 PR 범위:
- ``inventory.check`` — documents.kind='inventory_item' 검색 + 상태 응답.
- 외부 PIM/POS (카페24/스마트스토어/Shopify) 연동 X — 추상 layer.
- ``inventory.update`` 는 후속 PR (admin 권한 + audit log 필요).

산업 매트릭스 (P0 가치):
- retail / clothing / kids — 재입고 알림 (가장 빈번).
- restaurant_cafe / plants_flowers — 메뉴/주력 상품 재고.
- it_electronics — 부품 / 액세서리 재고.

저장 schema (``documents.processing_meta.body``):
- ``item_name``: 상품명 (검색 키).
- ``sku``: SKU (검색 키, 옵션).
- ``current_qty``: 현재 수량 (int).
- ``low_threshold``: low 임계 (int, 옵션, default 5).
- ``last_updated``: 최종 갱신 시각 (ISO).
- ``restock_eta``: 재입고 예정 (ISO, 옵션).

응답 status 결정:
- current_qty <= 0  → 'out_of_stock'
- 0 < current_qty <= low_threshold → 'low'
- current_qty > low_threshold → 'in_stock'

후속 PR 예정:
- ``inventory.update`` (admin only).
- 외부 webhook (카페24/스마트스토어 SKU sync).
- 재입고 알림 구독 (`stock_alert.subscribe`).
"""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools.schedule_store import _get_shared_engine

_DOCUMENT_TYPE = "inventory_item"
_DEFAULT_LOW_THRESHOLD = 5


def _store_mode() -> str:
    return os.environ.get("AGENT_DATA_STORE", "redis").lower()


def _require_tenant(args: dict[str, Any]) -> tuple[UUID | None, dict[str, Any] | None]:
    tenant_id = args.get("tenant_id")
    if not tenant_id:
        return None, {
            "success": False,
            "error": "tenant_id required (inventory 는 multi-tenant 도구)",
        }
    try:
        return UUID(str(tenant_id)), None
    except (ValueError, TypeError):
        return None, {
            "success": False,
            "error": "tenant_id 형식 오류 — UUID 문자열이어야 합니다",
        }


def _classify_status(qty: int, low_threshold: int) -> str:
    if qty <= 0:
        return "out_of_stock"
    if qty <= low_threshold:
        return "low"
    return "in_stock"


def _matches(item: dict[str, Any], *, name: str | None, sku: str | None, item_id: str | None) -> bool:
    """검색 매칭 — id 우선, sku, item_name (case-insensitive substring)."""
    if item_id and str(item.get("id")) == str(item_id):
        return True
    if sku:
        it_sku = str(item.get("sku") or "").strip()
        if it_sku and it_sku.lower() == sku.strip().lower():
            return True
    if name:
        it_name = str(item.get("item_name") or item.get("title") or "").strip().lower()
        q = name.strip().lower()
        if q and (q in it_name or it_name in q):
            return True
    return False


# ── Public tool entry points ─────────────────────────────────────────


async def check(args: dict[str, Any]) -> dict[str, Any]:
    """재고 조회.

    Args (셋 중 하나라도 필요):
      - item_id (UUID str, 옵션): 정확한 document id.
      - sku (str, 옵션): SKU.
      - item_name (str, 옵션): 상품명 (case-insensitive substring).
      - tenant_id (UUID, 필수, auto-injected).

    반환:
      매칭 1건: ``{success, item: {...}, current_qty, status, last_updated, summary}``
      매칭 다건: ``{success, matched, candidates: [...top 5...]}`` — disambiguate.
      매칭 0건: ``{success: False, matched: 0, summary}``.
    """
    if _store_mode() != "kms":
        return {
            "success": False,
            "error": "inventory tool 은 AGENT_DATA_STORE=kms 환경에서만 동작",
        }

    tenant_id, err = _require_tenant(args)
    if err:
        return err
    assert tenant_id is not None

    item_id = args.get("item_id") or args.get("id")
    sku = args.get("sku")
    name = args.get("item_name") or args.get("name")
    if not (item_id or sku or name):
        return {
            "success": False,
            "error": "item_id / sku / item_name 중 최소 하나 필요",
        }

    items = await agent_document_store.list_items(
        _get_shared_engine(),
        tenant_id,
        _DOCUMENT_TYPE,
    )
    matches = [it for it in items if _matches(it, name=name, sku=sku, item_id=item_id)]

    if not matches:
        return {
            "success": False,
            "matched": 0,
            "summary": (
                f"'{name or sku or item_id}' 와 일치하는 재고 항목을 찾지 못했습니다."
            ),
        }
    if len(matches) > 1 and not item_id:
        # disambiguate — 답변 LLM 이 사용자에게 "어떤 거?" 라고 묻게.
        return {
            "success": True,
            "matched": len(matches),
            "candidates": [
                {
                    "id": c.get("id"),
                    "item_name": c.get("item_name") or c.get("title"),
                    "sku": c.get("sku"),
                    "current_qty": c.get("current_qty"),
                }
                for c in matches[:5]
            ],
            "summary": f"동일 키워드로 {len(matches)}건이 검색됩니다. SKU 또는 정확한 상품명으로 알려 주세요.",
        }

    item = matches[0]
    qty_raw = item.get("current_qty")
    try:
        qty = int(qty_raw) if qty_raw is not None else 0
    except (TypeError, ValueError):
        qty = 0
    low_threshold_raw = item.get("low_threshold")
    try:
        low_threshold = int(low_threshold_raw) if low_threshold_raw is not None else _DEFAULT_LOW_THRESHOLD
    except (TypeError, ValueError):
        low_threshold = _DEFAULT_LOW_THRESHOLD

    status = _classify_status(qty, low_threshold)
    item_label = item.get("item_name") or item.get("title") or "(이름 없음)"

    summary_map = {
        "in_stock": f"재고 있음 — {item_label} · 현재 {qty}개",
        "low": f"재고 적음 — {item_label} · 현재 {qty}개 (임계 {low_threshold})",
        "out_of_stock": f"품절 — {item_label}",
    }

    return {
        "success": True,
        "matched": 1,
        "item": {
            "id": item.get("id"),
            "item_name": item_label,
            "sku": item.get("sku"),
        },
        "current_qty": qty,
        "low_threshold": low_threshold,
        "last_updated": item.get("last_updated"),
        "restock_eta": item.get("restock_eta"),
        "status": status,
        "summary": summary_map[status],
    }
