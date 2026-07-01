"""BlockVerifier -- LLM 기반 블럭 경계 검증 및 헤딩 계층 교정.

세그멘터가 만든 BlockObject 목록을 후처리하여:
1. 잘못 분리된 인접 블럭을 병합 (verify_boundaries)
2. 헤딩 계층 구조를 교정 (correct_heading_hierarchy)
3. 과대 paragraph 를 자연스러운 지점에서 분할 (split_oversized_paragraph)
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from src.common.llm.base import LLMRequest, LLMResponse, LLMTask
from src.common.llm.router import llm_router
from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType

log = get_logger(__name__)

# ── 기본 설정 ──────────────────────────────────────────────────────────────────
_MIN_BLOCKS_FOR_VERIFICATION = 3
"""블럭 수가 이 미만이면 검증을 건너뛴다."""

_OVERSIZED_PARAGRAPH_CHARS = 2000
"""이 길이를 초과하는 paragraph 는 분할 대상."""

_BOUNDARY_CONCURRENCY = 6
"""경계 검증 LLM 동시 호출 수."""

_CONTENT_PREVIEW_CHARS = 500
"""LLM 프롬프트에 포함할 블럭 내용의 최대 문자 수."""

# ── 프롬프트 ──────────────────────────────────────────────────────────────────

BOUNDARY_CHECK_PROMPT = """다음 두 블럭이 하나의 의미 단위인지 판단하라.

블럭 A (타입: {type_a}):
{content_a}

블럭 B (타입: {type_b}):
{content_b}

판단 기준:
- 두 블럭이 동일한 주제/논점을 이어서 설명하면 merge
- 리스트 항목이 분리된 경우 merge
- 서로 다른 주제이거나, 헤딩-본문 관계이면 keep_separate

JSON만 반환: {{"action": "merge"|"keep_separate", "reason": "..."}}"""

HEADING_HIERARCHY_PROMPT = """다음 헤딩들의 올바른 계층 구조를 분석하라.

헤딩 목록 (현재 분류):
{headings_list}

문서 전체 맥락 (앞부분):
{doc_context}

규칙:
- 문서 제목/최상위 섹션 = level 1
- 하위 섹션 = level 2
- 세부 항목 = level 3
- 원래 레벨이 맞으면 그대로 유지

각 헤딩의 적절한 level (1/2/3)을 JSON 배열로 반환:
[{{"index": 0, "level": 1}}, {{"index": 1, "level": 2}}, ...]"""

SPLIT_PARAGRAPH_PROMPT = """다음 긴 문단을 의미 단위로 분할할 자연스러운 지점을 찾아라.

문단 내용:
{content}

규칙:
- 주제가 전환되는 지점에서 분할
- 각 분할 블럭은 200자 이상이어야 함
- 분할이 불필요하면 빈 배열 반환

