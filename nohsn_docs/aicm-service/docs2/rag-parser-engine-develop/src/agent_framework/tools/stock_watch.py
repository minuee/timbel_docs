"""사용자 보유·관심 종목 + 모니터링 잡 저장소.

데이터 모델 (agent_documents 백엔드, document_type='agent_stock_watch'):

- ``code`` (str, 6자리)        — KRX 종목 코드
- ``name`` (str)               — 종목명 (캐시본, 표시용)
- ``qty`` (int|None)           — 보유 수량 (없으면 watchlist only)
- ``avg_cost`` (int|None)      — 평단가 (원)
- ``alert_high`` (int|None)    — 상단 alert 가격
- ``alert_low`` (int|None)     — 하단 alert 가격
- ``monitor_interval_min``     — 모니터링 주기 (분, 0 = 모니터 끔)
- ``last_monitor_at``          — 마지막 모니터 실행 ISO datetime
- ``note`` (str)               — 사용자 메모
- ``created_at`` (ISO str)

도구:
- ``stock.add_watch`` — 추가
- ``stock.list_watch`` — 목록 + 현재가/손익 동시 조회
- ``stock.update_watch`` — 일부 필드 수정
- ``stock.delete_watch`` — 삭제
"""
from __future__ import annotations

import datetime as _dt
import os
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools import _redis_store as rs
from src.agent_framework.tools import stock_data
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


_CATEGORY = "stock_watch"
_DOCUMENT_TYPE = "agent_stock_watch"


_SHARED_ENGINE: AsyncEngine | None = None


def _get_shared_engine() -> AsyncEngine:
    global _SHARED_ENGINE
    if _SHARED_ENGINE is None:
        _SHARED_ENGINE = create_async_engine(settings.DATABASE_URL)
    return _SHARED_ENGINE


def _store_mode() -> str:
    return os.environ.get("AGENT_DATA_STORE", "redis").lower()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


