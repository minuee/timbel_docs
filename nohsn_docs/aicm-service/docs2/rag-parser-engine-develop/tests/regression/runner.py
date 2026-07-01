"""Regression suite runner — PR P9.

CLI::

    python -m tests.regression --suite all
    python -m tests.regression --base-url http://localhost:5101

memory rule: 패턴 우선. runner 자체는 패턴 매칭의 토대만 제공하고,
시나리오 yaml 이 패턴(역할/제약/엣지케이스)을 표현.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from typing import Any

import httpx

from .executors.chat_executor import execute_chat
from .executors.http_executor import execute_http
from .loaders import load_yaml_scenarios
from .types import ChatStep, HttpStep, Scenario, ScenarioResult, StepResult


DEFAULT_BASE_URL = os.environ.get("KMS_REG_BASE_URL", "http://localhost:5101")

# yaml 의 ``auth_account`` / ``account`` alias → 실제 로그인 email.
# 어시스턴트가 임의로 사례 enum 을 늘리지 않도록 — 실제 시드 계정 ID 만.
SEED_ACCOUNTS: dict[str, dict[str, str]] = {
    "demo-admin": {
        "email": os.environ.get("KMS_DEMO_ADMIN_EMAIL", "demo-admin@kms-plus.io"),
        "password": os.environ.get("KMS_DEMO_ADMIN_PW", "demo-admin"),
    },
    "demo-user": {
        "email": os.environ.get("KMS_DEMO_USER_EMAIL", "demo-user@kms-plus.io"),
        "password": os.environ.get("KMS_DEMO_USER_PW", "demo-user"),
    },
}


async def acquire_account_tokens(base_url: str) -> dict[str, str]:
    """seed account 로그인 → {alias: bearer_token}.

    실패하면 빈 dict — 해당 시나리오는 자동 스킵 (token 없음 사유).
    """
    out: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for alias, creds in SEED_ACCOUNTS.items():
            try:
                resp = await client.post(
                    base_url + "/api/v1/auth/v2/login",
                    json={"email": creds["email"], "password": creds["password"]},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    tok = data.get("access_token")
                    if tok:
                        out[alias] = tok
            except httpx.RequestError:
                continue
    return out


async def _resolve_tenant(account_alias: str | None, alias: str) -> str | None:
    """``personal`` / ``business`` alias 는 그대로 반환 (서버가 alias 를 처리)."""
    return alias


async def run_scenario(
    s: Scenario,
    base_url: str,
    tokens: dict[str, str],
) -> ScenarioResult:
    t0 = time.perf_counter()
    results: list[StepResult] = []
    for step in s.steps:
        if isinstance(step, HttpStep):
            r = await execute_http(step, base_url, tokens, _resolve_tenant)
        elif isinstance(step, ChatStep):
            r = await execute_chat(step, base_url, tokens, _resolve_tenant)
        else:  # pragma: no cover — defensive
            r = StepResult(False, f"unknown step {type(step).__name__}")
        results.append(r)
        if not r.passed:
            break  # halt on first fail (다음 step 은 의미 없음)
    dur = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        name=s.name,
        passed=all(r.passed for r in results) if results else False,
        duration_ms=dur,
        step_results=results,
    )


def _print_result(r: ScenarioResult) -> None:
    tag = "PASS" if r.passed else "FAIL"
    print(f"[{tag}] {r.name} ({r.duration_ms}ms, {len(r.step_results)} steps)")
    for i, sr in enumerate(r.step_results, start=1):
        if not sr.passed:
            print(f"   - step {i}: {sr.detail}")


async def _amain(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tests.regression")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--suite", default="all")
    p.add_argument(
        "--name",
        default=None,
        help="Scenario name 부분 일치 — 단일 시나리오만 실행할 때.",
    )
    args = p.parse_args(argv)

    scenarios = load_yaml_scenarios()
    if args.name:
        scenarios = [s for s in scenarios if args.name in s.name]
    if not scenarios:
        print("no scenarios matched")
        return 0

    tokens = await acquire_account_tokens(args.base_url)
    if not tokens:
        print(
            "WARN: seed account login failed — chat / auth-required steps will fail. "
            "set KMS_DEMO_ADMIN_EMAIL/PW or seed accounts.",
            file=sys.stderr,
        )

    results: list[ScenarioResult] = []
    for s in scenarios:
        r = await run_scenario(s, args.base_url, tokens)
        _print_result(r)
        results.append(r)

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    print(f"\n{passed} passed / {failed} failed / {len(results)} total")
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
