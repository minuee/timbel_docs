# tests/agent_framework/workers/test_stock_worker.py
import asyncio
from src.agent_framework.workers.stock_worker import StockWorker


def test_stock_snapshot_auto_approves():
    class PriceFn:
        async def __call__(self, symbol):
            return {"symbol": symbol, "close": 71000, "change_pct": 1.2,
                    "date": "2026-04-25"}
    class Store:
        def __init__(self): self.inserted = []
        async def insert(self, **k):
            self.inserted.append(k); return k["id"]
    store = Store()
    w = StockWorker(price_fn=PriceFn(), doc_store=store, tenant_id="t1")
    res = asyncio.run(w.snapshot(symbols=["005930"]))
    assert res["auto_approved"] == 1
    assert store.inserted[0]["status"] == "active"
    assert store.inserted[0]["document_type"] == "stock_snapshot"
