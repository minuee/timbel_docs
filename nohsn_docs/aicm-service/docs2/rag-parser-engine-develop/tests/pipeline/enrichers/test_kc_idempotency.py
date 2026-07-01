"""D17-v5 §1 — KC idempotency cleanup unit test.

검증 대상: `KnowledgeCompiler._cleanup_prior_kc_outputs` (static method).

GPT-5 v2 phase0 verdict GO 의 risk fix 검증:
- risk 1 fix: generated=True + source ∈ _KC_GENERATED_SOURCES *AND* 조건
- risk 2 fix: 외부 enricher 가 동일 source 가져도 generated=False 면 보존
- risk 3 fix: contextual_prefix 는 _kc_owned 마커 가진 block 만 reset
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from src.pipeline.enrichers.knowledge_compiler import (
    KC_VERSION,
    KnowledgeCompiler,
    _KC_GENERATED_SOURCES,
    _KC_OWNED_CTX_PREFIX_MARKER,
)
from src.pipeline.models.block import BlockObject, BlockType


def _make_block(
    content: str = "본문 텍스트",
    block_type: BlockType = BlockType.PARAGRAPH,
    *,
    metadata: dict | None = None,
    contextual_prefix: str | None = None,
) -> BlockObject:
    return BlockObject(
        id=uuid4(),
        document_id=uuid4(),
        block_type=block_type,
        content=content,
        block_index=0,
        metadata=metadata or {},
        contextual_prefix=contextual_prefix,
    )


def test_kc_version_is_int_and_sources_set() -> None:
    """KC_VERSION 상수 + _KC_GENERATED_SOURCES set 정합성."""
    assert isinstance(KC_VERSION, int)
    assert KC_VERSION >= 1
    assert _KC_GENERATED_SOURCES == frozenset({
        "llm_summary", "stats_summary", "entity_page",
    })


def test_cleanup_removes_kc_generated_summary_block() -> None:
    """generated=True + source ∈ 화이트리스트 인 block 제거."""
    user_block = _make_block(
        content="사용자 본문",
        block_type=BlockType.PARAGRAPH,
        metadata={"foo": "bar"},
    )
    kc_summary = _make_block(
        content="KC 요약",
        block_type=BlockType.SUMMARY,
        metadata={"generated": True, "source": "llm_summary"},
    )
    kc_entity = _make_block(
        content="# KRX\n증권거래소",
        block_type=BlockType.SUMMARY,
        metadata={"generated": True, "source": "entity_page", "entity_name": "KRX"},
    )
    cleaned = KnowledgeCompiler._cleanup_prior_kc_outputs(
        [user_block, kc_summary, kc_entity]
    )
    # 사용자 block 만 살아남음
    assert len(cleaned) == 1
    assert cleaned[0].id == user_block.id


def test_cleanup_preserves_external_block_with_same_source_but_no_generated() -> None:
    """RISK 1/2 fix — generated=False 면 source 가 동일 값이어도 보존."""
    external_block = _make_block(
        content="외부 enricher 가 만든 요약",
        block_type=BlockType.SUMMARY,
        # source 는 동일하지만 generated 가 False
        metadata={"source": "llm_summary", "external": True},
    )
    cleaned = KnowledgeCompiler._cleanup_prior_kc_outputs([external_block])
    assert len(cleaned) == 1
    assert cleaned[0].id == external_block.id


def test_cleanup_preserves_block_with_generated_but_different_source() -> None:
    """generated=True 라도 source 가 화이트리스트 외 → 보존 (외부 enricher)."""
    other_generated = _make_block(
        content="다른 enricher 가 만든 block",
        block_type=BlockType.PARAGRAPH,
        metadata={"generated": True, "source": "qa_pair_extractor"},
    )
    cleaned = KnowledgeCompiler._cleanup_prior_kc_outputs([other_generated])
    assert len(cleaned) == 1
    assert cleaned[0].id == other_generated.id


def test_cleanup_pops_kc_owned_metadata_keys() -> None:
    """KC-owned metadata 키 (crosslinks/linked_block_ids/crosslink_count) pop."""
    block = _make_block(
        content="본문",
        metadata={
            "foo": "bar",  # 보존
            "crosslinks": [{"id": "x"}],  # KC-owned, pop
            "linked_block_ids": ["abc"],  # KC-owned, pop
            "crosslink_count": 3,  # KC-owned, pop
            "topic_tags": ["tag1"],  # 보존
        },
    )
    cleaned = KnowledgeCompiler._cleanup_prior_kc_outputs([block])
    assert len(cleaned) == 1
    meta = cleaned[0].metadata
    assert meta.get("foo") == "bar"
    assert meta.get("topic_tags") == ["tag1"]
    assert "crosslinks" not in meta
    assert "linked_block_ids" not in meta
    assert "crosslink_count" not in meta


def test_cleanup_resets_kc_owned_contextual_prefix_only() -> None:
    """RISK 3 fix — KC-owned 마커 set 된 block 만 contextual_prefix reset."""
    kc_owned = _make_block(
        content="KC 가 채운 prefix block",
        metadata={_KC_OWNED_CTX_PREFIX_MARKER: True, "foo": "bar"},
        contextual_prefix="KC가 채운 맥락 텍스트",
    )
    external_owned = _make_block(
        content="외부 단계가 채운 prefix block",
        metadata={"foo": "bar"},  # 마커 없음
        contextual_prefix="외부 단계가 채운 맥락",
    )
    cleaned = KnowledgeCompiler._cleanup_prior_kc_outputs([kc_owned, external_owned])
    assert len(cleaned) == 2
    # KC-owned → reset + 마커 pop
    assert cleaned[0].contextual_prefix is None
    assert _KC_OWNED_CTX_PREFIX_MARKER not in cleaned[0].metadata
    # 외부 → 보존
    assert cleaned[1].contextual_prefix == "외부 단계가 채운 맥락"


def test_cleanup_idempotent_double_call() -> None:
    """cleanup → cleanup 2회 호출해도 결과 동일 (누적 0)."""
    blocks = [
        _make_block(content="user1"),
        _make_block(
            content="kc summary",
            block_type=BlockType.SUMMARY,
            metadata={"generated": True, "source": "llm_summary"},
        ),
        _make_block(content="user2", metadata={"crosslinks": [{"x": 1}]}),
    ]
    pass1 = KnowledgeCompiler._cleanup_prior_kc_outputs(blocks)
    pass2 = KnowledgeCompiler._cleanup_prior_kc_outputs(pass1)
    assert len(pass1) == len(pass2) == 2
    assert {b.id for b in pass1} == {b.id for b in pass2}
    # 2번째 cleanup 도 crosslinks 가 이미 없으니 동일 결과
    for b in pass2:
        assert "crosslinks" not in b.metadata


def test_cleanup_handles_none_metadata_gracefully() -> None:
    """metadata=None 인 block 도 안전하게 처리 (제거 X)."""
    block = _make_block(content="기본 block")
    block.metadata = None  # type: ignore[assignment]  # extreme edge case
    cleaned = KnowledgeCompiler._cleanup_prior_kc_outputs([block])
    assert len(cleaned) == 1
    assert cleaned[0].id == block.id


def test_cleanup_preserves_kc_owned_marker_on_non_prefix_block() -> None:
    """contextual_prefix=None 인데 마커만 있는 block — 제거/변경 X."""
    block = _make_block(
        content="prefix 가 None 이지만 마커 있는 block (이론상 0)",
        metadata={_KC_OWNED_CTX_PREFIX_MARKER: True, "foo": "bar"},
        contextual_prefix=None,
    )
    cleaned = KnowledgeCompiler._cleanup_prior_kc_outputs([block])
    assert len(cleaned) == 1
    # contextual_prefix 가 None 이면 reset 분기 진입 안함 → 마커도 그대로
    # (이론상 발생 안하지만 안전한 동작)
    assert cleaned[0].metadata.get(_KC_OWNED_CTX_PREFIX_MARKER) is True


@pytest.mark.asyncio
async def test_compile_idempotent_double_call_no_accumulation() -> None:
    """compile() 2회 호출해도 KC SUMMARY block 누적 0 (llm_client=None — stats_summary).

    GPT-5 c1-post 권고 — compile-level idempotency 직접 검증.
    """
    from src.pipeline.models.document import ProcessingConfig

    # 사용자 block 2개. llm_client=None 이므로 stats_summary 만 생성.
    blocks = [
        _make_block(content="첫 번째 본문 텍스트입니다."),
        _make_block(content="두 번째 본문 텍스트입니다."),
    ]
    cfg = ProcessingConfig(
        contextual_retrieval=False,
        auto_metadata=False,
        enable_search_summary=False,
        enable_query_keywords=False,
        enable_self_verification=False,
    )
    kc = KnowledgeCompiler(config=cfg, llm_client=None)

    pass1 = await kc.compile(list(blocks), document_text="", document_title="doc")
    pass1_summary_count = sum(
        1
        for b in pass1
        if b.metadata.get("generated") is True
        and b.metadata.get("source") in _KC_GENERATED_SOURCES
    )
    pass1_user_block_ids = {
        b.id for b in pass1 if not b.metadata.get("generated")
    }

    # 2회차 호출 — pass1 결과를 그대로 입력
    pass2 = await kc.compile(pass1, document_text="", document_title="doc")
    pass2_summary_count = sum(
        1
        for b in pass2
        if b.metadata.get("generated") is True
        and b.metadata.get("source") in _KC_GENERATED_SOURCES
    )
    pass2_user_block_ids = {
        b.id for b in pass2 if not b.metadata.get("generated")
    }

    # KC summary block 누적 X — 1회차와 2회차 갯수 동일
    assert pass1_summary_count == pass2_summary_count
    # 사용자 block 보존 — id set 동일
    assert pass1_user_block_ids == pass2_user_block_ids


def test_cleanup_only_marks_changed_prefix_via_v2_path() -> None:
    """RISK 3 deeper fix — v2 가 외부 prefix 보존 시 마커 inject X 검증.

    cleanup 동작은 marker 있는 경우만 reset. 외부 prefix 가 v2 에서
    변경되지 않으면 marker 도 inject 되지 않아야 함.
    동작 검증은 _apply_contextual_prefix 흐름 내 prev/new 비교 로직.
    여기서는 cleanup 단독 검증 — 외부 prefix + 마커 X → 보존.
    """
    external_prefix_block = _make_block(
        content="외부 prefix 보존 block",
        metadata={"foo": "bar"},  # _KC_OWNED 마커 X
        contextual_prefix="외부가 채운 prefix",
    )
    cleaned = KnowledgeCompiler._cleanup_prior_kc_outputs([external_prefix_block])
    assert len(cleaned) == 1
    # 외부 prefix 보존 (cleanup 의 reset 진입 X)
    assert cleaned[0].contextual_prefix == "외부가 채운 prefix"
