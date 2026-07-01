"""Retrieval gate — KMS RAG 호출 직전 skip 결정 단위 테스트 (PR-A ❼).

게이트 두 단:
  (a) base: skill.retrieval == "none" 이면 skip.
  (b) 안전망: retrieval == "kms" 이지만 intent_classifier 가 "검색 불필요" 판정 시 skip.

본 모듈은 LLM 호출이 없는 *순수 결정 함수* 만 검증. classifier 호출은 호출자가 미리
실행해 결과를 게이트에 주입한다 (테스트 결정성 + LLM 의존 격리).
"""

from __future__ import annotations

import pytest

from src.agent_framework.runtime.retrieval_gate import (
    RetrievalDecision,
    decide_retrieval,
)


def test_retrieval_none_short_circuits_skip():
    """skill.retrieval='none' — base 게이트가 즉시 skip. classifier 호출도 안 함."""
    decision = decide_retrieval(
        skill_retrieval="none",
        intent_search_needed=None,  # classifier 호출 안 됨
    )
    assert decision.proceed is False
    assert decision.reason_key == "skill_retrieval_none"


def test_retrieval_kms_with_intent_search_true_proceeds():
    """skill.retrieval='kms' + classifier search=True → 진행."""
    decision = decide_retrieval(
        skill_retrieval="kms",
        intent_search_needed=True,
    )
    assert decision.proceed is True
    assert decision.reason_key == "ok_kms_search_needed"


def test_retrieval_kms_with_intent_search_false_skips():
    """skill.retrieval='kms' 여도 classifier 가 일상/비검색 판정 → skip (안전망)."""
    decision = decide_retrieval(
        skill_retrieval="kms",
        intent_search_needed=False,
    )
    assert decision.proceed is False
    assert decision.reason_key == "intent_classifier_non_search"


def test_retrieval_tool_skips_kms_path():
    """skill.retrieval='tool' — KMS 검색 path 는 skip, tool 호출이 사실 출처."""
    decision = decide_retrieval(
        skill_retrieval="tool",
        intent_search_needed=None,
    )
    assert decision.proceed is False
    assert decision.reason_key == "skill_retrieval_tool"


def test_retrieval_default_kms_when_unknown_value_safe():
    """알 수 없는 값이 들어와도 conservative — 검색 진행 (회귀 안전)."""
    decision = decide_retrieval(
        skill_retrieval=None,
        intent_search_needed=True,
    )
    assert decision.proceed is True


def test_decision_has_emit_payload():
    """skip 결정은 SSE trace 용 payload 를 노출 (event=grounding_skipped)."""
    decision = decide_retrieval(
        skill_retrieval="none",
        intent_search_needed=None,
    )
    payload = decision.to_skip_event()
    assert payload["event"] == "grounding_skipped"
    assert "reason" in payload["data"]
    assert payload["data"]["reason"] == "skill_retrieval_none"
