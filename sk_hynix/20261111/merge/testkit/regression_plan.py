"""Aggregate lane-4 scaffolding into one machine-readable regression plan."""

from __future__ import annotations

from dataclasses import asdict

from testkit.ingestion_matrix import build_ingestion_matrix
from testkit.load_profile import build_default_load_profile
from testkit.verification_matrix import build_verification_matrix


def build_regression_plan() -> dict:
    load_profile = build_default_load_profile()
    return {
        "ingestion_matrix": [asdict(item) for item in build_ingestion_matrix()],
        "verification_matrix": [asdict(item) for item in build_verification_matrix()],
        "load_profile": asdict(load_profile),
        "summary": {
            "ingestion_case_count": len(build_ingestion_matrix()),
            "verification_scenario_count": len(build_verification_matrix()),
            "retry_case_count": len(load_profile.retry_cases),
        },
    }

