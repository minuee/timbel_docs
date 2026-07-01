"""Periodic cross-scan worker (델타 #4)."""
from __future__ import annotations
from itertools import combinations


class KnowledgeFreshnessWorker:
    def __init__(self, *, analyzer, tenant_loader, store):
        self.analyzer = analyzer
        self.tenant_loader = tenant_loader
        self.store = store

    async def run(self, *, tenant_id: str, trigger: str = "scheduled") -> dict:
        run_id = await self.store.start_run(tenant_id, trigger)
        ids = await self.tenant_loader.list_active_doc_ids(tenant_id)
        pairs = list(combinations(ids, 2))
        issues_found = 0
        for a, b in pairs:
            try:
                res = await self.analyzer.analyze_pair(doc_a=a, doc_b=b)
            except Exception:
                continue
            rel = res.get("relation")
            if rel in ("supersedes_existing", "duplicate", "conflicts"):
                issue = {"type": rel, "peer_doc_id": b,
                         "confidence": res.get("confidence", 0.0),
                         "evidence": res.get("evidence", "")}
                await self.store.append_issue_to_doc(a, issue)
                issues_found += 1
        await self.store.finish_run(
            run_id,
            docs_scanned=len(ids), pairs_classified=len(pairs),
            issues_found=issues_found, status="succeeded",
        )
        return {"run_id": run_id, "issues_found": issues_found,
                "docs_scanned": len(ids)}
