import asyncio
import pytest
from src.agent_framework.connectors.mock_hr_api import MockHrApiPlugin


def test_probe_success():
    p = MockHrApiPlugin()
    res = asyncio.run(p.probe(
        spec={"base_url":"mock://hr_api","ops":[{"method":"POST","path":"/travel-report"}]},
        credential={"auth_type":"bearer","token":"mock-token-valid"}))
    assert res.ok and res.auth_valid
    assert any(o["path"]=="/travel-report" for o in res.detected_ops)


def test_probe_bad_token():
    p = MockHrApiPlugin()
    res = asyncio.run(p.probe(
        spec={"base_url":"mock://hr_api","ops":[]},
        credential={"auth_type":"bearer","token":"BAD"}))
    assert not res.ok and not res.auth_valid and "token" in (res.error or "").lower()
