"""Pytest entry — runs all yaml regression scenarios against live API.

KMS-Plus PR P9. ``-m regression`` 마커로 선택/스킵.

기본 base_url 은 ``KMS_REG_BASE_URL`` 또는 ``http://localhost:5101``.
시드 계정 (demo-admin / demo-user) 이 API 에 등록되어 있어야 SSE/auth
의존 시나리오가 통과한다.
"""
from __future__ import annotations

import os

import pytest

from .loaders import load_yaml_scenarios
from .runner import acquire_account_tokens, run_scenario


_BASE_URL = os.environ.get("KMS_REG_BASE_URL", "http://localhost:5101")


def _scenario_ids() -> list[str]:
    return [s.name for s in load_yaml_scenarios()]


@pytest.mark.regression
@pytest.mark.parametrize(
    "scenario",
    load_yaml_scenarios(),
    ids=lambda s: s.name,
)
async def test_scenario(scenario):
    tokens = await acquire_account_tokens(_BASE_URL)
    result = await run_scenario(scenario, _BASE_URL, tokens)
    if not result.passed:
        details = "\n".join(
            f"  step {i}: {sr.detail}"
            for i, sr in enumerate(result.step_results, start=1)
            if not sr.passed
        )
        pytest.fail(f"{scenario.name} failed:\n{details}")
