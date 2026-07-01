"""generic webhook caller — custom_tools 동적 호출.

agent 가 custom tool name (e.g. "custom.weather_external") 호출 시
이 caller 가 DB 에서 tool 조회 → endpoint_url 호출 → 결과 반환.

ToolRegistry 통합:
    engine 초기화 시 DB 에 있는 custom tool 을 ToolRegistry.register() 로
    동적 등록하거나, 혹은 registry 에 fallback handler 를 하나 등록해두고
    "custom." prefix 이름을 이 caller 로 라우팅하는 방식 둘 다 가능.

    현재(Level 1) 는 별도 관리 페이지에서 등록 + /test endpoint 로 직접 검증.
    Level 2 에서 ToolPicker 통합 시 register_custom_tools_for_tenant() 를
    engine.build() 단계에서 호출하면 allowed_tools 검증도 자동으로 됨.
"""
from __future__ import annotations
import logging
from typing import Any
from uuid import UUID
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.crypto.fernet import decrypt_dict
from src.core.models.custom_tool import CustomTool

log = logging.getLogger(__name__)


class CustomToolNotFound(RuntimeError):
    pass


class CustomToolCallError(RuntimeError):
    pass


async def call_custom_tool(
    db: AsyncSession,
    tenant_id: UUID,
    tool_name: str,
    input_data: dict[str, Any],
    *,
    timeout_s: float = 15.0,
) -> dict[str, Any]:
    """tenant 의 custom tool 조회 → webhook 호출 → 응답 반환.

    Args:
        db: 비동기 DB 세션.
        tenant_id: 현재 tenant (cross-tenant 접근 차단).
        tool_name: custom_tools.name (예: "custom.weather_api").
        input_data: tool 에 전달할 args.
        timeout_s: httpx 타임아웃 (초). 기본 15초.

    Returns:
        ``{"ok": True, "tool": str, "status_code": int, "data": dict}``

    Raises:
        CustomToolNotFound: tool 명 미존재 또는 비활성.
        CustomToolCallError: webhook 4xx/5xx, timeout, JSON parse 실패.
    """
    stmt = select(CustomTool).where(
        CustomTool.tenant_id == tenant_id,
        CustomTool.name == tool_name,
        CustomTool.is_active == True,
    )
    tool = (await db.execute(stmt)).scalar_one_or_none()
    if not tool:
        raise CustomToolNotFound(
            f"custom tool '{tool_name}' not found in tenant {tenant_id}"
        )

    # config 복호 → auth headers 추출
    try:
        config = decrypt_dict(tool.config_encrypted) if tool.config_encrypted else {}
    except Exception as e:
        log.exception("custom_tool_config_decrypt_failed", extra={"tool": tool_name})
        raise CustomToolCallError(f"config decrypt failed: {e!r}") from e

    auth_headers: dict[str, str] = config.get("auth_headers") or {}
    headers = {"Content-Type": "application/json", **auth_headers}

    log.info(
        "custom_tool_call",
        extra={
            "tool": tool_name,
            "method": tool.method,
            "url": tool.endpoint_url,
        },
    )

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        try:
            if tool.method == "GET":
                resp = await client.get(
                    tool.endpoint_url,
                    params={k: str(v) for k, v in input_data.items()},
                    headers=headers,
                )
            else:
                resp = await client.request(
                    tool.method,
                    tool.endpoint_url,
                    json=input_data,
                    headers=headers,
                )
        except httpx.TimeoutException as e:
            raise CustomToolCallError(
                f"webhook timeout after {timeout_s}s: {tool_name}"
            ) from e
        except httpx.RequestError as e:
            raise CustomToolCallError(f"request error: {e!r}") from e

    if resp.status_code >= 400:
        raise CustomToolCallError(
            f"webhook {resp.status_code} for tool '{tool_name}': {resp.text[:200]}"
        )

    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text}

    return {
        "ok": True,
        "tool": tool_name,
        "status_code": resp.status_code,
        "data": body,
    }


async def register_custom_tools_for_tenant(
    db: AsyncSession,
    tenant_id: UUID,
    registry: Any,
) -> int:
    """tenant 의 활성 custom tool 을 ToolRegistry 에 동적 등록.

    Level 2 (ToolPicker 통합) 를 위한 진입점.
    engine.build() 시 호출하면 allowed_tools 검증이 builtin/custom 통합으로 동작.

    Returns:
        등록된 tool 수.
    """
    stmt = select(CustomTool).where(
        CustomTool.tenant_id == tenant_id,
        CustomTool.is_active == True,
    )
    tools = list((await db.execute(stmt)).scalars().all())

    registered = 0
    for tool in tools:
        # 클로저 캡처 — tool 변수 바인딩 필수.
        _tool = tool

        async def _fn(args: dict[str, Any], *, _t: CustomTool = _tool) -> dict[str, Any]:
            return await call_custom_tool(db, tenant_id, _t.name, args)

        try:
            registry.register(
                _tool.name,
                _fn,
                description=_tool.description,
                replace=True,
            )
            registered += 1
        except Exception as e:
            log.warning(
                "custom_tool_register_failed",
                extra={"tool": _tool.name, "error": str(e)},
            )

    log.info(
        "custom_tools_registered",
        extra={"tenant_id": str(tenant_id), "count": registered},
    )
    return registered
