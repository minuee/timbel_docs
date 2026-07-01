"""ProcessRunner factory — engine 의 detection-only 람다를 대체.

V5-P4 미완 close. ``engine.py:636`` 의
    process_runner_factory=lambda **_kw: None,  # detection-only
를 본 모듈의 :func:`make_process_runner_factory` 결과로 교체한다.

factory(skill_name=...) 호출 시 해당 skill 의 ProcessRunner 인스턴스를 반환.
process 정의가 없는 sub-skill 은 None 반환 → orchestrator 가 retrieval-only fallback.

2026-05-07 fix — ``ProcessRunner.__init__`` 은 ``skill, llm_client, tool_invoker``
3 개를 모두 요구하는데, 이전 구현은 ``llm`` 이라는 잘못된 키워드 + ``tool_invoker``
누락으로 매번 TypeError → fallback 을 거치며 ``orchestrator_factory_init_failed``
warning 을 남기고 None 반환했다 (daily_briefing 등 process 정의 있는 sub-skill 의
실 실행 자체가 봉쇄). 정상 DI 로 교체.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

log = structlog.get_logger(__name__)


# ProcessRunner 가 기대하는 ToolInvoker 시그니처 — process_runner.ToolInvoker 와 동일.
# (name: str, args: dict, slots: dict) -> Awaitable[str]
ToolInvoker = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[str]]


async def _noop_tool_invoker(
    name: str, args: dict[str, Any], slots: dict[str, Any]
) -> str:
    """tool_invoker 미주입 시 안전 fallback. 빈 문자열 반환 (tool 결과 없음).

    ProcessRunner._handle_run 은 결과를 ``slots[<tool>_result]`` 에 저장만 하고
    다음 step 으로 진행하므로, 빈 결과여도 워크플로 자체는 깨지지 않는다.
    실 운영 wire 에선 engine 이 ToolRegistry 어댑터를 주입.
    """
    log.debug("orchestrator_factory_noop_tool_invoker", tool=name)
    return ""


@dataclass
class OrchestratorDeps:
    """ProcessRunner 가 advance() 시 필요로 하는 의존성 묶음."""
    llm_client: Any
    skill_catalog: dict[str, Any]  # name -> SkillV2
    response_generator: Any | None = None  # 옵션 (template render 시)
    # 2026-05-07 — ProcessRunner 의 ``run`` step (tool 호출) 을 실 실행하려면
    # tool_invoker 가 필요. 미주입이면 _noop_tool_invoker 로 안전 fallback.
    tool_invoker: ToolInvoker = field(default=_noop_tool_invoker)


def make_process_runner_factory(deps: OrchestratorDeps) -> Callable[..., Any]:
    """factory(skill_name) -> ProcessRunner | None 클로저 반환.

    skill 의 process 정의가 없거나 알 수 없는 skill 이면 None — orchestrator 가
    sub-skill 을 retrieval-only (페르소나 답변 단편) 로 fallback.
    """
    def _factory(*, skill_name: str, **_kw: Any) -> Any:
        skill = deps.skill_catalog.get(skill_name)
        if skill is None:
            log.debug("orchestrator_factory_unknown_skill", skill=skill_name)
            return None
        process = getattr(skill, "process", None)
        if not process:
            log.debug("orchestrator_factory_no_process", skill=skill_name)
            return None
        try:
            from src.agent_framework.skills.process_runner import ProcessRunner
        except Exception as e:  # noqa: BLE001
            log.warning("orchestrator_factory_import_failed", error=str(e))
            return None
        try:
            # ProcessRunner.__init__(skill, llm_client, tool_invoker) — 3 개 모두 명시 DI.
            return ProcessRunner(
                skill=skill,
                llm_client=deps.llm_client,
                tool_invoker=deps.tool_invoker,
            )
        except TypeError as e:
            # ProcessRunner 시그니처 변형 (legacy ``llm=`` 등) — 호환 최소 인자 + 경고.
            log.warning(
                "orchestrator_factory_init_signature_mismatch",
                skill=skill_name,
                error=str(e),
            )
            try:
                return ProcessRunner(skill=skill)
            except Exception as e2:  # noqa: BLE001
                log.warning(
                    "orchestrator_factory_init_failed",
                    skill=skill_name,
                    error=str(e2),
                )
                return None
        except Exception as e:  # noqa: BLE001
            log.warning(
                "orchestrator_factory_init_failed",
                skill=skill_name,
                error=str(e),
            )
            return None
    return _factory
