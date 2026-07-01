"""Tool 스키마 — 필수/선택 args + default + 누락 시 되묻기 질문 (P11-19i, 2026-05-01).

## 배경

plan_orchestrator 가 LLM 으로 plan 생성 후 도구 args 가 *부족* 할 수 있다.
예: "내일 미팅 등록" → schedule.create 필수 슬롯 ``when`` (정확한 시각) 누락
→ 도구가 실패하거나 잘못된 default 로 등록.

## 해결

각 도구의 required / optional / defaults / clarify_questions 를 코드로 명시.
plan_orchestrator 가 plan 생성 후:
  1. 각 tool step 의 args 검증
  2. required 누락 + default 없음 → 해당 step 을 ``ask_user_clarify`` 로 교체
     (한 번에 *하나* 만 묻기 — 사용자 메모리 정합)
  3. 다음 turn 에 사용자 답변 받아 plan 복귀 (session 의 pending_plan 영속)

## 키 정의

- ``required``: 모든 항목이 *반드시* 채워져야 하는 args 이름.
- ``required_groups``: one-of 그룹. 한 그룹의 모든 항목이 채워지면 OK.
  예: reminder.schedule — ``[["at"], ["recurrence_kind", "time"]]``
- ``defaults``: 누락 시 자동 적용 (사용자에게 안 물음).
- ``clarify``: 슬롯 누락 시 되묻기 질문 (한 줄, 자연스러운 한국어).
"""
from __future__ import annotations

