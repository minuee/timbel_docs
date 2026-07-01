"""Connector plugin base — probe() contract + registry.

Each connector plugin implements `async def probe(spec, credential) -> ProbeResult`.
Triggered at CC-pair save-time + periodic re-probe.

Plugin 식별 — `(spec_kind, name)` 튜플:
- `spec_kind` ∈ {openapi, rss, mcp, custom} — connectors 테이블 CHECK 와 일치
- `name` — 같은 spec_kind 내에서 plugin 을 구분 (e.g. spec_kind="custom" 에 mock_hr_api / acme_crm 공존)

조회는 `get_plugin(spec_kind, name)` 권장. spec_kind 만 주면 첫 매치 반환 (호환).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ProbeResult:
    ok: bool
    detected_ops: list[dict]
    auth_valid: bool
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class ConnectorPlugin(Protocol):
    spec_kind: str
    name: str

    async def probe(self, spec: dict, credential: dict) -> ProbeResult: ...


class UnknownConnectorKind(KeyError):
    pass


# key = (spec_kind, name)
_REGISTRY: dict[tuple[str, str], ConnectorPlugin] = {}


def register_plugin(plugin: ConnectorPlugin) -> None:
    name = getattr(plugin, "name", None) or plugin.spec_kind
    _REGISTRY[(plugin.spec_kind, name)] = plugin


def get_plugin(spec_kind: str, name: str | None = None) -> ConnectorPlugin:
    """spec_kind + name 으로 plugin 조회. name 생략 시 spec_kind 의 첫 매치."""
    if name is not None:
        try:
            return _REGISTRY[(spec_kind, name)]
        except KeyError as e:
            raise UnknownConnectorKind(f"{spec_kind}:{name}") from e
    for (kind, _), plugin in _REGISTRY.items():
        if kind == spec_kind:
            return plugin
    raise UnknownConnectorKind(spec_kind)


def all_kinds() -> list[str]:
    return sorted({kind for (kind, _) in _REGISTRY.keys()})


def all_plugins() -> list[tuple[str, str]]:
    return sorted(_REGISTRY.keys())
