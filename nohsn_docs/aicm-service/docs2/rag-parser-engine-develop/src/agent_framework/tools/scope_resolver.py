"""Tool scope resolver — Phase 3 (#154) + Phase 4 wire (#155, D23 §3) + D26 (#201).

Spec: docs/superpowers/specs/2026-05-07-agent-tool-scope-overrides.md
D23 §3 (2026-05-08): _TOOL_SUPPORTS_AGENT_ID + tool_supports_agent_id() helper.
D26 (2026-05-08): 단일 소스-of-truth 통합. dependencies.py:scopes={} drift 정리.

agent.tool_scope_overrides (JSONB) 가 도구별로 *하향* override 한 scope 를
반환. 미등록 / 미override 시 _TOOL_DEFAULT_SCOPES 또는 fallback ('agent').

D23 §3 — engine 의 _resolve_args_with_defaults 가 agent_id 를 server-side
inject 할 도구는 두 조건 모두 만족:
  1. effective_scope (resolve_tool_scope) == 'agent'
  2. tool_name in _TOOL_SUPPORTS_AGENT_ID (manifest opt-in)

unknown tool fallback 'agent' 만으로는 inject 안 함 — 보수적 default.

D26 단일 소스 통합 — 본 모듈의 _TOOL_DEFAULT_SCOPES 가 *유일한* default scope
SoT. dependencies.py:ToolRegistry(scopes=...) 는 본 dict 의 등록 도구 sub-set 을
그대로 import 해서 사용 (literal 중복 0).
"""
from __future__ import annotations

from typing import Final, Literal


Scope = Literal["tenant", "user", "agent", "session"]


# 사다리 — 큰 숫자가 *넓은* 범위. validator 는 default 보다 큰 (= 승격) 시 reject.
SCOPE_RANK: Final[dict[str, int]] = {
    "tenant": 4,
    "user": 3,
    "agent": 2,
    "session": 1,
}


