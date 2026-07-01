"""DependencyDiscover (델타 #1) — SOP 본문·tool_calls 를 보고:
- side_effect_level (read_only|write_external|irreversible)
- consequential: bool
- required_connectors: [{endpoint_hint, registered, cc_pair_id?}]
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict


@dataclass
class DependencyReport:
    side_effect_level: str
    consequential: bool
    reversible: bool = True
    undo_hint: str | None = None
    required_connectors: list[dict] = field(default_factory=list)
    unresolved_apis: int = 0
    reason: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class DependencyDiscover:
    def __init__(self, *, llm_client, cc_pair_resolver):
        self.llm = llm_client
        self.resolver = cc_pair_resolver

    async def analyze(self, *, skill_yaml: dict, tenant_id: str = "t_default") -> DependencyReport:
        classification = await self.llm.classify_side_effect(
            skill_yaml=skill_yaml, tools=skill_yaml.get("tools") or [],
        )
        level = classification.get("level", "write_external")
        consequential = bool(classification.get("consequential",
                                                level != "read_only"))
        reason = classification.get("reason", "")

        required: list[dict] = []
        unresolved = 0
        for t in skill_yaml.get("tools") or []:
            http = t.get("http") or {}
            tool_name = t.get("name") or ""
            # tool name 의 namespace 접두어 (예: ticket_api.create → ticket_api) 를
            # endpoint_hint 에 포함시켜 base URL 이 축약된 경우에도 상위 API 식별자가 남도록 함.
            namespace = tool_name.split(".", 1)[0] if "." in tool_name else ""
            raw_endpoint = f"{http.get('base','')}{http.get('path','')}"
            if namespace and namespace not in raw_endpoint:
                endpoint_hint = f"{namespace}:{raw_endpoint}" if raw_endpoint else namespace
            else:
                endpoint_hint = raw_endpoint
            spec_kind = t.get("spec_kind") or "custom"
            if not endpoint_hint:
                continue
            match = await self.resolver.find(tenant_id, spec_kind, endpoint_hint)
            registered = bool(match)
            entry = {
                "tool_name": t.get("name"),
                "endpoint_hint": endpoint_hint,
                "spec_kind": spec_kind,
                "registered": registered,
            }
            if match:
                entry["cc_pair_id"] = match["cc_pair_id"]
                entry["cc_pair_status"] = match.get("status")
            else:
                unresolved += 1
            required.append(entry)

        undo_hint = None
        reversible = True
        for t in skill_yaml.get("tools") or []:
            if t.get("http", {}).get("undo_endpoint"):
                undo_hint = t["http"]["undo_endpoint"]
                break
        if level == "irreversible":
            reversible = False

        return DependencyReport(
            side_effect_level=level,
            consequential=consequential,
            reversible=reversible,
            undo_hint=undo_hint,
            required_connectors=required,
            unresolved_apis=unresolved,
            reason=reason,
        )
