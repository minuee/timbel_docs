"""Tool-calling agent loop — JSON mode 클라이언트 파싱.

Gemma 4 가 매 턴 단일 JSON 객체 출력하도록 강제.
  {"tool": {"name": "...", "arguments": {...}}}  → tool 호출
  {"response": "..."}                            → 사용자에게 직접 답변

vLLM tool-call parser 불필요 (response_format=json_object 만 사용).

SSE event 매핑:
- tool_call_request {name, arguments}
- tool_call_result  {name, result_keys, result}
- token             {text}
- done              {}
- kms_rag_dedup_hit {name, key_hash}  (D22 — turn-내 중복 차단 시)
"""
from __future__ import annotations

import hashlib
import json
from typing import AsyncIterator, Protocol

from src.agent_framework.agent.tool_schemas import all_schemas, tool_name_set
from src.agent_framework.conversation.fallback_composer import (
    FallbackComposer,
    FallbackContext,
)
from src.agent_framework.runtime.time_context import prepend_time
from src.agent_framework.tools.registry import ToolNotFound, ToolRegistry
from src.common.logging import get_logger

log = get_logger(__name__)


def _classify_error_kind(exc: Exception) -> str:
    """exception 을 fallback_composer 의 error_kind 분류 라벨로 매핑.

    httpx 가 없는 경우도 안전하게 — 클래스명 부분 일치만으로 판정.
    """
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg:
        return "timeout"
    if "unauthor" in name or "401" in msg or "403" in msg or "auth" in msg:
        return "unauthorized"
    if "ratelimit" in name or "429" in msg or "rate limit" in msg:
        return "rate_limited"
    if "connect" in name or "503" in msg or "502" in msg or "service" in msg:
        return "service_down"
    return "unknown"


