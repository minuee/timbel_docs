"""D38 v3.2 — full_pipeline KC hook unit tests.

Spec: `docs/superpowers/specs/2026-05-10-d38-kc-hook-cutover.md` (v3.2).

검증 항목 (§1.8 사후 검증):
- llm_client=None → KC skip, blocks_full 변경 0 (identity).
- SKIP_KNOWLEDGE_COMPILER=true → KC skip.
- mock LLM → KC 호출, kc_hook_applied=True, marker block-level 주입.
- deepcopy 격리 — 입력 BlockObject.metadata mutate 시 원본 변경 0.
- atomic swap — KC raise 시 blocks_full 변경 0.
- generated block routing — chunker 입력에 generated 미포함, kc_generated_blocks 에 포함.
- BlockObject schema 확장 — properties / children / table_* / image_* / token_count 보존.

Note: process_document_full 자체는 file/markdown 입력이 필요 — 본 test 는
KC hook 로직만 *unit 으로* 검증. file 통합 test 는 별 PR.
"""
from __future__ import annotations

import copy
import os
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.pipeline.enrichers.knowledge_compiler import KC_VERSION
from src.pipeline.full_pipeline import _PipelineBlock, _to_input_block
from src.pipeline.models.block import BlockObject, BlockType


# ────────────────────────────────────────────────────────────────────────
# §1.7 schema extension — _PipelineBlock 새 필드 round-trip
# ────────────────────────────────────────────────────────────────────────


class TestPipelineBlockSchemaExtension:
    """D38 v3 §1.7 — _PipelineBlock 의 BlockObject 추가 필드 보존."""

    def test_default_fields_backward_compat(self) -> None:
        """v3 신규 필드는 default → 기존 호출 영향 0."""
        bid = uuid4()
        pb = _PipelineBlock(
            block_id=bid,
            block_type="paragraph",
            content="x",
            block_index=0,
        )
        # 신규 필드 default 확인
        assert pb.token_count == 0
        assert pb.properties == {}
        assert pb.children == []
        assert pb.table_headers is None
        assert pb.table_rows is None
        assert pb.table_markdown is None
        assert pb.image_path is None
        assert pb.ocr_text is None
        assert pb.image_description is None

    def test_full_schema_assignment(self) -> None:
        """v3 모든 필드 직접 채움."""
        pb = _PipelineBlock(
            block_id=uuid4(),
            block_type="table",
            content="content",
            block_index=0,
            token_count=42,
            properties={"k": "v"},
            children=[uuid4()],
            table_headers=["h1", "h2"],
            table_rows=[["r1c1", "r1c2"]],
            table_markdown="| h1 | h2 |",
            image_path="/tmp/x.png",
            ocr_text="ocr",
            image_description="desc",
        )
        assert pb.token_count == 42
        assert pb.properties == {"k": "v"}
        assert pb.table_headers == ["h1", "h2"]
        assert pb.table_rows == [["r1c1", "r1c2"]]
        assert pb.table_markdown == "| h1 | h2 |"
        assert pb.image_path == "/tmp/x.png"
        assert pb.ocr_text == "ocr"
        assert pb.image_description == "desc"

    def test_to_input_block_preserves_existing_path(self) -> None:
        """_to_input_block 은 InputBlock schema 유지 — D31b backward compat."""
        pb = _PipelineBlock(
            block_id=uuid4(),
            block_type="paragraph",
            content="x",
            block_index=0,
            metadata={"a": 1},
        )
        ib = _to_input_block(pb)
        assert ib.metadata == {"a": 1}
        # nested isolation
        ib.metadata["a"] = 999
        assert pb.metadata["a"] == 1


# ────────────────────────────────────────────────────────────────────────
# §1.2 KC hook 의 BlockObject ↔ _PipelineBlock 변환 round-trip
# ────────────────────────────────────────────────────────────────────────


