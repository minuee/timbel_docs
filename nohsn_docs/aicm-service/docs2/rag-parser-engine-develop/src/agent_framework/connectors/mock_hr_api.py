"""Mock HR API plugin — seed 테스트용. 실제 네트워크 호출 없음.

spec_kind="custom" — connectors CHECK 제약과 일치. plugin 구분은 name="mock_hr_api".
"""
from .base import ConnectorPlugin, ProbeResult, register_plugin


class MockHrApiPlugin:
    spec_kind = "custom"
    name = "mock_hr_api"

    async def probe(self, spec: dict, credential: dict) -> ProbeResult:
        token = (credential or {}).get("token", "")
        if not token.startswith("mock-token-"):
            return ProbeResult(ok=False, detected_ops=[], auth_valid=False,
                               error="invalid token format (mock_hr_api expects mock-token-*)")
        if not token.endswith("-valid"):
            return ProbeResult(ok=False, detected_ops=[], auth_valid=False,
                               error="token signature failed")
        ops = (spec or {}).get("ops") or [
            {"method": "POST", "path": "/travel-report"},
            {"method": "POST", "path": "/travel-report/{id}/cancel"},
        ]
        return ProbeResult(
            ok=True, auth_valid=True,
            detected_ops=[{**o, "sample_latency_ms": 42} for o in ops],
            warnings=["mock plugin — do not use in prod"],
        )


register_plugin(MockHrApiPlugin())
