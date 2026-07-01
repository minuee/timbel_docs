import pytest

from src.search.context_weighting import build_anchor_query_text, select_anchors


@pytest.mark.asyncio
async def test_resolve_then_select(monkeypatch):
    # 통합 단위: build_anchor_query_text → resolve(mock) → select_anchors
    text = build_anchor_query_text(
        "환매 수수료?", [{"role": "user", "content": "하나코리아 펀드"}]
    )
    ranked = [("docHANA", 8.0), ("docHANTU", 1.0)]  # resolve_documents_by_title mock 결과
    anchors = select_anchors(ranked, abs_min=4.0, rel_ratio=0.8)
    assert anchors == ["docHANA"]
    assert "하나코리아" in text
