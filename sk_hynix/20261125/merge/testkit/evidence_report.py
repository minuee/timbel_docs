"""Structured evidence template for task-5 verification handoff."""

from __future__ import annotations

from testkit.regression_plan import build_regression_plan


def build_evidence_template() -> dict:
    plan = build_regression_plan()
    return {
        "task": "task-5 synthetic corpus + regression test lane",
        "status": "in_progress",
        "acceptance_checks": [
            {
                "acceptance_criterion": "AC1",
                "evidence_sources": ["verification_matrix", "load_profile"],
                "current_state": "scaffolded",
            },
            {
                "acceptance_criterion": "AC2",
                "evidence_sources": ["ingestion_matrix", "synthetic_corpus"],
                "current_state": "scaffolded",
            },
            {
                "acceptance_criterion": "AC6",
                "evidence_sources": ["benchmark", "verification_matrix"],
                "current_state": "scaffolded",
            },
            {
                "acceptance_criterion": "AC9",
                "evidence_sources": ["ingestion_matrix", "synthetic_corpus"],
                "current_state": "scaffolded",
            },
        ],
        "summary": plan["summary"],
    }

