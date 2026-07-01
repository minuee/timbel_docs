"""role_faq 결정론 plan synthesizer — 2026-05-07 사용자 통찰 (role agent 중복 처리).

5 role agent (baemin / homeshop / kbsoldier / musinsa / samchully) 는
*FAQ + 매뉴얼 인용 + SOP 안내* 만 담당하는 좁은 도메인. allowed_tools 가
``{kms_rag.search, kms_sop.search}`` 의 부분집합이면 plan 결과는 항상 동일:
1) kms_rag.search → 2) kms_sop.search → 3) reasoning.

그런데 admin (Locus) 와 동일 pipeline 을 거쳐 매 turn LLM 3 회 호출
(intent_classifier + utterance_classifier + plan_orchestrator) 로 평균 7-10 s
의 *순수 비용* 발생. 이 모듈은 LLM 호출 0 회로 plan 합성하는 결정론 함수.

설계 원칙:
- ``info_lookup.py`` 와 동일 패턴 (PlanStep dataclass, no LLM).
- ``include_sop=False`` 옵션 — agent 가 SOP 도구 미보유 (kms_rag 만) 시 graceful.
- 결정론 — *동일 입력 → 동일 출력*. plan_router 의 카테고리 라우팅도 우회.
- query 는 user_message 그대로. plan_orchestrator 의 query rewrite 는 별도 layer.

호출자 (engine.turn) 는:
1) ``is_role_fast_trackable(agent_context)`` 로 진입 조건 검사.
2) FEATURE_ROLE_FAST_TRACK flag on 확인.
3) ``synthesize_role_faq_plan(...)`` 으로 plan 합성 + 기존 plan executor 재사용.

기존 plan executor (engine.py:2127+) 가 이미 ``PLAN_PARALLEL_STEPS`` flag 로
연속 tool step 을 asyncio.gather 로 병렬 실행 — 즉 kms_rag + kms_sop 자동 병렬.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PlanStep:
    """info_lookup.py 와 동일 schema — engine 의 어댑터 재사용."""

    kind: str            # tool / reasoning
    tool: str | None
    args: dict[str, Any]
    expr: str | None = None


# role agent 의 *허용* 도구 superset. allowed_tools 가 이 셋의 부분집합이고
# 비어있지 않으면 fast-track trackable. mail.send / schedule.create 등이 추가
# 되면 *복합 role agent* 라 기존 LLM plan path 가 안전 (확장 호환).
ALLOWED_FAST_TRACK_TOOLS: frozenset[str] = frozenset({
    "kms_rag.search",
    "kms_sop.search",
})


def is_role_fast_trackable(agent_context: Any) -> bool:
    """role agent 가 결정론 fast-track 적용 대상인지 판단.

    조건:
    1) agent_context 가 None 이 아님.
    2) ``is_admin`` 가 False (admin 은 전방위 도구, fast-track 부적합).
    3) ``kind == "role"`` (default 도 role, agent_context.py 보장).
    4) ``allowed_tools`` 가 비어있지 않고 ``ALLOWED_FAST_TRACK_TOOLS`` 의
       *부분집합*. 외부 도구 (mail/schedule 등) 가 하나라도 있으면 False.

    Args:
        agent_context: ``AgentContext`` 또는 임의 attribute holder.

    Returns:
        bool — fast-track 적용 가능 여부.
    """
    if agent_context is None:
        return False
    if getattr(agent_context, "is_admin", False):
        return False
    kind = getattr(agent_context, "kind", "role")
    if kind != "role":
        return False
    allowed = getattr(agent_context, "allowed_tools", None) or []
    if not allowed:
        return False
    allowed_set = set(allowed)
    if not allowed_set.issubset(ALLOWED_FAST_TRACK_TOOLS):
        return False
    return True


def synthesize_role_faq_plan(
    user_message: str,
    agent_context: Any,
    *,
    include_sop: bool | None = None,
) -> list[PlanStep]:
    """role agent FAQ/매뉴얼/SOP 조회용 결정론 plan 합성.

    합성 규칙 (no LLM):
      step 1: kms_rag.search (query=user_message)
      step 2: kms_sop.search (query=user_message)  — include_sop=True 일 때만
      step 3: reasoning      (KMS 본문 + SOP 절차 합성 instruction)

    Args:
        user_message: 사용자 발화 그대로. query rewrite 는 별도 layer.
        agent_context: ``AgentContext`` — allowed_tools 보고 SOP 포함 여부 결정.
        include_sop: 명시 지정 시 우선. None 이면 ``kms_sop.search`` 가
            allowed_tools 안에 있을 때만 step 2 포함.

    Returns:
        list[PlanStep] — 2-3 step.
    """
    if include_sop is None:
        allowed = set(getattr(agent_context, "allowed_tools", []) or [])
        include_sop = "kms_sop.search" in allowed

    plan: list[PlanStep] = []
    plan.append(PlanStep(
        kind="tool",
        tool="kms_rag.search",
        args={"query": user_message},
    ))
    if include_sop:
        plan.append(PlanStep(
            kind="tool",
            tool="kms_sop.search",
            args={"query": user_message},
        ))
        reasoning_expr = (
            "KMS 자료를 1차 인용하고 SOP 자료가 있으면 절차/규정 답변에 우선 "
            "반영. 본문에 [N] 마커로 출처 표기. 자료가 충분하지 않으면 일반 "
            "지식 선에서 안내 + disclaimer 한 줄 (사람 상담사·공식 채널 권고)."
        )
    else:
        reasoning_expr = (
            "KMS 자료를 1차 인용. 본문에 [N] 마커로 출처 표기. 자료가 부족하면 "
            "일반 지식 선에서 안내 + disclaimer 한 줄."
        )
    plan.append(PlanStep(
        kind="reasoning",
        tool=None,
        args={},
        expr=reasoning_expr,
    ))
    return plan


__all__ = [
    "PlanStep",
    "ALLOWED_FAST_TRACK_TOOLS",
    "is_role_fast_trackable",
    "synthesize_role_faq_plan",
]
