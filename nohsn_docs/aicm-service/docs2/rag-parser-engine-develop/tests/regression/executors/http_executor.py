"""HTTP step executor — live API 호출.

memory rule: 하드코딩 금지. 모든 expect 키는 yaml 시나리오 측 정의를
일반 패턴으로 비교 (정수/부분문자/dict subset 등).
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from ..types import HttpStep, StepResult


def _dict_contains(haystack: Any, needle: dict[str, Any]) -> tuple[bool, str]:
    """needle 의 모든 key/value 가 haystack(dict) 에 존재하는지 확인."""
    if not isinstance(haystack, dict):
        return False, f"not a dict: {type(haystack).__name__}"
    for k, v in needle.items():
        if k not in haystack:
            return False, f"missing key {k!r}"
        if haystack[k] != v:
            return False, f"key {k!r} mismatch: {haystack[k]!r} != {v!r}"
    return True, ""


async def execute_http(
    step: HttpStep,
    base_url: str,
    account_tokens: dict[str, str],
    tenant_resolver: Any | None = None,
) -> StepResult:
    """HTTP step 1개 실행.

    Parameters
    ----------
    step : HttpStep
    base_url : str
        예: ``http://localhost:5101``.
    account_tokens : dict[str, str]
        ``demo-admin`` / ``demo-user`` 식의 식별자 → bearer token.
    tenant_resolver : callable, optional
        ``(account, tenant_alias) -> tenant_uuid`` — yaml 의 ``tenant: personal``
        같은 alias 를 실제 uuid 로 변환. 미주입이면 alias 를 그대로 헤더에 박음.
    """
    headers = dict(step.headers or {})

    if step.auth_account:
        token = account_tokens.get(step.auth_account)
        if not token:
            return StepResult(
                False, f"no token for account {step.auth_account!r}"
            )
        headers["Authorization"] = f"Bearer {token}"

    # tenant alias → uuid 변환 (제공 시).
    if step.tenant and "X-Tenant-ID" not in headers:
        tenant_id: str | None = step.tenant
        if tenant_resolver:
            try:
                tenant_id = await tenant_resolver(step.auth_account, step.tenant)
            except Exception:  # noqa: BLE001
                tenant_id = step.tenant
        if tenant_id:
            headers["X-Tenant-ID"] = tenant_id

    files = None
    data = None
    if step.file:
        files = {
            "file": (
                step.file.get("name", "test.txt"),
                step.file.get("content", "x"),
                step.file.get("content_type", "text/plain"),
            )
        }
        # files 사용 시 Content-Type 은 httpx 가 multipart 로 설정. 충돌 방지.
        headers.pop("Content-Type", None)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                step.method.upper(),
                base_url + step.path,
                headers=headers,
                json=step.json_body if not files else None,
                files=files,
                data=data,
            )
    except httpx.RequestError as e:
        return StepResult(False, f"http request error: {e}")

    expect = step.expect or {}

    if "status" in expect:
        if resp.status_code != expect["status"]:
            return StepResult(
                False,
                f"status {resp.status_code} != expected {expect['status']} "
                f"(body: {resp.text[:200]!r})",
            )

    if "body_contains" in expect:
        if expect["body_contains"] not in resp.text:
            return StepResult(
                False,
                f"body missing {expect['body_contains']!r} "
                f"(got: {resp.text[:200]!r})",
            )

    if "json_contains" in expect:
        try:
            body_json = resp.json()
        except (ValueError, json.JSONDecodeError):
            return StepResult(False, f"response is not JSON: {resp.text[:120]!r}")
        ok, why = _dict_contains(body_json, expect["json_contains"])
        if not ok:
            return StepResult(False, f"json_contains: {why}")

    return StepResult(True, "OK", raw_response={"status": resp.status_code})