class JSONModeLLM(Protocol):
    """OpenAI-compatible chat completion with response_format=json_object."""

    async def chat_completion_json(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str: ...


_SYSTEM_BASE = """너는 개인 AI 매니저다. 사용자의 일정·일기·뉴스 구독·개인 자료 검색을 돕는다.

**출력 규칙 (절대 준수)**:
매 턴 JSON 객체 하나만 출력하라. 두 형식 중 하나:

1) tool 호출이 필요하면:
   {{"tool": {{"name": "tool_name", "arguments": {{"key": "value"}}}}}}

2) tool 없이 사용자에게 직접 답하면:
   {{"response": "사용자에게 보여줄 자연어 메시지"}}

**사용 가능한 tool** (정확한 이름 + 인자 스키마 준수):
{tools_doc}

**행동 원칙**:
- 사용자가 행동을 요청하면 적절한 tool 을 호출해 실제로 수행.
- 정보 부족하면 tool 호출 대신 response 로 짧게 되묻기.
- 여러 tool 이 필요하면 한 턴에 하나씩 순차 호출 (결과 보고 다음 결정).
- tool 결과가 실패·비어있으면 사용자에게 투명하게 알림.
- 의료 예약 (피부과) 은 별도 상태머신이 처리 — 여기서 관여 금지.
- JSON 외 텍스트 절대 출력 금지. 설명·해설·백틱 모두 금지."""


def _required_slots_str(tool_name: str) -> str:
    """tool 의 *필수 슬롯* 을 LLM 안내용 짧은 문자열로 합성.

    단일 진실원: `src/agent_framework/runtime/tool_schemas.TOOL_SCHEMAS`.
    auto_inject 슬롯 (tenant_id/phone/account_id 등) 은 *제외* — engine 이
    자동 채우므로 사용자/LLM 가 인식할 필요 없음.

    누락 시 빈 문자열 반환 (schema 정의 없는 도구 안전 fallback).
    """
    try:
        from src.agent_framework.runtime.tool_schemas import TOOL_SCHEMAS
    except Exception:  # noqa: BLE001
        return ""
    sch = TOOL_SCHEMAS.get(tool_name)
    if not sch:
        return ""
    auto = set((sch.get("auto_inject") or []))
    required = [s for s in (sch.get("required") or []) if s not in auto]
    groups = sch.get("required_groups") or []
    if required:
        return ", ".join(required)
    if groups:
        # one-of group — '|' 로 표기. 첫 그룹만 노출 (LLM 단순화).
        parts = []
        for g in groups[:2]:  # 최대 2 그룹만
            gp = [s for s in g if s not in auto]
            if gp:
                parts.append(" + ".join(gp))
        if parts:
            return " | ".join(parts) + " (택1)"
    return ""


def _format_tools_doc(
    tool_registry: "ToolRegistry | None" = None,
    *,
    allowed_filter: "set[str] | None" = None,
) -> str:
    """system prompt 에 넣을 tool 문서 (이름 + 설명 + required 파라미터).

    D39 (2026-05-11) — registry 단일 진실원 + agent_context.allowed_tools filter.

    구조화 API (registry.list_names / get_description + runtime.TOOL_SCHEMAS) 사용.
    문자열 파싱 X (포맷 drift 위험 0). 두 source 는 의도적 분리:
      - registry: *카탈로그* (이름 + 설명) 단일 진실원
      - runtime.TOOL_SCHEMAS: *slot policy* (required / auto_inject) 단일 진실원

    - ``allowed_filter`` 주입 시: 해당 set 의 도구만 노출 (defense-in-depth).
    - registry 미주입 / list_names 호출 실패 / 결과 0 lines → 정적 ``_SCHEMAS``
      fallback (옛 호환 — agent_context 없는 legacy/test path 에서만 사용).
    """
    lines: list[str] = []
    _used_registry = False
    if tool_registry is not None and hasattr(tool_registry, "list_names"):
        _used_registry = True
        try:
            names = sorted(tool_registry.list_names())
        except Exception:  # noqa: BLE001
            names = []
        for name in names:
            if allowed_filter is not None and name not in allowed_filter:
                continue
            if hasattr(tool_registry, "get_description"):
                desc = tool_registry.get_description(name) or ""
            else:
                desc = ""
            req = _required_slots_str(name)
            head = f'- "{name}"'
            if desc:
                head += f": {desc}"
            if req:
                head += f" (필수: {req})"
            lines.append(head)
        # registry 가 *주입* 되었으면 그 결과 (빈 list 포함) 를 반환.
        # 빈 list 는 "이 agent 는 도구 허용 없음" 의 명시적 fail-closed 신호.
        # 정적 fallback 으로 *떨어지지 않음* — 권한 우회 차단.
        return "\n".join(lines)
    # fallback — 정적 schema list (registry 미주입 시에만, agent_context 없는
    # legacy/test path).
    for s in all_schemas():
        fn = s["function"]
        name = fn["name"]
        if allowed_filter is not None and name not in allowed_filter:
            continue
        desc = fn["description"]
        params = fn.get("parameters", {})
        required = params.get("required", [])
        props = params.get("properties", {})
        req_str = ", ".join(
            f"{k}: {props.get(k, {}).get('type', 'any')}" for k in required
        )
        lines.append(f'- "{name}": {desc} (필수: {req_str})')
    return "\n".join(lines)


class ToolCallingLoop:
    def __init__(
        self,
        llm_client: JSONModeLLM,
        tool_registry: ToolRegistry,
        *,
        max_rounds: int = 5,
        fallback_composer: FallbackComposer | None = None,
    ):
        self.llm = llm_client
        self.tools = tool_registry
        self.max_rounds = max_rounds
        # Wave D (KMS-Plus, 2026-04-25): 외부 호출 실패 시 자연 안내 합성기.
        # None 이면 default 인스턴스 사용 — wire-up 의 최소 침습 default.
        self.fallback_composer = fallback_composer or FallbackComposer()
        # #76 (2026-05-19) — SOP RAG inject layer (lazy). agent_context 가
        # 들어온 첫 호출 시 init. registry 의 ``kms_sop.search`` tool 위임.
        self._sop_inject_layer = None  # type: ignore[assignment]

    async def run(
        self,
        user_message: str,
        *,
        phone: str,
        tenant_id: str,
        history: list[dict] | None = None,
        user_groups: list[str] | None = None,
        default_scope_group: str | None = None,
        agent_context: object | None = None,
    ) -> AsyncIterator[dict]:
        """user turn 실행. dict events yield (engine 이 SSE 로 변환).

        ``user_groups`` 와 ``default_scope_group`` 은 PR-T4 — 사용자가 가진
        scope (개인/회사/사업체/1인사업자) 인지를 LLM 에게 노출. tool 호출 시
        ``scope_group`` 인자 자동 inject (LLM 이 명시한 게 있으면 우선).

        events:
          {type: "tool_call_request", name, arguments}
          {type: "tool_call_result",  name, result_keys, result}
          {type: "token",              text}
          {type: "done"}
        """
        # D39 (2026-05-11) — registry 단일 진실원 + admin allowlist filter.
        # 분기:
        #   - admin (is_admin=True): allowed_tools ∩ registry 로 제한 + registry
        #     사용 (drift guard — admin row 의 outdated typo 차단). fail-closed:
        #     allowed_tools 비어있거나 registry 실패 시 빈 set (명시적 차단).
        #   - non-admin role agent: registry 전체를 직접 노출하면 role 권한 누설
        #     → 옛 정적 _SCHEMAS list 사용 (회귀 0 + 권한 누설 차단의 균형).
        #     role agent allowed_tools 정합 격리는 별도 PR 범위 (D39 외).
        #   - agent_context 없음 (legacy/test): 정적 _SCHEMAS (옛 동작).
        try:
            _registered_names: set[str] | None = (
                set(self.tools.list_names())
                if hasattr(self.tools, "list_names")
                else None
            )
        except Exception:  # noqa: BLE001
            _registered_names = None
        _is_admin_ctx = bool(
            agent_context is not None
            and getattr(agent_context, "is_admin", False)
        )
        _allowed_filter: set[str] | None = None
        _use_registry_for_doc = False
        if _is_admin_ctx:
            _use_registry_for_doc = True  # admin → registry 단일 진실원
            _ac_tools_raw = getattr(agent_context, "allowed_tools", None)
            _ac_tools = list(_ac_tools_raw or [])
            if _registered_names is None:
                # admin 인데 registry 사용 불가 → 정적 fallback 으로 폴백
                # (배포 안전 — fail-closed 시 서비스 중단 회귀 차단).
                _use_registry_for_doc = False
                log.warning(
                    "tool_loop_admin_registry_unavailable_static_fallback",
                    agent_name=getattr(agent_context, "name", "") if agent_context else "",
                )
            elif not _ac_tools:
                # admin 인데 allowed_tools 정의 미비 (None / 빈 list) →
                # admin 의 권한은 모든 등록 도구. 경고 + registry 전체 허용
                # (DB 동기화 전 배포 안전망 — 회귀 0).
                _allowed_filter = set(_registered_names)
                log.warning(
                    "tool_loop_admin_allowed_tools_missing_default_full",
                    agent_name=getattr(agent_context, "name", "") if agent_context else "",
                )
            else:
                _allowed_filter = {
                    t for t in _ac_tools if t in _registered_names
                }
                _unknown = [t for t in _ac_tools if t not in _registered_names]
                if _unknown:
                    log.warning(
                        "tool_loop_admin_filter_unknown",
                        agent_name=getattr(agent_context, "name", ""),
                        unknown=_unknown,
                        kept=len(_allowed_filter),
                    )
                if not _allowed_filter:
                    # admin allowed_tools 가 *전부* unknown → DB 데이터 결함.
                    # 회귀 차단 (서비스 중단 회피) — registry 전체로 폴백 + 경고.
                    _allowed_filter = set(_registered_names)
                    log.warning(
                        "tool_loop_admin_filter_all_unknown_default_full",
                        agent_name=getattr(agent_context, "name", ""),
                    )
        # non-admin / no agent_context 경로는 registry 사용 X — 정적 fallback.
        tools_doc = _format_tools_doc(
            self.tools if _use_registry_for_doc else None,
            allowed_filter=_allowed_filter,
        )
        scope_hint = ""
        if user_groups:
            scope_hint = (
                f"\n\n사용자 보유 scope: {', '.join(user_groups)}."
                + " 일정·일기·가계부·메일 등 도메인 도구 호출 시 발화에서 추론한"
                + " ``scope_group`` 인자(personal | company | business |"
                + " sole_proprietor) 를 함께 넘겨라. 명시 없으면"
                + f" '{default_scope_group or 'personal'}' default."
            )
        # #76 (2026-05-19) — agent_context 있는 path 는 binding policy +
        # SOP context 를 system 메시지에 prepend. 단일 system role message 로
        # 합성 (GPT-5.5 권고: provider/gateway 별 다중 system 해석 차이 회피).
        # agent_context=None (default chat / legacy / test) 시 회귀 0 — 기존
        # prompt byte-equal.
        _dynamic_blocks: list[str] = []
        if agent_context is not None:
            # 1. binding policy (guidelines_md → OOS guard + 일관 응대 가이드).
            try:
                _bp = agent_context.to_binding_policy_block(sop_rag_mode=True) or ""
                if _bp:
                    _dynamic_blocks.append(_bp)
            except TypeError:
                # 옛 시그니처 호환.
                try:
                    _bp = agent_context.to_binding_policy_block() or ""
                    if _bp:
                        _dynamic_blocks.append(_bp)
                except Exception as _bp_err:  # noqa: BLE001
                    log.warning(
                        "tool_loop_binding_policy_failed", error=str(_bp_err)
                    )
            except Exception as _bp_err:  # noqa: BLE001
                log.warning("tool_loop_binding_policy_failed", error=str(_bp_err))

            # static base 를 먼저 합성 (SOP budget 계산에 token 비용 합산).
            _static_base_for_budget = (
                _SYSTEM_BASE.format(tools_doc=tools_doc)
                + f"\n\n사용자 식별: phone={phone}, tenant_id={tenant_id}"
                + "\n(tool 호출 시 이 값을 써라. 사용자가 다시 알려주지 않아도 OK.)"
                + scope_hint
            )

            # 2. SOP context block (path-독립 helper 위임).
            # GPT-5.5 verdict §3: static base + tools_doc 비용을 SOP budget 에
            # 합산 — tool_loop path 의 prompt 가 system 한도 초과 방지.
            try:
                from src.agent_framework.runtime.sop_inject import (
                    SopInjectLayer,
                    estimate_tokens,
                )
                from src.agent_framework.runtime.sop_inject_builder import (
                    build_sop_context_block,
                )

                if self._sop_inject_layer is None:
                    async def _tool_call(name: str, args: dict) -> dict:
                        try:
                            return await self.tools.call(name, args) or {}
                        except Exception:  # noqa: BLE001
                            return {"success": False, "chunks": []}

                    self._sop_inject_layer = SopInjectLayer(_tool_call)
                _extra_pre_used = estimate_tokens(_static_base_for_budget)
                _sop_block = await build_sop_context_block(
                    sop_inject_layer=self._sop_inject_layer,
                    agent_ctx=agent_context,
                    user_message=user_message,
                    extra_pre_used_tokens=_extra_pre_used,
                )
                if _sop_block:
                    _dynamic_blocks.append(_sop_block)
            except Exception as _sop_err:  # noqa: BLE001
                # fail-open: SOP inject 실패해도 tool loop 는 정상 진행.
                log.warning(
                    "tool_loop_sop_inject_failed_fail_open", error=str(_sop_err)
                )

        _static_base = (
            _SYSTEM_BASE.format(tools_doc=tools_doc)
            + f"\n\n사용자 식별: phone={phone}, tenant_id={tenant_id}"
            + "\n(tool 호출 시 이 값을 써라. 사용자가 다시 알려주지 않아도 OK.)"
            + scope_hint
        )
        # 단일 system role message 로 합침. dynamic block (binding/SOP) 가
        # 앞에 — static base 의 tool 출력 규칙·페르소나 보조 지시 보다 *우선*
        # 적용. 충돌 시 binding/SOP 우선 (precedence 명시).
        if _dynamic_blocks:
            _precedence_note = (
                "주의: 위 BINDING POLICY 또는 SOP CONTEXT 가 아래 출력 규칙·"
                "도구 행동과 충돌하면 BINDING POLICY / SOP CONTEXT 를 우선한다."
            )
            sys = prepend_time(
                "\n\n".join(_dynamic_blocks)
                + "\n\n" + _precedence_note
                + "\n\n" + _static_base
            )
        else:
            sys = prepend_time(_static_base)
        messages: list[dict] = [{"role": "system", "content": sys}]

        if history:
            for h in history[-6:]:
                r = h.get("role", "user")
                c = h.get("content", "")
                if r and c:
                    messages.append({"role": r, "content": str(c)})

        messages.append({"role": "user", "content": user_message})

        # D39 (2026-05-11) — valid_names 도 tools_doc 와 정합 (admin filter 적용).
        # admin: _allowed_filter (registry ∩ allowed_tools). registry 사용 불가
        #        시 정적 _SCHEMAS fallback (서비스 중단 회피).
        # non-admin / legacy: 정적 tool_name_set() (옛 동작 보존, 회귀 0).
        if _is_admin_ctx and _use_registry_for_doc:
            valid_names = (
                set(_allowed_filter)
                if _allowed_filter is not None
                else set(_registered_names or set())
            )
        else:
            valid_names = tool_name_set()

        # D22 (2026-05-08) — kms_rag.search turn-scope dedup cache.
        # key = (name, normalized_query, repo_ids tuple, top_k, search_mode, history_hash)
        # 동일 key 재호출 시 첫 result 재사용 — 4× cache hit search 의 +3.3s 차단.
        # GPT-5 phase 0 verdict — history hash 조건부 포함 (false-dedup 회피).
        _kms_dedup_cache: dict[tuple, dict] = {}

        for _round_idx in range(self.max_rounds):
            try:
                raw = await self.llm.chat_completion_json(messages=messages)
            except Exception as e:
                log.warning("llm_json_call_failed", error=str(e))
                # Wave D — fallback_composer 로 자연 안내 합성.
                fb = self.fallback_composer.compose(
                    FallbackContext(
                        failed_action="응답 생성",
                        error_kind=_classify_error_kind(e),
                    )
                )
                yield {"type": "token", "text": fb}
                yield {"type": "done"}
                return

            parsed = _parse_json_response(raw)
            if parsed is None:
                yield {"type": "token", "text": "응답 형식 오류가 있어 다시 시도해 주세요."}
                yield {"type": "done"}
                return

            # 분기: response / tool
            if "response" in parsed and parsed["response"]:
                final = str(parsed["response"])
                for chunk in _chunk_text(final, size=30):
                    yield {"type": "token", "text": chunk}
                yield {"type": "done"}
                return

            if "tool" in parsed and isinstance(parsed["tool"], dict):
                name = parsed["tool"].get("name", "")
                args = parsed["tool"].get("arguments", {}) or {}

                # scope_group default — LLM 이 명시 안 했고 default 가 주어지면 주입.
                if (
                    default_scope_group
                    and "scope_group" not in args
                    and any(
                        name.startswith(prefix)
                        for prefix in ("schedule.", "diary.", "expense.", "inbox.")
                    )
                ):
                    args["scope_group"] = default_scope_group

                # Phase 1 (알렘빅 072 — 사용자 명시 2026-05-07) — schedule.*
                # *agent scope hardcode*. agent_id 를 server-side 에서 *덮어씀*.
                # LLM 가 다른 agent_id 를 시도해도 boucle 안에서 강제. agent_context
                # 가 None 이면 (default chat) — 옛 동작 (NULL owner) 유지.
                if name.startswith("schedule.") and agent_context is not None:
                    _aid = getattr(agent_context, "agent_id", None)
                    if _aid is not None:
                        args["agent_id"] = str(_aid)

                # 2026-05-08 — assist-stream align. kms_rag.search /
                # kms_sop.search args 에 conversation_history 자동 inject.
                # messages 는 전체 LLM 대화 (system/user/assistant) — 마지막
                # 6 메시지 (3턴) 사용 (assist-stream `_truncate_history` 와 동일).
                # 검색 파이프라인의 LLMQueryRewriter 가 내부에서 ``[-6:]`` 로
                # 3턴까지 활용 — 그 분량을 손실 없이 통과시켜 자연어 query 생성/
                # 리라이팅 능력을 활용 (2026-05-08 사용자 절칙).
                # role 화이트리스트 (user/assistant 만), 길이 cap 1000 char
                # (200 너무 짧음 — 표 답변 1턴이 잘려 의미 손실).
                # LLM 명시 시 유지.
                if name in ("kms_rag.search", "kms_sop.search"):
                    if "conversation_history" not in args or args.get("conversation_history") in (None, ""):
                        _ALLOWED_ROLES = ("user", "assistant")
                        _hist: list[dict[str, str]] = []
                        for _m in (messages or [])[-12:]:  # 최근 12 message scan
                            _r = _m.get("role") if isinstance(_m, dict) else None
                            _c = _m.get("content") if isinstance(_m, dict) else None
                            if not _r or not _c:
                                continue
                            _rs = str(_r).strip().lower()
                            if _rs not in _ALLOWED_ROLES:
                                continue
                            _cs = str(_c).strip()
                            if not _cs:
                                continue
                            if len(_cs) > 1000:
                                _cs = _cs[:1000].rstrip() + "..."
                            _hist.append({"role": _rs, "content": _cs})
                        # 최근 6 메시지 (3턴) — LLMQueryRewriter [-6:] 와 정합.
                        if _hist:
                            args["conversation_history"] = _hist[-6:]

                # cross-industry RAG isolation (KMS-Plus, 2026-05-07) —
                # role agent (admin 아닌 agent_context) 가 kms_rag.search 호출 시
                # primary_repo_ids / fallback_repo_ids 자동 inject. strict 는 LLM
                # 의 명시값을 항상 덮어씀.
                if (
                    name == "kms_rag.search"
                    and agent_context is not None
                    and not getattr(agent_context, "is_admin", False)
                ):
                    isolation = (
                        getattr(agent_context, "knowledge_isolation", None)
                        or "priority"
                    ).lower()
                    primary = list(
                        getattr(agent_context, "primary_repo_ids", None) or []
                    )
                    fallback = list(
                        getattr(agent_context, "fallback_repo_ids", None) or []
                    )
                    if isolation == "strict":
                        args["repo_ids"] = [str(r) for r in primary]
                        args["enforce_repo_ids"] = True
                    elif isolation == "priority":
                        if "repo_ids" not in args or args.get("repo_ids") in (None, ""):
                            merged = primary + [
                                r for r in fallback if r not in primary
                            ]
                            if merged:
                                args["repo_ids"] = [str(r) for r in merged]
                                args["enforce_repo_ids"] = False

                # D22 (2026-05-08) — role agent path 에 use_fallback=False 주입.
                # GPT-5 phase 0 verdict 권고: kms_rag.py 전역 default 유지하되
                # tool_calling_loop 에서 *non-admin role agent* 만 주입. L1→L4
                # 통째 재실행 차단 (0 결과 시 1회 만 검색). LLM 명시 시 보존.
                # GPT-5 phase 1 사전 verdict — enforce_repository_ids 동시 주입.
                if (
                    name == "kms_rag.search"
                    and agent_context is not None
                    and not getattr(agent_context, "is_admin", False)
                    and getattr(agent_context, "kind", "role") == "role"
                    and "use_fallback" not in args
                ):
                    args["use_fallback"] = False
                    # enforce repository_ids 보강 — L4 확장 시에도 cross-tenant 차단.
                    # tool arg 키는 'enforce_repo_ids' (kms_rag.py 가 읽고 SearchRequest
                    # 의 'enforce_repository_ids' 로 mapping). 위 strict 분기에서 이미
                    # 명시된 경우는 보존, 미명시 시 (priority 분기 등) 보강 주입.
                    if "enforce_repo_ids" not in args:
                        args["enforce_repo_ids"] = True

                # D22 dedup — kms_rag.search 만 적용. key 에 history hash 포함.
                _dedup_hit = False
                _dedup_key: tuple | None = None
                if name == "kms_rag.search":
                    _q_norm = " ".join(str(args.get("query", "")).split()).lower()
                    _repo_tuple = tuple(sorted(
                        str(r) for r in (args.get("repo_ids") or [])
                    ))
                    _top_k = int(args.get("top_k", 5))
                    _mode = str(args.get("search_mode", "hybrid"))
                    _hist = args.get("conversation_history")
                    _hist_hash = ""
                    if isinstance(_hist, list) and _hist:
                        try:
                            _hist_str = json.dumps(_hist[-6:], sort_keys=True, ensure_ascii=False)
                            _hist_hash = hashlib.sha1(
                                _hist_str.encode("utf-8", errors="replace")
                            ).hexdigest()[:16]
                        except Exception:  # noqa: BLE001
                            _hist_hash = ""
                    _dedup_key = (name, _q_norm, _repo_tuple, _top_k, _mode, _hist_hash)
                    if _dedup_key in _kms_dedup_cache:
                        _dedup_hit = True
                        result = _kms_dedup_cache[_dedup_key]
                        log.info(
                            "kms_rag_dedup_hit",
                            query_len=len(_q_norm),
                            repo_count=len(_repo_tuple),
                            top_k=_top_k,
                            history_present=bool(_hist_hash),
                        )

                if not _dedup_hit:
                    # D72 (2026-05-12) — call-time allowed_tools 가드 (LLM 환각
                    # 도구 호출 차단). agent_context 가 정의된 path 에 한해 검사.
                    # registry.call() 의 choke point 와 belt-and-suspenders.
                    from src.agent_framework.runtime.tool_guard import (
                        blocked_result as _blocked_result,
                        enforce_allowed_tools as _enforce_allowed,
                        log_block as _log_block,
                    )

                    _guard_decision = _enforce_allowed(agent_context, name)
                    if not _guard_decision.allowed:
                        _log_block(
                            agent_context=agent_context,
                            tool_name=name,
                            decision=_guard_decision,
                            source="tool_calling_loop",
                        )
                        result = _blocked_result(name, _guard_decision)
                    elif name not in valid_names:
                        result = {"error": f"unknown tool: {name}"}
                    else:
                        try:
                            result = await self.tools.call(
                                name, args, agent_context=agent_context
                            )
                        except ToolNotFound:
                            result = {"error": f"tool not registered: {name}"}
                        except Exception as e:
                            log.warning("tool_call_failed", name=name, error=str(e))
                            # Wave D — tool 호출 실패도 fallback_composer 로 사용자
                            # 친화 안내. result 는 LLM 다음 턴 입력으로 그대로 둬
                            # 모델이 컨텍스트에 따라 다음 행동을 결정 가능.
                            result = {
                                "error": str(e),
                                "error_kind": _classify_error_kind(e),
                                "user_message": self.fallback_composer.compose(
                                    FallbackContext(
                                        failed_action=name.replace(".", " "),
                                        error_kind=_classify_error_kind(e),
                                    )
                                ),
                            }
                    # 성공한 kms_rag.search 결과만 cache (error 는 cache X — retry 가능).
                    if (
                        _dedup_key is not None
                        and isinstance(result, dict)
                        and not result.get("error")
                    ):
                        _kms_dedup_cache[_dedup_key] = result

                if _dedup_hit:
                    yield {
                        "type": "kms_rag_dedup_hit",
                        "name": name,
                        "key_hash": hashlib.sha1(
                            json.dumps(_dedup_key, sort_keys=True, ensure_ascii=False).encode("utf-8")
                        ).hexdigest()[:8] if _dedup_key else "",
                    }

                yield {"type": "tool_call_request", "name": name, "arguments": args}
                yield {
                    "type": "tool_call_result",
                    "name": name,
                    "result_keys": list(result.keys()) if isinstance(result, dict) else [],
                    "result": result,
                }

                # assistant 응답 (tool 호출) + 그에 대한 tool 결과 를 히스토리에 append
                messages.append(
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)}
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"[tool 결과 '{name}']\n"
                            f"{json.dumps(result, ensure_ascii=False)}\n\n"
                            "이제 사용자에게 응답하거나 다음 tool 호출을 결정해라."
                        ),
                    }
                )
                continue

            # tool 도 response 도 아닌 이상한 JSON
            yield {"type": "token", "text": "응답을 이해하지 못했어요. 다시 말씀해 주실래요?"}
            yield {"type": "done"}
            return

        # max_rounds 초과
        yield {"type": "token", "text": "처리가 복잡해 마무리 못 했어요. 다시 시도해 주세요."}
        yield {"type": "done"}


def _parse_json_response(raw: str) -> dict | None:
    """Gemma 응답에서 JSON 객체 추출 (markdown 펜스 등 래핑 내성)."""
    from src.agent_framework.llm.json_parse import extract_json

    try:
        data = extract_json(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _chunk_text(s: str, size: int = 30) -> list[str]:
    if not s:
        return []
    return [s[i : i + size] for i in range(0, len(s), size)]
