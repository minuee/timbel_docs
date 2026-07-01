"""PR-AA1 — 가계부 (지출) 저장소. schedule_store 와 같은 dual-backend 패턴.

★ 직전 버그 수정: 이전엔 ``expense_logger`` skill 이 ``tool: kms_search`` 호출만
하고 실제 저장 없음 → "기록 완료" 응답은 LLM hallucination. 본 파일이 *실 저장
인프라* 제공.

env ``AGENT_DATA_STORE``:
- ``redis`` (default) — phone-scoped 리스트.
- ``kms``               — agent_documents (tenant_id scoped, document_type=agent_expense).

Schema (한 지출 = 한 item/document):
- ``id`` (UUID)
- ``amount`` (int, 원)
- ``category`` (식비/교통/주거/여가/의료/교육/기타 — LLM 자동 분류)
- ``description`` (영수증 / 가게명 / 상품)
- ``spent_at`` (ISO date or datetime)
- ``payment_method`` (선택, 카드/현금/계좌이체 등)
- ``raw_utterance`` (사용자 원 발화 — 디버깅·재해석용)

Idempotency:
- (scope, spent_at, amount, description) 동일 시 silent skip + duplicate flag.
- "샐러드 13000원 두 번 입력" 시 두 줄 안 만듦.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools import _redis_store as rs
from src.agent_framework.tools.outcomes import (
    OutcomeKind,
    ToolOutcome,
    ToolResult,
    ToolResultMeta,
)
from src.common.config import settings


_CATEGORY = "expense"
_DOCUMENT_TYPE = "agent_expense"


_SHARED_ENGINE: AsyncEngine | None = None


def _get_shared_engine() -> AsyncEngine:
    global _SHARED_ENGINE
    if _SHARED_ENGINE is None:
        _SHARED_ENGINE = create_async_engine(settings.DATABASE_URL)
    return _SHARED_ENGINE


def _store_mode() -> str:
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
    """D23 §7 — engine 의 admin sentinel 만 storage 로 forward."""
    sentinel = args.get("_admin_null_owner_sentinel")
    if sentinel is agent_document_store.ADMIN_NULL_OWNER_OK:
        return agent_document_store.ADMIN_NULL_OWNER_OK
    return False


def _normalize_date(raw: Any) -> str:
    """spent_at 자연어/ISO → ISO date. 빈값/실패 → 오늘.

    LLM 이 args 에 자연어 ("오늘", "어제") 도 넣을 수 있어 graceful 처리.
    """
    if isinstance(raw, _dt.date):
        return raw.isoformat()
    s = str(raw or "").strip()
    if not s:
        return _dt.date.today().isoformat()
    try:
        return _dt.date.fromisoformat(s[:10]).isoformat()
    except (ValueError, TypeError):
        pass
    today = _dt.date.today()
    if s in ("오늘", "today"):
        return today.isoformat()
    if s in ("어제", "yesterday"):
        return (today - _dt.timedelta(days=1)).isoformat()
    if s == "그저께":
        return (today - _dt.timedelta(days=2)).isoformat()
    return today.isoformat()


def _coerce_amount(raw: Any) -> int:
    """amount 자연어/문자열 → int (원).

    LLM 이 "13,000원" / "1만3천원" / 13000 등 다양하게 넘길 수 있어 단순 변환만.
    복잡한 한국어 숫자 ("일만 삼천원") 는 plan_generator 에서 미리 정규화 권장.
    """
    if isinstance(raw, int):
        return raw
    s = str(raw or "0").strip()
    s = s.replace(",", "").replace(" ", "")
    # "원" / "₩" 제거
    for suf in ("원", "₩", "krw", "KRW"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    try:
        return int(s)
    except ValueError:
        # "1만3천" 같은 한국어 숫자는 LLM 이 미리 ISO 로 보내야 — fallback 0
        return 0


def _dedup_signature(spent_at: Any, amount: Any, description: Any) -> str:
    base = f"{_normalize_date(spent_at)}|{_coerce_amount(amount)}|{(description or '').strip().lower()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _duplicate_response(
    existing_id: str,
    *,
    spent_at: str | None = None,
    amount: int | None = None,
    category: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """P11-19f — duplicate 시 정보 echo. '이미 등록된: 2026-04-30 식비 17,000원
    (점심비)' 같이 어떤 항목인지 사용자가 즉시 확인. 이전엔 한 줄 안내만 → judge
    가 '금액 정보 없음' 으로 fail 다발.
    """
    parts = []
    if spent_at:
        parts.append(spent_at)
    if category:
        parts.append(category)
    if amount is not None:
        parts.append(f"{amount:,}원")
    if description:
        parts.append(f"({description})")
    detail = " ".join(parts)
    summary = (
        f"이미 동일 지출이 기록되어 있습니다 — {detail}"
        if detail
        else "이미 동일 지출이 기록되어 있습니다"
    )
    return {
        "id": existing_id,
        "success": True,
        "duplicate": True,
        "spent_at": spent_at,
        "amount": amount,
        "category": category,
        "description": description,
        "summary": summary,
    }


async def create(args: dict[str, Any]) -> dict[str, Any]:
    """지출 기록 생성.

    Args:
    - amount (int|str): 금액 (원). LLM 이 "13000" 또는 "13,000원" 으로 넘길 수 있음.
    - category (str): 식비 / 교통 / 주거 / 여가 / 의료 / 교육 / 기타 (LLM 분류).
    - description (str): 가게명 / 상품 / 영수증 한 줄.
    - spent_at (str): ISO 또는 자연어. 빈값 → 오늘.
    - payment_method (str, 옵션)
    - raw_utterance (str, 옵션): 사용자 원 발화.
    - tenant_id 또는 phone (engine 자동 주입).

    반환: {id, success, duplicate?, summary}
    """
    amount = _coerce_amount(args.get("amount"))
    category = str(args.get("category") or "기타").strip() or "기타"
    description = str(args.get("description") or "").strip()
    spent_at = _normalize_date(args.get("spent_at"))
    payment_method = (args.get("payment_method") or None)
    raw_utt = str(args.get("raw_utterance") or "").strip()

    sig = _dedup_signature(spent_at, amount, description)

    body = {
        "amount": amount,
        "category": category,
        "description": description,
        "spent_at": spent_at,
        "payment_method": payment_method,
        "raw_utterance": raw_utt or None,
    }

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"success": False, "error": "tenant_id required when AGENT_DATA_STORE=kms"}
        scope_group = args.get("scope_group") or "personal"
        owner_agent_uuid = _owner_agent_uuid(args)
        try:
            # D23 §1 — dedup 도 동일 owner 안에서.
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
            if _dedup_signature(
                it_body.get("spent_at"), it_body.get("amount"), it_body.get("description"),
            ) == sig:
                return _duplicate_response(
                    str(it.get("id", "")),
                    spent_at=spent_at,
                    amount=amount,
                    category=category,
                    description=description,
                )
        try:
            doc_id = await agent_document_store.create_item(
                _get_shared_engine(),
                UUID(str(tenant_id)),
                _DOCUMENT_TYPE,
                title=description or f"{amount}원 {category}",
                body=body,
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
            "summary": f"{spent_at} {category} {amount:,}원 기록 ({description})",
        }

    # DEPRECATED (D24 §2, 2026-05-08) — agent 격리 X.
    # AGENT_DATA_STORE=kms 권장. 후속 제거 plan: D25.
    # redis (legacy)
    phone = args.get("phone")
    if not phone:
        return {"success": False, "error": "phone required when AGENT_DATA_STORE=redis"}
    try:
        existing = await rs.list_items(_CATEGORY, phone)
    except Exception:
        existing = []
    for it in existing:
        if _dedup_signature(it.get("spent_at"), it.get("amount"), it.get("description")) == sig:
            return _duplicate_response(
                str(it.get("id", "")),
                spent_at=spent_at,
                amount=amount,
                category=category,
                description=description,
            )
    item = {"id": str(uuid.uuid4()), **body}
    await rs.rpush_item(_CATEGORY, phone, item)
    return {
        "id": item["id"],
        "success": True,
        "summary": f"{spent_at} {category} {amount:,}원 기록 ({description})",
    }


async def list_all(args: dict[str, Any]) -> dict[str, Any]:
    """지출 목록 조회. 기간 필터 옵션."""
    period_start = args.get("period_start")
    period_end = args.get("period_end")

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"items": [], "error": "tenant_id required when AGENT_DATA_STORE=kms"}
        owner_agent_uuid = _owner_agent_uuid(args)
        include_null_arg = _resolve_null_owner_arg(args)
        items = await agent_document_store.list_items(
            _get_shared_engine(),
            UUID(str(tenant_id)),
            _DOCUMENT_TYPE,
            scope_group=args.get("scope_group"),
            owner_agent_id=owner_agent_uuid,
            include_null_owner=include_null_arg,
        )
    else:
        phone = args.get("phone")
        if not phone:
            return {"items": [], "error": "phone required when AGENT_DATA_STORE=redis"}
        items = await rs.list_items(_CATEGORY, phone)

    # 기간 필터 (옵션) — LLM 이 args 에 ISO 날짜로 넘김
    if period_start or period_end:
        ps = _normalize_date(period_start) if period_start else "0000-01-01"
        pe = _normalize_date(period_end) if period_end else "9999-12-31"
        items = [
            it
            for it in items
            if ps <= _normalize_date((it.get("body") or it).get("spent_at")) <= pe
        ]
    return {"items": items}


async def sum_by_category(args: dict[str, Any]) -> dict[str, Any]:
    """기간 내 카테고리별 합계. analyzer skill 의 핵심 도구.

    반환: {total, by_category: {식비: 50000, 교통: 12000, ...}, count, period}
    """
    listed = await list_all(args)
    items = listed.get("items") or []
    total = 0
    by_category: dict[str, int] = {}
    for it in items:
        body = it.get("body") or it
        amt = _coerce_amount(body.get("amount"))
        cat = str(body.get("category") or "기타").strip() or "기타"
        total += amt
        by_category[cat] = by_category.get(cat, 0) + amt
    # 사용자가 "방금 기록한 거" 같이 개별 항목을 알고 싶을 때를 대비해 items 도
    # 함께 노출. analyzer 템플릿이 by_category·total 만 보여줄지, 항목까지 보여줄지
    # 결정.
    flat_items = []
    for it in items:
        body = it.get("body") if isinstance(it, dict) else None
        flat = dict(body) if body else dict(it)
        # P11-19 — id 보존. LLM 이 후속 turn 에서 expense.delete 로 id 참조 가능.
        if "id" not in flat:
            flat["id"] = it.get("id") if isinstance(it, dict) else None
        flat_items.append(flat)
    return {
        "success": True,
        "total": total,
        "by_category": by_category,
        "count": len(items),
        "items": flat_items,
        "period": {
            "start": _normalize_date(args.get("period_start")) if args.get("period_start") else None,
            "end": _normalize_date(args.get("period_end")) if args.get("period_end") else None,
        },
        "summary": (
            f"기간 내 총 {len(items)}건, 합계 {total:,}원"
            + (f" — " + ", ".join(f"{k} {v:,}원" for k, v in sorted(by_category.items(), key=lambda x: -x[1])[:5]) if by_category else "")
        ),
    }


async def update(args: dict[str, Any]) -> dict[str, Any]:
    """지출 항목 수정 — id 또는 매칭 조건으로 기존 row 찾아 patch.

    P11-19g (2026-05-01) — expense_update 회귀 (15% PASS) 직접 해결. 이전엔
    plan path 가 update = expense.delete + expense.create 2-step 으로 풀었으나
    응답 톤이 "삭제 실패 + 신규 등록" 으로 사용자 의도와 어긋남.

    args:
      매칭 조건 (셋 중 하나 이상):
        - id (str)
        - description (str, substring 매칭)
        - spent_at (ISO date)
        - amount (int 원, 매칭용 — 옛 값)

      변경 필드 (None 이면 기존 보존):
        - new_amount (int)
        - new_category (str)
        - new_description (str)
        - new_spent_at (str ISO)

      tenant_id 또는 phone — 식별.

    반환: {success, updated_count, summary}.
    """
    item_id = args.get("id")
    description = (args.get("description") or "").strip().lower()
    spent_at = _normalize_date(args.get("spent_at")) if args.get("spent_at") else None
    target_amount = _coerce_amount(args.get("amount")) if args.get("amount") is not None else None

    if not item_id and not (description or spent_at or target_amount is not None):
        return {
            "success": False,
            "error": "id 또는 (description / spent_at / amount) 중 하나 이상 필요",
        }

    # 변경 필드 — None 이면 기존 보존.
    patch: dict[str, Any] = {}
    if args.get("new_amount") is not None:
        patch["amount"] = _coerce_amount(args["new_amount"])
    if args.get("new_category"):
        patch["category"] = str(args["new_category"]).strip()
    if args.get("new_description") is not None:
        patch["description"] = str(args["new_description"]).strip()
    if args.get("new_spent_at"):
        patch["spent_at"] = _normalize_date(args["new_spent_at"])
    if not patch:
        return {
            "success": False,
            "error": "변경할 필드 (new_amount / new_category / new_description / new_spent_at) 중 하나 이상 필요",
        }

    def _matches(item: dict[str, Any]) -> bool:
        body = item.get("body") if isinstance(item, dict) and "body" in item else item
        if item_id and str(item.get("id") or body.get("id")) == str(item_id):
            return True
        if not (description or spent_at or target_amount is not None):
            return False
        if description:
            d = (body.get("description") or "").lower()
            if description not in d:
                return False
        if spent_at:
            sa = _normalize_date(body.get("spent_at"))
            if sa != spent_at:
                return False
        if target_amount is not None:
            a = _coerce_amount(body.get("amount"))
            if a != target_amount:
                return False
        return True

    def _summary_one(body_after: dict, count: int) -> str:
        sa = body_after.get("spent_at") or ""
        cat = body_after.get("category") or ""
        amt = _coerce_amount(body_after.get("amount"))
        desc = body_after.get("description") or ""
        if count > 1:
            return f"지출 {count} 건을 수정했습니다 — {sa} {cat} {amt:,}원 ({desc})"
        return f"지출 수정 완료 — {sa} {cat} {amt:,}원 ({desc})"

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"success": False, "error": "tenant_id required when AGENT_DATA_STORE=kms"}
        owner_agent_uuid = _owner_agent_uuid(args)
        try:
            existing = await agent_document_store.list_items(
                _get_shared_engine(), UUID(str(tenant_id)), _DOCUMENT_TYPE,
                owner_agent_id=owner_agent_uuid,
            )
        except Exception:
            existing = []
        matched = [it for it in existing if _matches(it)]
        if not matched:
            return {
                "success": False,
                "updated_count": 0,
                "summary": "조건에 맞는 지출을 찾지 못해 수정하지 못했습니다.",
            }
        last_body = None
        for it in matched:
            body = it.get("body") if isinstance(it, dict) and "body" in it else it
            new_body = {**body, **patch}
            await agent_document_store.update_item(
                _get_shared_engine(),
                UUID(str(tenant_id)),
                _DOCUMENT_TYPE,
                str(it.get("id")),
                body_patch=new_body,
                owner_agent_id=owner_agent_uuid,
            )
            last_body = new_body
        return {
            "success": True,
            "updated_count": len(matched),
            "summary": _summary_one(last_body or {}, len(matched)),
        }

    # redis
    phone = args.get("phone")
    if not phone:
        return {"success": False, "error": "phone required when AGENT_DATA_STORE=redis"}
    items = await rs.list_items(_CATEGORY, phone)
    new_items = []
    matched_count = 0
    last_body = None
    for it in items:
        if _matches(it):
            updated = {**it, **patch}
            new_items.append(updated)
            last_body = updated
            matched_count += 1
        else:
            new_items.append(it)
    if not matched_count:
        return {
            "success": False,
            "updated_count": 0,
            "summary": "조건에 맞는 지출을 찾지 못해 수정하지 못했습니다.",
        }
    await rs.replace_items(_CATEGORY, phone, new_items)
    return {
        "success": True,
        "updated_count": matched_count,
        "summary": _summary_one(last_body or {}, matched_count),
    }


def _is_valid_uuid(raw: Any) -> bool:
    """UUID 형식 엄격 검증 — LLM 이 임의 문자열 ('첫번째' / '식비' 등) 을 id 로

    넘기는 것 차단. UUID 객체이거나 UUID parsable string 만 통과.
    """
    if isinstance(raw, UUID):
        return True
    s = str(raw or "").strip()
    if not s:
        return False
    try:
        UUID(s)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _id_required_response() -> dict[str, Any]:
    """id 가 누락/유효하지 않을 때 표준 INVALID_INPUT 응답.

    Phase 1.5A Task 8e — broad mutation 차단 가드. LLM 은 list/sum_by_category
    로 id 확보 후 다시 호출해야 함 (preview-confirm 패턴).
    """
    result = ToolResult(
        success=True,
        summary="삭제 대상 ID 가 필요합니다",
        meta=ToolResultMeta(
            outcome=ToolOutcome.INVALID_INPUT,
            reason="id_required",
            kind=OutcomeKind.VALIDATION.value,
            user_action_required=True,
        ),
    )
    payload = result.to_dict()
    # 기존 호출자 호환 — deleted_count / error 필드도 예측 가능하게 노출.
    payload.setdefault("deleted_count", 0)
    payload.setdefault("error", "id (UUID) 가 필요합니다 — 먼저 list/sum_by_category 로 ID 확보 후 호출하세요.")
    return payload


async def delete(args: dict[str, Any]) -> dict[str, Any]:
    """지출 삭제 — id (UUID) 단건만 허용.

    Phase 1.5A Task 8e (2026-05-07): GPT-5.5 deep dive 발견 결함 차단.
    이전엔 ``description`` / ``spent_at`` / ``amount`` 만으로도 broad mutation
    가능 (예: ``delete(amount=5000)`` 5천원짜리 모든 지출 일괄 삭제). 이제 id
    필수 — LLM 이 list/sum_by_category 로 id 확보 후 *그 id 만으로* 호출 강제.

    args:
      - id (UUID str, 필수) — 삭제 대상 단건 id.
      - tenant_id / phone — 식별 (engine 자동 주입).

    *id 외 다른 필터 (description/spent_at/amount/category) 가 함께 와도 무시*
    — id 가 sufficient. 의도치 않은 broad delete 방지.

    반환:
      - 정상: {success: True, deleted_count: 0|1, summary, meta.outcome: ok|not_found}
      - id 누락/유효 X: {success: True, deleted_count: 0,
                         meta.outcome: invalid_input, reason: id_required}
    """
    raw_id = args.get("id")
    if not _is_valid_uuid(raw_id):
        return _id_required_response()
    item_id = str(raw_id)

    if _store_mode() == "kms":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {
                "success": False,
                "deleted_count": 0,
                "error": "tenant_id required when AGENT_DATA_STORE=kms",
            }
        owner_agent_uuid = _owner_agent_uuid(args)
        ok = await agent_document_store.delete_item(
            _get_shared_engine(), UUID(str(tenant_id)), _DOCUMENT_TYPE, item_id,
            owner_agent_id=owner_agent_uuid,
        )
        return {
            "success": bool(ok),
            "deleted_count": 1 if ok else 0,
            "summary": (
                "지출 1 건 삭제했습니다." if ok else "삭제할 항목을 찾지 못했습니다."
            ),
        }

    # redis
    phone = args.get("phone")
    if not phone:
        return {
            "success": False,
            "deleted_count": 0,
            "error": "phone required when AGENT_DATA_STORE=redis",
        }
    ok = await rs.remove_by_id(_CATEGORY, phone, item_id)
    return {
        "success": bool(ok),
        "deleted_count": 1 if ok else 0,
        "summary": "지출 1 건 삭제했습니다." if ok else "삭제할 항목을 찾지 못했습니다.",
    }
