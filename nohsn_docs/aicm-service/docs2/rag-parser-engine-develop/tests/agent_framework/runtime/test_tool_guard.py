"""D72 (2026-05-12) — tool_guard.py 단위 테스트.

call-time allowed_tools 강제 가드 의미 검증.

# 의미 표
| agent_context | allowed_tools | 도구 | 결과         |
| ------------- | ------------- | ---- | ------------ |
| None          | -             | any  | allowed=True |
| 객체          | None          | any  | allowed=True |
| 객체          | []            | any  | allowed=False (empty_allowed_tools) |
| 객체          | ["X"]         | X    | allowed=True |
| 객체          | ["X"]         | Y    | allowed=False (tool_not_in_allowed_tools) |

# 적용 site
1. ``tool_guard.enforce_allowed_tools()`` — 직접 검증.
2. ``ToolRegistry.call(..., agent_context=...)`` — choke point 통합.
3. ``tool_guard.visible_tools()`` — planner exposure 헬퍼.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.agent_framework.runtime.tool_guard import (
    GuardDecision,
    blocked_result,
    enforce_allowed_tools,
    visible_tools,
)
from src.agent_framework.tools.registry import ToolRegistry


@dataclass
class _FakeCtx:
    """agent_context 덕 타입 — D73 SenderContext 도 동일 형태."""
    is_admin: bool = False
    allowed_tools: list[str] | None = None
    agent_id: str = "fake-agent"
    name: str = "fake"


# ─── enforce_allowed_tools ────────────────────────────────────────────────

def test_none_context_allows_all():
    d = enforce_allowed_tools(None, "stock.add_watch")
    assert d.allowed is True
    assert d.code is None


def test_none_allowed_tools_allows_all():
    """allowed_tools is None = open (legacy / 정의 안 됨)."""
    ctx = _FakeCtx(allowed_tools=None)
    d = enforce_allowed_tools(ctx, "stock.add_watch")
    assert d.allowed is True


def test_empty_allowed_tools_blocks_all():
    """allowed_tools == [] = 명시적 deny-all."""
    ctx = _FakeCtx(allowed_tools=[])
    d = enforce_allowed_tools(ctx, "stock.add_watch")
    assert d.allowed is False
    assert d.code == "empty_allowed_tools"


def test_tool_not_in_allowed_blocks():
    ctx = _FakeCtx(allowed_tools=["kms_rag.search", "kms_sop.search"])
    d = enforce_allowed_tools(ctx, "stock.add_watch")
    assert d.allowed is False
    assert d.code == "tool_not_in_allowed_tools"
    assert "stock.add_watch" in (d.reason or "")


def test_tool_in_allowed_passes():
    ctx = _FakeCtx(allowed_tools=["stock.add_watch", "stock.list_watch"])
    d = enforce_allowed_tools(ctx, "stock.add_watch")
    assert d.allowed is True


def test_admin_empty_also_blocks():
    """admin/role asymmetry footgun 차단 — admin 도 빈 list 면 deny.
    (admin 의 'allowed_tools 미정의' 자동 fallback 은 호출자 측 별도 처리)."""
    ctx = _FakeCtx(is_admin=True, allowed_tools=[])
    d = enforce_allowed_tools(ctx, "stock.add_watch")
    assert d.allowed is False
    assert d.code == "empty_allowed_tools"


def test_admin_with_allowed_passes_in_list():
    ctx = _FakeCtx(is_admin=True, allowed_tools=["mail.send"])
    d = enforce_allowed_tools(ctx, "mail.send")
    assert d.allowed is True


def test_blocked_result_shape():
    decision = GuardDecision(allowed=False, code="empty_allowed_tools", reason="x")
    r = blocked_result("stock.add_watch", decision)
    assert r["success"] is False
    assert r["error"] == "tool_blocked_by_allowed_tools"
    assert r["blocked_reason"] == "empty_allowed_tools"
    assert r["tool"] == "stock.add_watch"
    assert "user_message" in r


# ─── visible_tools ──────────────────────────────────────────────────────────

def test_visible_tools_no_ctx_returns_candidate():
    assert visible_tools(None, ["a", "b"]) == ["a", "b"]


def test_visible_tools_none_allowed_returns_candidate():
    ctx = _FakeCtx(allowed_tools=None)
    assert visible_tools(ctx, ["a", "b"]) == ["a", "b"]


def test_visible_tools_empty_allowed_returns_empty():
    ctx = _FakeCtx(allowed_tools=[])
    assert visible_tools(ctx, ["a", "b", "c"]) == []


def test_visible_tools_intersection():
    ctx = _FakeCtx(allowed_tools=["a", "c"])
    assert visible_tools(ctx, ["a", "b", "c", "d"]) == ["a", "c"]


# ─── ToolRegistry choke point ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registry_call_no_context_executes():
    """agent_context=None → 옛 동작 (byte-equal). 회귀 0 보장."""
    async def _ok(args):
        return {"called": True, "args": args}
    reg = ToolRegistry(tools={"x.test": _ok})
    out = await reg.call("x.test", {"k": 1})
    assert out == {"called": True, "args": {"k": 1}}


@pytest.mark.asyncio
async def test_registry_call_blocks_role_agent_empty_allowed():
    """D71 #261 재현: stock_info (allowed_tools=[]) → 차단."""
    async def _stock(args):
        return {"executed": True}  # 만약 실행되면 fail.
    reg = ToolRegistry(tools={"stock.add_watch": _stock})
    ctx = _FakeCtx(is_admin=False, allowed_tools=[])
    out = await reg.call("stock.add_watch", {}, agent_context=ctx)
    assert out["success"] is False
    assert out["error"] == "tool_blocked_by_allowed_tools"
    assert out["blocked_reason"] == "empty_allowed_tools"
    # 진짜 함수는 호출되지 않음.
    assert "executed" not in out