# 도구별 default scope — *단일 소스* (SoT). dependencies.py:ToolRegistry 가 본
# dict 를 import 해서 사용. Phase 4 (#155) wire 와 D26 (#201) 통합 적용.
#
# 미등록 도구는 resolve_tool_scope() 에서 'agent' fallback (가장 좁은 default).
#
# D26 (2026-05-08, GPT-5 phase0 GO 조건부 반영):
#   - mail.compose: agent → user (draft 도 사용자 메일함 자산)
#   - kms_meta.get_my_inventory: tenant → user (함수명 "my" = 사용자 본인)
#   - schedule.availability/delete_all/delete_duplicates/suggest_slots,
#     reservation.check_availability: 누락 추가 (모두 agent)
#   - calendar.create/list/cancel, concert.list, inventory.update,
#     kms_inventory.summary, kms_meta.list, movie.detail/list: 미등록 도구
#     삭제 (deps.py 미등록, drift 정리)
#   - diary.* / expense.* default 'agent' 유지 (SUPPORTS=true, NULL 버킷 위험)
_TOOL_DEFAULT_SCOPES: Final[dict[str, Scope]] = {
    # schedule — Phase 1 alembic 072 hardcode 와 일치.
    "schedule.create": "agent",
    "schedule.list": "agent",
    "schedule.update": "agent",
    "schedule.delete": "agent",
    # D26 — 누락 보강: schedule helper 4종 (모두 agent — agent 별 일정 컨텍스트).
    "schedule.availability": "agent",
    "schedule.delete_all": "agent",
    "schedule.delete_duplicates": "agent",
    "schedule.suggest_slots": "agent",
    # mail — D26: mail.compose user (draft 도 사용자 메일함 자산).
    "mail.send": "user",
    "mail.search": "user",
    "mail.compose": "user",
    "inbox.summary": "user",
    # memo
    "memo.create": "agent",
    "memo.list": "agent",
    "memo.update": "agent",
    "memo.delete": "agent",
    "memo.complete": "agent",
    # KMS save (note.save_research 는 kms.save_research alias 로 SUPPORTS test 의존).
    "note.save_research": "agent",
    "kms.save_research": "agent",
    # reservation (산업 mock) — D26: check_availability 누락 보강.
    "reservation.create": "agent",
    "reservation.cancel": "agent",
    "reservation.reschedule": "agent",
    "reservation.check_availability": "agent",
    # payment
    "payment.refund": "agent",
    # inventory — D26: inventory.update 미등록이라 삭제.
    "inventory.check": "agent",
    # delivery
    "delivery.track": "agent",
    # expense — D26: SUPPORTS=true 라 default 'agent' 유지 (NULL 버킷 위험).
    "expense.create": "agent",
    "expense.list": "agent",
    "expense.sum_by_category": "agent",
    "expense.delete": "agent",
    "expense.update": "agent",
    # diary — D26: SUPPORTS=true 라 default 'agent' 유지.
    "diary.save": "agent",
    "diary.search": "agent",
    # reminder
    "reminder.schedule": "agent",
    "reminder.list": "agent",
    "reminder.cancel": "agent",
    # news
    "news.add_subscription": "agent",
    "news.remove_subscription": "agent",
    "news.list_subscriptions": "agent",
    "news.fetch_and_summarize": "agent",
    "news.list_recent_reports": "agent",
    "news.search": "tenant",
    # stock — watchlist 는 user 자산, 시장 데이터는 tenant.
    "stock.add_watch": "user",
    "stock.list_watch": "user",
    "stock.update_watch": "user",
    "stock.delete_watch": "user",
    "stock.quote": "tenant",
    "stock.predict": "tenant",
    "stock.market_movers": "tenant",
    "stock.analyze": "tenant",
    # external read-only
    "weather.lookup": "tenant",
    "web.search": "tenant",
    "web.fetch": "tenant",
    # KMS read-only — D26: kms_inventory.summary / kms_meta.list 삭제 (미등록).
    # kms_meta.get_my_inventory: tenant → user ("my" 의미).
    "kms_rag.search": "tenant",
    "kms_sop.search": "tenant",
    "kms_inventory.get_summary": "tenant",
    "kms_inventory.list_documents": "tenant",
    "kms_meta.get_my_inventory": "user",
    # demo (clinic) — D26: calendar.create/list/cancel 삭제 (미등록).
    "calendar.check_availability": "agent",
    "calendar.book": "agent",
    "calendar.list_doctors": "agent",
    "calendar.list_available_slots": "agent",
    # lifestyle (외부 자료) — D26: movie.detail/list, concert.list 삭제 (미등록).
    "restaurant.search": "tenant",
    "movie.lookup": "tenant",
    "movie.boxoffice": "tenant",
    "fx.rate": "tenant",
    "transit.status": "tenant",
    "flight.price": "tenant",
    "concert.schedule": "tenant",
    "menu.recommend": "tenant",
    "streaming.lookup": "tenant",
    "air.quality": "tenant",
}