from typing import Any


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # === schedule ===
    "schedule.create": {
        # 정말 없으면 도구 실행 불가 — 도구 호출 차단.
        "required": ["title"],
        # 있으면 좋지만 없어도 도구 실행 가능 — default 또는 placeholder.
        "optional_for_quality": ["when", "where", "who", "recurrence"],
        "defaults": {},
        "clarify": {
            "title": "어떤 일정을 등록해 드릴까요? 제목을 알려 주세요.",
        },
        # 내부 필드 — 자동 주입, 사용자에게 안 물음.
        "auto_inject": ["tenant_id", "phone", "scope_group"],
    },
    "schedule.list": {
        "required": [],
        "optional": ["period_start", "period_end", "scope_group"],
        "defaults": {},
        "clarify": {},
        "auto_inject": ["tenant_id", "phone"],
    },
    "schedule.delete": {
        # id / title / when 중 하나라도 있으면 OK. required_groups one-of.
        "required": [],
        "required_groups": [["id"], ["title"], ["when"]],
        "optional": ["id", "title", "when"],
        "defaults": {},
        "clarify": {
            "title": "어떤 일정을 삭제할까요? 일정 제목 또는 날짜로 알려 주세요.",
        },
        "auto_inject": ["tenant_id", "phone"],
    },

    # === expense ===
    "expense.create": {
        "required": ["amount"],
        "optional": ["category", "description", "spent_at", "payment_method"],
        "defaults": {"category": "기타", "spent_at": "오늘"},
        "clarify": {
            "amount": "얼마를 기록해 드릴까요? 금액을 알려 주세요.",
        },
        "auto_inject": ["tenant_id", "phone"],
    },
    "expense.sum_by_category": {
        "required": [],
        "optional": ["period_start", "period_end"],
        "defaults": {},
        "clarify": {},
        "auto_inject": ["tenant_id", "phone"],
    },
    "expense.delete": {
        # Phase 1.5A Task 8e — id-only enforcement. broad mutation 차단.
        # description/spent_at/amount 만으로 삭제 X — list/sum_by_category 로
        # id 확보 후 그 id 만으로 호출.
        "required": ["id"],
        "optional": [],
        "defaults": {},
        "clarify": {
            "id": "어떤 항목을 삭제할까요? 먼저 목록에서 항목을 확인한 뒤 ID 로 알려 주세요.",
        },
        "auto_inject": ["tenant_id", "phone"],
    },
    "expense.update": {
        "required": [],
        # 매칭 조건 (셋 중 하나) + 변경 필드 (하나 이상) 둘 다 필요.
        "required_groups": [
            ["id"], ["description"], ["spent_at"], ["amount"],
        ],
        "optional": [
            "id", "description", "spent_at", "amount",
            "new_amount", "new_category", "new_description", "new_spent_at",
        ],
        "defaults": {},
        "clarify": {
            "id": "어떤 항목을 수정할까요? 날짜·금액·메모 중 하나로 알려 주세요.",
        },
        "auto_inject": ["tenant_id", "phone"],
    },

    # === reminder ===
    "reminder.schedule": {
        "required": [],
        "required_groups": [
            ["at"],  # 단발
            ["recurrence_kind", "time"],  # 주기
        ],
        "optional": [
            "title", "template", "channel",
            "at", "recurrence_kind", "time", "weekday", "every_n",
        ],
        "defaults": {"channel": "in_app"},
        "clarify": {
            "title": "어떤 알람인가요? 알람 제목을 알려 주세요 (예: 혈압약 / 운동).",
            "time": "몇 시에 알려드릴까요? (예: 오전 8시)",
            "recurrence_kind": "한 번만 알려드릴까요, 매일·매주·N일마다 반복할까요?",
            "at": "언제 알려드릴까요? 정확한 날짜와 시각을 알려 주세요.",
            "weekday": "어느 요일에 알려드릴까요?",
            "every_n": "며칠마다 알려드릴까요?",
        },
        "auto_inject": ["tenant_id", "phone"],
    },
    "reminder.list": {
        "required": [],
        "optional": [],
        "defaults": {},
        "clarify": {},
        "auto_inject": ["tenant_id"],
    },
    "reminder.cancel": {
        "required": [],
        "required_groups": [["id"], ["title"]],
        "optional": ["id", "title", "action"],
        "defaults": {"action": "cancel"},
        "clarify": {
            "title": "어떤 알람을 취소할까요? 알람 제목으로 알려 주세요.",
        },
        "auto_inject": ["tenant_id"],
    },

    # === stock ===
    "stock.quote": {
        "required": [],
        "required_groups": [["code_or_name"], ["symbol"], ["ticker"], ["name"], ["query"]],
        "optional": ["code_or_name", "symbol", "ticker", "name", "query"],
        "defaults": {},
        "clarify": {
            "code_or_name": "어떤 종목 시세가 궁금하신가요? 종목명 또는 6자리 코드를 알려 주세요.",
        },
        "auto_inject": [],
    },
    "stock.add_watch": {
        "required": [],
        "required_groups": [["code_or_name"], ["symbol"], ["name"], ["code"]],
        "optional": [
            "code_or_name", "symbol", "name", "code",
            "qty", "avg_cost", "alert_high", "alert_low",
            "monitor_interval_min", "note",
        ],
        "defaults": {},
        "clarify": {
            "code_or_name": "어떤 종목인가요? 종목명을 알려 주세요.",
        },
        "auto_inject": ["tenant_id", "phone"],
    },
    "stock.update_watch": {
        "required": [],
        "required_groups": [["id"], ["code_or_name"], ["code"]],
        "optional": [
            "id", "code_or_name", "code", "match_qty", "match_avg_cost",
            "qty", "avg_cost",
        ],
        "defaults": {},
        "clarify": {
            "code_or_name": "어떤 종목 정보를 변경하시나요? 종목명을 알려 주세요.",
        },
        "auto_inject": ["tenant_id", "phone"],
    },

    # === info / search ===
    # Phase 1.5B-β — SOP RAG. agent.sop_repo_ids 안의 markdown chunks 검색.
    # evidence (kms_rag) 와 분리: SOP 는 instruction (정책/절차) 검색용.
    "kms_sop.search": {
        "required": ["query"],
        "optional": ["top_k", "tenant_id"],
        "defaults": {"top_k": 5},
        "clarify": {
            "query": "어떤 정책/절차를 찾을까요?",
        },
        # agent_id 는 plan_orchestrator 가 sess.agent_id 로 자동 주입.
        "auto_inject": ["agent_id", "tenant_id"],
    },
    "kms_rag.search": {
        "required": ["query"],
        "optional": [
            "tenant_id", "tenant_slug", "limit",
            "created_after", "created_before",
            "document_type", "source_type",
        ],
        "defaults": {"limit": 5},
        "clarify": {
            "query": "어떤 자료를 검색할까요? 검색어를 알려 주세요.",
        },
        "auto_inject": ["tenant_id"],
    },
    "web.search": {
        "required": ["query"],
        "optional": ["count", "lang", "country"],
        "defaults": {"count": 5},
        "clarify": {
            "query": "무엇을 검색할까요?",
        },
        "auto_inject": [],
    },
    "inbox.summary": {
        "required": [],
        "optional": ["since", "until", "limit_per_category"],
        "defaults": {"since": "today", "until": "now"},
        "clarify": {},
        "auto_inject": ["tenant_id", "phone"],
    },

    # === reservation (Phase 1.5C P0) ===
    "reservation.create": {
        "required": ["title", "start_at", "end_at"],
        "optional": ["attendee_count", "location", "contact", "notes"],
        "defaults": {},
        "clarify": {
            "title": "어떤 예약인가요? 예약 제목/이름을 알려 주세요.",
            "start_at": "예약 시작 시각을 알려 주세요 (예: 2026-05-08 19:00).",
            "end_at": "예약 종료 시각을 알려 주세요.",
        },
        "auto_inject": ["tenant_id", "account_id_hint"],
    },
    "reservation.cancel": {
        # Phase 1.5A Task 8e id-only enforcement — broad mutation 차단.
        "required": ["id"],
        "optional": ["reason"],
        "defaults": {},
        "clarify": {
            "id": "어떤 예약을 취소할까요? 먼저 예약 목록에서 확인 후 ID 로 알려 주세요.",
        },
        "auto_inject": ["tenant_id"],
    },
    "reservation.check_availability": {
        "required": ["start_at", "end_at"],
        "optional": [],
        "defaults": {},
        "clarify": {
            "start_at": "확인할 시작 시각을 알려 주세요 (예: 2026-05-08 19:00).",
            "end_at": "확인할 종료 시각을 알려 주세요.",
        },
        "auto_inject": ["tenant_id"],
    },
    "reservation.reschedule": {
        "required": ["id", "new_start_at", "new_end_at"],
        "optional": [],
        "defaults": {},
        "clarify": {
            "id": "어떤 예약 일정을 변경할까요? 먼저 예약 목록에서 ID 를 확인해 주세요.",
            "new_start_at": "새 예약 시작 시각을 알려 주세요.",
            "new_end_at": "새 예약 종료 시각을 알려 주세요.",
        },
        "auto_inject": ["tenant_id"],
    },

    # === payment.refund (Phase 1.5C P0 — 추상 layer) ===
    "payment.refund": {
        "required": ["order_id", "amount"],
        "optional": ["reason"],
        "defaults": {},
        "clarify": {
            "order_id": "어떤 주문의 환불인가요? 주문번호 또는 결제 키를 알려 주세요.",
            "amount": "환불 금액을 알려 주세요 (원).",
        },
        "auto_inject": ["tenant_id", "account_id_hint"],
    },

    # === inventory.check (Phase 1.5C P0 — read-only) ===
    "inventory.check": {
        "required": [],
        # one-of: item_id / sku / item_name 중 하나라도 있으면 OK.
        "required_groups": [["item_id"], ["sku"], ["item_name"]],
        "optional": ["item_id", "sku", "item_name", "name"],
        "defaults": {},
        "clarify": {
            "item_name": "어떤 상품의 재고를 확인할까요? 상품명 또는 SKU 를 알려 주세요.",
        },
        "auto_inject": ["tenant_id"],
    },

    # === delivery.track (Phase 1.5C P0 — 추상 layer) ===
    "delivery.track": {
        "required": ["tracking_number"],
        "optional": ["carrier"],
        "defaults": {},
        "clarify": {
            "tracking_number": "송장번호를 알려 주세요.",
        },
        "auto_inject": ["tenant_id"],
    },

    # === mail.send ===
    # 실제 SMTP 발송 도구. account_id 는 engine 의 _enrich_plan_tool_args 가
    # 자동 주입 (auto_inject) — webhook account_id_hint 로부터 sess.account_id
    # 가 set 된 상태. body_text 가 비어 있어도 mail_send.py 가 "(본문 없음)" 로
    # 동작하므로 hard required 는 to/subject 만.
    "mail.send": {
        "required": ["to", "subject"],
        "optional": [
            "body_text", "body", "body_html",
            "cc", "bcc", "in_reply_to",
            "mail_account_id", "mail_account_label", "mail_account_query",
        ],
        "defaults": {},
        "clarify": {
            "to": "어떤 이메일 주소로 보낼까요? 받는 사람을 알려 주세요.",
            "subject": "메일 제목을 알려 주세요.",
        },
        # account_id — engine.turn 의 account_id_hint 로 주입. 사용자에게 묻지 않음.
        "auto_inject": ["account_id"],
    },

    # === mail.compose ===
    # 메일 초안 생성 — 발송 X. recipient 또는 body_hint 중 하나라도 있으면 OK.
    # 둘 다 없으면 LLM 호출 의미 없음 → recipient 를 우선 되묻기.
    "mail.compose": {
        "required": [],
        # 2026-05-07 — to/recipients 도 *수신자* synonym 으로 인정. LLM 이 자연스러운
        # 'to' 키로 args 채우는 경우가 많아 (mail.send 와 동일 키명) recipient 만
        # 인정하면 plan_slot_missing_clarify 회귀 → 초안 의도 좌절.
        "required_groups": [
            ["recipient"], ["to"], ["recipients"],
            ["body_hint"], ["topic"], ["subject_hint"],
        ],
        "optional": [
            "recipient", "to", "recipients",
            "subject_hint", "subject",
            "body_hint", "body", "topic", "content", "message",
            "tone", "language",
        ],
        "defaults": {"tone": "정중", "language": "ko"},
        "clarify": {
            "recipient": "누구에게 보내는 메일인가요? 받는 사람의 이메일 또는 이름을 알려 주세요.",
            "body_hint": "메일 본문에 어떤 내용을 담을까요? 핵심 메시지를 알려 주세요.",
        },
        "auto_inject": [],
    },
}


