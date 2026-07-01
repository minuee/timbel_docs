"""Topic resolver 분리 검증 — overlap 0 강제."""

from src.common.constants import (
    TOPIC_DOCUMENT_PART_BLOCKED,
    TOPIC_DOCUMENT_SPLIT,
    TOPIC_DOCUMENT_PART_READY,
)
from src.pipeline.workers.main import (
    _resolve_main_topics,
    _resolve_merge_topics,
)


def test_large_main_excludes_part_blocked():
    """large profile 의 main topics 에 part_blocked 없어야 한다."""
    topics = _resolve_main_topics("large")
    assert TOPIC_DOCUMENT_PART_BLOCKED not in topics
    assert TOPIC_DOCUMENT_SPLIT in topics
    assert TOPIC_DOCUMENT_PART_READY in topics


def test_large_merge_only_part_blocked():
    """large profile 의 merge topics 는 오직 part_blocked."""
    topics = _resolve_merge_topics("large")
    assert topics == [TOPIC_DOCUMENT_PART_BLOCKED]


def test_no_overlap_between_main_and_merge():
    """main 과 merge 의 topic 교집합 0."""
    main = set(_resolve_main_topics("large"))
    merge = set(_resolve_merge_topics("large"))
    assert main & merge == set()


def test_small_merge_is_empty():
    """small profile 은 merge consumer 없음 (split/merge 자체 없음)."""
    assert _resolve_merge_topics("small") == []


def test_legacy_merge_is_empty():
    """legacy profile 도 merge 없음 (역호환)."""
    assert _resolve_merge_topics("legacy") == []


def test_dedup_key_with_discriminator():
    """spec §3.3 — discriminator 가 key 에 포함."""
    from src.pipeline.workers.main import _dedup_key, _dedup_key_part

    assert _dedup_key("doc-x", "parse") == "aicm:processing:doc-x:parse:main"
    assert (
        _dedup_key("doc-x", "parse", discriminator="custom")
        == "aicm:processing:doc-x:parse:custom"
    )
    assert _dedup_key_part("doc-x", 3, "block") == "aicm:processing:doc-x:block:3"
