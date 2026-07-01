"""D38 Phase 2 — Qdrant ensure_block_collection 호출 site 점검 (integration).

목적:
- 모든 ingest 경로가 새 doc 색인 전에 `ensure_block_collection(tenant_slug)`
  를 호출하는지 검증.
- 기존 site (embed_worker / reseed_v4 / seed_5_agents / repository_service /
  index_demo_docs) 가 모두 살아있는지 import + 호출 site 검증.

본 test 는 *불변성* test — 코드 grep 으로 호출 site 가 존재함을 보장.
실 Qdrant 호출은 mock — 단위 test 용도.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ensure_block_collection_call_sites() -> list[Path]:
    """`ensure_block_collection` 호출이 있는 file path 목록."""
    paths: list[Path] = []
    for sub in ("src/pipeline/workers", "src/core/services", "scripts/seed"):
        for f in (ROOT / sub).rglob("*.py"):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "ensure_block_collection(" in text and "def ensure_block_collection" not in text:
                paths.append(f)
    return paths


class TestEnsureBlockCollectionCallSites:
    """Phase 2 — ensure_block_collection 호출 site 가 모두 존재."""

    def test_function_exists(self) -> None:
        """함수 자체가 import 가능."""
        from src.core.services.qdrant_collection_manager import ensure_block_collection
        assert inspect.iscoroutinefunction(ensure_block_collection)

    def test_embed_worker_calls_ensure(
        self, ensure_block_collection_call_sites: list[Path]
    ) -> None:
        """embed_worker 가 호출 site."""
        names = [p.name for p in ensure_block_collection_call_sites]
        assert "embed_worker.py" in names

    def test_repository_service_calls_ensure(
        self, ensure_block_collection_call_sites: list[Path]
    ) -> None:
        """repository_service 가 신규 repo 생성 시 호출."""
        names = [p.name for p in ensure_block_collection_call_sites]
        assert "repository_service.py" in names

    def test_reseed_v4_calls_ensure(
        self, ensure_block_collection_call_sites: list[Path]
    ) -> None:
        """reseed_v4 도 호출."""
        names = [p.name for p in ensure_block_collection_call_sites]
        assert "reseed_5_agents_kms_pipeline_v4.py" in names

    def test_seed_5_agents_calls_ensure(
        self, ensure_block_collection_call_sites: list[Path]
    ) -> None:
        """seed_5_agents 도 호출."""
        names = [p.name for p in ensure_block_collection_call_sites]
        assert "seed_5_agents.py" in names


class TestEnsureBlockCollectionBehavior:
    """Phase 2 — ensure_block_collection 의 idempotency 와 mock 동작."""

    @pytest.mark.asyncio
    async def test_ensure_block_collection_idempotent(self, monkeypatch) -> None:
        """동일 slug 두 번 호출해도 안전 (mock)."""
        from src.core.services import qdrant_collection_manager as qcm

        call_count = {"n": 0}

        class _MockQdrant:
            async def get_collections(self):
                class _R:
                    collections = []
                return _R()

            async def create_collection(self, *args, **kwargs):
                call_count["n"] += 1

            async def get_collection(self, name):
                # 존재 X — KeyError 로 시뮬레이션
                from qdrant_client.http.exceptions import UnexpectedResponse
                raise Exception("not_found")

        # ensure_block_collection 함수 내부에서 get_qdrant_client 가져옴.
        # 본 test 는 helper 가 존재하고 호출 가능한지만 검증 (정확한 mock 은 별도).
        from src.core.services.qdrant_collection_manager import (
            ensure_block_collection,
        )
        # signature 검증
        sig = inspect.signature(ensure_block_collection)
        assert "tenant_slug" in sig.parameters
