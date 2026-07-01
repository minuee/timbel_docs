"""의도 단위 plan router (P11-19, 2026-04-29).

## 설계 원칙 (GPT-5.5 자문 + 사용자 메모리 정합)

GPT-5.5 자문 결론 (2026-04-29) — **A + D + 제한적 E** 조합:

- **A**: intent_classifier prompt 가 root cause. 주식 *행동* (시세/등록) 과 주식
  *정보* (시간/수수료/규정) 를 구분하도록 prompt 강화. (intent_classifier.py 책임)

- **D**: 라우터는 *결정적 코드 매핑* 우선. 단, *애매한 라벨* (stock_quote 처럼
  행동·정보 둘 다 가능) 만 *작은 LLM 호출* 로 재판단.

- **E (제한적)**: 모든 카테고리에 `kms_rag.search` 만 escape hatch 로 추가.
  `web.search` 까지 항상 노출하면 과검색·개인정보·hallucinated citation 위험.

라우터는 키워드 매칭 X (`feedback_pattern_over_case_enumeration` 정합).
표현 변형 일반화는 LLM 책임 — intent_classifier 또는 라우터의 disambiguation LLM.

## 토큰 절감 효과

기존 plan_generation.md = 29KB → base + 카테고리 가이드 = 평균 5KB (83% 감소).
LLM attention 밀도 회복 + 카테고리별 도구 서브셋 노출.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.common.logging import get_logger

log = get_logger(__name__)


# 의도 카테고리 enum (str 으로 사용)
INFO_LOOKUP = "info_lookup"
SCHEDULE = "schedule"
EXPENSE = "expense"
REMINDER = "reminder"
MEMO = "memo"
MAIL = "mail"
STOCK = "stock"
KMS_INVENTORY = "kms_inventory"
SMALL_TALK = "small_talk"
FALLBACK = "fallback"
# Phase 1.5C P0 — top 7 SMB 산업 핵심 도메인.
# reservation 은 schedule (개인 일정) 과 별도 — 매장 예약은 multi-tenant
# 격리 + 산업 SOP 차이가 큼. 분리 권고 (gap analysis report Q5).
RESERVATION = "reservation"
PAYMENT = "payment"
INVENTORY = "inventory"
DELIVERY = "delivery"

ALL_CATEGORIES = (
    INFO_LOOKUP, SCHEDULE, EXPENSE, REMINDER, MEMO, MAIL, STOCK,
    KMS_INVENTORY, SMALL_TALK, FALLBACK,
    RESERVATION, PAYMENT, INVENTORY, DELIVERY,
)


# ── intent label → category 결정적 매핑 ──────────────────────────────
# intent_classifier 가 라벨 분류 책임. 라우터는 매핑만.
# 새 intent 라벨 추가 시 여기에만 등록.

_INTENT_TO_CATEGORY: dict[str, str] = {
    # schedule (일정 등록·조회·수정·삭제)
    "create_schedule": SCHEDULE,
    "list_schedule": SCHEDULE,
    "update_schedule": SCHEDULE,
    "delete_schedule": SCHEDULE,

    # expense (지출)
    "log_expense": EXPENSE,
    "expense_analyzer": EXPENSE,
    "expense_log": EXPENSE,
    "expense_query": EXPENSE,
    "expense_delete": EXPENSE,
    "expense_summary": EXPENSE,

    # reminder (알람·리마인더)
    "set_reminder": REMINDER,
    "medication_tracker": REMINDER,
    "list_reminder": REMINDER,
    "cancel_reminder": REMINDER,

    # memo (캐주얼 캡처 + 마감 관리 — todo 노트)
    "memo_capture": MEMO,
    "memo_create": MEMO,
    "memo_list": MEMO,
    "memo_update": MEMO,
    "memo_delete": MEMO,
    "memo_complete": MEMO,
    "todo_capture": MEMO,
    "todo_complete": MEMO,

    # mail
    "mail_summary": MAIL,
    "mail_query": MAIL,
    "mail_search": MAIL,
    "inbox_summary": MAIL,
    "mail_send": MAIL,
    "send_mail": MAIL,
    "reply_mail": MAIL,

    # stock (시세·등록·모니터링·분석)
    "stock_price": STOCK,
    "stock_quote": STOCK,
    "stock_register": STOCK,
    "stock_watch": STOCK,
    "stock_update": STOCK,
    "stock_analyze": STOCK,

    # kms_inventory (자료 보유 메타)
    "kms_inventory_query": KMS_INVENTORY,
    "ask_my_data_inventory": KMS_INVENTORY,

    # info_lookup (지식 조회 — intent_classifier 에 명시적 라벨 필요)
    "info_lookup": INFO_LOOKUP,
    "knowledge_query": INFO_LOOKUP,

    # Phase 1.5C P0 — reservation (매장 예약, multi-tenant)
    "reservation_create": RESERVATION,
    "reservation_book": RESERVATION,
    "reservation_cancel": RESERVATION,
    "reservation_reschedule": RESERVATION,
    "reservation_check_availability": RESERVATION,

    # Phase 1.5C P0 — payment (결제 환불)
    "payment_refund": PAYMENT,
    "refund_request": PAYMENT,

    # Phase 1.5C P0 — inventory (재고)
    "inventory_check": INVENTORY,
    "inventory_query": INVENTORY,

    # Phase 1.5C P0 — delivery (배송 추적)
    "delivery_track": DELIVERY,
    "delivery_query": DELIVERY,

    # small talk
    "_capability_query": SMALL_TALK,
    "greeting": SMALL_TALK,
}


# ── 애매한 intent — 행동·정보 둘 다 가능 (D 안전망 트리거) ─────────────
# 이 셋에 들어가는 라벨은 *작은 LLM 호출* 로 발화 + 라벨을 보고 카테고리를
# 재판단. GPT-5.5 자문 권장 — intent classifier 강화 (A) 와 함께 안전망.
_AMBIGUOUS_INTENTS: set[str] = {
    "stock_quote",     # "삼성전자 시세" (action) vs "주식 거래 시간" (info)
    "stock_price",     # 동일
    "stock_analyze",   # "이 종목 어때" (action) vs "T+2 결제 뜻" (info)
    "list_schedule",   # "내 일정" (schedule) vs "내 알람" (reminder)
}


# ── 카테고리별 도구 카탈로그 서브셋 ───────────────────────────────────
# LLM 에 노출할 도구 이름 목록. plan_orchestrator 가 available_tools 로 전달.

# 모든 카테고리에 공통 노출되는 escape hatch 도구 (GPT-5.5 자문 — 제한적 E).
# kms_rag.search 만 — 잘못 라우팅돼도 LLM 이 사내 자료 조회 가능. web.search 까지는
# 노출 X (과검색·hallucinated citation 위험).
_COMMON_ESCAPE_HATCH: tuple[str, ...] = ("kms_rag.search",)


CATEGORY_TOOLS: dict[str, list[str]] = {
    INFO_LOOKUP: ["kms_rag.search", "web.search", "web.fetch", "kms.save_research"],
    SCHEDULE: [
        "schedule.create", "schedule.list", "schedule.delete",
        "schedule.delete_duplicates", "schedule.delete_all", "schedule.update",
    ],
    EXPENSE: [
        "expense.create", "expense.list", "expense.sum_by_category",
        "expense.delete", "expense.update",
    ],
    REMINDER: ["reminder.schedule", "reminder.list", "reminder.cancel"],
    MEMO: [
        "memo.create", "memo.list", "memo.update", "memo.delete", "memo.complete",
    ],
    MAIL: ["inbox.summary", "mail.search", "mail.send", "mail.compose"],
    STOCK: [
        "stock.quote", "stock.add_watch", "stock.list_watch", "stock.update_watch",
        "stock.delete_watch", "stock.market_movers", "stock.analyze",
    ],
    KMS_INVENTORY: [
        "kms_inventory.get_summary",
        "kms_inventory.list_documents",
        "kms_meta.get_my_inventory",
    ],
    # Phase 1.5C P0 — reservation 4 verbs.
    # kms_sop.search 도 함께 노출 — 산업별 취소/환불 정책 조회 (예: 30분 전
    # 환불 불가) 가 자주 동반된다.
    RESERVATION: [
        "reservation.create",
        "reservation.cancel",
        "reservation.check_availability",
        "reservation.reschedule",
        "kms_sop.search",
    ],
    # Phase 1.5C P0 — payment.refund (추상 layer).
    # kms_sop.search 동반 — 환불 정책 안내가 거의 항상 묶임.
    PAYMENT: [
        "payment.refund",
        "kms_sop.search",
    ],
    # Phase 1.5C P0 — inventory.check (read-only).
    INVENTORY: [
        "inventory.check",
    ],
    # Phase 1.5C P0 — delivery.track (추상 layer).
    DELIVERY: [
        "delivery.track",
    ],
    SMALL_TALK: [],
    FALLBACK: [
        "web.search",
        "schedule.create", "expense.create", "reminder.schedule",
        "inbox.summary", "kms_inventory.get_summary",
    ],
}


@dataclass
class RouteDecision:
    """라우터 결정 결과."""

    category: str
    reason: str
    matched_intent: str | None = None
    needs_llm_disambiguation: bool = False
    verb: str | None = None
    domain: str | None = None


# ── (verb, domain) → category 결정적 매핑 (P11-19d) ──────────────────
#
# GPT-5.5 자문 (2026-04-30) 권장 — 96라벨 단일 분류 대신 verb × domain 2축.
# `(delete, expense)` 같은 명확한 조합이면 expense 카테고리 *delete subset* 으로
# 라우팅. 비직교 조합 (예: log + kms) 은 fallback.
#
# canonical_intent 는 V1 호환용 — 후속 코드가 intent label 기반 매핑 사용 시.

_VERB_DOMAIN_MAP: dict[tuple[str, str], dict[str, Any]] = {
    # === expense ===
    ("log", "expense"): {"category": EXPENSE, "canonical_intent": "log_expense"},
    ("query", "expense"): {"category": EXPENSE, "canonical_intent": "expense_query"},
    ("delete", "expense"): {"category": EXPENSE, "canonical_intent": "expense_delete"},
    ("update", "expense"): {"category": EXPENSE, "canonical_intent": "expense_update"},

    # === schedule ===
    ("log", "schedule"): {"category": SCHEDULE, "canonical_intent": "create_schedule"},
    ("query", "schedule"): {"category": SCHEDULE, "canonical_intent": "list_schedule"},
    ("delete", "schedule"): {"category": SCHEDULE, "canonical_intent": "delete_schedule"},
    ("update", "schedule"): {"category": SCHEDULE, "canonical_intent": "update_schedule"},

    # === reminder ===
    ("log", "reminder"): {"category": REMINDER, "canonical_intent": "set_reminder"},
    ("query", "reminder"): {"category": REMINDER, "canonical_intent": "list_reminder"},
    ("delete", "reminder"): {"category": REMINDER, "canonical_intent": "cancel_reminder"},
    ("cancel", "reminder"): {"category": REMINDER, "canonical_intent": "cancel_reminder"},
    ("update", "reminder"): {"category": REMINDER, "canonical_intent": "update_reminder"},

    # === mail ===
    ("query", "mail"): {"category": MAIL, "canonical_intent": "mail_query"},
    ("info", "mail"): {"category": MAIL, "canonical_intent": "mail_summary"},
    # 2026-05-07 — 메일 *발송/회신* 의도. utterance_classifier 는 'send' 단독
    # verb 가 없고 *새 데이터 추가* 의미의 ``log`` 로 분류한다 (mail 도메인의
    # log = 새 메일 송신 행위). 누락 시 plan_router 가 fallback 으로 떨어져
    # mail.send 가 카테고리 도구 셋 밖에 있어 LLM 이 mail.compose 만 반복 호출
    # 하던 회귀의 직접 원인 (admin 실증 2026-05-07: 텔레그램 '발송해줘'
    # → mail_compose_ok 3회, mail.send 0회).
    ("log", "mail"): {"category": MAIL, "canonical_intent": "mail_send"},
    # 메일 폐기/임시저장 삭제 등 — mail 도메인 데이터 변경 verb 도 MAIL 로 라우팅.
    # 실제 도구는 카테고리 안에서 LLM 이 picked. (현재 mail.delete 미구현
    # 이지만, 의도 분류는 fallback 보다 mail 카테고리가 정확해 mail.search 등
    # 으로 fallback 가능.)
    ("delete", "mail"): {"category": MAIL, "canonical_intent": "mail_send"},
    ("update", "mail"): {"category": MAIL, "canonical_intent": "mail_send"},
    ("cancel", "mail"): {"category": MAIL, "canonical_intent": "mail_send"},

    # === stock ===
    ("query", "stock"): {"category": STOCK, "canonical_intent": "stock_quote"},
    ("log", "stock"): {"category": STOCK, "canonical_intent": "stock_register"},
    ("update", "stock"): {"category": STOCK, "canonical_intent": "stock_update"},
    ("delete", "stock"): {"category": STOCK, "canonical_intent": "stock_delete"},
    ("info", "stock"): {"category": INFO_LOOKUP, "canonical_intent": "info_lookup"},

    # === kms ===
    ("query", "kms"): {"category": KMS_INVENTORY, "canonical_intent": "kms_inventory_query"},
    ("info", "kms"): {"category": INFO_LOOKUP, "canonical_intent": "knowledge_query"},

    # === reservation (Phase 1.5C P0) ===
    ("log", "reservation"): {"category": RESERVATION, "canonical_intent": "reservation_create"},
    ("query", "reservation"): {"category": RESERVATION, "canonical_intent": "reservation_check_availability"},
    ("delete", "reservation"): {"category": RESERVATION, "canonical_intent": "reservation_cancel"},
    ("cancel", "reservation"): {"category": RESERVATION, "canonical_intent": "reservation_cancel"},
    ("update", "reservation"): {"category": RESERVATION, "canonical_intent": "reservation_reschedule"},

    # === payment (Phase 1.5C P0) ===
    ("log", "payment"): {"category": PAYMENT, "canonical_intent": "payment_refund"},
    ("delete", "payment"): {"category": PAYMENT, "canonical_intent": "payment_refund"},
    ("cancel", "payment"): {"category": PAYMENT, "canonical_intent": "payment_refund"},
    ("info", "payment"): {"category": INFO_LOOKUP, "canonical_intent": "info_lookup"},

    # === inventory (Phase 1.5C P0) ===
    ("query", "inventory"): {"category": INVENTORY, "canonical_intent": "inventory_check"},
    ("info", "inventory"): {"category": INVENTORY, "canonical_intent": "inventory_check"},

    # === delivery (Phase 1.5C P0) ===
    ("query", "delivery"): {"category": DELIVERY, "canonical_intent": "delivery_track"},
    ("info", "delivery"): {"category": DELIVERY, "canonical_intent": "delivery_track"},

    # === info / smalltalk / settings ===
    ("info", "none"): {"category": INFO_LOOKUP, "canonical_intent": "info_lookup"},
    ("info", "expense"): {"category": INFO_LOOKUP, "canonical_intent": "info_lookup"},
    ("info", "schedule"): {"category": INFO_LOOKUP, "canonical_intent": "info_lookup"},
    ("info", "reminder"): {"category": INFO_LOOKUP, "canonical_intent": "info_lookup"},
    ("smalltalk", "none"): {"category": SMALL_TALK, "canonical_intent": "greeting"},
}


# verb 가 *write* 류 (실제 데이터 변경) — V1/V2 가로채기 차단 강제.
_WRITE_VERBS = frozenset({"log", "delete", "update", "cancel"})

# verb 가 *query* 류 — 보통 plan path 가 정확하지만 V1 야영도 OK.
_READ_VERBS = frozenset({"query", "info"})


def route_by_verb_domain(
    *,
    verb: str | None,
    domain: str | None,
    user_message: str,
) -> RouteDecision | None:
    """verb × domain → category 결정적 매핑.

    매칭되면 RouteDecision 반환, 안 되면 None — 호출자가 legacy ``route()`` 로 fallback.
    """
    if not verb or not domain:
        return None
    key = (verb.strip().lower(), domain.strip().lower())
    entry = _VERB_DOMAIN_MAP.get(key)
    if entry is None:
        return None
    return RouteDecision(
        category=entry["category"],
        reason="verb_domain_direct_mapping",
        matched_intent=entry["canonical_intent"],
        needs_llm_disambiguation=False,
        verb=key[0],
        domain=key[1],
    )


def is_write_verb(verb: str | None) -> bool:
    """verb 가 데이터 변경 동사인지 — V1/V2 가로채기 차단 결정."""
    return bool(verb and verb.strip().lower() in _WRITE_VERBS)


def is_read_verb(verb: str | None) -> bool:
    return bool(verb and verb.strip().lower() in _READ_VERBS)


def route(
    *,
    intents: list[str],
    user_message: str,
) -> RouteDecision:
    """intent → category 결정적 매핑 + 애매한 라벨 표시.

    우선 순위:
    1. intent 라벨이 매핑 테이블에 있고 *애매하지 않으면* 그 카테고리.
    2. intent 라벨이 ``_AMBIGUOUS_INTENTS`` 면 ``needs_llm_disambiguation=True``
       표시 + 1차 매핑 카테고리. 호출자가 별도 LLM disambiguate 호출.
    3. 매핑 없으면 fallback.

    GPT-5.5 자문 (D 안전망) — 라우터는 *결정* 까지 가지 않고 *추정 + flag* 만
    반환. 실제 LLM 재판단은 `disambiguate_with_llm` 호출자가 결정.
    """
    intents = list(intents or [])
    for intent in intents:
        cat = _INTENT_TO_CATEGORY.get(intent)
        if cat is None:
            continue
        if intent in _AMBIGUOUS_INTENTS:
            return RouteDecision(
                category=cat,
                reason="ambiguous_intent_provisional_mapping",
                matched_intent=intent,
                needs_llm_disambiguation=True,
            )
        return RouteDecision(
            category=cat,
            reason="intent_direct_mapping",
            matched_intent=intent,
        )

    return RouteDecision(category=FALLBACK, reason="no_intent_match")


# ── D 안전망 — 작은 LLM 으로 애매한 라벨 재판단 ──────────────────────


_DISAMBIGUATE_SYSTEM = (
    "당신은 한국어 챗봇의 의도 카테고리 분류기입니다. 주어진 발화를 보고 다음 9 개 "
    "카테고리 중 *정확히 하나* 만 선택하세요. 답은 JSON `{\"category\": \"...\"}` 한 줄.\n"
    "\n"
    "카테고리 정의:\n"
    "- info_lookup: 지식·정보 조회 (시간/방법/규정/정의/뜻/배경). 답이 *사실 안내* 인 발화.\n"
    "  예: '주식 거래 시간 알려줘', '매매 수수료는 어떻게 돼', 'T+2 가 무슨 뜻'.\n"
    "- schedule: 사용자 *일정* 등록·조회·수정 (약속/미팅/이벤트). 시간 + 사람 + 장소 컨텍스트.\n"
    "- expense: 가계부·지출 기록·합계·삭제.\n"
    "- reminder: *알람*·리마인더 등록·해제·조회. 발화에 '알람' '리마인더' '복용 알림' '주기 알림' 같은 단어 또는 문맥이 있으면 reminder.\n"
    "  예: '내 알람 리스트', '혈압약 알람 멈춰', '매일 8시 알람 등록'.\n"
    "- mail: 메일함 요약·조회.\n"
    "- stock: 주식 *행동* — 시세 조회 / 보유 등록 / 가격 모니터링 등 *해당 종목에 대한 행위*.\n"
    "  '주식 거래 시간' 같은 일반 정보 질문은 stock 이 아니라 info_lookup.\n"
    "- kms_inventory: 사용자 자료 보유 메타 (블록 수, 문서 수).\n"
    "- small_talk: 인사·감사 같은 자유 대화.\n"
    "- fallback: 위 어디에도 명확히 안 들어가는 발화.\n"
    "\n"
    "원칙:\n"
    "- *행동 의도* (시세 조회·등록·매수) 와 *정보 조회 의도* (제도/시간/방법/뜻) 를 구분.\n"
    "- 발화에 *특정 종목명* (삼성전자/카카오 등) + 행위 (현재가/샀어/매수/모니터링) 면 stock.\n"
    "- 발화에 *일반 명사* (주식/거래/매매) + 정보 verb (알려줘/어떻게 되/뭐야) 면 info_lookup.\n"
    "- 사용자 메모리·일정·식비·메일·알람 도메인 명사가 있으면 해당 도메인 우선.\n"
    "- 모호하면 fallback.\n"
)


async def disambiguate_with_llm(
    *,
    user_message: str,
    matched_intent: str | None,
    provisional_category: str,
    llm_client: Any,
) -> str:
    """애매한 라벨 → LLM 한 번 호출로 카테고리 결정.

    호출자는 ``RouteDecision.needs_llm_disambiguation=True`` 일 때만 이 함수 호출.
    LLM 미주입 / 실패 시 ``provisional_category`` 그대로 반환 (graceful).
    """
    if llm_client is None:
        return provisional_category
    import json

    user_payload = json.dumps(
        {
            "utterance": user_message,
            "intent_label": matched_intent or "",
            "provisional_category": provisional_category,
        },
        ensure_ascii=False,
    )
    try:
        raw = await llm_client.complete(
            _DISAMBIGUATE_SYSTEM, user_payload, response_format="json_object"
        )
    except Exception as e:  # noqa: BLE001
        log.warning("disambiguate_llm_failed", error=str(e))
        return provisional_category
    try:
        data = json.loads((raw or "").strip())
        cat = (data.get("category") or "").strip()
        if cat in ALL_CATEGORIES:
            return cat
    except Exception as e:  # noqa: BLE001
        log.debug("disambiguate_parse_failed", error=str(e), raw=str(raw)[:120])
    return provisional_category


def tools_for_category(category: str) -> list[str]:
    """카테고리에 노출할 도구 이름 리스트.

    GPT-5.5 자문 (제한적 E) — 모든 카테고리에 ``_COMMON_ESCAPE_HATCH``
    (현재는 ``kms_rag.search``) 도 함께 노출. 잘못 라우팅된 발화도 사내 자료
    조회 가능 → fallback escape hatch. small_talk 는 도구 X (인사라 X).
    """
    base = list(CATEGORY_TOOLS.get(category, CATEGORY_TOOLS[FALLBACK]))
    if category == SMALL_TALK:
        return base
    for hatch in _COMMON_ESCAPE_HATCH:
        if hatch not in base:
            base.append(hatch)
    return base


# ── plan tool allowlist 검증 (GPT-5.5 자문 — 가짜 도구 차단) ─────────


def validate_plan_tools(
    plan_steps: list[Any],
    category: str,
    *,
    extra_allowed: list[str] | None = None,
) -> tuple[list[Any], list[str]]:
    """LLM 이 생성한 plan 의 tool step 이 카테고리 도구 셋 안에 있는지 검증.

    매칭 안 되는 도구 이름 (예: ``info_lookup.search`` 같은 hallucination) 이면
    그 step 을 제거하고 invalid 리스트 반환. 호출자는 invalid 가 비어있지 않으면
    재시도 또는 fallback 카테고리로 escalate.

    인자:
        plan_steps: ``GeneratedPlan.plan`` (PlanStep 객체 리스트)
        category: 노출된 카테고리
        extra_allowed: 추가 허용 도구 (테스트 등)
    """
    allowed = set(tools_for_category(category))
    if extra_allowed:
        allowed.update(extra_allowed)
    valid: list[Any] = []
    invalid: list[str] = []
    for s in plan_steps:
        if getattr(s, "kind", None) != "tool":
            valid.append(s)
            continue
        tool_name = str((s.raw or {}).get("tool") or "").strip()
        if not tool_name:
            invalid.append("(empty)")
            continue
        if tool_name in allowed:
            valid.append(s)
        else:
            invalid.append(tool_name)
            log.warning(
                "plan_tool_not_in_allowlist",
                tool=tool_name,
                category=category,
                allowlist_size=len(allowed),
            )
    return valid, invalid


def template_path(category: str) -> str:
    """카테고리 sub-template 파일 이름 (plan_intents/ 하위)."""
    if category not in ALL_CATEGORIES:
        category = FALLBACK
    return f"plan_intents/{category}.md"