@pytest.mark.asyncio
async def test_registry_call_blocks_tool_not_in_allowed():
    async def _stock(args):
        return {"executed": True}
    reg = ToolRegistry(tools={"stock.add_watch": _stock})
    ctx = _FakeCtx(allowed_tools=["kms_rag.search"])
    out = await reg.call("stock.add_watch", {}, agent_context=ctx)
    assert out["success"] is False
    assert out["blocked_reason"] == "tool_not_in_allowed_tools"


@pytest.mark.asyncio
async def test_registry_call_allows_in_allowed():
    async def _kms(args):
        return {"results": []}
    reg = ToolRegistry(tools={"kms_rag.search": _kms})
    ctx = _FakeCtx(allowed_tools=["kms_rag.search"])
    out = await reg.call("kms_rag.search", {"q": "x"}, agent_context=ctx)
    assert out == {"results": []}


@pytest.mark.asyncio
async def test_registry_call_missing_context_warns_when_env_set(monkeypatch):
    """D72 GPT-5 post verdict — agent_context 누락 감지 (ENV opt-in)."""
    import os
    import warnings

    async def _ok(args):
        return {"ok": True}

    reg = ToolRegistry(tools={"x.test": _ok})
    monkeypatch.setenv("TOOL_GUARD_WARN_ON_MISSING_CONTEXT", "1")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = await reg.call("x.test", {})
    assert out == {"ok": True}
    # ENV on 시 RuntimeWarning 발생.
    assert any(issubclass(x.category, RuntimeWarning) for x in w)


@pytest.mark.asyncio
async def test_registry_call_missing_context_silent_default():
    """기본은 silent — 회귀 0 (legacy/test/default chat path 정상)."""
    import warnings

    async def _ok(args):
        return {"ok": True}

    reg = ToolRegistry(tools={"x.test": _ok})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = await reg.call("x.test", {})
    assert out == {"ok": True}
    # ENV 미설정 → 경고 X.
    rt = [x for x in w if issubclass(x.category, RuntimeWarning)]
    assert len(rt) == 0


@pytest.mark.asyncio
async def test_registry_unknown_tool_raises_with_context():
    """admin/role context 가 있어도 미등록 tool 은 ToolNotFound 예외."""
    from src.agent_framework.tools.registry import ToolNotFound

    reg = ToolRegistry(tools={})
    ctx = _FakeCtx(allowed_tools=["unknown.tool"])
    with pytest.raises(ToolNotFound):
        await reg.call("unknown.tool", {}, agent_context=ctx)