def schema(tool: str) -> dict[str, Any] | None:
    """tool 이름의 schema 반환. 미정의 시 None (검증 skip)."""
    return TOOL_SCHEMAS.get(tool)


def _is_obvious_default(slot: str, value: Any) -> bool:
    """value 가 *명백한 default* 인지 — 사용자가 진짜 의도한 값이 아닐 가능성 높음.

    P11-19j (GPT-5.5 자문) — slot policy 3-tier 분리 후 *required_for_execution*
    슬롯에서만 이 함수 호출. *optional_for_quality* 슬롯은 default 가 OK 이므로
    이 검사 우회.
    """
    if value is None:
        return True
    s = str(value).strip()
    if not s:
        return True
    # datetime 슬롯 — 자정 'T00:00:00' 으로 끝나면 시각 미명시 추정.
    # 단, 자정이 *진짜 의도* 인 경우 ('자정에 등록') 도 있으므로 conservatively.
    # P11-19j: optional_for_quality 슬롯이면 이 검사 자체가 호출되지 않음.
    if slot in ("when", "remind_at", "at"):
        return s.endswith("T00:00:00") or s.endswith("T00:00")
    return False


def find_missing_slot(tool: str, args: dict[str, Any]) -> tuple[str, str] | None:
    """tool args 검증 후 *첫* 누락 필수 슬롯 + 되묻기 질문 반환.

    None 반환 = 모두 충족 또는 schema 정의 없음.

    우선순위:
      1. required 모두 검사 (정의 순서)
      2. required_groups (one-of) — 어느 그룹도 완전치 못 하면 첫 그룹의 첫 슬롯 누락
      3. defaults 적용 후에도 여전히 빈 슬롯이면 누락으로 처리

    auto_inject 슬롯은 사용자에게 안 물음 (engine 이 채울 책임).
    """
    sch = schema(tool)
    if not sch:
        return None

    # P11-19j — required (= required_for_execution) 만 hard check.
    # optional_for_quality 슬롯은 default/placeholder OK.
    for slot in sch.get("required", []) or []:
        v = args.get(slot)
        is_empty = v is None or (isinstance(v, str) and not v.strip())
        if is_empty or _is_obvious_default(slot, v):
            if slot in (sch.get("defaults") or {}) and not _is_obvious_default(slot, v):
                continue
            q = (sch.get("clarify") or {}).get(slot)
            if q:
                return (slot, q)

    # required_groups one-of — 어느 그룹도 만족하지 못하면 첫 그룹의 첫 슬롯 질문.
    groups = sch.get("required_groups") or []
    if groups:
        for group in groups:
            if all(
                args.get(s) is not None
                and not (isinstance(args.get(s), str) and not args[s].strip())
                for s in group
            ):
                return None  # 한 그룹 충족 → OK
        # 모든 그룹 미충족 — 첫 그룹의 첫 슬롯으로 질문.
        first_group = groups[0]
        for slot in first_group:
            q = (sch.get("clarify") or {}).get(slot)
            if q:
                return (slot, q)
        # clarify 정의 없으면 generic.
        return (first_group[0], f"필수 정보가 부족합니다. {first_group[0]} 을 알려 주세요.")

    return None


def apply_defaults(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """도구의 defaults 를 args 에 적용 (이미 있으면 보존). 새 dict 반환."""
    sch = schema(tool)
    if not sch:
        return dict(args)
    out = dict(args)
    for k, v in (sch.get("defaults") or {}).items():
        if k not in out or out[k] is None:
            out[k] = v
    return out
