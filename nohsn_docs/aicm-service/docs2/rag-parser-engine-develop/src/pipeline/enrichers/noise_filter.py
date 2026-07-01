"""블럭 노이즈 필터 — Stage 1 document_structure에서 추출된 noise_patterns 활용.

헤더/푸터/페이지번호/워터마크 등 의미 없는 블럭을 제거/플래그한다.

D17-v5 §4 (2026-05-08) — IMAGE block 노이즈 결정은 *LLM is_decorative* 단독.
이전 _NOISE_IMAGE_TYPES enum fallback 는 사용자 절칙 (LLM 판단 우선) 위반.
LLM 이 is_decorative 를 누락하면 *보존* (보수적). image_type 은 image_describer
prompt prior signal 로만 inject (filter 결정에 직접 영향 X).
"""

from __future__ import annotations

import re

from src.common.logging import get_logger
from src.pipeline.enrichers.image_describer import _parse_strict_bool
from src.pipeline.models.block import BlockObject, BlockType

log = get_logger(__name__)


class NoiseFilterResult:
    """노이즈 필터 결과 — 본문 블럭과 노이즈 블럭을 분리하여 반환."""

    __slots__ = ("content_blocks", "noise_blocks")

    def __init__(
        self,
        content_blocks: list[BlockObject],
        noise_blocks: list[BlockObject],
    ) -> None:
        self.content_blocks = content_blocks
        self.noise_blocks = noise_blocks


def filter_noise_blocks(
    blocks: list[BlockObject],
    noise_patterns: list[str] | None = None,
) -> list[BlockObject]:
    """noise_patterns에 매칭되는 블럭을 제거한다.

    Args:
        blocks: 원본 블럭 목록
        noise_patterns: Stage 1이 추출한 노이즈 패턴 (문자열 또는 정규식)

    Returns:
        노이즈 제거된 블럭 목록 (하위 호환)
    """
    result = partition_noise_blocks(blocks, noise_patterns)
    return result.content_blocks


def partition_noise_blocks(
    blocks: list[BlockObject],
    noise_patterns: list[str] | None = None,
) -> NoiseFilterResult:
    """noise_patterns에 매칭되는 블럭을 분리한다 (제거하지 않음).

    Args:
        blocks: 원본 블럭 목록
        noise_patterns: Stage 1이 추출한 노이즈 패턴 (문자열 또는 정규식)

    Returns:
        NoiseFilterResult(content_blocks, noise_blocks)
    """
    if not noise_patterns:
        # 기본 노이즈 패턴 (Stage 1이 없을 때)
        noise_patterns = [
            r"^-?\s*\d+\s*-?$",  # 페이지 번호만 (예: "- 3 -", "3")
            r"^Page\s+\d+\s+of\s+\d+$",  # "Page 3 of 10"
            r"^\d+\s*/\s*\d+$",  # "3/10"
        ]

    # 정규식 컴파일 (실패해도 넘어감)
    compiled: list[re.Pattern] = []
    for pattern in noise_patterns:
        if not isinstance(pattern, str):
            continue
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        except re.error:
            # 정규식 실패 시 문자열 매치로 전환
            compiled.append(re.compile(re.escape(pattern), re.IGNORECASE))

    content_blocks: list[BlockObject] = []
    noise_blocks: list[BlockObject] = []

    for block in blocks:
        # summary/table 은 무조건 보호
        if block.block_type in (BlockType.SUMMARY, BlockType.TABLE):
            content_blocks.append(block)
            continue

        # D17-v5 §4 — IMAGE 노이즈 결정은 LLM is_decorative 단독.
        # is_decorative 누락 시 → 보존 (보수적, 룰 fallback X).
        # image_type 은 metric log 용 (filter 결정에 직접 영향 X).
        if block.block_type == BlockType.IMAGE:
            meta = block.metadata or {}
            raw_is_dec = meta.get("is_decorative")
            raw_should = meta.get("should_index")
            image_type = (meta.get("image_type") or "").strip().lower()

            # strict bool — bool("false") == True 함정 방어
            is_dec_present = raw_is_dec is not None
            is_decorative = (
                _parse_strict_bool(raw_is_dec, default=False)
                if is_dec_present
                else None
            )
            should_index = (
                _parse_strict_bool(raw_should, default=True)
                if raw_should is not None
                else True
            )

            llm_says_noise = bool(is_decorative) or (should_index is False)

            if llm_says_noise:
                block.metadata["is_noise"] = True
                rationale = str(meta.get("decorative_rationale", ""))[:120]
                # GPT-5 c2-post — 결정 사유 정확히 기록
                # (is_decorative=true vs should_index=false 구분)
                reason_parts: list[str] = []
                if bool(is_decorative):
                    reason_parts.append("llm_is_decorative=true")
                if should_index is False:
                    reason_parts.append("llm_should_index=false")
                reason_parts.append(f"type={image_type or 'unknown'}")
                reason = " ".join(reason_parts)
                if rationale:
                    reason += f" rationale={rationale}"
                block.metadata["noise_reason"] = reason
                noise_blocks.append(block)
                continue
            # is_decorative=null/false → 보존 (LLM 미결정 시 노이즈 X — 보수적)
            # GPT-5 risk 4 mitigation — is_decorative 누락 시 metric log
            if not is_dec_present:
                log.info(
                    "noise_filter_image_decorative_missing",
                    block_id=str(block.id),
                    image_type=image_type,
                )
            content_blocks.append(block)
            continue

        content = block.content.strip()

        # 너무 짧고 숫자/특수문자만 있으면 노이즈
        if len(content) <= 5 and re.match(r"^[\d\-\s\|\.]+$", content):
            noise_blocks.append(block)
            continue

        # 노이즈 패턴 매칭
        is_noise = False
        for pattern in compiled:
            if pattern.match(content):
                # content 전체가 패턴에 매칭되면 노이즈
                is_noise = True
                break

        if is_noise:
            noise_blocks.append(block)
        else:
            content_blocks.append(block)

    if noise_blocks:
        log.info(
            "noise_filter_applied",
            removed=len(noise_blocks),
            remaining=len(content_blocks),
            patterns=len(compiled),
        )

    return NoiseFilterResult(
        content_blocks=content_blocks,
        noise_blocks=noise_blocks,
    )
