from __future__ import annotations
from typing import Any, Awaitable, Callable, Literal

ToolFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# Phase 2 (#153) — 도구별 default scope.
# spec: docs/superpowers/specs/2026-05-07-tool-scope-architecture.md §3.
# 4 단계: tenant > user > agent > session.
ScopeLiteral = Literal["tenant", "user", "agent", "session"]


class ToolNotFound(KeyError):
    pass


class ToolRegistry:
    def __init__(
        self,
        tools: dict[str, ToolFn] | None = None,
        descriptions: dict[str, str] | None = None,
        scopes: dict[str, ScopeLiteral] | None = None,
    ):
        """ToolRegistry — 도구 호출 + 메타데이터 보관.

        Parameters
        ----------
        tools: 도구 이름 → async callable. 호출 규약 ``(args:dict) -> dict``.
        descriptions: 도구 이름 → 한 줄 한국어 설명. plan_orchestrator catalog 용.
        scopes: 도구 이름 → ``'tenant' | 'user' | 'agent' | 'session'``.
            Phase 2 (#153) — manifest 메타데이터 *only*. runtime 동작 변경 X
            (Phase 4 #155 에서 engine 자동 inject 도입 예정). 미등록 도구는
            ``get_default_scope`` 가 보수적으로 ``'agent'`` 반환 (over-isolate).
        """
        self._tools: dict[str, ToolFn] = dict(tools or {})
        self._descriptions: dict[str, str] = dict(descriptions or {})
        self._scopes: dict[str, str] = dict(scopes or {})

    def register(
        self,
        name: str,
        fn: ToolFn,
        *,
        description: str = "",
        replace: bool = False,
        default_scope: ScopeLiteral | None = None,
    ) -> None:
        if name in self._tools and not replace:
            raise ValueError(f"tool already registered: {name} (pass replace=True to override)")
        self._tools[name] = fn
        if description:
            self._descriptions[name] = description
        if default_scope is not None:
            # set_default_scope 재사용 — invalid scope 검증 일관성.
            self.set_default_scope(name, default_scope)

    def set_description(self, name: str, description: str) -> None:
        """tool 등록 후 설명 추가/교체."""
        self._descriptions[name] = description

    def get_description(self, name: str) -> str:
        """tool 한 줄 설명 조회 — 등록 안 됐거나 description 없으면 빈 문자열.

        D39 (2026-05-11) — `describe_catalog()` 문자열 파싱 대신 structured API.
        """
        return (self._descriptions.get(name) or "").strip()

    def set_default_scope(self, name: str, scope: ScopeLiteral) -> None:
        """tool 등록 후 default_scope 추가/교체. Phase 2 manifest 메타."""
        if scope not in ("tenant", "user", "agent", "session"):
            raise ValueError(
                f"invalid scope '{scope}' — must be one of tenant|user|agent|session"
            )
        self._scopes[name] = scope

    def get_default_scope(self, name: str) -> str:
        """default_scope 조회. Phase 2 (#153).

        매핑에 없으면 ``'agent'`` 반환 — 보수적 over-isolate fallback.
        Phase 4 (#155) enforcement 도입 시 cross-agent leak 보다 access denied
        가 회귀 진단이 쉬우므로 fail-closed 설계.
        """
        return self._scopes.get(name, "agent")

    def list_scopes(self) -> dict[str, str]:
        """tool catalog API / UI 가 모든 도구 default_scope 일괄 노출 용도.

        등록은 됐지만 ``scopes`` 매핑에 없는 도구도 fallback 'agent' 로 채워
        반환. 미등록 도구는 결과에 없음.
        """
        return {name: self.get_default_scope(name) for name in self._tools}

    async def call(
        self,
        name: str,
        args: dict[str, Any],
        *,
        agent_context: Any = None,
    ) -> dict[str, Any]:
        """tool 단일 dispatch.

        D72 (2026-05-12) — single choke point allowed_tools 가드.
        ``agent_context`` 를 받으면 ``enforce_allowed_tools()`` 로 사전 검증.
        차단 시 tool 미실행 + 통일된 ``blocked_result`` dict 반환 (LLM 에
        OOS 컨텍스트 피드백). ``agent_context=None`` (default) 일 때 옛 동작
        그대로 — 회귀 0 보장.

        # 호출자 책임
        - admin / role 정합은 ``agent_context.allowed_tools`` 의 의미
          (``None``=open, ``[]``=closed, ``[...]``=명시 list) 에 따른다.
        - helper 가 차단해도 호출자는 결과 dict 를 정상 흐름으로 처리
          (LLM 컨텍스트에 결과 piped — 다음 턴에 OOS 합성 가능).

        # canonical name
        현재 ToolRegistry 는 alias 시스템이 없음 — 모든 tool 이 단일 정식
        이름으로 ``self._tools`` dict key 에 등록. ``name`` 인자가 곧
        canonical. GPT-5 D72 post verdict 권고: 추후 alias 도입 시 ``name``
        을 canonical name 으로 *먼저* 변환한 후 가드 실행하도록 보강할 것
        (현재 NA).

        # 에러 schema 정합 (GPT-5 D72 post verdict 권고)
        - 차단: ``blocked_result`` (success=False, error="tool_blocked_by_allowed_tools",
          blocked_reason, tool, user_message)
        - 미등록: ``ToolNotFound`` 예외 (raise) — 호출자 측에서 처리.
          기존 시그니처와 호환 (호출자가 try/except 로 unknown tool 처리).
        """
        if agent_context is not None:
            # 지연 import — 순환 의존 차단 (tool_guard → registry 역방향 X).
            from src.agent_framework.runtime.tool_guard import (
                blocked_result,
                enforce_allowed_tools,
                log_block,
            )

            decision = enforce_allowed_tools(agent_context, name)
            if not decision.allowed:
                log_block(
                    agent_context=agent_context,
                    tool_name=name,
                    decision=decision,
                    source="registry",
                )
                return blocked_result(name, decision)
        else:
            # D72 GPT-5 post verdict 권고 — agent_context=None 누락 감지.
            # registry.call 이 agent_context 없이 호출되면 choke point 가드가
            # 비활성. 의도된 (legacy / default chat / test) 경로일 수 있으나,
            # 신규 코드 path 에서 누락이면 backdoor 가능. ENV 로 opt-in.
            import os as _os
            if _os.environ.get("TOOL_GUARD_WARN_ON_MISSING_CONTEXT") == "1":
                import warnings as _warnings
                _warnings.warn(
                    f"ToolRegistry.call('{name}') invoked without agent_context "
                    "— allowed_tools guard inactive on this path.",
                    RuntimeWarning,
                    stacklevel=2,
                )
        if name not in self._tools:
            raise ToolNotFound(name)
        return await self._tools[name](args)

    def list_names(self) -> list[str]:
        """등록된 모든 tool 이름. plan_orchestrator 의 available_tools_summary 용."""
        return list(self._tools.keys())

    def describe_catalog(self) -> str:
        """plan_generation prompt 의 available_tools 입력. 이름 + 한 줄 설명.

        설명 미등록 tool 은 이름만 노출. 설명은 LLM 이 *어떤 tool 이 무슨
        목적인지* 바로 파악하게 해주는 자연어 anchor (사례 enum 아닌 도메인
        설명).
        """
        out = []
        for name in sorted(self._tools):
            desc = self._descriptions.get(name, "").strip()
            if desc:
                out.append(f"- {name}: {desc}")
            else:
                out.append(f"- {name}")
        return "\n".join(out)
