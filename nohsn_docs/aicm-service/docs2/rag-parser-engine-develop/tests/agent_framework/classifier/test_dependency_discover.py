from unittest.mock import AsyncMock
import asyncio
from src.agent_framework.classifier.dependency_discover import (
    DependencyDiscover, DependencyReport,
)


def test_side_effect_level_proposal():
    llm = AsyncMock()
    llm.classify_side_effect = AsyncMock(return_value={
        "level": "write_external",
        "consequential": True,
        "reason": "POST /travel-report 제출 — 외부 HR 시스템 상태 변경",
    })
    discover = DependencyDiscover(llm_client=llm, cc_pair_resolver=_empty_resolver())
    report = asyncio.run(discover.analyze(skill_yaml={
        "name": "travel_report",
        "description": "출장 복귀 후 HR 제출",
        "tools": [],
    }))
    assert report.side_effect_level == "write_external"
    assert report.consequential is True


def test_connector_match_and_unresolved():
    llm = AsyncMock()
    llm.classify_side_effect = AsyncMock(return_value={
        "level": "write_external", "consequential": True, "reason": "..."})

    class Resolver:
        async def find(self, tenant_id, spec_kind, endpoint_hint):
            if "hr_api" in endpoint_hint:
                return {"cc_pair_id": "ccp_hr_01", "status": "active"}
            return None

    discover = DependencyDiscover(llm_client=llm, cc_pair_resolver=Resolver())
    report = asyncio.run(discover.analyze(skill_yaml={
        "name": "demo",
        "tools": [
            {"name": "hr_api.submit_travel_report",
             "http": {"method": "POST", "path": "/travel-report", "base": "mock://hr_api"}},
            {"name": "ticket_api.create",
             "http": {"method": "POST", "path": "/tickets", "base": "mock://ticket"}},
        ],
    }, tenant_id="t1"))
    assert report.unresolved_apis == 1
    registered = [c for c in report.required_connectors if c["registered"]]
    missing = [c for c in report.required_connectors if not c["registered"]]
    assert len(registered) == 1 and registered[0]["cc_pair_id"] == "ccp_hr_01"
    assert len(missing) == 1 and "ticket_api" in missing[0]["endpoint_hint"]


def _empty_resolver():
    class R:
        async def find(self, *a, **k):
            return None
    return R()
