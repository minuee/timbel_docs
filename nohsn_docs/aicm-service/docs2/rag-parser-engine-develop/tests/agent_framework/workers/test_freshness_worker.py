# tests/agent_framework/workers/test_freshness_worker.py
import asyncio
from unittest.mock import AsyncMock
from src.agent_framework.workers.knowledge_freshness_worker import (
    KnowledgeFreshnessWorker,
)


def test_run_logs_issues_to_metadata():
    analyzer = AsyncMock()
    analyzer.analyze_pair = AsyncMock(return_value={
        "relation": "supersedes_existing", "confidence": 0.9,
        "evidence": "신규 > 기존",
    })
    class TenantLoader:
        async def list_active_doc_ids(self, tenant_id): return ["d1", "d2"]
    store = _stub_fresh_store()
    w = KnowledgeFreshnessWorker(
        analyzer=analyzer, tenant_loader=TenantLoader(), store=store,
    )
    result = asyncio.run(w.run(tenant_id="t1", trigger="manual"))
    assert result["issues_found"] >= 1


def _stub_fresh_store():
    class S:
        async def start_run(self, tenant_id, trigger):
            return "run_x"
        async def finish_run(self, run_id, **k):
            pass
        async def append_issue_to_doc(self, doc_id, issue):
            pass
    return S()