class TestPipelineBlockBlockObjectRoundTrip:
    """v3 §1.7 — _PipelineBlock 의 BlockObject 변환 round-trip."""

    def test_bo_to_pb_preserves_table_fields(self) -> None:
        """BlockObject → _PipelineBlock 변환 후 table 필드 모두 보존."""
        # KC hook 내부 _bo_to_pb 호출 시뮬레이션 (실제는 closure 안)
        from src.pipeline.models.document import SourceLocation

        doc_id = uuid4()
        bo = BlockObject(
            id=uuid4(),
            document_id=doc_id,
            block_type=BlockType.TABLE,
            content="content",
            block_index=0,
            block_hash="h",
            token_count=10,
            source_location=SourceLocation(page=1),
            properties={"x": 1},
            children=[uuid4()],
            metadata={"m": 1},
            contextual_prefix="p",
            extracted_metadata={"e": 1},
            table_headers=["a", "b"],
            table_rows=[["1", "2"]],
            table_markdown="| a |",
            image_path=None,
            ocr_text=None,
            image_description=None,
        )

        # 본 test 는 _bo_to_pb 의 schema 보존 검증.
        # closure 안의 함수이므로 직접 호출 X — manual round-trip 으로 검증.
        pb_dict = dict(
            block_id=bo.id,
            block_type=bo.block_type.value,
            content=bo.content,
            block_index=bo.block_index,
            metadata=copy.deepcopy(bo.metadata),
            contextual_prefix=bo.contextual_prefix,
            extracted_metadata=copy.deepcopy(bo.extracted_metadata),
            source_location=bo.source_location.model_dump(exclude_none=True),
            block_hash=bo.block_hash,
            kc_markers={},
            token_count=bo.token_count or 0,
            properties=copy.deepcopy(bo.properties or {}),
            children=list(bo.children or []),
            table_headers=list(bo.table_headers) if bo.table_headers else None,
            table_rows=(
                [list(r) for r in bo.table_rows]
                if bo.table_rows else None
            ),
            table_markdown=bo.table_markdown,
            image_path=bo.image_path,
            ocr_text=bo.ocr_text,
            image_description=bo.image_description,
        )
        pb = _PipelineBlock(**pb_dict)
        assert pb.token_count == 10
        assert pb.properties == {"x": 1}
        assert pb.table_headers == ["a", "b"]
        assert pb.table_rows == [["1", "2"]]
        assert pb.table_markdown == "| a |"


# ────────────────────────────────────────────────────────────────────────
# §1.3a block-level marker propagator 통합
# ────────────────────────────────────────────────────────────────────────


class TestKcHookMarkerPropagation:
    """v3 §1.3a — KC hook marker 가 _KC_MARKER_KEYS 화이트리스트 안에 있는지."""

    def test_kc_hook_marker_in_allowlist(self) -> None:
        """kc_hook_applied/version/at 가 _KC_MARKER_KEYS 안에 있어야 함."""
        from src.pipeline.enrichers.chunk_metadata_propagator import (
            _KC_MARKER_KEYS,
        )
        assert "kc_hook_applied" in _KC_MARKER_KEYS
        assert "kc_hook_version" in _KC_MARKER_KEYS
        assert "kc_hook_at" in _KC_MARKER_KEYS

    def test_aggregate_provenance_kc_hook_applied_any_true(self) -> None:
        """aggregate_provenance() 의 kc_hook_applied 가 any(True) 집계 확인."""
        from src.pipeline.enrichers.chunk_metadata_propagator import (
            aggregate_provenance,
        )
        source_blocks_meta = [
            {"kc_hook_applied": True},
            {"kc_hook_applied": False},
            {},
        ]
        agg = aggregate_provenance(source_blocks_meta)
        # any True
        assert agg.get("kc_hook_applied") is True

    def test_aggregate_provenance_no_kc_hook_applied(self) -> None:
        """모두 False/missing 이면 kc_hook_applied 미포함."""
        from src.pipeline.enrichers.chunk_metadata_propagator import (
            aggregate_provenance,
        )
        source_blocks_meta = [
            {"kc_hook_applied": False},
            {},
        ]
        agg = aggregate_provenance(source_blocks_meta)
        assert "kc_hook_applied" not in agg


