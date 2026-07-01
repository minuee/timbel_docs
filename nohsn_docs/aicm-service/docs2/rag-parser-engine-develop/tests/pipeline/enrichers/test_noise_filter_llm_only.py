"""D17-v5 §4 — noise_filter LLM-only unit test.

검증 대상: `partition_noise_blocks` 의 IMAGE block 분기.

GPT-5 v2 phase0 verdict:
- is_decorative=true → noise (image_type 무관)
- is_decorative=false 면 image_type=logo 라도 NOT noise (LLM 우선)
- is_decorative 미존재 (key 누락) → NOT noise (보수적, 룰 fallback X)
- should_index=false → noise (LLM 의 별도 의지)
- is_decorative=null + image_type=logo → NOT noise (이전 v2 와 정반대)
"""
from __future__ import annotations

from uuid import uuid4

from src.pipeline.enrichers.noise_filter import partition_noise_blocks
from src.pipeline.models.block import BlockObject, BlockType


def _img_block(*, metadata: dict | None = None) -> BlockObject:
    return BlockObject(
        id=uuid4(),
        document_id=uuid4(),
        block_type=BlockType.IMAGE,
        content="image_block",
        block_index=0,
        metadata=metadata or {},
    )


def test_is_decorative_true_treated_as_noise() -> None:
    """is_decorative=true → noise (image_type 무관)."""
    block = _img_block(
        metadata={"is_decorative": True, "image_type": "diagram"}
    )
    result = partition_noise_blocks([block])
    assert len(result.noise_blocks) == 1
    assert result.noise_blocks[0].metadata.get("is_noise") is True
    assert "llm_is_decorative=true" in result.noise_blocks[0].metadata.get(
        "noise_reason", ""
    )


def test_is_decorative_false_with_logo_type_kept() -> None:
    """is_decorative=false 면 image_type=logo 라도 NOT noise (LLM 우선)."""
    block = _img_block(
        metadata={"is_decorative": False, "image_type": "logo"}
    )
    result = partition_noise_blocks([block])
    assert len(result.noise_blocks) == 0
    assert len(result.content_blocks) == 1


def test_is_decorative_missing_key_kept_no_rule_fallback() -> None:
    """is_decorative 키 누락 → NOT noise (룰 fallback 제거 — 보수적).

    *D17-v5 §4 핵심 fix*. 이전 v3.1 에서는 image_type ∈ _NOISE_IMAGE_TYPES
    면 enum_says_noise → noise 분류했음. 본 PR 에서 룰 fallback 제거 → 보존.
    """
    block = _img_block(metadata={"image_type": "logo"})  # is_decorative 키 X
    result = partition_noise_blocks([block])
    assert len(result.noise_blocks) == 0
    assert len(result.content_blocks) == 1


def test_should_index_false_treated_as_noise() -> None:
    """should_index=false → noise (LLM 의 별도 의지)."""
    block = _img_block(
        metadata={"is_decorative": False, "should_index": False}
    )
    result = partition_noise_blocks([block])
    assert len(result.noise_blocks) == 1
    assert result.noise_blocks[0].metadata.get("is_noise") is True


def test_is_decorative_null_with_logo_type_kept() -> None:
    """is_decorative=null + image_type=logo → NOT noise (이전 v2 와 정반대).

    이 케이스가 *진짜 LLM-only* 의 핵심. LLM 이 미결정 (null) 이면
    룰로 결정 X → 보존.
    """
    block = _img_block(
        metadata={"is_decorative": None, "image_type": "logo"}
    )
    result = partition_noise_blocks([block])
    assert len(result.noise_blocks) == 0
    assert len(result.content_blocks) == 1


def test_strict_bool_string_false_not_treated_as_noise() -> None:
    """is_decorative='false' (string) → bool('false') == True 함정 방어.

    _parse_strict_bool 이 'false' → False 로 정확히 변환해야 함.
    """
    block = _img_block(
        metadata={"is_decorative": "false", "image_type": "logo"}
    )
    result = partition_noise_blocks([block])
    assert len(result.noise_blocks) == 0


def test_strict_bool_string_true_treated_as_noise() -> None:
    """is_decorative='true' (string) → noise (정상 동작)."""
    block = _img_block(
        metadata={"is_decorative": "true", "image_type": "diagram"}
    )
    result = partition_noise_blocks([block])
    assert len(result.noise_blocks) == 1


def test_should_index_string_false_treated_as_noise() -> None:
    """should_index='false' (string) → noise."""
    block = _img_block(
        metadata={"is_decorative": False, "should_index": "false"}
    )
    result = partition_noise_blocks([block])
    assert len(result.noise_blocks) == 1


def test_other_block_types_unaffected_by_image_branch() -> None:
    """IMAGE 외 block_type 은 image branch 영향 받지 않음 — 회귀 0."""
    para = BlockObject(
        id=uuid4(),
        document_id=uuid4(),
        block_type=BlockType.PARAGRAPH,
        content="이것은 본문 텍스트입니다.",
        block_index=0,
    )
    table = BlockObject(
        id=uuid4(),
        document_id=uuid4(),
        block_type=BlockType.TABLE,
        content="표 본문",
        block_index=1,
    )
    result = partition_noise_blocks([para, table])
    # PARAGRAPH 본문 → content_blocks
    # TABLE → 무조건 보호 (line 102)
    assert len(result.content_blocks) == 2
    assert len(result.noise_blocks) == 0