async def add_watch(args: dict[str, Any]) -> dict[str, Any]:
    """관심·보유 종목 추가.

    Args:
    - symbol|name|code: 종목명 또는 코드 (필수)
    - qty: 보유 수량 (옵션 — 없으면 watchlist only)
    - avg_cost: 평단가 (옵션)
    - alert_high / alert_low: alert 가격 (옵션)
    - monitor_interval_min: 모니터링 주기, 분 (옵션, 0 = 끔)
    - note: 메모 (옵션)
    - tenant_id 또는 phone (engine 자동 주입)
    """
    # P11-19b — args 이름 일관성 (plan_intents/stock.md = code_or_name).
    raw = (
        args.get("code_or_name")
        or args.get("symbol")
        or args.get("name")
        or args.get("code")
        or args.get("query")
    )
    code, resolved_name = await stock_data.resolve_ticker(str(raw or ""))
    if not code:
        # P11-19m: 종목 인식 실패도 사용자 입력 (원래 종목명 + 가격/조건) echo.
        _alert_h = args.get("alert_high")
        _alert_l = args.get("alert_low")
        _qty_in = args.get("qty") or args.get("quantity")
        _avg_in = args.get("avg_cost") or args.get("price")
        echo_parts = [str(raw)]
        if _alert_h:
            echo_parts.append(f"상한 {_alert_h:,}원" if isinstance(_alert_h, int) else f"상한 {_alert_h}")
        if _alert_l:
            echo_parts.append(f"하한 {_alert_l:,}원" if isinstance(_alert_l, int) else f"하한 {_alert_l}")
        if _qty_in:
            echo_parts.append(f"{_qty_in}주")
        if _avg_in:
            echo_parts.append(f"평단 {_avg_in:,}원" if isinstance(_avg_in, int) else f"평단 {_avg_in}")
        echo = " · ".join(echo_parts)
        return {
            "success": False,
            "error": "종목 인식 실패",
            "summary": (
                f"종목 인식 실패 ({echo}). 종목명 또는 6자리 코드로 알려주세요. "
                f"미국 주식은 현재 미지원."
            ),
        }
    name = resolved_name or str(args.get("name") or code)

    qty = args.get("qty") or args.get("quantity")
    avg_cost = args.get("avg_cost") or args.get("price") or args.get("cost")
    qty_i = int(qty) if (qty is not None and str(qty).strip()) else None
    avg_cost_i = int(avg_cost) if (avg_cost is not None and str(avg_cost).strip()) else None

    # P10l (2026-04-29): alert 임계값 (high/low) 가 있으면 monitor_interval_min
    # default 30분. 사용자 chat "23만원 되면 알려줘" 가 monitor_interval_min 명시
    # 없이 alert_high 만 설정 → interval=0 → 모니터링 안 도는 회귀.
    _alert_high = args.get("alert_high")
    _alert_low = args.get("alert_low")
    _user_interval = args.get("monitor_interval_min")
    if _user_interval is None and (_alert_high is not None or _alert_low is not None):
        _user_interval = 30
    body = {
        "code": code,
        "name": name,
        "qty": qty_i,
        "avg_cost": avg_cost_i,
        "alert_high": _alert_high,
        "alert_low": _alert_low,
        "monitor_interval_min": int(_user_interval or 0),
        "note": str(args.get("note") or "").strip() or None,
        "created_at": _now_iso(),
        "last_monitor_at": None,
    }

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"success": False, "error": "tenant_id required"}
        scope_group = args.get("scope_group") or "personal"
        try:
            existing = await agent_document_store.list_items(
                _get_shared_engine(),
                UUID(str(tenant_id)),
                _DOCUMENT_TYPE,
                scope_group=scope_group,
            )
        except Exception:
            existing = []
        for it in existing:
            b = it.get("body") if isinstance(it, dict) else {}
            if isinstance(b, dict) and b.get("code") == code:
                # 이미 등록된 종목 — qty/avg_cost/alert 업데이트
                merged = dict(b)
                for k in ("qty", "avg_cost", "alert_high", "alert_low", "monitor_interval_min", "note"):
                    if body.get(k) is not None:
                        merged[k] = body[k]
                merged["updated_at"] = _now_iso()
                ok = await agent_document_store.update_item(
                    _get_shared_engine(),
                    UUID(str(tenant_id)),
                    _DOCUMENT_TYPE,
                    str(it.get("id")),
                    body_patch=merged,
                )
                return {
                    "success": bool(ok),
                    "id": str(it.get("id")),
                    "code": code,
                    "name": name,
                    "merged": True,
                    "summary": f"{name} ({code}) 종목 정보 업데이트 — 수량 {merged.get('qty') or '-'}, 평단 {merged.get('avg_cost') or '-'}원",
                }
        doc_id = await agent_document_store.create_item(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            title=f"{name} ({code})",
            body=body,
            scope_group=scope_group,
        )
        return {
            "success": True,
            "id": str(doc_id),
            "code": code,
            "name": name,
            "summary": _build_register_summary(name, code, qty_i, avg_cost_i, body),
        }

    # DEPRECATED (D24 §2, 2026-05-08) — agent 격리 X.
    # AGENT_DATA_STORE=kms 권장. 후속 제거 plan: D25.
    # redis (legacy) — P11-10 (2026-04-29): KMS mode 와 동등하게 dedup-by-code.
    # 동일 종목이 이미 있으면 신규 row 추가 X, 기존 row 의 비-None 필드 merge.
    # 사용자: "삼성전자 53주 등록" → "수량 530주야" → 신규 row 가 또 추가되던 회귀.
    phone = args.get("phone")
    if not phone:
        return {"success": False, "error": "phone or tenant_id required"}
    try:
        existing = await rs.list_items(_CATEGORY, phone)
    except Exception:
        existing = []
    for ex in existing:
        if isinstance(ex, dict) and ex.get("code") == code:
            # 같은 종목 — 비-None 필드만 merge (None 은 옛 값 보존).
            merged = dict(ex)
            for k in (
                "qty",
                "avg_cost",
                "alert_high",
                "alert_low",
                "monitor_interval_min",
                "note",
                "name",
            ):
                if body.get(k) is not None:
                    merged[k] = body[k]
            merged["updated_at"] = _now_iso()
            new_items = [
                merged if (isinstance(it, dict) and it.get("id") == ex.get("id")) else it
                for it in existing
            ]
            await rs.replace_items(_CATEGORY, phone, new_items)
            return {
                "success": True,
                "id": str(ex.get("id")),
                "code": code,
                "name": name,
                "merged": True,
                "summary": _build_register_summary(
                    name, code, merged.get("qty"), merged.get("avg_cost"), merged
                )
                + " (기존 항목과 병합)",
            }
    item = {"id": str(uuid.uuid4()), **body}
    await rs.rpush_item(_CATEGORY, phone, item)
    return {
        "success": True,
        "id": item["id"],
        "code": code,
        "name": name,
        "summary": _build_register_summary(name, code, qty_i, avg_cost_i, body),
    }


