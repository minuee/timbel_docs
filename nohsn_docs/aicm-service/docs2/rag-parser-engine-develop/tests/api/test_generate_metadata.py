from src.api.routers.blocks import _merge_generated_metadata, _METADATA_FIELDS


def test_merge_keeps_existing_and_overwrites_target_fields():
    existing = {"hint": "수동힌트", "nature": "old", "custom": "x"}
    generated = {"search_summary": "요약", "nature": "fact", "query_keywords": ["q1"], "topic_tags": ["t1"]}
    merged = _merge_generated_metadata(existing, generated)
    assert merged["search_summary"] == "요약"
    assert merged["nature"] == "fact"
    assert merged["query_keywords"] == ["q1"]
    assert merged["topic_tags"] == ["t1"]
    assert merged["hint"] == "수동힌트"
    assert merged["custom"] == "x"


def test_merge_skips_none_generated():
    existing = {"nature": "old"}
    generated = {"search_summary": "요약", "nature": None}
    merged = _merge_generated_metadata(existing, generated)
    assert merged["search_summary"] == "요약"
    assert merged["nature"] == "old"


def test_metadata_fields_constant():
    assert _METADATA_FIELDS == ("search_summary", "nature", "query_keywords", "topic_tags")
