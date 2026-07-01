"""D84 — strict_evidence_policy gate 단위 테스트.

knowledge_isolation=strict 인 agent 가 KMS 매칭 0건 일 때 LLM 일반지식
fallback 을 *코드* 로 차단하는지 검증. priority / broad 는 기존 fallback_hint
경로 그대로 유지 (회귀 0).
"""

import pytest

from src.agent_framework.runtime.strict_evidence_policy import (
    STRICT_NO_EVIDENCE_REFUSAL,
    StrictEvidenceVerdict,
    evaluate_evidence,
)


def _kms_tool_result(hits: list[dict]) -> dict:
    return {"tool": "kms_rag.search", "result": {"hits": hits}}


def _web_tool_result(hits: list[dict]) -> dict:
    return {"tool": "web_search.run", "result": {"hits": hits}}


def test_strict_no_kms_hit_returns_refuse():
    verdict = evaluate_evidence(
        isolation="strict",
        web_search_mode="off",
        tool_results=[_kms_tool_result([])],
    )
    assert verdict.action == "refuse"
    assert verdict.refusal_text == STRICT_NO_EVIDENCE_REFUSAL


def test_strict_low_score_kms_hit_returns_allow():
    """D85 (2026-05-13) — 사용자 절칙 'KMS + 루카스 분리'. score 무관, hit 있으면 allow.

    이전 D84 동작: score < 0.3 면 refuse. D85 변경: KMS 결과를 그대로 사용 →
    hit 가 1개라도 있으면 (score 무관) 루카스가 LLM compose 진행.
    """
    verdict = evaluate_evidence(
        isolation="strict",
        web_search_mode="off",
        tool_results=[_kms_tool_result([{"score": 0.12}])],
    )
    assert verdict.action == "allow"


def test_strict_with_meaningful_kms_hit_returns_allow():
    verdict = evaluate_evidence(
        isolation="strict",
        web_search_mode="off",
        tool_results=[_kms_tool_result([{"score": 0.8}])],
    )
    assert verdict.action == "allow"


def test_strict_with_web_only_results_still_refuses():
    # strict 의 UI 라벨이 "문서만" — web 결과만으로 일반지식 합성 금지.
    verdict = evaluate_evidence(
        isolation="strict",
        web_search_mode="blended",
        tool_results=[
            _kms_tool_result([]),
            _web_tool_result([{"score": 0.9}]),
        ],
    )
    assert verdict.action == "refuse"


def test_priority_no_hit_returns_fallback_hint():
    verdict = evaluate_evidence(
        isolation="priority",
        web_search_mode="off",
        tool_results=[_kms_tool_result([])],
    )
    assert verdict.action == "fallback_hint"


def test_broad_no_hit_returns_fallback_hint():
    verdict = evaluate_evidence(
        isolation="broad",
        web_search_mode="off",
        tool_results=[_kms_tool_result([])],
    )
    assert verdict.action == "fallback_hint"


def test_no_kms_tool_at_all_treated_as_no_evidence():
    # tool_results 자체가 비면 strict 는 거절.
    verdict = evaluate_evidence(
        isolation="strict",
        web_search_mode="off",
        tool_results=[],
    )
    assert verdict.action == "refuse"


def test_none_isolation_defaults_to_priority():
    # AgentContext 기본 폴백 — None / 빈 문자열은 priority 로 해석.
    verdict = evaluate_evidence(
        isolation=None,
        web_search_mode="off",
        tool_results=[_kms_tool_result([])],
    )
    assert verdict.action == "fallback_hint"


def test_isolation_case_insensitive():
    verdict = evaluate_evidence(
        isolation="STRICT",
        web_search_mode="off",
        tool_results=[_kms_tool_result([])],
    )
    assert verdict.action == "refuse"


def test_score_threshold_exact_boundary_passes():
    # score == 0.3 → 0.3 이상 = allow.
    verdict = evaluate_evidence(
        isolation="strict",
        web_search_mode="off",
        tool_results=[_kms_tool_result([{"score": 0.3}])],
    )
    assert verdict.action == "allow"


def test_malformed_tool_result_safe():
    """D85 — 비-dict tool 결과는 skip. KMS hit 가 있으면 score 무관 allow.

    사용자 절칙: KMS 가 만든 hit 는 그대로 LLM 에. score=None / 형식 변형도 KMS
    가 신뢰. 루카스가 hit 의 score 까지 검증 = 절칙 위배.
    """
    verdict = evaluate_evidence(
        isolation="strict",
        web_search_mode="off",
        tool_results=[
            "not_a_dict",  # type: ignore[list-item]
            {"tool": "kms_rag.search", "result": {"hits": [{"score": None}]}},
        ],
    )
    assert verdict.action == "allow"


def test_strict_empty_hits_refuses():
    """KMS hit 0 = KMS 도 답할 게 없는 케이스. strict 거절."""
    verdict = evaluate_evidence(
        isolation="strict",
        web_search_mode="off",
        tool_results=[
            {"tool": "kms_rag.search", "result": {"hits": []}},
        ],
    )
    assert verdict.action == "refuse"


def test_verdict_is_frozen_dataclass():
    verdict = StrictEvidenceVerdict(action="allow")
    with pytest.raises(Exception):
        verdict.action = "refuse"  # type: ignore[misc]
