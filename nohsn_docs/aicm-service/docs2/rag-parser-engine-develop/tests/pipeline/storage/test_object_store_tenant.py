"""Phase 2.7 — ObjectStore tenant 격리 회귀 테스트.

ObjectStore 의 ``save_intermediate``, ``save_checkpoint``, ``upload_image`` 메서드가
tenant_id 인자 제공 시 ``{tenant_id}/{document_id}/...`` prefix 를 생성하는지,
미제공 시 legacy ``{document_id}/...`` prefix 로 회귀 호환되는지 검증한다.

로컬 폴백 모드 (`_use_local_fallback=True`) 로 강제하여 MinIO 의존성 없이 테스트.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.pipeline.storage.object_store import ObjectStore


@pytest.fixture
def store(tmp_path: Path) -> ObjectStore:
    """로컬 폴백 모드의 ObjectStore — MinIO 의존 없음."""
    s = ObjectStore()
    s._use_local_fallback = True
    s._local_base = tmp_path / "aicm-storage"
    s._ensure_local_dirs()
    return s


# ---------------------------------------------------------------------------
# save_intermediate / load_intermediate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_intermediate_with_tenant_creates_scoped_key(
    store: ObjectStore, tmp_path: Path
) -> None:
    await store.save_intermediate(
        document_id="doc-42",
        stage="parsed",
        data={"text": "hello"},
        tenant_id="t1",
    )
    # 로컬 폴백 — {bucket}/{tenant_id}/{doc_id}/{stage}.json 경로에 저장됨.
    expected = (
        store._local_base
        / store._intermediate_bucket
        / "t1"
        / "doc-42"
        / "parsed.json"
    )
    assert expected.exists()


@pytest.mark.asyncio
async def test_save_intermediate_without_tenant_uses_legacy_key(
    store: ObjectStore, tmp_path: Path
) -> None:
    await store.save_intermediate(
        document_id="doc-42",
        stage="parsed",
        data={"text": "hello"},
    )
    expected = (
        store._local_base
        / store._intermediate_bucket
        / "doc-42"
        / "parsed.json"
    )
    assert expected.exists()


@pytest.mark.asyncio
async def test_load_intermediate_prefers_tenant_scoped(
    store: ObjectStore,
) -> None:
    # 두 위치 모두에 다른 데이터를 저장한 뒤, tenant_id 제공 시 scoped 가 우선.
    await store.save_intermediate(
        document_id="doc-42", stage="parsed", data={"v": "legacy"}
    )
    await store.save_intermediate(
        document_id="doc-42",
        stage="parsed",
        data={"v": "scoped"},
        tenant_id="t1",
    )
    got = await store.load_intermediate("doc-42", "parsed", tenant_id="t1")
    assert got == {"v": "scoped"}


@pytest.mark.asyncio
async def test_load_intermediate_falls_back_to_legacy(
    store: ObjectStore,
) -> None:
    # tenant-scoped 가 없을 때 legacy 위치에서 fallback 으로 로드.
    await store.save_intermediate(
        document_id="doc-42", stage="parsed", data={"v": "legacy"}
    )
    got = await store.load_intermediate("doc-42", "parsed", tenant_id="t1")
    assert got == {"v": "legacy"}


@pytest.mark.asyncio
async def test_load_intermediate_missing_returns_none(
    store: ObjectStore,
) -> None:
    got = await store.load_intermediate("doc-99", "parsed", tenant_id="t1")
    assert got is None


@pytest.mark.asyncio
async def test_cross_tenant_intermediate_isolation(
    store: ObjectStore,
) -> None:
    # 동일 document_id 라도 tenant 가 다르면 데이터가 섞이지 않아야 함.
    await store.save_intermediate(
        document_id="doc-42",
        stage="parsed",
        data={"owner": "t1"},
        tenant_id="t1",
    )
    await store.save_intermediate(
        document_id="doc-42",
        stage="parsed",
        data={"owner": "t2"},
        tenant_id="t2",
    )
    t1_got = await store.load_intermediate("doc-42", "parsed", tenant_id="t1")
    t2_got = await store.load_intermediate("doc-42", "parsed", tenant_id="t2")
    assert t1_got == {"owner": "t1"}
    assert t2_got == {"owner": "t2"}


# ---------------------------------------------------------------------------
# save_checkpoint / load_checkpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkpoint_tenant_scoped(store: ObjectStore) -> None:
    await store.save_checkpoint(
        document_id="doc-42",
        checkpoint={"page": 5},
        tenant_id="t1",
    )
    got = await store.load_checkpoint("doc-42", tenant_id="t1")
    assert got == {"page": 5}


@pytest.mark.asyncio
async def test_checkpoint_legacy_compat(store: ObjectStore) -> None:
    # tenant_id 없이 저장된 legacy checkpoint 도 tenant 인자와 함께 로드 가능.
    await store.save_checkpoint(document_id="doc-42", checkpoint={"page": 10})
    got = await store.load_checkpoint("doc-42", tenant_id="t1")
    assert got == {"page": 10}


# ---------------------------------------------------------------------------
# upload_image
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_image_tenant_scoped(store: ObjectStore) -> None:
    key = await store.upload_image(
        document_id="doc-42",
        image_name="page1.png",
        image_data=b"fake-png",
        tenant_id="t1",
    )
    assert key == "t1/doc-42/page1.png"
    saved = store._local_base / store._image_bucket / "t1" / "doc-42" / "page1.png"
    assert saved.exists()
    assert saved.read_bytes() == b"fake-png"


@pytest.mark.asyncio
async def test_upload_image_legacy_key(store: ObjectStore) -> None:
    key = await store.upload_image(
        document_id="doc-42",
        image_name="page1.png",
        image_data=b"fake-png",
    )
    assert key == "doc-42/page1.png"
    saved = store._local_base / store._image_bucket / "doc-42" / "page1.png"
    assert saved.exists()


# ---------------------------------------------------------------------------
# delete_intermediate — tenant + legacy 모두 정리
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_intermediate_clears_both_prefixes(store: ObjectStore) -> None:
    await store.save_intermediate(
        document_id="doc-42", stage="parsed", data={"v": "legacy"}
    )
    await store.save_intermediate(
        document_id="doc-42",
        stage="parsed",
        data={"v": "scoped"},
        tenant_id="t1",
    )
    await store.delete_intermediate("doc-42", tenant_id="t1")

    legacy = (
        store._local_base
        / store._intermediate_bucket
        / "doc-42"
        / "parsed.json"
    )
    scoped = (
        store._local_base
        / store._intermediate_bucket
        / "t1"
        / "doc-42"
        / "parsed.json"
    )
    assert not legacy.exists()
    assert not scoped.exists()
