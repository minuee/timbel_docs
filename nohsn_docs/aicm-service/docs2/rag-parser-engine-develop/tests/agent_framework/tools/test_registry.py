import pytest
from src.agent_framework.tools.registry import ToolRegistry, ToolNotFound


@pytest.mark.asyncio
async def test_registry_lookup_missing():
    reg = ToolRegistry()
    with pytest.raises(ToolNotFound):
        await reg.call("does.not.exist", {})


@pytest.mark.asyncio
async def test_registry_lookup_ok():
    async def my_tool(args):
        return {"ok": True, "echo": args}

    reg = ToolRegistry({"echo": my_tool})
    got = await reg.call("echo", {"x": 1})
    assert got == {"ok": True, "echo": {"x": 1}}


@pytest.mark.asyncio
async def test_registry_rejects_duplicate():
    async def t1(args): return {}
    async def t2(args): return {}
    reg = ToolRegistry({"echo": t1})
    with pytest.raises(ValueError, match="already registered"):
        reg.register("echo", t2)


@pytest.mark.asyncio
async def test_registry_replace_override():
    async def t1(args): return {"v": 1}
    async def t2(args): return {"v": 2}
    reg = ToolRegistry({"echo": t1})
    reg.register("echo", t2, replace=True)
    got = await reg.call("echo", {})
    assert got == {"v": 2}


# Phase 2 (#153) — default_scope manifest 메타.
# spec: docs/superpowers/specs/2026-05-07-tool-scope-architecture.md §3.

def test_registry_default_scope_returns_agent_when_unmapped():
    """매핑 없는 도구는 보수적 fallback 'agent' (over-isolate, fail-closed)."""
    async def t(args): return {}
    reg = ToolRegistry({"foo": t})
    assert reg.get_default_scope("foo") == "agent"
    # 미등록 도구도 동일 fallback (호출은 ToolNotFound 따로 검증).
    assert reg.get_default_scope("does.not.exist") == "agent"


def test_registry_scopes_init_param():
    async def t1(args): return {}
    async def t2(args): return {}
    async def t3(args): return {}
    reg = ToolRegistry(
        {"mail.send": t1, "schedule.create": t2, "weather.lookup": t3},
        scopes={
            "mail.send": "user",
            "schedule.create": "agent",
            "weather.lookup": "tenant",
        },
    )
    assert reg.get_default_scope("mail.send") == "user"
    assert reg.get_default_scope("schedule.create") == "agent"
    assert reg.get_default_scope("weather.lookup") == "tenant"


def test_registry_set_default_scope():
    async def t(args): return {}
    reg = ToolRegistry({"foo": t})
    assert reg.get_default_scope("foo") == "agent"  # fallback
    reg.set_default_scope("foo", "user")
    assert reg.get_default_scope("foo") == "user"
    # invalid scope 거부
    with pytest.raises(ValueError, match="invalid scope"):
        reg.set_default_scope("foo", "invalid")  # type: ignore[arg-type]


def test_registry_register_with_default_scope():
    async def t(args): return {}
    reg = ToolRegistry()
    reg.register("mail.send", t, description="메일 발송", default_scope="user")
    assert reg.get_default_scope("mail.send") == "user"


def test_registry_list_scopes():
    """list_scopes 는 등록된 모든 도구 + fallback 'agent' 채움."""
    async def t1(args): return {}
    async def t2(args): return {}
    async def t3(args): return {}
    reg = ToolRegistry(
        {"a": t1, "b": t2, "c": t3},
        scopes={"a": "user", "b": "tenant"},
    )
    out = reg.list_scopes()
    assert out == {"a": "user", "b": "tenant", "c": "agent"}


@pytest.mark.asyncio
async def test_registry_scopes_runtime_no_op():
    """Phase 2 — manifest 추가만으로 기존 동작 무영향. call 결과 동일."""
    async def t(args): return {"ok": True, "echo": args}
    reg_old = ToolRegistry({"echo": t})  # scopes 미전달
    reg_new = ToolRegistry({"echo": t}, scopes={"echo": "user"})

    out_old = await reg_old.call("echo", {"x": 1})
    out_new = await reg_new.call("echo", {"x": 1})
    assert out_old == out_new == {"ok": True, "echo": {"x": 1}}
