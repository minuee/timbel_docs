"""Smoke tests for scripts/loadtest/generate_synthetic_data.py.

scale=0.01 로 단일 테넌트 (T-medical) 만 실제 삽입한 뒤 카운트 검증.
멱등성: 같은 옵션을 두 번 실행해도 row 가 추가되지 않음.

NOTE: 풀스위트 시간을 짧게 유지하기 위해 스케일을 매우 작게 잡는다 —
T-medical 만, doc 100 + pending 20 = 120, skill 1, invocation 500.
"""
from __future__ import annotations

import subprocess

import pytest
from sqlalchemy import text


SCRIPT = "/app/scripts/loadtest/generate_synthetic_data.py"


def _run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python", SCRIPT, *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _count_seed_docs(db) -> int:
    return db.execute(
        text(
            "SELECT COUNT(*) FROM documents "
            "WHERE processing_meta->>'seed_source' = 'loadtest_synthetic' "
            "  AND processing_meta->>'tenant_profile' = 'T-medical'"
        )
    ).scalar()


def _count_seed_skills(db) -> int:
    return db.execute(
        text(
            "SELECT COUNT(*) FROM skill_drafts "
            "WHERE processing_meta->>'seed_source' = 'loadtest_synthetic' "
            "  AND processing_meta->>'domain' = 'medical'"
        )
    ).scalar()


def _count_seed_invocations(db) -> int:
    # tool_invocations 는 별도 seed_source 칼럼이 없어 id prefix 또는
    # tenant 로 식별 — 여기선 tenant uuid 비교가 어려워 input_args.profile 로 검증.
    return db.execute(
        text(
            "SELECT COUNT(*) FROM tool_invocations "
            "WHERE input_args->>'profile' = 'T-medical'"
        )
    ).scalar()


def test_scale_001_inserts_expected_counts(db):
    """T-medical scale=0.01 — 100 main + 20 pending docs / 1 skill / 500 invocations."""
    _run_script("--tenant", "T-medical", "--scale", "0.01", "--execute")

    n_docs = _count_seed_docs(db)
    n_skills = _count_seed_skills(db)
    n_invs = _count_seed_invocations(db)

    # 기대치: 120 docs, 1 skill, 500 invocations.  ON CONFLICT DO NOTHING 라 정확히 일치.
    assert n_docs == 120, f"docs count {n_docs} != 120"
    assert n_skills == 1, f"skills count {n_skills} != 1"
    assert n_invs == 500, f"invocations count {n_invs} != 500"


def test_scale_001_idempotent(db):
    """두 번째 실행해도 행 수가 증가하지 않아야 한다."""
    _run_script("--tenant", "T-medical", "--scale", "0.01", "--execute")
    n1_docs = _count_seed_docs(db)
    n1_skills = _count_seed_skills(db)
    n1_invs = _count_seed_invocations(db)

    _run_script("--tenant", "T-medical", "--scale", "0.01", "--execute")
    n2_docs = _count_seed_docs(db)
    n2_skills = _count_seed_skills(db)
    n2_invs = _count_seed_invocations(db)

    assert n1_docs == n2_docs, f"docs not idempotent: {n1_docs} -> {n2_docs}"
    assert n1_skills == n2_skills, f"skills not idempotent: {n1_skills} -> {n2_skills}"
    assert n1_invs == n2_invs, f"invocations not idempotent: {n1_invs} -> {n2_invs}"