def _build_register_summary(
    name: str,
    code: str,
    qty: int | None,
    avg_cost: int | None,
    body: dict[str, Any],
) -> str:
    """P11-9 (사용자 요청): 모니터링 동작 방식까지 설명하는 응답 본문.

    chat 응답이 사용자에게 무엇이 어떻게 작동할지 명확히 알려야 신뢰 형성.
    """
    parts: list[str] = [f"{name} ({code}) 등록 완료."]
    detail: list[str] = []
    if qty:
        detail.append(f"수량 {qty}주")
    if avg_cost:
        detail.append(f"평단 {avg_cost:,}원")
    if detail:
        parts.append(" · ".join(detail) + ".")

    interval = body.get("monitor_interval_min") or 0
    alert_high = body.get("alert_high")
    alert_low = body.get("alert_low")
    if interval:
        parts.append(f"매 {interval}분마다 시세 확인.")
        if alert_high:
            parts.append(f"가격이 {alert_high:,}원 이상이면 챗·피드로 알림.")
        if alert_low:
            parts.append(f"가격이 {alert_low:,}원 이하이면 챗·피드로 알림.")
        if not alert_high and not alert_low:
            parts.append("(임계값 없음 — 단순 시세 추적만)")
    else:
        parts.append("모니터링 주기 미설정 — 알림 없음.")
    return " ".join(parts)


async def list_watch(args: dict[str, Any]) -> dict[str, Any]:
    """관심·보유 종목 + 현재가 + 손익 한 번에.

    실시간 가격은 stock_data.quote 호출 (60s 캐시).
    """
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"items": [], "error": "tenant_id required"}
        items = await agent_document_store.list_items(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            scope_group=args.get("scope_group"),
        )
        # body 평탄화
        flat = []
        for it in items:
            b = it.get("body") if isinstance(it, dict) else {}
            if isinstance(b, dict):
                flat.append({"id": str(it.get("id")), **b})
    else:
        phone = args.get("phone")
        if not phone:
            return {"items": [], "error": "phone or tenant_id required"}
        flat = await rs.list_items(_CATEGORY, phone)

    # 각 종목 현재가 enrich
    enriched: list[dict] = []
    total_value = 0
    total_cost = 0
    for w in flat:
        code = w.get("code")
        if not code:
            continue
        q = await stock_data.quote({"symbol": code})
        cur = q.get("close") if q.get("success") else None
        chg_pct = q.get("change_pct") if q.get("success") else None
        qty = w.get("qty") or 0
        avg = w.get("avg_cost") or 0
        market_value = (cur or 0) * (qty or 0)
        cost_basis = (avg or 0) * (qty or 0)
        pnl = market_value - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis else None
        if qty and cur:
            total_value += market_value
            total_cost += cost_basis
        enriched.append({
            **w,
            "current_price": cur,
            "change_pct": chg_pct,
            "market_value": market_value if qty else None,
            "pnl": pnl if cost_basis else None,
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        })

    # 보유 우선 → 평가금액 큰 순
    enriched.sort(key=lambda x: (-(x.get("market_value") or 0), x.get("name") or ""))

    summary_total = total_value - total_cost
    return {
        "success": True,
        "items": enriched,
        "total_market_value": total_value if total_cost else None,
        "total_cost": total_cost or None,
        "total_pnl": summary_total if total_cost else None,
        "total_pnl_pct": round(summary_total / total_cost * 100, 2) if total_cost else None,
        "summary": (
            f"보유·관심 {len(enriched)}건"
            + (f" · 평가 {total_value:,}원 · 손익 {summary_total:+,}원 ({summary_total/total_cost*100:+.2f}%)" if total_cost else "")
        ),
    }


