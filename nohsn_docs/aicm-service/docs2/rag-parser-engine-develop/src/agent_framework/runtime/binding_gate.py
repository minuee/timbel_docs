"""BindingGate — L8 (2026-05-07) OOS fast-track.

turn 진입 직후 *user_message* 와 *agent.binding_policy* 를 비교해 도메인 외 발화
이면 plan_orchestrator / state_machine / RAG retrieval 모두 건너뛰고 즉시 거절
template 으로 응답한다.

목표: KB 장병 봇이 "가스 폭발 위험?" 같은 OOS 발화에 20s 8단계 plan 모두 실행 후
거절하던 회귀 → 1.5s 1-shot LLM 분류 후 즉시 응답.

설계 원칙:
- *small model* (gemma-4-12b 등 PLAN_SMALL_MODEL) 사용 — 31B 호출 회피.
- 분류 결과 ``{in_scope: bool, reason: str}`` 만. enum 하드코딩 X.
- in_scope=True → 기존 path 그대로 (binding_gate 효과 0).
- in_scope=False → 거절 메시지 stream + done.
- LLM 실패 / 타임아웃 → in_scope=True default (안전한 fallback — 기존 path).
- flag-gated (FEATURE_BINDING_GATE) — default off.

사용처: ``engine.turn`` 의 첫 step. agent_context 가 set 된 경우만 활성.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from src.common.logging import get_logger

log = get_logger(__name__)


_DEFAULT_TIMEOUT_S = 1.2  # small model 1-shot — 평균 300ms, p95 1.0s.
_DEFAULT_SMALL_MODEL = "google/gemma-3-12b-it"  # PLAN_SMALL_MODEL 와 동일 default.


@dataclass(frozen=True)
class GateDecision:
    in_scope: bool
    reason: str
    rejection_message: str = ""
    elapsed_ms: float = 0.0


def _build_classifier_system(agent_name: str, agent_goal: str, binding_policy: str) -> str:
    """small model 1-shot 분류 prompt — 의도 enum 미사용, in_scope 결정만.

    LLM 패턴 인식 (사용자 발화 ↔ agent 도메인) 으로 일반화. 어휘 리스트 X.
    """
    return (
        "당신은 *상담 도메인 게이트* 다. 주어진 에이전트 정체성 / 목표 / 바인딩 정책을\n"
        "참고해, 사용자 발화가 이 에이전트의 응대 도메인 안인지 한 번에 판단한다.\n\n"
        f"에이전트 이름: {agent_name}\n"
        f"에이전트 목표: {agent_goal or '(미지정)'}\n\n"
        "## 바인딩 정책 / 역할 범위\n"
        f"{binding_policy or '(정책 미지정 — 에이전트 이름·목표 기반 판단)'}\n\n"
        "## 판단 규칙 (in-scope 우선)\n"
        "- *agent.goal / 도메인 운영의 일반 변형* (조회/등록/취소/환불/지연/재배송/\n"
        "  결제/메뉴/매장/리뷰/배달원·라이더·교환·반품·약관·시뮬레이션 같은 일상\n"
        "  요청) 은 *반드시 in_scope=true*. 발화가 짧거나 추상적이라도 도메인\n"
        "  운영의 자연스러운 일상 발화면 true.\n"
        "- 발화가 *명백히 cross-domain* (예: 배달봇에 가스누출, 적금봇에 일정 등록,\n"
        "  가스봇에 주식 시세) 이거나 위험·민감 토픽으로 상담 범위 밖이면\n"
        "  in_scope=false.\n"
        "- *모호하면 true* — false 는 *명백한 cross-domain* 만 (false negative\n"
        "  방지 우선).\n"
        "- 인사말 / 짧은 follow-up / 추가 질문 등은 직전 turn 의 도메인 추정 —\n"
        "  모호하므로 true.\n\n"
        "## 출력 (JSON, 다른 말 없이)\n"
        '{"in_scope": true | false, "reason": "한 줄 한국어 — 왜 이렇게 판단했는지"}'
    )


def _user_payload(user_message: str) -> str:
    return f"사용자 발화:\n{user_message.strip()}\n\nJSON 만 출력하라."


class BindingGate:
    """OOS fast-track classifier + reject responder.

    Args:
        llm: ``VLLMAdapter`` 호환 — ``complete(system, user, *, model=...)``.
        small_model: 분류용 small model 이름. 미지정 시 env ``PLAN_SMALL_MODEL``
            또는 default ``gemma-3-12b-it``.
        timeout_s: 분류 호출 타임아웃 (default 1.2s).
    """

    def __init__(
        self,
        llm: Any,
        *,
        small_model: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ):
        self._llm = llm
        self._small_model = (
            small_model
            or os.environ.get("PLAN_SMALL_MODEL")
            or _DEFAULT_SMALL_MODEL
        )
        self._timeout_s = max(0.3, float(timeout_s))

    async def classify(
        self,
        user_message: str,
        agent_context: Any,
    ) -> GateDecision:
        """small-model 1-shot in/out scope 분류. 실패 시 in_scope=True default."""
        import time as _t

        if self._llm is None or agent_context is None:
            return GateDecision(in_scope=True, reason="llm_or_ctx_unavailable")
        msg = (user_message or "").strip()
        if not msg:
            return GateDecision(in_scope=True, reason="empty_message")
        # 너무 짧은 발화 (인사 등) 는 도메인 추정 모호 → in_scope=True default.
        if len(msg) < 6:
            return GateDecision(in_scope=True, reason="too_short_inconclusive")
        agent_name = getattr(agent_context, "name", "(미지정)") or "(미지정)"
        agent_goal = getattr(agent_context, "goal", "") or ""
        # binding_policy 미설정 시 guidelines_md 의 첫 1500 char 만 사용 (small model
        # context 절약).
        binding_policy = ""
        try:
            binding_policy = (
                agent_context.to_binding_policy_block(sop_rag_mode=True) or ""
            )
        except TypeError:
            try:
                binding_policy = agent_context.to_binding_policy_block() or ""
            except Exception:  # noqa: BLE001
                binding_policy = ""
        except Exception:  # noqa: BLE001
            binding_policy = ""
        if len(binding_policy) > 2500:
            binding_policy = binding_policy[:2500] + "...(truncated)"
        sys_p = _build_classifier_system(agent_name, agent_goal, binding_policy)
        usr_p = _user_payload(msg)
        t0 = _t.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._llm.complete(
                    sys_p,
                    usr_p,
                    response_format="json_object",
                    model=self._small_model,
                ),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            elapsed = (_t.monotonic() - t0) * 1000
            log.info(
                "binding_gate_timeout",
                agent=agent_name,
                elapsed_ms=round(elapsed, 1),
            )
            return GateDecision(
                in_scope=True, reason="timeout_default_pass", elapsed_ms=elapsed
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = (_t.monotonic() - t0) * 1000
            log.warning(
                "binding_gate_call_failed",
                error=str(exc),
                elapsed_ms=round(elapsed, 1),
            )
            return GateDecision(
                in_scope=True, reason="call_failed_default_pass", elapsed_ms=elapsed
            )
        elapsed = (_t.monotonic() - t0) * 1000
        # JSON parse — fence / 잡음 제거.
        s = (raw or "").strip()
        if s.startswith("```"):
            nl = s.find("\n")
            if nl > 0:
                s = s[nl + 1 :]
        if s.endswith("```"):
            s = s[:-3].rstrip()
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            log.info(
                "binding_gate_json_parse_failed",
                agent=agent_name,
                raw=s[:200],
            )
            return GateDecision(
                in_scope=True, reason="parse_failed_default_pass", elapsed_ms=elapsed
            )
        in_scope = bool(data.get("in_scope", True))
        reason = str(data.get("reason") or "").strip() or "(no reason)"
        rejection = ""
        if not in_scope:
            rejection = self._build_rejection_message(agent_context, reason)
        log.info(
            "binding_gate_decision",
            agent=agent_name,
            in_scope=in_scope,
            reason=reason[:120],
            elapsed_ms=round(elapsed, 1),
        )
        return GateDecision(
            in_scope=in_scope,
            reason=reason,
            rejection_message=rejection,
            elapsed_ms=elapsed,
        )

    def _build_rejection_message(
        self, agent_context: Any, reason: str
    ) -> str:
        """OOS 거절 메시지 — 하드코딩 X. agent.name + role 만 echo.

        guidelines_md 안 별도 거절 문구가 있으면 LLM 이 답변 시 활용하도록 후속
        SOP RAG inject 가 가져옴 — 이 fast-track 은 *간단한 fallback* 만.
        """
        agent_name = getattr(agent_context, "name", "이 에이전트") or "이 에이전트"
        goal = getattr(agent_context, "goal", "") or ""
        if goal:
            return (
                f"죄송합니다. 저는 *{agent_name}* — {goal} 를 담당합니다. "
                f"문의주신 내용은 이 상담 범위 밖입니다. 도와드릴 수 있는 다른 "
                f"질문이 있으면 알려주세요."
            )
        return (
            f"죄송합니다. *{agent_name}* 의 응대 범위 밖 문의입니다. "
            f"이 상담의 도메인 안에서 도와드릴 수 있는 질문을 알려주세요."
        )


__all__ = ["BindingGate", "GateDecision"]
