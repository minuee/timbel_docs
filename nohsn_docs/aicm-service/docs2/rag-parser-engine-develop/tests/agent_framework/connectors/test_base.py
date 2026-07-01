import asyncio
import pytest
from src.agent_framework.connectors.base import (
    ConnectorPlugin, ProbeResult, register_plugin, get_plugin, UnknownConnectorKind,
)


class EchoPlugin:
    spec_kind = "custom"
    name = "echo"

    async def probe(self, spec: dict, credential: dict) -> ProbeResult:
        return ProbeResult(ok=True, detected_ops=[{"method":"GET","path":"/ping"}],
                           auth_valid=True, warnings=[])


def test_probe_result_defaults():
    r = ProbeResult(ok=True, detected_ops=[], auth_valid=True)
    assert r.error is None
    assert r.warnings == []


def test_register_and_resolve_by_name():
    register_plugin(EchoPlugin())
    p = get_plugin("custom", "echo")
    assert isinstance(p, EchoPlugin)


def test_resolve_by_kind_only_returns_first():
    register_plugin(EchoPlugin())
    p = get_plugin("custom")
    assert p.spec_kind == "custom"


def test_unknown_plugin():
    with pytest.raises(UnknownConnectorKind):
        get_plugin("nonexistent-kind")


def test_unknown_name_within_kind():
    register_plugin(EchoPlugin())
    with pytest.raises(UnknownConnectorKind):
        get_plugin("custom", "nonexistent_name")


def test_probe_coroutine():
    res = asyncio.run(EchoPlugin().probe({}, {}))
    assert res.ok and res.auth_valid
