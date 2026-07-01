"""D84 — runtime policy matrix.

GPT-5.5 권고: isolation × KMS hit × web hit 조합 매트릭스 회귀 가드.
strict / priority / broad 의 verdict 가 어떤 평가에도 일관성을 유지하는지 검증.
"""

import pytest

from src.agent_framework.runtime.strict_evidence_policy import evaluate_evidence


def _kms(hits: list[dict]) -> dict:
    return {"tool": "kms_rag.search", "result": {"hits": hits}}


def _web(hits: list[dict]) -> dict:
    return {"tool": "web_search.run", "result": {"hits": hits}}


# D85 (2026-05-13) — 사용자 절칙 'KMS + 루카스 분리': score threshold 제거.
# KMS 가 hit 를 줬으면 (score 무관) allow. hit 0 일 때만 strict refuse /
# priority,broad fallback_hint.
# (isolation, kms_hits, web_hits, expected_action)
CASES = [
    ("strict",   [],                 [],                 "refuse"),
    ("strict",   [],                 [{"score": 0.9}],    "refuse"),
    ("strict",   [{"score": 0.8}],   [],                 "allow"),
    ("strict",   [{"score": 0.8}],   [{"score": 0.9}],   "allow"),
    ("strict",   [{"score": 0.12}],  [],                 "allow"),
    ("priority", [],                 [],                 "fallback_hint"),
    ("priority", [],                 [{"score": 0.9}],    "fallback_hint"),
    ("priority", [{"score": 0.8}],   [],                 "allow"),
    ("priority", [{"score": 0.12}],  [],                 "allow"),
    ("broad",    [],                 [],                 "fallback_hint"),
    ("broad",    [{"score": 0.8}],   [],                 "allow"),
    ("broad",    [{"score": 0.12}],  [],                 "allow"),
]


@pytest.mark.parametrize("iso,kms_hits,web_hits,expected", CASES)
def test_policy_matrix(iso, kms_hits, web_hits, expected):
    tool_results = [_kms(kms_hits)]
    if web_hits:
        tool_results.append(_web(web_hits))
    verdict = evaluate_evidence(
        isolation=iso, web_search_mode="off", tool_results=tool_results,
    )
    assert verdict.action == expected, (
        f"isolation={iso}, kms_hits={kms_hits}, web_hits={web_hits} → "
        f"expected={expected}, got={verdict.action}"
    )
