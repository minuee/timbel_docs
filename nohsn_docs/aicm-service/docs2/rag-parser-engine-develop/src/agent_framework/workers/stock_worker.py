"""StockWorker 스텁 — read_only snapshot auto-approve."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone


class StockWorker:
    def __init__(self, *, price_fn, doc_store, tenant_id: str):
        self.price_fn = price_fn
        self.store = doc_store
        self.tenant_id = tenant_id

    async def snapshot(self, *, symbols: list[str]) -> dict:
        approved = 0
        for sym in symbols:
            try:
                price = await self.price_fn(sym)
            except Exception:
                continue
            doc_id = f"d_stock_{uuid.uuid4().hex[:8]}"
            await self.store.insert(
                id=doc_id, tenant_id=self.tenant_id,
                title=f"{sym} 일별 스냅샷 {price.get('date')}",
                document_type="stock_snapshot",
                status="active",
                processing_meta={
                    "document_type": "stock_snapshot",
                    "body": price,
                    "activation": {
                        "auto_approved": True,
                        "policy": "snapshot_read_only",
                        "approved_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )
            approved += 1
        return {"auto_approved": approved}
