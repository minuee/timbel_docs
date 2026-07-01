"""P0.3 — `event: citations` payload assigns 1-indexed `number` per item.

Frontend P8 will render `[N]` markers inline in answer body; clicking `[N]`
opens the evidence side panel by looking up the citation with the matching
`number`. Backend must guarantee:

1. Each item carries a `number` field (int, 1-indexed).
2. Numbering is sequential — same candidate keeps the same number across
   the response (we test this via the helper which is deterministic).
3. Order of items matches the prompt enumeration order so `[1]` from the
   LLM resolves to items[0].

We unit-test the helper ``AgentEngine._build_citation_items`` directly —
``engine.turn`` E2E coverage already lives in
``test_grounding_citations_pr_b.py`` (single-emit + schema), so this file
focuses on the new ``number`` contract.
"""
from __future__ import annotations


def _docs(n: int) -> list[dict]:
    return [
        {
            "block_id": f"b{i}",
            "doc_id": f"d{i}",
            "title": f"문서 {i}",
            "heading": "본문",
            "snippet": f"내용 {i}",
            "score": 0.9 - 0.1 * i,
            "doctype": "manual",
        }
        for i in range(1, n + 1)
    ]


def test_citation_items_have_1_indexed_number():
    from src.agent_framework.runtime.engine import AgentEngine

    items = AgentEngine._build_citation_items(_docs(3))
    assert len(items) == 3
    assert [it["number"] for it in items] == [1, 2, 3]


def test_citation_items_number_matches_prompt_order():
    """Item index N → number == N+1. Prompt enumerates [1], [2], … in same order."""
    from src.agent_framework.runtime.engine import AgentEngine

    docs = _docs(5)
    items = AgentEngine._build_citation_items(docs)
    for i, it in enumerate(items):
        assert it["number"] == i + 1, (
            f"item {i}: number={it['number']} expected {i + 1} — "
            "drift breaks [N] → evidence-panel mapping"
        )
        # id must come from the underlying grounding block (stable across response)
        assert it["id"] == f"b{i + 1}"


def test_citation_items_empty_input_yields_empty_list():
    from src.agent_framework.runtime.engine import AgentEngine

    assert AgentEngine._build_citation_items([]) == []
    assert AgentEngine._build_citation_items(None) == []  # type: ignore[arg-type]


def test_citation_item_number_is_int_not_string():
    """frontend `parseInt(number)` 회피용 — JSON 직렬화 시 int 로 보내야 함."""
    from src.agent_framework.runtime.engine import AgentEngine

    items = AgentEngine._build_citation_items(_docs(2))
    for it in items:
        assert isinstance(it["number"], int), (
            f"number must be int, got {type(it['number']).__name__}"
        )
