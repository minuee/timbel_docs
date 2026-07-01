"""info_lookup 카테고리 결정론 plan 합성 — 2026-05-06 spec § 4.3 A.

plan_router 가 INFO_LOOKUP 으로 라우트 + FAST_INFO_LOOKUP_PLAN flag on 시
LLM (plan_generator) 호출 없이 카테고리 템플릿에서 plan 합성.

pre-demo: 어디서도 호출 안 됨. 단위 테스트만.

GPT-5.5 권고: 'always multi-source' 강제 제거. KMS-first / web 후순위 /
reasoning 1회. user_message 를 그대로 query 로 — 별도 query rewrite 불필요.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class IntentResult:
    intent: str
    domain: str
    confidence: float


@dataclass
class PlanStep:
    kind: str            # tool / reasoning / ask_user_clarify
    tool: str | None
    args: dict[str, Any]
    expr: str | None = None


def synthesize_info_lookup_plan(
    user_message: str,
    classifier: IntentResult,
    *,
    include_web: bool = True,
) -> list[PlanStep]:
    """KMS-first plan 결정론 합성. include_web=False 이면 KMS + reasoning 만.

    합성 규칙 (no LLM):
      step 1: kms_rag.search (query=user_message)
      step 2: web.search     (include_web=True 일 때만)
      step 3: reasoning      (KMS-first 합성 instruction)
    """
    plan: list[PlanStep] = []
    plan.append(PlanStep(
        kind="tool",
        tool="kms_rag.search",
        args={"query": user_message},
    ))
    if include_web:
        plan.append(PlanStep(
            kind="tool",
            tool="web.search",
            args={"query": user_message},
        ))
    plan.append(PlanStep(
        kind="reasoning",
        tool=None,
        args={},
        expr="KMS 결과를 우선 인용. 부족하면 web 보충. 출처는 본문에 [N] 마커로.",
    ))
    return plan