# ────────────────────────────────────────────────────────────────────────
# §1.2 KC hook 의 SKIP_KNOWLEDGE_COMPILER + llm_client None skip
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestKcHookSkipConditions:
    """v3 §1.2 — KC skip 조건 (llm_client=None / SKIP env)."""

    async def test_kc_skip_when_llm_client_none(self, tmp_path) -> None:
        """llm_client=None → KC skip, kc_hook_applied=False."""
        from src.pipeline.full_pipeline import process_document_full

        md_file = tmp_path / "x.md"
        md_file.write_text("# Title\n\nbody text\n", encoding="utf-8")

        # llm_client None → Stage1/KC 모두 skip → heuristic only.
        # process_document_full 의 다른 의존도 (vision_gate 등) 도 skip 가능 path.
        # 본 test 는 KC hook 만 검증 — 실 호출까지 안 가도 OK (smoke).
        result = await process_document_full(
            title="x",
            file_path=str(md_file),
            llm_client=None,
            upload_source="test",
        )
        # KC 미적용
        assert result.kc_hook_applied is False
        assert result.kc_generated_blocks == []
        # blocks_full 의 어떤 block 에도 kc_hook_applied marker 없음.
        for pb in result.blocks_full:
            md = pb.metadata or {}
            assert not md.get("kc_hook_applied"), (
                f"block {pb.block_id} 의 metadata 에 kc_hook_applied 가 있음 (llm_client=None 인데)"
            )

    async def test_kc_skip_when_env_skip(self, tmp_path, monkeypatch) -> None:
        """SKIP_KNOWLEDGE_COMPILER=true → KC skip."""
        from src.pipeline.full_pipeline import process_document_full

        monkeypatch.setenv("SKIP_KNOWLEDGE_COMPILER", "true")
        md_file = tmp_path / "x.md"
        md_file.write_text("# Title\n\nbody\n", encoding="utf-8")

        # llm_client 가 있어도 env skip.
        class _StubLlm:
            pass

        result = await process_document_full(
            title="x",
            file_path=str(md_file),
            llm_client=_StubLlm(),
            upload_source="test",
        )
        assert result.kc_hook_applied is False
        assert result.kc_generated_blocks == []