async def update_watch(args: dict[str, Any]) -> dict[str, Any]:
    """일부 필드 수정. id 또는 (code + match_qty / match_avg_cost) 로 식별.

    P11-10 (2026-04-29): 사용자가 "53주짜리를 530주로 바꿔줘" 처럼 자연어로
    지정한 경우 LLM 이 args 에 `code`, `match_qty=53`, `qty=530` 식으로 전달
    가능하게 확장. id 명시 시 옛 path 그대로.

    redis (legacy) mode 도 지원 — 옛에는 add_watch 가 dedup 안 해서 update 가
    필요 없다고 가정했지만 P11-10 후엔 add_watch 가 dedup 하므로 update 도 redis
    에서 동등히 동작해야 함.
    """
    item_id = args.get("id")
    # P11-19b — code 인자도 종목명일 수 있음. resolve_ticker 로 정규화.
    code_raw = (
        args.get("code")
        or args.get("symbol")
        or args.get("code_or_name")
        or args.get("name")
    )
    code = code_raw
    if code_raw and not (str(code_raw).isdigit() and len(str(code_raw)) == 6):
        resolved_code, _ = await stock_data.resolve_ticker(str(code_raw))
        if resolved_code:
            code = resolved_code
    match_qty = args.get("match_qty") or args.get("qty")
    match_avg = args.get("match_avg_cost") or args.get("avg_cost") or args.get("price")
    if not item_id and not (code and (match_qty is not None or match_avg is not None)):
        return {
            "success": False,
            "error": "id or (code + match_qty/match_avg_cost) required",
        }

    if _store_mode() != "kms":
        # redis path — id 또는 (code + match) 매칭.
        phone = args.get("phone")
        if not phone:
            return {"success": False, "error": "phone required (redis mode)"}
        flat = await rs.list_items(_CATEGORY, phone)
        target = None
        if item_id:
            target = next(
                (it for it in flat if isinstance(it, dict) and it.get("id") == item_id),
                None,
            )
        else:
            for it in flat:
                if not isinstance(it, dict) or it.get("code") != code:
                    continue
                if match_qty is not None and it.get("qty") != int(match_qty):
                    continue
                if match_avg is not None and it.get("avg_cost") != int(match_avg):
                    continue
                target = it
                break
        if target is None:
            return {"success": False, "error": "watch not found"}
        merged = dict(target)
        for k in (
            "qty",
            "avg_cost",
            "alert_high",
            "alert_low",
            "monitor_interval_min",
            "note",
        ):
            if args.get(k) is not None:
                merged[k] = args[k]
        merged["updated_at"] = _now_iso()
        new_items = [
            merged if (isinstance(it, dict) and it.get("id") == target.get("id")) else it
            for it in flat
        ]
        await rs.replace_items(_CATEGORY, phone, new_items)
        return {
            "success": True,
            "id": str(target.get("id")),
            "code": merged.get("code"),
            "name": merged.get("name"),
            "summary": (
                f"{merged.get('name')} ({merged.get('code')}) 항목 수정 — "
                f"수량 {merged.get('qty') or '-'}, "
                f"평단 {merged.get('avg_cost') or '-'}원"
            ),
        }
    tenant_id = args.get("tenant_id")
    if not tenant_id:
        return {"success": False, "error": "tenant_id required"}
    items = await agent_document_store.list_items(
        _get_shared_engine(),
        UUID(str(tenant_id)),
        _DOCUMENT_TYPE,
    )
    target = next((it for it in items if str(it.get("id")) == str(item_id)), None)
    if not target:
        return {"success": False, "error": "not found"}
    b = dict(target.get("body") or {})
    for k in ("qty", "avg_cost", "alert_high", "alert_low", "monitor_interval_min", "note"):
        if k in args and args[k] is not None:
            b[k] = args[k]
    b["updated_at"] = _now_iso()
    ok = await agent_document_store.update_item(
        _get_shared_engine(),
        UUID(str(tenant_id)),
        _DOCUMENT_TYPE,
        str(item_id),
        body_patch=b,
    )
    return {"success": bool(ok), "id": str(item_id), "summary": f"{b.get('name')} 정보 업데이트"}


async def delete_watch(args: dict[str, Any]) -> dict[str, Any]:
    item_id = args.get("id")
    if not item_id:
        return {"success": False, "error": "id required"}
    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"success": False, "error": "tenant_id required"}
        ok = await agent_document_store.delete_item(
            _get_shared_engine(), UUID(str(tenant_id)), _DOCUMENT_TYPE, str(item_id)
        )
        return {"success": bool(ok)}
    phone = args.get("phone")
    if not phone:
        return {"success": False, "error": "phone or tenant_id required"}
    ok = await rs.remove_by_id(_CATEGORY, phone, str(item_id))
    return {"success": bool(ok)}
