from src.api.routers.blocks import _apply_editor_metadata


def test_apply_merges_display_fields_preserving_enrichment():
    existing = {"nature": "old", "entities": {"people": ["A"]}, "contextual_prefix": "ctx", "hint": "h0"}
    provided = {"search_summary": "요약", "nature": "fact", "query_keywords": ["q"], "topic_tags": ["t"], "hint": "h1"}
    merged = _apply_editor_metadata(existing, provided)
    assert merged["search_summary"] == "요약"
    assert merged["nature"] == "fact"
    assert merged["query_keywords"] == ["q"]
    assert merged["topic_tags"] == ["t"]
    assert merged["hint"] == "h1"
    assert merged["entities"] == {"people": ["A"]}
    assert merged["contextual_prefix"] == "ctx"


def test_apply_none_provided_keeps_existing():
    existing = {"nature": "old", "x": 1}
    assert _apply_editor_metadata(existing, None) == {"nature": "old", "x": 1}
    assert _apply_editor_metadata(existing, {}) == {"nature": "old", "x": 1}


def test_apply_overwrites_with_provided_empty_but_preserves_absent():
    # 계약 고정: provided 에 존재하는 키는 빈 값이라도 덮어쓴다(사용자 의도적 비움),
    # provided 에 없는 키는 보존한다.
    existing = {"query_keywords": ["a", "b"], "topic_tags": ["금융"], "entities": {"people": ["A"]}}
    provided = {"query_keywords": []}  # 사용자가 비운 필드만 전송
    merged = _apply_editor_metadata(existing, provided)
    assert merged["query_keywords"] == []          # 명시적 빈 값 → 덮어씀
    assert merged["topic_tags"] == ["금융"]         # 미전송 → 보존
    assert merged["entities"] == {"people": ["A"]}  # 비표시 enrichment 보존
