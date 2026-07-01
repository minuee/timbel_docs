"""Plan router 단위 테스트 — 의도 단위 라우팅 정확도 검증.

P11-19 (2026-04-29). 라우터는 *순수 intent → category 매핑* 만 검증.
사용자 메모리 ``feedback_pattern_over_case_enumeration`` /
``feedback_no_hardcoding_first_principle`` 정합 — 키워드 매칭 / 발화 휴리스틱
테스트 없음. 발화 변형 일반화는 intent_classifier prompt 책임 (LLM).

GPT-5.5 자문 결과 적용:
- A: intent_classifier 강화 (별도 PR — intent_classifier.py prompt)
- D: 애매한 intent 만 LLM disambiguation (이 파일 테스트)
- E: 모든 카테고리에 ``kms_rag.search`` escape hatch 공통 노출
- 추가: plan tool allowlist 검증 (가짜 도구 차단)
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.agent_framework.runtime.plan_router import (
    EXPENSE, FALLBACK, INFO_LOOKUP, KMS_INVENTORY, MAIL, REMINDER, SCHEDULE,
    SMALL_TALK, STOCK,
    _AMBIGUOUS_INTENTS,
    _COMMON_ESCAPE_HATCH,
    disambiguate_with_llm,
    is_read_verb,
    is_write_verb,
    route, route_by_verb_domain,
    template_path, tools_for_category, validate_plan_tools,
)


# ── 1. intent → category 직접 매핑 (애매하지 않은 라벨) ───────────────────


class TestDirectIntentMapping:
    """intent classifier 라벨이 명확한 경우."""

    @pytest.mark.parametrize("intent,expected", [
        ("create_schedule", SCHEDULE),
        ("update_schedule", SCHEDULE),
        ("delete_schedule", SCHEDULE),
        ("log_expense", EXPENSE),
        ("expense_analyzer", EXPENSE),
        ("expense_query", EXPENSE),
        ("expense_delete", EXPENSE),
        ("set_reminder", REMINDER),
        ("medication_tracker", REMINDER),
        ("cancel_reminder", REMINDER),
        ("mail_summary", MAIL),
        ("mail_query", MAIL),
        ("inbox_summary", MAIL),
        ("stock_register", STOCK),
        ("stock_watch", STOCK),
        ("stock_update", STOCK),
        ("kms_inventory_query", KMS_INVENTORY),
        ("ask_my_data_inventory", KMS_INVENTORY),
        ("greeting", SMALL_TALK),
        ("_capability_query", SMALL_TALK),
        ("info_lookup", INFO_LOOKUP),
        ("knowledge_query", INFO_LOOKUP),
    ])
    def test_intent_routes_to_expected_category(self, intent, expected):
        d = route(intents=[intent], user_message="아무 발화")
        assert d.category == expected
        assert d.matched_intent == intent
        assert d.reason == "intent_direct_mapping"
        assert d.needs_llm_disambiguation is False


# ── 2. 애매한 intent → provisional + disambiguation flag ───────────────


class TestAmbiguousIntents:
    """행동/정보 둘 다 가능한 라벨 — 라우터가 needs_llm_disambiguation 표시."""

    @pytest.mark.parametrize("intent,provisional", [
        ("stock_quote", STOCK),
        ("stock_price", STOCK),
        ("stock_analyze", STOCK),
        ("list_schedule", SCHEDULE),
    ])
    def test_ambiguous_intent_flags_for_llm(self, intent, provisional):
        d = route(intents=[intent], user_message="발화 무관")
        assert d.matched_intent == intent
        assert d.category == provisional
        assert d.needs_llm_disambiguation is True
        assert d.reason == "ambiguous_intent_provisional_mapping"

    def test_ambiguous_intents_set_complete(self):
        # 회귀 가드 — 새 ambiguous intent 추가 시 이 테스트도 업데이트
        assert "stock_quote" in _AMBIGUOUS_INTENTS
        assert "list_schedule" in _AMBIGUOUS_INTENTS


# ── 3. fallback ─────────────────────────────────────────────────────


class TestFallback:
    """intent 미매핑 → fallback. 키워드 휴리스틱 X."""

    def test_unknown_intent(self):
        d = route(intents=["totally_unknown_intent"], user_message="발화")
        assert d.category == FALLBACK
        assert d.reason == "no_intent_match"

    def test_empty_intents(self):
        d = route(intents=[], user_message="안녕")
        assert d.category == FALLBACK
        assert d.reason == "no_intent_match"

    def test_sentinel_intent_falls_back(self):
        # unsupported / _no_skills_available 같은 sentinel 도 fallback
        d = route(intents=["unsupported"], user_message="뭔가")
        assert d.category == FALLBACK


# ── 4. 다중 intent (첫 매칭 우선) ──────────────────────────────────────


class TestMultipleIntents:
    """intent classifier 가 2개 라벨 반환 — 첫 매칭 우선."""

    def test_set_reminder_first(self):
        d = route(
            intents=["set_reminder", "medication_tracker"],
            user_message="발화 무관",
        )
        assert d.category == REMINDER
        assert d.matched_intent == "set_reminder"

    def test_unknown_first_then_known(self):
        d = route(
            intents=["totally_unknown", "log_expense"],
            user_message="발화 무관",
        )
        assert d.category == EXPENSE
        assert d.matched_intent == "log_expense"


# ── 5. tools_for_category — escape hatch 공통 노출 ────────────────────


class TestToolSubsets:
    """카테고리별 노출 도구. GPT-5.5 자문 (제한적 E) — kms_rag.search 항상 노출."""

    def test_info_lookup_includes_kms_and_web(self):
        tools = tools_for_category(INFO_LOOKUP)
        assert "kms_rag.search" in tools
        assert "web.search" in tools

    def test_expense_includes_delete(self):
        # 회귀 가드 — expense.delete 가 빠져있던 case 방지
        tools = tools_for_category(EXPENSE)
        assert "expense.delete" in tools
        assert "expense.create" in tools
        assert "expense.sum_by_category" in tools

    def test_reminder_full_set(self):
        tools = tools_for_category(REMINDER)
        for need in ("reminder.schedule", "reminder.list", "reminder.cancel"):
            assert need in tools

    def test_kms_rag_search_in_every_non_smalltalk_category(self):
        """E (제한적) — kms_rag.search 가 모든 non-smalltalk 카테고리에 escape hatch 로 추가"""
        for cat in (
            INFO_LOOKUP, SCHEDULE, EXPENSE, REMINDER, MAIL, STOCK,
            KMS_INVENTORY, FALLBACK,
        ):
            tools = tools_for_category(cat)
            assert "kms_rag.search" in tools, (
                f"{cat} 카테고리에 kms_rag.search escape hatch 누락"
            )

    def test_small_talk_no_tools(self):
        # 인사라 도구 X — escape hatch 도 X
        assert tools_for_category(SMALL_TALK) == []

    def test_web_search_not_in_every_category(self):
        """web.search 는 escape hatch 가 아님 — 과검색 방지."""
        # info_lookup 과 fallback 에만 있어야 함
        assert "web.search" in tools_for_category(INFO_LOOKUP)
        assert "web.search" in tools_for_category(FALLBACK)
        assert "web.search" not in tools_for_category(EXPENSE)
        assert "web.search" not in tools_for_category(REMINDER)
        assert "web.search" not in tools_for_category(STOCK)


# ── 6. template path ────────────────────────────────────────────────


class TestTemplatePath:
    @pytest.mark.parametrize("cat,path", [
        (INFO_LOOKUP, "plan_intents/info_lookup.md"),
        (SCHEDULE, "plan_intents/schedule.md"),
        (EXPENSE, "plan_intents/expense.md"),
        (REMINDER, "plan_intents/reminder.md"),
        (MAIL, "plan_intents/mail.md"),
        (STOCK, "plan_intents/stock.md"),
        (KMS_INVENTORY, "plan_intents/kms_inventory.md"),
        (SMALL_TALK, "plan_intents/small_talk.md"),
        (FALLBACK, "plan_intents/fallback.md"),
    ])
    def test_template_paths(self, cat, path):
        assert template_path(cat) == path

    def test_unknown_category_falls_back(self):
        assert template_path("not_a_category") == "plan_intents/fallback.md"


# ── 7. plan tool allowlist 검증 (GPT-5.5 자문 — 가짜 도구 차단) ──────────


@dataclass
class _FakeStep:
    """PlanStep 모킹 — kind + raw."""

    kind: str
    raw: dict


class TestValidatePlanTools:
    """LLM 이 hallucinated 도구 (info_lookup.search 같은) 만들면 차단."""

    def test_valid_tools_pass(self):
        steps = [
            _FakeStep("tool", {"tool": "kms_rag.search", "args": {}}),
            _FakeStep("tool", {"tool": "web.search", "args": {}}),
            _FakeStep("reasoning", {"expr": "..."}),
        ]
        valid, invalid = validate_plan_tools(steps, INFO_LOOKUP)
        assert len(valid) == 3
        assert invalid == []

    def test_hallucinated_tool_filtered(self):
        # 사용자 보고 회귀: stock 카테고리에서 LLM 이 "info_lookup.search" 만듦
        steps = [
            _FakeStep("tool", {"tool": "info_lookup.search", "args": {}}),
            _FakeStep("tool", {"tool": "stock.quote", "args": {}}),
        ]
        valid, invalid = validate_plan_tools(steps, STOCK)
        assert len(valid) == 1
        assert valid[0].raw["tool"] == "stock.quote"
        assert "info_lookup.search" in invalid

    def test_empty_tool_name_invalid(self):
        steps = [_FakeStep("tool", {"tool": "", "args": {}})]
        valid, invalid = validate_plan_tools(steps, EXPENSE)
        assert len(valid) == 0
        assert len(invalid) == 1

    def test_kms_rag_search_allowed_everywhere(self):
        # E (제한적) — kms_rag.search 는 stock 카테고리에서도 허용
        steps = [_FakeStep("tool", {"tool": "kms_rag.search", "args": {}})]
        valid, invalid = validate_plan_tools(steps, STOCK)
        assert len(valid) == 1
        assert invalid == []

    def test_non_tool_steps_pass_through(self):
        # reasoning, ask_user_clarify 등은 검증 X
        steps = [
            _FakeStep("reasoning", {"expr": "..."}),
            _FakeStep("ask_user_clarify", {"question": "..."}),
            _FakeStep("invoke_skill", {"skill_id": "..."}),
        ]
        valid, invalid = validate_plan_tools(steps, INFO_LOOKUP)
        assert len(valid) == 3
        assert invalid == []


# ── 7-C. verb × domain 라우팅 (P11-19d) ──────────────────────────────


class TestVerbDomainRouting:
    """GPT-5.5 자문 권장 — verb × domain 2축 분류 → 카테고리 결정적 매핑."""

    @pytest.mark.parametrize("verb,domain,expected_category,expected_canonical", [
        # expense
        ("log", "expense", EXPENSE, "log_expense"),
        ("query", "expense", EXPENSE, "expense_query"),
        ("delete", "expense", EXPENSE, "expense_delete"),
        ("update", "expense", EXPENSE, "expense_update"),
        # schedule
        ("log", "schedule", SCHEDULE, "create_schedule"),
        ("query", "schedule", SCHEDULE, "list_schedule"),
        ("delete", "schedule", SCHEDULE, "delete_schedule"),
        ("update", "schedule", SCHEDULE, "update_schedule"),
        # reminder
        ("log", "reminder", REMINDER, "set_reminder"),
        ("query", "reminder", REMINDER, "list_reminder"),
        ("delete", "reminder", REMINDER, "cancel_reminder"),
        ("cancel", "reminder", REMINDER, "cancel_reminder"),
        # mail
        ("query", "mail", MAIL, "mail_query"),
        ("info", "mail", MAIL, "mail_summary"),
        # stock — info 는 stock 도메인이라도 INFO_LOOKUP 으로 라우팅 (사용자 보고 회귀)
        ("query", "stock", STOCK, "stock_quote"),
        ("log", "stock", STOCK, "stock_register"),
        ("update", "stock", STOCK, "stock_update"),
        ("info", "stock", INFO_LOOKUP, "info_lookup"),
        # kms
        ("query", "kms", KMS_INVENTORY, "kms_inventory_query"),
        ("info", "kms", INFO_LOOKUP, "knowledge_query"),
        # info / smalltalk
        ("info", "none", INFO_LOOKUP, "info_lookup"),
        ("info", "expense", INFO_LOOKUP, "info_lookup"),
        ("info", "schedule", INFO_LOOKUP, "info_lookup"),
        ("smalltalk", "none", SMALL_TALK, "greeting"),
    ])
    def test_verb_domain_to_category(
        self, verb, domain, expected_category, expected_canonical,
    ):
        d = route_by_verb_domain(
            verb=verb, domain=domain, user_message="발화 무관",
        )
        assert d is not None, f"({verb}, {domain}) 매핑 X"
        assert d.category == expected_category
        assert d.matched_intent == expected_canonical
        assert d.verb == verb
        assert d.domain == domain
        assert d.reason == "verb_domain_direct_mapping"

    def test_unknown_verb_returns_none(self):
        d = route_by_verb_domain(
            verb="unknown", domain="expense", user_message="발화",
        )
        assert d is None

    def test_unknown_domain_returns_none(self):
        d = route_by_verb_domain(
            verb="log", domain="unknown_domain", user_message="발화",
        )
        assert d is None

    def test_empty_verb_domain_returns_none(self):
        assert route_by_verb_domain(
            verb=None, domain="expense", user_message="x",
        ) is None
        assert route_by_verb_domain(
            verb="log", domain=None, user_message="x",
        ) is None

    def test_user_reported_regression_delete_expense(self):
        """사용자 회귀 (2026-04-30): '삭제해줘' 가 log_expense 로 잘못 분류.
        verb=delete + domain=expense 로 분류되면 expense_delete 로 라우팅 보장.
        """
        d = route_by_verb_domain(
            verb="delete", domain="expense",
            user_message="27만원 두개 항목이랑 인베스트먼트 비용 삭제해줘",
        )
        assert d is not None
        assert d.category == EXPENSE
        assert d.matched_intent == "expense_delete"


# ── 7-D. write/read verb 헬퍼 ──────────────────────────────────────


class TestWriteReadVerbs:
    """write verb 면 V1/V2 가로채기 차단 결정에 사용."""

    @pytest.mark.parametrize("verb", ["log", "delete", "update", "cancel"])
    def test_write_verbs(self, verb):
        assert is_write_verb(verb) is True
        assert is_read_verb(verb) is False

    @pytest.mark.parametrize("verb", ["query", "info"])
    def test_read_verbs(self, verb):
        assert is_read_verb(verb) is True
        assert is_write_verb(verb) is False

    @pytest.mark.parametrize("verb", ["smalltalk", "unknown", None, ""])
    def test_neither(self, verb):
        assert is_write_verb(verb) is False
        assert is_read_verb(verb) is False


# ── 8. disambiguate_with_llm — D 안전망 동작 ─────────────────────────


class _FakeLLM:
    """LLM 모킹 — complete 메서드만 noop async."""

    def __init__(self, response: str | None = None, raise_exc: bool = False):
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[tuple[str, str, str | None]] = []

    async def complete(self, system, user, response_format=None):
        self.calls.append((system, user, response_format))
        if self.raise_exc:
            raise RuntimeError("llm down")
        return self.response


class TestDisambiguateWithLLM:
    @pytest.mark.asyncio
    async def test_llm_returns_info_lookup(self):
        llm = _FakeLLM(response='{"category": "info_lookup"}')
        cat = await disambiguate_with_llm(
            user_message="주식 거래 시간 알려줘",
            matched_intent="stock_quote",
            provisional_category=STOCK,
            llm_client=llm,
        )
        assert cat == INFO_LOOKUP
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_llm_confirms_stock(self):
        llm = _FakeLLM(response='{"category": "stock"}')
        cat = await disambiguate_with_llm(
            user_message="삼성전자 현재가 알려줘",
            matched_intent="stock_quote",
            provisional_category=STOCK,
            llm_client=llm,
        )
        assert cat == STOCK

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_provisional(self):
        llm = _FakeLLM(raise_exc=True)
        cat = await disambiguate_with_llm(
            user_message="발화",
            matched_intent="stock_quote",
            provisional_category=STOCK,
            llm_client=llm,
        )
        assert cat == STOCK  # graceful

    @pytest.mark.asyncio
    async def test_llm_invalid_category_falls_back(self):
        llm = _FakeLLM(response='{"category": "totally_made_up"}')
        cat = await disambiguate_with_llm(
            user_message="발화",
            matched_intent="stock_quote",
            provisional_category=STOCK,
            llm_client=llm,
        )
        assert cat == STOCK  # invalid → 무시

    @pytest.mark.asyncio
    async def test_no_llm_returns_provisional(self):
        cat = await disambiguate_with_llm(
            user_message="발화",
            matched_intent="stock_quote",
            provisional_category=STOCK,
            llm_client=None,
        )
        assert cat == STOCK

    @pytest.mark.asyncio
    async def test_unparseable_response_falls_back(self):
        llm = _FakeLLM(response="not json at all")
        cat = await disambiguate_with_llm(
            user_message="발화",
            matched_intent="stock_quote",
            provisional_category=STOCK,
            llm_client=llm,
        )
        assert cat == STOCK