# D23 §3 (2026-05-08, GPT-5 phase 0 R4 GO) — agent_id args 를 storage 컬럼으로
# 사용하는 도구 *명시 등록*. unknown tool 의 fallback 'agent' 만으로는 inject
# 안 함 (회귀 0 + 보수적 default).
#
# 도구가 owner_agent_id 컬럼 격리에 *실제로* 의존할 때만 등록. 예:
#   - schedule.* / memo.* / expense.* / diary.* / reminder.* — agent_document_store
#     의 owner_agent_id 컬럼 사용 (확인 완료, D23 §1)
#   - note.save_research / kms.save_research — KMS save 도구 (agent_data repo)
#
# 미등록 도구 (mail.send / kms_rag.search 등) — engine 이 agent_id inject 안 함.
# 후속 phase 에서 도구별 verification 후 점진 추가.
#
# D26 (2026-05-08, GPT-5 phase0 risk #2 권고) — 파괴적/대량작업 보강:
#   schedule.delete_all / delete_duplicates: 내부적으로 list_all + delete 호출,
#   args 의 agent_id 가 inner 호출에 inherit. SUPPORTS 추가로 outer 에 inject 보장.
#   schedule.availability / suggest_slots: 일정 조회 시 cross-agent leak 방지.
_TOOL_SUPPORTS_AGENT_ID: Final[frozenset[str]] = frozenset(
    {
        # schedule (alembic 072 — 이미 작동)
        "schedule.create",
        "schedule.list",
        "schedule.update",
        "schedule.delete",
        # D26 — 파괴적/대량작업 + 조회 helper 보강 (GPT-5 phase0 risk #2)
        "schedule.delete_all",
        "schedule.delete_duplicates",
        "schedule.availability",
        "schedule.suggest_slots",
        # memo (D23 §1 — 본 dispatch 에서 적용)
        "memo.create",
        "memo.list",
        "memo.update",
        "memo.delete",
        "memo.complete",
        # expense (D23 §1)
        "expense.create",
        "expense.list",
        "expense.sum_by_category",
        "expense.delete",
        "expense.update",
        # diary (D23 §1)
        "diary.save",
        "diary.search",
        "diary.delete",
        # reminder (D23 §1)
        "reminder.schedule",
        "reminder.list",
        "reminder.cancel",
        # KMS save — note/research (agent_data 카테고리)
        "note.save_research",
        "kms.save_research",
    }
)


def get_default_scope(tool_name: str) -> Scope:
    """tool default scope. 미등록은 'agent' (가장 좁은 fallback)."""
    return _TOOL_DEFAULT_SCOPES.get(tool_name, "agent")


# D26 (2026-05-08, GPT-5 phase2 post-§2 WARN R2) — 공개 API 별칭.
# 외부 모듈 (deps.py / test) 이 private 상수 직접 import 안 하도록 alias 노출.
# 본 변수는 *동일 객체* 의 reference — frozenset/Final 으로 immutable 보장.
TOOL_DEFAULT_SCOPES: Final[dict[str, Scope]] = _TOOL_DEFAULT_SCOPES


def tool_supports_agent_id(tool_name: str) -> bool:
    """도구가 owner_agent_id args 를 받아 storage 격리에 사용하는가.

    D23 §3 (2026-05-08, GPT-5 phase 0 R4 GO) — engine 의 server-side agent_id
    inject 조건. 두 조건 모두 만족해야 inject:
        1. effective_scope (resolve_tool_scope) == 'agent'
        2. tool_supports_agent_id(tool_name) == True

    unknown tool / fallback 'agent' 만으로는 inject 안 함 (회귀 0).
    """
    return tool_name in _TOOL_SUPPORTS_AGENT_ID


def resolve_tool_scope(
    *,
    agent_overrides: dict[str, str] | None,
    tool_name: str,
) -> Scope:
    """agent override 우선, 없으면 tool default.

    Phase 3 한정: 함수만 제공. engine 의 도구 dispatch layer 는 Phase 4 (#155)
    가 wire. 호출자가 Pydantic validator 통과한 데이터만 넣을 것 (승격 차단은
    schema layer 에서).

    Args:
        agent_overrides: agents.tool_scope_overrides JSONB. None / {} 는 모두
            default 사용 의미.
        tool_name: 도구 이름 (예: "schedule.create").

    Returns:
        scope literal — Phase 4 enforcement 가 의미를 정의.
    """
    overrides = agent_overrides or {}
    candidate = overrides.get(tool_name)
    if isinstance(candidate, str) and candidate in SCOPE_RANK:
        # validator 가 통과시킨 값 — 승격은 이미 차단됨.
        return candidate  # type: ignore[return-value]
    return get_default_scope(tool_name)


def is_promotion(*, default: str, override: str) -> bool:
    """override 가 default 보다 *넓은* (= 승격) scope 인가."""
    return SCOPE_RANK.get(override, 0) > SCOPE_RANK.get(default, 0)