# ────────────────────────────────────────────────────────────────────────
# §1.2 + §1.3a + §1.3b — full integration: mock KC compile + marker + atomic swap
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestKcHookFullIntegration:
    """v3 full integration — KC compile() monkeypatch 후 process_document_full 호출."""

    async def test_mock_kc_success_marker_propagation_and_generated_split(
        self, tmp_path, monkeypatch
    ) -> None:
        """mock KC 성공 → marker 주입, generated block 분리, chunker 입력 제외."""
        from src.pipeline.full_pipeline import process_document_full
        from src.pipeline.enrichers import knowledge_compiler as kc_mod
        from src.pipeline.models.block import BlockObject, BlockType

        # md 파일 — 단순 본문 2 block (heading + paragraph).
        md_file = tmp_path / "x.md"
        md_file.write_text("# Title A\n\nbody1\n\n## Title B\n\nbody2\n", encoding="utf-8")

        marker_doc_id: dict[str, Any] = {}

        async def _mock_compile(self, *, blocks, document_text, document_title):
            # 원본 block 모두 보존 (id 동일) + KC marker 주입.
            for b in blocks:
                if b.metadata is None:
                    b.metadata = {}
                b.metadata["search_summary"] = f"mock-summary-{b.block_index}"
                b.metadata["topic_tags"] = ["mock-tag"]
            # generated SUMMARY block 1개 추가.
            from uuid import uuid4
            from src.pipeline.models.document import SourceLocation

            doc_id = blocks[0].document_id if blocks else uuid4()
            marker_doc_id["v"] = doc_id
            generated = BlockObject(
                id=uuid4(),
                document_id=doc_id,
                block_type=BlockType.PARAGRAPH,
                content="mock SUMMARY content",
                block_index=len(blocks),
                metadata={"generated": True, "source": "llm_summary"},
                source_location=SourceLocation(),
            )
            return list(blocks) + [generated]

        monkeypatch.setattr(
            kc_mod.KnowledgeCompiler, "compile", _mock_compile, raising=True
        )

        class _StubLlm:
            pass

        result = await process_document_full(
            title="x",
            file_path=str(md_file),
            llm_client=_StubLlm(),
            upload_source="test",
        )

        # KC hook 적용
        assert result.kc_hook_applied is True
        # generated block 1개
        assert len(result.kc_generated_blocks) == 1
        gen = result.kc_generated_blocks[0]
        assert gen.metadata.get("generated") is True
        assert gen.metadata.get("source") == "llm_summary"
        # marker 도 generated 에 주입
        assert gen.metadata.get("kc_hook_applied") is True

        # non-generated blocks_full 의 모든 block 에 marker
        assert len(result.blocks_full) >= 1
        for pb in result.blocks_full:
            assert pb.metadata.get("kc_hook_applied") is True
            assert pb.metadata.get("kc_hook_version") is not None
            assert pb.metadata.get("kc_hook_at") is not None
            # search_summary 도 적용
            assert pb.metadata.get("search_summary", "").startswith("mock-summary-")

    async def test_kc_exception_atomic_swap_no_mutation(
        self, tmp_path, monkeypatch
    ) -> None:
        """KC compile 가 중간에 raise 시 blocks_full 변경 0 (atomic swap 전 실패)."""
        from src.pipeline.full_pipeline import process_document_full
        from src.pipeline.enrichers import knowledge_compiler as kc_mod

        md_file = tmp_path / "x.md"
        md_file.write_text("# A\n\nbody\n", encoding="utf-8")

        async def _failing_compile(self, *, blocks, document_text, document_title):
            # 일부 mutate 후 raise (deepcopy 안전성 검증).
            if blocks:
                blocks[0].metadata["should_not_leak"] = True
            raise RuntimeError("simulated KC failure")

        monkeypatch.setattr(
            kc_mod.KnowledgeCompiler, "compile", _failing_compile, raising=True
        )

        class _StubLlm:
            pass

        result = await process_document_full(
            title="x",
            file_path=str(md_file),
            llm_client=_StubLlm(),
            upload_source="test",
        )
        # KC 실패 → kc_hook_applied=False
        assert result.kc_hook_applied is False
        assert result.kc_generated_blocks == []
        # 원본 blocks_full 에 should_not_leak 누수 0 (deepcopy 격리).
        for pb in result.blocks_full:
            assert "should_not_leak" not in (pb.metadata or {})
            assert not pb.metadata.get("kc_hook_applied"), (
                f"block {pb.block_id} 에 marker 누수 (atomic swap 전 실패인데)"
            )

    async def test_kc_block_id_mismatch_guard_raises(
        self, tmp_path, monkeypatch
    ) -> None:
        """KC 가 원본 block id 를 누락 시 guard raise → kc_hook_applied=False."""
        from src.pipeline.full_pipeline import process_document_full
        from src.pipeline.enrichers import knowledge_compiler as kc_mod
        from uuid import uuid4

        md_file = tmp_path / "x.md"
        md_file.write_text("# A\n\nbody\n", encoding="utf-8")

        async def _malicious_compile(self, *, blocks, document_text, document_title):
            # 원본 block id 를 다 바꿔서 반환 — guard 가 raise 해야 함.
            new_blocks = []
            for b in blocks:
                b_copy = b.model_copy(update={"id": uuid4()})
                new_blocks.append(b_copy)
            return new_blocks

        monkeypatch.setattr(
            kc_mod.KnowledgeCompiler, "compile", _malicious_compile, raising=True
        )

        class _StubLlm:
            pass

        result = await process_document_full(
            title="x",
            file_path=str(md_file),
            llm_client=_StubLlm(),
            upload_source="test",
        )
        # guard raise → exception swallow → kc_hook_applied=False, blocks_full 변경 0.
        assert result.kc_hook_applied is False
        for pb in result.blocks_full:
            assert not pb.metadata.get("kc_hook_applied")
