"""Knowledge overlap analyzer — spec §1.5 + 델타 #6/#7.

1) new_summary embed
2) SemHashPreFilter (stage 2a) → top-50
3) reranker (caller-injected, optional) → top-10
4) LLM relation classifier for each hit
5) supersedes/conflicts/complementary → generate replacement_draft
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import numpy as np

from .overlap_prefilter import SemHashPreFilter, Candidate


_REPLACE_DRAFT_RELATIONS = {"supersedes_existing", "complementary"}


@dataclass
class OverlapReport:
    summary: str
    hits: list[dict] = field(default_factory=list)
    suggested_action: str | None = None
    requires_human: bool = False
    analyzed_at: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class KnowledgeOverlapAnalyzer:
    def __init__(
        self,
        embedder,
        corpus_loader,
        llm_client,
        prefilter: SemHashPreFilter | None = None,
        reranker=None,
        final_topk: int = 10,
    ):
        self.embedder = embedder
        self.corpus_loader = corpus_loader
        self.llm = llm_client
        self.prefilter = prefilter or SemHashPreFilter()
        self.reranker = reranker
        self.final_topk = final_topk

    async def analyze(
        self, *, tenant_id: str, new_doc_id: str, new_summary: str,
        temporal_hint: dict | None = None,
    ) -> OverlapReport:
        analyzed_at = datetime.now(timezone.utc).isoformat()
        corpus = await self.corpus_loader.load_active(tenant_id)
        if not corpus:
            return OverlapReport(summary=new_summary, hits=[], suggested_action="approve_add",
                                 requires_human=False, analyzed_at=analyzed_at)

        new_emb = await self.embedder.embed(new_summary)
        stage2a = self.prefilter.stage2a_filter(new_emb, corpus)

        if self.reranker and len(stage2a) > self.final_topk:
            stage2b = await self.reranker.rerank(new_summary, stage2a, self.final_topk)
        else:
            stage2b = stage2a[: self.final_topk]

        hits: list[dict] = []
        for c in stage2b:
            try:
                rel = await self.llm.classify_relation(
                    new_summary=new_summary, peer_title=c.title,
                    peer_snippet=c.snippet or "", temporal_hint=temporal_hint or {},
                )
            except Exception as e:
                hits.append({"doc_id": c.doc_id, "title": c.title,
                             "relation": "unrelated", "confidence": 0.0,
                             "evidence": f"classifier error: {e}"})
                continue
            if rel.get("relation") == "unrelated":
                continue
            hit = {
                "doc_id": c.doc_id,
                "title": c.title,
                "snippet": c.snippet or "",
                "relation": rel["relation"],
                "confidence": float(rel["confidence"]),
                "evidence": rel.get("evidence", ""),
                "suggested_action": _suggest_action(rel["relation"]),
            }
            if rel["relation"] in _REPLACE_DRAFT_RELATIONS:
                try:
                    draft = await self.llm.generate_replacement_draft(
                        new_summary=new_summary,
                        peer_title=c.title, peer_snippet=c.snippet or "",
                        relation=rel["relation"],
                    )
                    hit["replacement_draft"] = draft
                except Exception as e:
                    hit["replacement_draft_error"] = str(e)
            hits.append(hit)

        requires_human = any(h["relation"] == "conflicts" for h in hits)
        top_action = _top_action(hits)

        return OverlapReport(
            summary=new_summary, hits=hits, suggested_action=top_action,
            requires_human=requires_human, analyzed_at=analyzed_at,
        )


def _suggest_action(relation: str) -> str:
    return {
        "duplicate": "reject_duplicate",
        "supersedes_existing": "replace",
        "superseded_by_existing": "reject_outdated",
        "conflicts": "human_review",
        "complementary": "approve_add",
    }.get(relation, "approve_add")


def _top_action(hits: list[dict]) -> str:
    if not hits:
        return "approve_add"
    for h in hits:
        if h["relation"] == "conflicts":
            return "human_review"
    for h in hits:
        if h["relation"] == "supersedes_existing" and h["confidence"] >= 0.85:
            return f"approve_and_archive:{h['doc_id']}"
    for h in hits:
        if h["relation"] == "duplicate" and h["confidence"] >= 0.9:
            return f"reject_duplicate:{h['doc_id']}"
    return "approve_add"
