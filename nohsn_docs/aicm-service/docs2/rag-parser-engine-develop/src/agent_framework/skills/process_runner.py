"""Process Runner — SkillV2.process.steps 순회 실행 엔진.

Phase 8.5. 각 step kind:

- ``elicit``: LLM 으로 사용자 발화에서 slot 추출. 부족하면 재질문.
- ``run``: tool 호출 (외부에서 주입한 invoker 가 담당).
- ``render``: LLM 으로 답변 생성 (template + slot 값 + tool 결과).
- ``approve_request``: 사용자 yes/no 분기 (LLM 분류).
- ``notify``: 정해진 메시지 출력 후 다음 step.
- ``delegate``: 다른 skill 로 인계 (engine 이 처리하도록 신호).

State 는 dict — engine 이 turn 마다 ``advance`` 호출. dataclass 의 단순한
참조 구현이며, 외부 영속화/타임아웃은 호출자가 결정.

LLM 사용 — rule/regex 없음. ``slot_extract.md``, ``approve_classify.md`` prompt 참조.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from src.agent_framework.llm.json_parse import extract_json
from src.agent_framework.skills.schema_v2 import SkillProcessStep, SkillV2
from src.common.logging import get_logger

log = get_logger(__name__)


_PROMPT_DIR = Path(__file__).parent / "prompts"


class LLMClient(Protocol):
    async def complete(
        self, system: str, user: str, *, response_format: str | None = None
    ) -> str: ...


# tool_invoker(name, args, slots) -> str (tool 결과 문자열)
ToolInvoker = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[str]]


@dataclass
class StepResult:
    """advance() 의 반환 — 외부 engine 이 그대로 응답에 넣고 state 갱신."""

    response: str
    next_state: dict[str, Any]
    done: bool


def _initial_state() -> dict[str, Any]:
    return {"slots": {}, "current_step_idx": 0, "last_tool_result": None}


def _format_template(template: str, ctx: dict[str, Any]) -> str:
    """간단한 ``{key}`` 치환. 누락 키는 빈 문자열로 둔다 (KeyError 회피)."""

    class _SafeDict(dict):
        def __missing__(self, key):  # type: ignore[override]
            return ""

    try:
        return template.format_map(_SafeDict(ctx))
    except (IndexError, ValueError):
        return template


class ProcessRunner:
    """SkillV2 의 process.steps 를 순차 실행하는 엔진.

    사용 패턴:
        runner = ProcessRunner(skill, llm_client, tool_invoker)
        state = {}
        result = await runner.advance(user_input="가입하려고요", state=state)
        # result.response 를 사용자에게 보여주고
        # result.next_state 를 다음 turn 까지 보관.
        # result.done == True 면 process 종료.
    """

    def __init__(
        self,
        skill: SkillV2,
        llm_client: LLMClient,
        tool_invoker: ToolInvoker,
    ):
        self.skill = skill
        self.llm = llm_client
        self.tool_invoker = tool_invoker

    # ----------------------------- core ---------------------------------

    async def advance(
        self,
        *,
        user_input: str | None,
        state: dict[str, Any],
        mode: str = "interactive",
    ) -> StepResult:
        """현재 step 1개를 처리하고, 가능하면 다음 step 으로 이동한다.

        - elicit/approve_request 는 사용자 입력이 더 필요하면 같은 step 에 머무름.
        - run/render/notify 는 즉시 처리하고 다음 step 으로.
        - delegate 는 done=True 로 두고 response 에 인계 신호.

        Wave 6 — ``mode`` 인자:
        - "interactive" (default): 기존 동작. elicit 시 사용자 입력 대기.
        - "auto": compound 모드 — elicit 의 missing 슬롯은 LLM default 추론으로 채움
          (사용자 질문 X). approve 는 자동 승인. UX 일관성 (compound 안 4 sub 가
          모두 사용자에게 질문하면 깨짐) 보장.
        """
        if not state:
            state = _initial_state()
        # state 에 누락된 키 보정
        state.setdefault("slots", {})
        state.setdefault("current_step_idx", 0)
        state.setdefault("last_tool_result", None)

        if self.skill.process is None or not self.skill.process.steps:
            return StepResult(response="", next_state=state, done=True)

        steps = self.skill.process.steps
        idx = int(state["current_step_idx"])
        if idx >= len(steps):
            return StepResult(response="", next_state=state, done=True)

        step = steps[idx]
        kind = step.kind

        if kind == "elicit":
            return await self._handle_elicit(step, user_input, state, idx, steps, mode=mode)
        if kind == "run":
            return await self._handle_run(step, state, idx, steps)
        if kind == "render":
            return await self._handle_render(step, state, idx, steps)
        if kind == "approve_request":
            return await self._handle_approve(step, user_input, state, idx, steps, mode=mode)
        if kind == "notify":
            return self._handle_notify(step, state, idx, steps)
        if kind == "delegate":
            return self._handle_delegate(step, state)

        # 알 수 없는 kind — skip 하고 다음 step
        log.error("process_runner unknown step kind", kind=kind, skill=self.skill.name)
        state["current_step_idx"] = idx + 1
        return StepResult(
            response="",
            next_state=state,
            done=state["current_step_idx"] >= len(steps),
        )

    # ----------------------------- handlers -----------------------------

    async def _handle_elicit(
        self,
        step: SkillProcessStep,
        user_input: str | None,
        state: dict[str, Any],
        idx: int,
        steps: list[SkillProcessStep],
        *,
        mode: str = "interactive",
    ) -> StepResult:
        required: list[str] = list(step.config.get("slots", []) or [])
        question: str = str(step.config.get("question", "필요한 정보를 알려주세요."))
        slots: dict[str, Any] = dict(state["slots"])

        # 1) user_input 이 있으면 LLM 으로 슬롯 추출 시도
        if user_input and user_input.strip():
            extracted = await self._extract_slots(
                required=required,
                user_input=user_input,
                accumulated=slots,
            )
            slots.update(extracted)
            state["slots"] = slots

        # 2) 충족 여부
        missing = [s for s in required if not slots.get(s)]
        if missing:
            # Wave 6 — mode="auto" (compound 안): LLM 이 default 추론으로 슬롯 자동 채움.
            # 사용자 질문 X. 부족한 슬롯은 None 으로 두되 다음 step 진행.
            if mode == "auto":
                # 기본값 추론 — _extract_slots 를 빈 user_input 으로 1회 호출 (LLM 이 컨텍스트로 추론)
                try:
                    auto_filled = await self._extract_slots(
                        required=missing,
                        user_input=str(state.get("auto_context", "") or "(컨텍스트로 자동 추론)"),
                        accumulated=slots,
                    )
                    slots.update(auto_filled or {})
                    state["slots"] = slots
                except Exception:  # noqa: BLE001
                    pass
                # 여전히 부족해도 진행 (부분 답변 수용)
                state["current_step_idx"] = idx + 1
                if state["current_step_idx"] >= len(steps):
                    return StepResult(response="", next_state=state, done=True)
                return await self.advance(user_input=None, state=state, mode=mode)

            # interactive — 같은 step 에 머무름. 첫 진입(=user_input None)이면 question, 재시도면 안내+question
            prefix = "" if user_input is None else f"'{', '.join(missing)}' 정보가 더 필요해요. "
            return StepResult(
                response=f"{prefix}{question}".strip(),
                next_state=state,
                done=False,
            )

        # 다 채워짐 → 다음 step 으로 자동 진행 (user gate 통과 후 즉시 다음 안내)
        state["current_step_idx"] = idx + 1
        if state["current_step_idx"] >= len(steps):
            return StepResult(response="", next_state=state, done=True)
        return await self.advance(user_input=None, state=state)

    async def _handle_run(
        self,
        step: SkillProcessStep,
        state: dict[str, Any],
        idx: int,
        steps: list[SkillProcessStep],
    ) -> StepResult:
        tool_name: str = str(step.config.get("tool", ""))
        args: dict[str, Any] = dict(step.config.get("args", {}) or {})
        if not tool_name:
            log.error("process_runner run step missing tool name", skill=self.skill.name)
            state["current_step_idx"] = idx + 1
            return StepResult(
                response="", next_state=state, done=state["current_step_idx"] >= len(steps)
            )

        try:
            result = await self.tool_invoker(tool_name, args, dict(state["slots"]))
        except Exception as e:  # noqa: BLE001
            log.error("process_runner tool failed", tool=tool_name, error=str(e))
            result = ""

        state["last_tool_result"] = result
        # tool 결과를 slots 에도 ``<tool>_result`` 로 기록 (template 참조용)
        state["slots"][f"{tool_name}_result"] = result
        state["current_step_idx"] = idx + 1
        return StepResult(
            response="", next_state=state, done=state["current_step_idx"] >= len(steps)
        )

    async def _handle_render(
        self,
        step: SkillProcessStep,
        state: dict[str, Any],
        idx: int,
        steps: list[SkillProcessStep],
    ) -> StepResult:
        template: str = str(step.config.get("template", ""))
        ctx = dict(state["slots"])
        if state.get("last_tool_result"):
            ctx.setdefault("tool_result", state["last_tool_result"])
        rendered = _format_template(template, ctx) if template else ""

        # 추가로 LLM 윤문이 필요하면 polish=True
        if step.config.get("polish"):
            try:
                rendered = await self.llm.complete(
                    system="아래 안내 문구를 자연스러운 한국어로 다듬어 주세요. 사실은 바꾸지 마세요.",
                    user=rendered,
                )
            except Exception as e:  # noqa: BLE001
                log.error("process_runner render polish failed", error=str(e))

        state["current_step_idx"] = idx + 1
        return StepResult(
            response=rendered,
            next_state=state,
            done=state["current_step_idx"] >= len(steps),
        )

    async def _handle_approve(
        self,
        step: SkillProcessStep,
        user_input: str | None,
        state: dict[str, Any],
        idx: int,
        steps: list[SkillProcessStep],
        *,
        mode: str = "interactive",
    ) -> StepResult:
        question: str = str(step.config.get("question", "진행할까요?"))

        # Wave 6 — mode="auto" 면 자동 승인 (compound 안 사용자 승인 단계 우회)
        if mode == "auto":
            state["current_step_idx"] = idx + 1
            if state["current_step_idx"] >= len(steps):
                return StepResult(response="", next_state=state, done=True)
            return await self.advance(user_input=None, state=state, mode=mode)

        # 첫 진입이면 질문만 표시
        if user_input is None or not user_input.strip():
            return StepResult(response=question, next_state=state, done=False)

        decision = await self._classify_approve(user_input)
        if decision == "approve":
            # 승인됨 → 다음 step 으로 자동 진행 (user gate 통과 후 즉시 결과 안내)
            state["current_step_idx"] = idx + 1
            if state["current_step_idx"] >= len(steps):
                return StepResult(response="", next_state=state, done=True)
            return await self.advance(user_input=None, state=state)
        if decision == "reject":
            # 종료 — 거절 시 done
            state["current_step_idx"] = len(steps)
            on_reject = str(step.config.get("on_reject", "알겠습니다. 진행하지 않을게요."))
            return StepResult(response=on_reject, next_state=state, done=True)
        # unclear → 같은 step 머무름, 재질문
        return StepResult(
            response=f"네/아니요로 답해 주실 수 있을까요? {question}",
            next_state=state,
            done=False,
        )

    def _handle_notify(
        self,
        step: SkillProcessStep,
        state: dict[str, Any],
        idx: int,
        steps: list[SkillProcessStep],
    ) -> StepResult:
        message: str = str(step.config.get("message", ""))
        ctx = dict(state["slots"])
        rendered = _format_template(message, ctx) if message else ""
        state["current_step_idx"] = idx + 1
        return StepResult(
            response=rendered,
            next_state=state,
            done=state["current_step_idx"] >= len(steps),
        )

    def _handle_delegate(
        self, step: SkillProcessStep, state: dict[str, Any]
    ) -> StepResult:
        target: str = str(step.config.get("to", ""))
        # delegate 는 즉시 종료. engine 이 ``next_state['delegate_to']`` 를 보고 처리.
        state["delegate_to"] = target
        return StepResult(
            response=f"[delegate→{target}]" if target else "",
            next_state=state,
            done=True,
        )

    # ----------------------------- helpers ------------------------------

    async def _extract_slots(
        self,
        *,
        required: list[str],
        user_input: str,
        accumulated: dict[str, Any],
    ) -> dict[str, Any]:
        if not required:
            return {}
        system = (_PROMPT_DIR / "slot_extract.md").read_text(encoding="utf-8")
        user = (
            f"[채워야 할 슬롯]\n- " + "\n- ".join(required) + "\n\n"
            f"[누적된 슬롯]\n{json.dumps(accumulated, ensure_ascii=False)}\n\n"
            f"[사용자 발화]\n{user_input.strip()}\n"
        )
        try:
            raw = await self.llm.complete(system, user, response_format="json_object")
        except Exception as e:  # noqa: BLE001
            log.error("process_runner slot extract llm failed", error=str(e))
            return {}
        try:
            parsed = extract_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            log.error("process_runner slot extract json parse failed", error=str(e))
            return {}
        slots = parsed.get("slots") if isinstance(parsed, dict) else None
        if not isinstance(slots, dict):
            return {}
        # 키를 required 안의 것만 허용 (할루시네이션 차단)
        allowed = set(required)
        return {k: v for k, v in slots.items() if k in allowed and v not in (None, "")}

    async def _classify_approve(self, user_input: str) -> str:
        system = (_PROMPT_DIR / "approve_classify.md").read_text(encoding="utf-8")
        user = f"[사용자 응답]\n{user_input.strip()}\n"
        try:
            raw = await self.llm.complete(system, user, response_format="json_object")
        except Exception as e:  # noqa: BLE001
            log.error("process_runner approve llm failed", error=str(e))
            return "unclear"
        try:
            parsed = extract_json(raw)
        except (ValueError, json.JSONDecodeError):
            return "unclear"
        decision = parsed.get("decision") if isinstance(parsed, dict) else None
        if decision in ("approve", "reject", "unclear"):
            return decision
        return "unclear"
