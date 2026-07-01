"""PR-L1 — Plan-based orchestrator (자비스 비전).

LLM 이 사용자 발화를 *multi-step plan* 으로 분해. engine 이 plan executor 로
tool chain + ask_user_clarify pause/resume 흐름 진행.

이 모듈 (L1) 범위:
- ``plan_generation.md`` prompt 호출
- ``GeneratedPlan`` / ``PlanStep`` dataclass
- ``PlanOrchestrator.generate_plan()`` — LLM 한 번 호출로 JSON plan 생성

L2 (후속 PR) 범위:
- ``execute_plan()`` — step list 차례로 실행 (tool 호출 / reasoning LLM /
  ask_user_clarify pause / invoke_skill 위임)
- pause/resume — sess 에 plan + step_index + accumulated_results 영속, 다음
  turn 의 사용자 답변으로 plan 재평가 또는 step 진행

L3 (후속 PR) 범위:
- 외부 tool registry 확장 (weather.lookup / search.web / news.fetch_realtime)

메모리 원칙: ``feedback_llm_driven_everywhere`` — 모든 분기·판단·추출은 LLM
정밀 prompt 위임. rule/regex 금지. ``feedback_pattern_core_not_case`` — 사례
yaml 추가 금지, plan generator prompt 한 곳에서 LLM 일반화.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.common.feature_flags import FeatureFlag, is_enabled
from src.common.logging import get_logger

if TYPE_CHECKING:
    from src.agent_framework.runtime.agent_context import AgentContext

log = get_logger(__name__)

# Option β Stage 5 — PLAN_MODEL_SMALL.
# 환경 변수로 모델 명 오버라이드 가능 (기본값: gemma-4-12b).
_PLAN_SMALL_MODEL_DEFAULT = "gemma-4-12b"

_PROMPT_PATH = (
    Path(__file__).parent.parent / "skills" / "prompts" / "plan_generation.md"
)
# P11-19 — 의도 단위 라우터 (sub-template 기반).
_INTENTS_DIR = (
    Path(__file__).parent.parent / "skills" / "prompts" / "plan_intents"
)
_BASE_TEMPLATE_PATH = _INTENTS_DIR / "_base.md"


@dataclass
class PlanStep:
    """단일 plan step.

    ``raw`` 는 LLM 이 만든 step dict 그대로 — kind 별 추가 필드 (tool/args/
    question/expr/skill_id 등) 가 그 안에 들어 있다. executor (PR-L2) 가
    raw 에서 필요한 키 추출.
    """

    step: int
    kind: str  # tool | reasoning | ask_user_clarify | ask_user_confirm | invoke_skill
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class GeneratedPlan:
    """LLM 이 생성한 plan 결과."""

    plan: list[PlanStep]
    needs_clarification: bool
    confidence: float
    ambiguity_reasons: list[str]
    summary: str
    raw_response: str = ""  # 원본 JSON 문자열 (디버깅·trace 영속 용)

    @property
    def is_empty(self) -> bool:
        """plan = [] — 자유 대화 신호. orchestrator 호출자가 옛 path 로 폴백."""
        return len(self.plan) == 0

    @property
    def is_single_skill(self) -> bool:
        """plan 이 단일 invoke_skill — 옛 state machine 진입과 동일.
        orchestrator layer 거치지 말고 곧바로 v1 routing 으로 위임.
        """
        return len(self.plan) == 1 and self.plan[0].kind == "invoke_skill"


class PlanOrchestrator:
    """L1 — plan generation. P11-19 부터 의도 단위 sub-template 라우팅."""

    def __init__(self, llm_client: Any):
        self.llm = llm_client
        self._prompt_cache: str | None = None
        self._base_cache: str | None = None
        self._intent_template_cache: dict[str, str] = {}

    def _load_prompt(self) -> str:
        if self._prompt_cache is None:
            self._prompt_cache = _PROMPT_PATH.read_text(encoding="utf-8")
        return self._prompt_cache

    def _load_base(self) -> str:
        """공통 base prompt — 출력 schema + 시간 변환 룰. P11-19."""
        if self._base_cache is None:
            try:
                self._base_cache = _BASE_TEMPLATE_PATH.read_text(encoding="utf-8")
            except FileNotFoundError:
                self._base_cache = ""
        return self._base_cache

    def _load_intent_template(self, category: str) -> str:
        """카테고리별 sub-template. 캐시. 누락 시 fallback 로 폴백."""
        cached = self._intent_template_cache.get(category)
        if cached is not None:
            return cached
        path = _INTENTS_DIR / f"{category}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            log.warning(
                "plan_intent_template_missing",
                category=category,
                path=str(path),
            )
            text = ""
        self._intent_template_cache[category] = text
        return text

    def _compose_routed_prompt(
        self, category: str, fallback_full: str
    ) -> str:
        """base + 카테고리 가이드 합성. base/카테고리 어느 쪽이든 비면
        legacy plan_generation.md 전체로 폴백 (회귀 안전망).
        """
        base = self._load_base()
        guide = self._load_intent_template(category)
        if not base or not guide:
            return fallback_full
        return base.replace("[CATEGORY_GUIDE_PLACEHOLDER]", guide)

    async def generate_plan(
        self,
        *,
        user_message: str,
        history: list[dict] | None = None,
        user_preference: dict | None = None,
        available_skills_summary: str = "",
        available_tools_summary: str = "",
        intents: list[str] | None = None,
        utterance_verb: str | None = None,
        utterance_domain: str | None = None,
        utterance_is_ambiguous: bool = False,
        utterance_clarification_question: str | None = None,
        utterance_intents: list[dict] | None = None,
        tenant_id: str | None = None,
        extra_system: str | None = None,
        agent_context: "AgentContext | None" = None,
        known_tool_names: "set[str] | None" = None,
    ) -> GeneratedPlan | None:
        """LLM 한 번 호출로 plan 생성. 실패·LLM 미주입 시 None.

        P11-19 — intents 가 주어지면 의도 단위 라우터로 sub-template 결정.
        legacy plan_generation.md (29KB) 대신 base (~3KB) + 카테고리 가이드
        (~2KB) 만 LLM 에 전달 → attention 밀도 회복 + 토큰 70% 감소.

        P11-19d — verb × domain 2축 분류 우선 사용. (verb, domain) 으로 카테고리
        결정적 매핑 → ambiguous intent 의 LLM 재판단 비용 절감 + 신뢰성 향상.

        호출자 (engine) 는 None 반환 시 *옛 single-skill path* 로 폴백.
        """
        if self.llm is None:
            return None
        # P11-19h — 애매한 인텐트 → LLM 호출 없이 ask_user_clarify plan 즉시 반환.
        if utterance_is_ambiguous and utterance_clarification_question:
            log.info(
                "plan_ambiguous_clarify",
                question=utterance_clarification_question[:120],
            )
            ambiguity_reasons = [
                "발화가 모호 — utterance_classifier 가 ambiguous=true 결정",
            ]
            clarify_step = PlanStep(
                step=1,
                kind="ask_user_clarify",
                raw={
                    "step": 1,
                    "kind": "ask_user_clarify",
                    "question": utterance_clarification_question,
                },
            )
            return GeneratedPlan(
                plan=[clarify_step],
                needs_clarification=True,
                confidence=0.5,
                ambiguity_reasons=ambiguity_reasons,
                summary="모호한 인텐트 — 사용자에게 명확화 요청",
                raw_response="",
            )
        try:
            from src.agent_framework.runtime.plan_router import (
                disambiguate_with_llm as _router_disambiguate,
                route as _router_route,
                route_by_verb_domain as _router_v2,
                tools_for_category as _router_tools,
                validate_plan_tools as _router_validate_tools,
            )

            # P11-19d — verb × domain 우선 매핑. 미매칭 시 legacy intent 매핑.
            decision = None
            if utterance_verb and utterance_domain:
                decision = _router_v2(
                    verb=utterance_verb,
                    domain=utterance_domain,
                    user_message=user_message,
                )
                if decision is not None:
                    log.info(
                        "plan_router_v2_decision",
                        category=decision.category,
                        verb=decision.verb,
                        domain=decision.domain,
                        canonical_intent=decision.matched_intent,
                    )
            if decision is None:
                decision = _router_route(
                    intents=intents or [],
                    user_message=user_message,
                )
                # P11-19 D 안전망 — 애매한 라벨이면 disambiguation LLM 호출.
                if decision.needs_llm_disambiguation:
                    resolved = await _router_disambiguate(
                        user_message=user_message,
                        matched_intent=decision.matched_intent,
                        provisional_category=decision.category,
                        llm_client=self.llm,
                    )
                    if resolved != decision.category:
                        log.info(
                            "plan_router_disambiguated",
                            from_=decision.category,
                            to=resolved,
                            intent=decision.matched_intent,
                        )
                    decision.category = resolved
                    decision.reason = "ambiguous_intent_resolved_by_llm"
            log.info(
                "plan_router_decision",
                category=decision.category,
                reason=decision.reason,
                matched_intent=decision.matched_intent,
            )

            # Option β — FAST_INFO_LOOKUP_PLAN: flag on + info_lookup 시
            # plan_generator LLM 호출 없이 결정론 plan 즉시 반환.
            # flag off 또는 다른 category 시 이 블록 완전 우회 (기존 LLM 경로).
            from src.agent_framework.runtime.plan_router import INFO_LOOKUP as _INFO_LOOKUP
            if (
                is_enabled(FeatureFlag.FAST_INFO_LOOKUP_PLAN, tenant_id=tenant_id or None)
                and decision.category == _INFO_LOOKUP
            ):
                from src.agent_framework.runtime.fast_planners.info_lookup import (
                    IntentResult as _FILIntentResult,
                    synthesize_info_lookup_plan as _synthesize,
                )
                _fil_steps = _synthesize(
                    user_message,
                    _FILIntentResult(
                        intent=decision.matched_intent or "info_lookup",
                        domain=utterance_domain or "general",
                        confidence=0.9,
                    ),
                )
                _plan_steps: list[PlanStep] = []
                for _i, _fs in enumerate(_fil_steps, start=1):
                    _raw: dict[str, Any] = {"step": _i, "kind": _fs.kind}
                    if _fs.tool is not None:
                        _raw["tool"] = _fs.tool
                    if _fs.args:
                        _raw["args"] = _fs.args
                    if _fs.expr is not None:
                        _raw["expr"] = _fs.expr
                    _plan_steps.append(PlanStep(step=_i, kind=_fs.kind, raw=_raw))
                log.info(
                    "fast_info_lookup_plan_used",
                    category=decision.category,
                    steps=len(_plan_steps),
                    tenant_id=tenant_id,
                )
                return GeneratedPlan(
                    plan=_plan_steps,
                    needs_clarification=False,
                    confidence=0.95,
                    ambiguity_reasons=[],
                    summary="fast_info_lookup_planner (LLM bypass)",
                    raw_response="",
                )

            system = self._compose_routed_prompt(
                decision.category, fallback_full=self._load_prompt()
            )
            # 058 — admin agent 면 카테고리 narrowing X. agent.allowed_tools 그대로 노출.
            # 단, allowed_tools 비면 router 의 카테고리 서브셋으로 fallback (안전망).
            _is_admin_ctx = bool(
                agent_context is not None
                and getattr(agent_context, "is_admin", False)
            )
            if _is_admin_ctx and getattr(agent_context, "allowed_tools", None):
                _admin_tools = list(agent_context.allowed_tools)
                # D39 (2026-05-11) — defense-in-depth: agent.allowed_tools 의
                # outdated/typo 도구가 LLM 환각 유발. 실 ToolRegistry 와 교집합만
                # 노출. 미등록 tool 은 WARN 로깅 + 제외.
                # fail-closed: known_tool_names 가 *주어졌으면* (빈 set 포함)
                # 항상 필터. None 일 때만 옛 동작 (legacy/test path).
                if known_tool_names is not None:
                    _admin_unknown = [
                        t for t in _admin_tools if t not in known_tool_names
                    ]
                    if _admin_unknown:
                        log.warning(
                            "plan_admin_allowed_tools_filter_unknown",
                            agent_name=getattr(agent_context, "name", ""),
                            unknown=_admin_unknown,
                            kept=len(_admin_tools) - len(_admin_unknown),
                        )
                    tool_subset = [
                        t for t in _admin_tools if t in known_tool_names
                    ]
                else:
                    tool_subset = _admin_tools
                log.info(
                    "plan_admin_full_tool_catalog",
                    agent_name=getattr(agent_context, "name", ""),
                    tool_count=len(tool_subset),
                    category=decision.category,
                )
            else:
                # 카테고리별 도구 서브셋 — LLM 에 노출. catalog 전체 (~30 줄) 대신
                # 이 카테고리 도구만 (~3-7 개) 표기. 라우터가 fallback 카테고리
                # 결정 시는 핵심 도구 셋이 노출됨.
                tool_subset = _router_tools(decision.category)
                # D72 (2026-05-12) — non-admin role agent 의 allowed_tools 와
                # 교집합. visible_tools() 의 의미: None=open, []=closed, list=명시.
                # role agent (allowed_tools=[]) 의 카테고리 도구가 plan 단계에서
                # 노출되어 LLM 환각 호출이 발생하던 결함 차단 (D71 #261).
                if agent_context is not None and not _is_admin_ctx:
                    from src.agent_framework.runtime.tool_guard import (
                        visible_tools as _visible_tools,
                    )
                    _before = list(tool_subset)
                    tool_subset = _visible_tools(agent_context, _before)
                    if len(tool_subset) != len(_before):
                        log.info(
                            "plan_role_agent_tool_subset_filtered",
                            agent_name=getattr(agent_context, "name", ""),
                            category=decision.category,
                            before=_before,
                            after=tool_subset,
                        )
            tools_summary_routed = (
                "\n".join(f"- {t}" for t in tool_subset)
                if tool_subset
                else available_tools_summary
            )

            user_payload = {
                "user_message": user_message,
                "history": (history or [])[-6:],
                "user_preference": user_preference or {},
                "available_skills": available_skills_summary,
                "available_tools": tools_summary_routed,
                "intent_category": decision.category,
            }
            # P11-19h — 다중 인텐트 정보 LLM 에 전달. plan generator 가 발화 안
            # 여러 distinct 요청을 *각각 sub-step* 으로 풀도록 유도.
            if utterance_intents and len(utterance_intents) > 1:
                user_payload["multi_intents"] = utterance_intents
                user_payload["multi_intent_hint"] = (
                    "★★ 발화에 *여러 distinct 의도* 가 식별되었습니다. 각 의도를 "
                    "하나씩 plan step 으로 풀어 *순차 실행* 되도록 plan 을 작성하세요. "
                    "한 응답에 두 작업 모두 수행 + 결과 안내."
                )
            user = json.dumps(user_payload, ensure_ascii=False, indent=2)
            # P11-19f — system prompt 에 현재 시각 prepend. LLM 이 '오늘/내일/어제'
            # 등 상대 시간을 ISO 로 변환할 때 기준점 필요. 누락 시 환각 (예: '오늘'
            # 을 '2025-05-14' 로 잘못 변환) 회귀 직접 원인.
            from src.agent_framework.runtime.time_context import append_time
            system_with_time = append_time(system)
            # Phase 1 Task 4 — agent_context 또는 extra_system 주입.
            # agent_context=None (default chat) 시 byte-equal — 기존 동작 그대로.
            #
            # 두 source 의 의미 차이:
            #   - `agent_context` : 명시적 agent (admin/custom agent) bind. 페르소나·
            #     도구·scope 제약 등 *전체 컨텍스트* 를 to_prompt_section() 로 풍부하게
            #     직렬화. 신뢰도 높은 binding source.
            #   - `extra_system`  : legacy / orchestration-side 단순 prepend (raw str).
            #                       caller 가 직접 prompt 조각을 합치는 경로.
            #
            # elif 순서의 의도 (D28 §1, 2026-05-08):
            #   agent_context 가 전달되면 *그 컨텍스트로 충분* 하다고 본다 — 동시에 들어온
            #   extra_system 은 *무시* 됨 (우선순위상 배제). 두 소스를 합치면 prompt
            #   토큰 예산 초과 + 페르소나 충돌 risk 가 높다 (truncation/dedup 정책 부재
            #   상태).
            #
            # 변경 가이드:
            #   - 두 source 를 합치고 싶다면 별도 PR 에서 "merge policy" 를 명시 후
            #     변경. 최소: (a) 순서 (앞/뒤), (b) 섹션 헤더/non-binding 표시, (c)
            #     토큰 예산 + 절단 우선순위, (d) 충돌 해결 규칙.
            #   - 권장 시작점: extra_system 을 *앞* 에 두고 "non-binding orchestration
            #     notes" 헤더 표시. agent_context 의 강한 binding 을 뒤에서 덮음.
            #   - extra_system 만 들어오는 caller path 는 옛 dispatcher / chat 진입점 —
            #     agent 시스템 도입 전. 단계적으로 agent_context 로 흡수 권장.
            if agent_context is not None:
                system_with_time += "\n\n" + agent_context.to_prompt_section()
            elif extra_system:
                system_with_time += "\n\n" + extra_system
            # Option β Stage 5 — PLAN_MODEL_SMALL flag 분기.
            # flag on 시 PLAN_SMALL_MODEL env (default gemma-4-12b) 사용.
            # flag off → plan_model=None → 기존 default 31B (byte-equal).
            plan_model: str | None = None
            if is_enabled(FeatureFlag.PLAN_MODEL_SMALL, tenant_id=tenant_id):
                plan_model = os.environ.get(
                    "PLAN_SMALL_MODEL", _PLAN_SMALL_MODEL_DEFAULT
                )
                log.info(
                    "plan_orchestrator_small_model",
                    model=plan_model,
                    tenant_id=tenant_id,
                )

            raw = await self.llm.complete(
                system_with_time, user,
                response_format="json_object",
                model=plan_model,
            )
            # PR-L1 — LLM 이 ```json fence 로 감싸 반환할 수 있음. parse 전 제거.
            def _strip_fence(s: str) -> str:
                s = (s or "").strip()
                if s.startswith("```"):
                    nl = s.find("\n")
                    if nl > 0:
                        s = s[nl + 1:]
                if s.endswith("```"):
                    s = s[:-3].rstrip()
                return s

            _stripped = _strip_fence(raw)
            # JSON parse — small model 실패 시 31B fallback (1회).
            try:
                data = json.loads(_stripped)
            except json.JSONDecodeError:
                if plan_model is not None:
                    log.warning(
                        "plan_small_model_json_parse_failed_fallback",
                        model=plan_model,
                        raw_preview=(raw or "")[:200],
                    )
                    raw = await self.llm.complete(
                        system_with_time, user,
                        response_format="json_object",
                        model=None,  # default 31B
                    )
                    _stripped = _strip_fence(raw)
                    data = json.loads(_stripped)  # 두 번째 실패 시 caller 로 전파
                else:
                    raise
            steps = [
                PlanStep(
                    step=int(s.get("step", 0)),
                    kind=str(s.get("kind", "")).strip(),
                    raw=s,
                )
                for s in (data.get("plan") or [])
                if isinstance(s, dict)
            ]
            # P11-19 — tool allowlist 검증 (GPT-5.5 자문). LLM 이 hallucinated
            # 도구 (예: info_lookup.search) 만들면 그 step 제거 + 로그.
            # 058 — admin agent 면 agent.allowed_tools 를 extra_allowed 로 추가
            # → 카테고리 subset 에 없는 mail.compose / news.search / weather.lookup
            # 등 admin 의 전체 카탈로그 모두 통과.
            # D39 (2026-05-11) — extra_allowed 도 known_tool_names 로 필터.
            # admin row 의 outdated typo (expense.add 등) 가 validate 통과 후
            # 실 storage 호출에서 ToolNotFound 로 죽던 회귀 차단.
            # fail-closed: known_tool_names 가 *주어졌으면* (빈 set 포함) 항상 필터.
            _extra_allowed: list[str] | None = None
            if _is_admin_ctx and getattr(agent_context, "allowed_tools", None):
                _raw_extra = list(agent_context.allowed_tools)
                if known_tool_names is not None:
                    _extra_allowed = [
                        t for t in _raw_extra if t in known_tool_names
                    ]
                else:
                    _extra_allowed = _raw_extra
            valid_steps, invalid_tools = _router_validate_tools(
                steps, decision.category, extra_allowed=_extra_allowed,
            )
            # D39 (2026-05-11) — 추가 hard guard: validate 통과한 step 도
            # known_tool_names 와 교집합 검사. CATEGORY_TOOLS 에 정의됐지만 실 registry
            # 등록 안 된 도구가 있으면 (drift) 환각 단계 차단.
            # fail-closed: known_tool_names 가 *주어졌으면* (빈 set 포함) 항상 검사.
            if known_tool_names is not None:
                _post_valid = []
                _drift = []
                for s in valid_steps:
                    if getattr(s, "kind", None) != "tool":
                        _post_valid.append(s)
                        continue
                    _tn = str((s.raw or {}).get("tool") or "").strip()
                    if _tn and _tn not in known_tool_names:
                        _drift.append(_tn)
                        continue
                    _post_valid.append(s)
                if _drift:
                    log.warning(
                        "plan_tool_drift_unregistered",
                        unknown=_drift,
                        category=decision.category,
                    )
                    invalid_tools = list(invalid_tools) + _drift
                    valid_steps = _post_valid
            # D72 (2026-05-12) — non-admin role agent 의 allowed_tools 강제 가드.
            # 위 _router_validate_tools 는 category subset 만 검사 → role agent 의
            # allowed_tools 와 *직접 교차* 필터링이 누락되어 있었음. 여기서 보강.
            # admin path 는 _extra_allowed 로 이미 처리됨 (위 D39 로직).
            if (
                agent_context is not None
                and not _is_admin_ctx
                and getattr(agent_context, "allowed_tools", None) is not None
            ):
                _role_allowed = set(getattr(agent_context, "allowed_tools", None) or [])
                _role_filtered: list[PlanStep] = []
                _role_blocked: list[str] = []
                for s in valid_steps:
                    if getattr(s, "kind", None) != "tool":
                        _role_filtered.append(s)
                        continue
                    _tn = str((s.raw or {}).get("tool") or "").strip()
                    if not _tn:
                        _role_filtered.append(s)
                        continue
                    if not _role_allowed or _tn not in _role_allowed:
                        _role_blocked.append(_tn)
                        continue
                    _role_filtered.append(s)
                if _role_blocked:
                    log.warning(
                        "plan_role_agent_tool_not_allowed",
                        agent_name=getattr(agent_context, "name", ""),
                        blocked=_role_blocked,
                        allowed=sorted(_role_allowed),
                        category=decision.category,
                    )
                    invalid_tools = list(invalid_tools) + _role_blocked
                    valid_steps = _role_filtered
            if invalid_tools:
                log.warning(
                    "plan_invalid_tools_filtered",
                    category=decision.category,
                    invalid=invalid_tools,
                    valid_count=len(valid_steps),
                )
            ambiguity = list(data.get("ambiguity_reasons") or [])
            if invalid_tools:
                ambiguity.append(
                    f"plan_router 가 hallucinated 도구 차단: {invalid_tools}"
                )

            # P11-19i — 누락 필수 슬롯 자동 되묻기. tool step 의 args 가 schema 의
            # required / required_groups 를 만족하지 못하면 *첫* 누락 슬롯에
            # 대해 ask_user_clarify 로 plan 교체. 한 번에 *하나* 만 묻기 — 사용자
            # 메모리 정합 ("복수 항목 동시 묻기 금지").
            try:
                from src.agent_framework.runtime.tool_schemas import (
                    apply_defaults as _apply_defaults,
                    find_missing_slot as _find_missing,
                )

                # 첫 tool step 의 args 검증.
                first_tool_step = next(
                    (s for s in valid_steps if s.kind == "tool"),
                    None,
                )
                if first_tool_step is not None:
                    tool_name = str(
                        (first_tool_step.raw or {}).get("tool") or ""
                    ).strip()
                    raw_args = (first_tool_step.raw or {}).get("args") or {}
                    args_with_defaults = _apply_defaults(tool_name, raw_args)
                    # auto_inject 키는 engine 이 채울 예정이므로 *이미 있다고 간주*
                    # 해 누락 검사 false positive 방지.
                    from src.agent_framework.runtime.tool_schemas import (
                        TOOL_SCHEMAS as _TS,
                    )
                    sch = _TS.get(tool_name) or {}
                    for k in (sch.get("auto_inject") or []):
                        if k not in args_with_defaults:
                            args_with_defaults[k] = "__auto__"
                    missing = _find_missing(tool_name, args_with_defaults)
                    if missing is not None:
                        slot_name, question = missing
                        log.info(
                            "plan_slot_missing_clarify",
                            tool=tool_name,
                            slot=slot_name,
                            category=decision.category,
                        )
                        ambiguity.append(
                            f"필수 슬롯 '{slot_name}' 누락 — 사용자에게 되묻기"
                        )
                        clarify_step = PlanStep(
                            step=1,
                            kind="ask_user_clarify",
                            raw={
                                "step": 1,
                                "kind": "ask_user_clarify",
                                "question": question,
                                "missing_slot": slot_name,
                                "deferred_tool": tool_name,
                                "deferred_args": raw_args,
                            },
                        )
                        return GeneratedPlan(
                            plan=[clarify_step],
                            needs_clarification=True,
                            confidence=float(data.get("confidence", 0.5)),
                            ambiguity_reasons=ambiguity,
                            summary=f"슬롯 '{slot_name}' 누락 — 추가 질문",
                            raw_response=raw,
                        )
            except Exception as e:  # noqa: BLE001
                log.debug("plan_slot_validation_failed", error=str(e))

            result = GeneratedPlan(
                plan=valid_steps,
                needs_clarification=bool(data.get("needs_clarification", False)),
                confidence=float(data.get("confidence", 0.0)),
                ambiguity_reasons=ambiguity,
                summary=str(data.get("summary") or ""),
                raw_response=raw,
            )

            # Stage 3 — PLAN_DEDUPE: flag on 시 중복 tool step 후처리.
            # flag off → 호출 자체 없음 (byte-equal 보장).
            if is_enabled(FeatureFlag.PLAN_DEDUPE, tenant_id=tenant_id):
                from src.agent_framework.runtime.plan_postprocess.plan_dedupe import (
                    dedupe_plan as _dedupe_plan,
                    from_plan_step as _from_plan_step,
                )

                # D28 §2 — 빌드 룰은 plan_dedupe 모듈이 캡슐화 (helper).
                # orchestrator 는 raw 의 키 구조 (tool/args/expr) 를 알 필요 없음.
                _deduped_inputs = [_from_plan_step(s) for s in result.plan]
                _deduped_steps, _dedupe_notes = _dedupe_plan(_deduped_inputs)
                if _dedupe_notes:
                    log.info(
                        "plan_dedupe_applied",
                        removed=len(_dedupe_notes),
                        original_len=len(result.plan),
                        new_len=len(_deduped_steps),
                    )
                    # deduped_steps 는 step number 보존 — 원본 PlanStep 객체 매핑.
                    _kept_step_nums = {ds.step for ds in _deduped_steps}
                    _new_plan = [s for s in result.plan if s.step in _kept_step_nums]
                    result = GeneratedPlan(
                        plan=_new_plan,
                        needs_clarification=result.needs_clarification,
                        confidence=result.confidence,
                        ambiguity_reasons=result.ambiguity_reasons,
                        summary=result.summary,
                        raw_response=result.raw_response,
                    )
                # dedupe_notes 비어 있으면 result 그대로 (재할당 X).

            return result
        except Exception as e:  # noqa: BLE001
            log.warning(
                "plan_generation_failed",
                error=str(e),
                error_type=type(e).__name__,
                raw_preview=(raw[:200] if "raw" in dir() and raw else "(no raw)"),
            )
            return None