분할 지점의 문자 오프셋을 JSON 배열로 반환 (0-based, 분할 시작 위치):
[{{"offset": 350, "reason": "주제 전환"}}, ...]"""


class BlockVerifier:
    """LLM 기반 블럭 경계 검증 및 헤딩 계층 교정기.

    세그멘터 출력을 후처리하여 블럭 품질을 높인다.
    모든 메서드는 async 이며 LLM 호출은 llm_router 를 통해 수행된다.
    """

    async def run(self, blocks: list[BlockObject]) -> list[BlockObject]:
        """전체 검증 파이프라인을 순차 실행한다.

        순서: verify_boundaries -> correct_heading_hierarchy -> split_oversized_paragraph
        """
        if len(blocks) < _MIN_BLOCKS_FOR_VERIFICATION:
            log.debug(
                "block_verifier_skipped",
                reason="too_few_blocks",
                block_count=len(blocks),
            )
            return blocks

        original_count = len(blocks)

        # 1단계: 경계 검증 (병합)
        blocks = await self.verify_boundaries(blocks)

        # 2단계: 헤딩 계층 교정
        blocks = await self.correct_heading_hierarchy(blocks)

        # 3단계: 과대 paragraph 분할
        blocks = await self.split_oversized_paragraph(blocks)

        # block_index 재정렬
        for i, block in enumerate(blocks):
            block.block_index = i

        log.info(
            "block_verifier_complete",
            original_blocks=original_count,
            final_blocks=len(blocks),
            merged=original_count - len(blocks)
            + sum(1 for b in blocks if b.block_type == BlockType.PARAGRAPH and len(b.content) > _OVERSIZED_PARAGRAPH_CHARS),
        )
        return blocks

    # ── 1. 경계 검증 ──────────────────────────────────────────────────────────

    async def verify_boundaries(self, blocks: list[BlockObject]) -> list[BlockObject]:
        """인접 블럭 쌍을 검사하여 잘못 분리된 블럭을 병합한다.

        N 개 블럭에 대해 N-1 회 pair-wise 검사를 수행한다.
        semaphore 로 동시 LLM 호출을 제한한다.
        """
        if len(blocks) < 2:
            return blocks

        sem = asyncio.Semaphore(_BOUNDARY_CONCURRENCY)
        merge_decisions: list[bool] = [False] * (len(blocks) - 1)

        async def _check_pair(idx: int) -> None:
            """blocks[idx] 와 blocks[idx+1] 의 병합 여부를 판단한다."""
            block_a = blocks[idx]
            block_b = blocks[idx + 1]

            # 타입이 다르고 헤딩이 포함된 경우 병합하지 않음 (빠른 스킵)
            heading_types = {BlockType.HEADING_1, BlockType.HEADING_2, BlockType.HEADING_3}
            if block_a.block_type in heading_types or block_b.block_type in heading_types:
                return
            # 테이블/이미지/구분선은 병합 대상이 아님
            # [수정 2026-06-16] QNA 추가 — FAQ 의 각 Q&A 는 그 자체로 완결 단위이며
            # 질문은 metadata.qna_title 에만 있다. 경계 검증기는 답변 content 만 보고
            # "같은 주제"면 병합하는데, _merge_blocks 가 block_a 메타만 유지해 block_b 의
            # qna_title(질문)을 통째로 버린다 → 서로 다른 FAQ 질문이 합쳐지고 한 질문이
            # 검색에서 사라짐(매장문의.docx Q2 누락 사례). QNA 는 병합 대상에서 제외한다.
            skip_types = {BlockType.TABLE, BlockType.IMAGE, BlockType.DIVIDER, BlockType.CODE, BlockType.QNA}
            if block_a.block_type in skip_types or block_b.block_type in skip_types:
                return

            async with sem:
                try:
                    should_merge = await self._llm_boundary_check(block_a, block_b)
                    merge_decisions[idx] = should_merge
                except Exception as exc:
                    log.warning(
                        "boundary_check_failed",
                        pair_index=idx,
                        error=str(exc),
                    )

        await asyncio.gather(*[_check_pair(i) for i in range(len(blocks) - 1)])

        # 병합 적용: 연속된 merge 가 있으면 모두 하나로
        merged: list[BlockObject] = []
        i = 0
        while i < len(blocks):
            current = blocks[i]
            # 연속 merge 체인 수집
            while i < len(blocks) - 1 and merge_decisions[i]:
                next_block = blocks[i + 1]
                current = self._merge_blocks(current, next_block)
                i += 1
            merged.append(current)
            i += 1

        if len(merged) < len(blocks):
            log.info(
                "boundary_verification_merged",
                original=len(blocks),
                after_merge=len(merged),
                merges=len(blocks) - len(merged),
            )

        return merged

    async def _llm_boundary_check(
        self, block_a: BlockObject, block_b: BlockObject
    ) -> bool:
        """LLM 에게 두 블럭의 병합 여부를 묻는다.

        Returns:
            True 면 merge, False 면 keep_separate.
        """
        prompt = BOUNDARY_CHECK_PROMPT.format(
            type_a=block_a.block_type.value,
            content_a=block_a.content[:_CONTENT_PREVIEW_CHARS],
            type_b=block_b.block_type.value,
            content_b=block_b.content[:_CONTENT_PREVIEW_CHARS],
        )

        request = LLMRequest(
            prompt=prompt,
            system_prompt="당신은 문서 구조 분석 전문가입니다. JSON만 출력하세요.",
            max_tokens=200,
            temperature=0.1,
            response_format="json",
        )

        response: LLMResponse = await llm_router.route(
            task=LLMTask.DOCUMENT_STRUCTURE,
            request=request,
        )

        parsed = _parse_json_response(response.text)
        action = parsed.get("action", "keep_separate")
        reason = parsed.get("reason", "")

        log.debug(
            "boundary_check_result",
            action=action,
            reason=reason,
            type_a=block_a.block_type.value,
            type_b=block_b.block_type.value,
        )

        return action == "merge"

    @staticmethod
    def _merge_blocks(block_a: BlockObject, block_b: BlockObject) -> BlockObject:
        """두 블럭을 하나로 병합한다.

        첫 번째 블럭의 타입과 메타데이터를 유지하고 content 를 합친다.
        """
        merged_content = block_a.content.rstrip() + "\n" + block_b.content.lstrip()

        merged = block_a.model_copy(
            update={
                "content": merged_content,
                "token_count": len(merged_content),
                "source_location": block_a.source_location.model_copy(
                    update={
                        "end_char_offset": block_b.source_location.end_char_offset,
                    }
                ),
            }
        )
        merged.compute_hash()
        return merged

    # ── 2. 헤딩 계층 교정 ────────────────────────────────────────────────────

    async def correct_heading_hierarchy(
        self, blocks: list[BlockObject]
    ) -> list[BlockObject]:
        """모든 헤딩의 계층 구조를 LLM 으로 교정한다.

        1회의 배치 LLM 호출로 모든 헤딩의 올바른 level 을 결정한다.
        """
        heading_types = {BlockType.HEADING_1, BlockType.HEADING_2, BlockType.HEADING_3}
        heading_indices = [
            i for i, b in enumerate(blocks) if b.block_type in heading_types
        ]

        if len(heading_indices) < 2:
            return blocks

        # 헤딩 목록 구성
        headings_list_parts: list[str] = []
        for seq_idx, block_idx in enumerate(heading_indices):
            block = blocks[block_idx]
            headings_list_parts.append(
                f"[{seq_idx}] (현재: {block.block_type.value}) "
                f"내용: {block.content[:200]}"
            )
        headings_list = "\n".join(headings_list_parts)

        # 문서 맥락: 앞 3개 블럭 내용
        doc_context_parts = [
            b.content[:300] for b in blocks[:3]
        ]
        doc_context = "\n---\n".join(doc_context_parts)

        prompt = HEADING_HIERARCHY_PROMPT.format(
            headings_list=headings_list,
            doc_context=doc_context,
        )

        request = LLMRequest(
            prompt=prompt,
            system_prompt="당신은 문서 구조 분석 전문가입니다. JSON만 출력하세요.",
            max_tokens=500,
            temperature=0.1,
            response_format="json",
        )

        try:
            response: LLMResponse = await llm_router.route(
                task=LLMTask.DOCUMENT_STRUCTURE,
                request=request,
            )

            assignments = _parse_json_array_response(response.text)

            level_to_type = {
                1: BlockType.HEADING_1,
                2: BlockType.HEADING_2,
                3: BlockType.HEADING_3,
            }

            corrections = 0
            for assignment in assignments:
                if not isinstance(assignment, dict):
                    continue
                seq_idx = assignment.get("index")
                level = assignment.get("level")
                if (
                    not isinstance(seq_idx, int)
                    or seq_idx >= len(heading_indices)
                    or level not in (1, 2, 3)
                ):
                    continue

                block_idx = heading_indices[seq_idx]
                new_type = level_to_type[level]
                if blocks[block_idx].block_type != new_type:
                    old_type = blocks[block_idx].block_type.value
                    blocks[block_idx].block_type = new_type
                    corrections += 1
                    log.debug(
                        "heading_level_corrected",
                        block_index=block_idx,
                        old_type=old_type,
                        new_type=new_type.value,
                        content_preview=blocks[block_idx].content[:80],
                    )

            if corrections > 0:
                log.info(
                    "heading_hierarchy_corrected",
                    total_headings=len(heading_indices),
                    corrections=corrections,
                )

        except Exception as exc:
            log.warning(
                "heading_hierarchy_correction_failed",
                error=str(exc),
                heading_count=len(heading_indices),
            )

        return blocks

    # ── 3. 과대 paragraph 분할 ───────────────────────────────────────────────

    async def split_oversized_paragraph(
        self, blocks: list[BlockObject]
    ) -> list[BlockObject]:
        """2000자를 초과하는 paragraph 블럭을 자연스러운 지점에서 분할한다."""
        result: list[BlockObject] = []

        for block in blocks:
            if (
                block.block_type == BlockType.PARAGRAPH
                and len(block.content) > _OVERSIZED_PARAGRAPH_CHARS
            ):
                try:
                    split_blocks = await self._split_one_paragraph(block)
                    result.extend(split_blocks)
                except Exception as exc:
                    log.warning(
                        "paragraph_split_failed",
                        block_id=str(block.id),
                        content_len=len(block.content),
                        error=str(exc),
                    )
                    result.append(block)
            else:
                result.append(block)

        return result

    async def _split_one_paragraph(self, block: BlockObject) -> list[BlockObject]:
        """단일 과대 paragraph 를 LLM 으로 분할한다."""
        prompt = SPLIT_PARAGRAPH_PROMPT.format(
            content=block.content[:4000],
        )

        request = LLMRequest(
            prompt=prompt,
            system_prompt="당신은 문서 구조 분석 전문가입니다. JSON만 출력하세요.",
            max_tokens=500,
            temperature=0.1,
            response_format="json",
        )

        response: LLMResponse = await llm_router.route(
            task=LLMTask.DOCUMENT_STRUCTURE,
            request=request,
        )

        split_points = _parse_json_array_response(response.text)
        if not split_points:
            return [block]

        # 오프셋 추출 및 정렬
        offsets: list[int] = []
        for sp in split_points:
            if isinstance(sp, dict):
                offset = sp.get("offset")
                if isinstance(offset, int) and 200 <= offset < len(block.content) - 200:
                    offsets.append(offset)

        if not offsets:
            return [block]

        offsets.sort()

        # 분할 실행
        new_blocks: list[BlockObject] = []
        prev = 0
        for offset in offsets:
            chunk_content = block.content[prev:offset].strip()
            if chunk_content:
                new_block = BlockObject(
                    id=uuid4(),
                    document_id=block.document_id,
                    block_type=BlockType.PARAGRAPH,
                    content=chunk_content,
                    block_index=0,
                    token_count=len(chunk_content),
                    source_location=block.source_location.model_copy(
                        update={
                            "start_char_offset": (
                                block.source_location.start_char_offset or 0
                            )
                            + prev,
                            "end_char_offset": (
                                block.source_location.start_char_offset or 0
                            )
                            + offset,
                        }
                    ),
                    metadata={**block.metadata, "split_from": str(block.id)},
                )
                new_block.compute_hash()
                new_blocks.append(new_block)
            prev = offset

        # 마지막 조각
        last_content = block.content[prev:].strip()
        if last_content:
            new_block = BlockObject(
                id=uuid4(),
                document_id=block.document_id,
                block_type=BlockType.PARAGRAPH,
                content=last_content,
                block_index=0,
                token_count=len(last_content),
                source_location=block.source_location.model_copy(
                    update={
                        "start_char_offset": (
                            block.source_location.start_char_offset or 0
                        )
                        + prev,
                    }
                ),
                metadata={**block.metadata, "split_from": str(block.id)},
            )
            new_block.compute_hash()
            new_blocks.append(new_block)

        if len(new_blocks) > 1:
            log.info(
                "paragraph_split",
                original_len=len(block.content),
                split_count=len(new_blocks),
                block_id=str(block.id),
            )
            return new_blocks

        return [block]


# ── 유틸리티 ──────────────────────────────────────────────────────────────────


def _parse_json_response(text: str) -> dict:
    """LLM 응답에서 JSON 객체를 추출한다."""
    cleaned = _strip_llm_wrapper(text)
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 중괄호 탐색
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass

    log.warning("json_object_parse_failed", response_preview=text[:200])
    return {}


def _parse_json_array_response(text: str) -> list[dict]:
    """LLM 응답에서 JSON 배열을 추출한다."""
    cleaned = _strip_llm_wrapper(text)
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # 대괄호 탐색
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start >= 0 and end > start:
        try:
            result = json.loads(cleaned[start : end + 1])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    log.warning("json_array_parse_failed", response_preview=text[:200])
    return []


def _strip_llm_wrapper(text: str) -> str:
    """LLM 응답에서 코드 펜스, thinking 태그 등을 제거한다."""
    import re

    text = text.strip()
    # <think>...</think> 제거
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL)
    # 코드 펜스 제거
    if "```" in text:
        # ```json ... ``` 패턴
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    return text.strip()
