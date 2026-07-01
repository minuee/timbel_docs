"""source_files 헬퍼 — MinIO 단일 원천 원본 저장/구체화 테스트.

로컬 폴백 모드 ObjectStore 를 싱글톤으로 주입해 MinIO 의존 없이 검증한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.pipeline.storage.source_files as sf
from src.pipeline.storage.object_store import ObjectStore


@pytest.fixture
def local_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ObjectStore:
    """로컬 폴백 ObjectStore 를 source_files 싱글톤으로 주입."""
    s = ObjectStore()
    s._use_local_fallback = True
    s._local_base = tmp_path / "aicm-storage"
    s._ensure_local_dirs()

    async def _get() -> ObjectStore:
        return s

    monkeypatch.setattr(sf, "_store", s)
    monkeypatch.setattr(sf, "get_object_store", _get)
    return s


# ---------------------------------------------------------------------------
# 순수 헬퍼
# ---------------------------------------------------------------------------

def test_build_source_key_adds_dot() -> None:
    assert sf.build_source_key("t1", "doc-1", "docx") == "t1/doc-1.docx"
    assert sf.build_source_key("t1", "doc-1", ".pdf") == "t1/doc-1.pdf"
    assert sf.build_source_key("t1", "doc-1", "") == "t1/doc-1"


def test_ext_from_prefers_filename() -> None:
    assert sf.ext_from("a.DOCX") == ".DOCX"
    assert sf.ext_from(None, "pdf") == ".pdf"
    assert sf.ext_from("noext", "docx") == ".docx"
    assert sf.ext_from(None, None) == ""


def test_looks_like_object_key() -> None:
    assert sf._looks_like_object_key("t1/doc-1.docx") is True
    assert sf._looks_like_object_key("/data/uploads/t1/x.docx") is False
    assert sf._looks_like_object_key("C:\\tmp\\x.docx") is False
    assert sf._looks_like_object_key("") is False
    assert sf._looks_like_object_key("plainname.docx") is False


# ---------------------------------------------------------------------------
# 저장 → 구체화 라운드트립
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_then_materialize_roundtrip(local_store: ObjectStore) -> None:
    data = b"PK\x03\x04 fake docx bytes"
    key = await sf.store_source_bytes("t1", "doc-9", data, ext=".docx")
    assert key == "t1/doc-9.docx"

    # object key 로 구체화 → 임시파일에 동일 바이트
    local_path, is_temp = await sf.materialize_source(key)
    try:
        assert is_temp is True
        assert Path(local_path).suffix == ".docx"
        assert Path(local_path).read_bytes() == data
    finally:
        sf.cleanup_temp(local_path, is_temp)
    assert not Path(local_path).exists()


@pytest.mark.asyncio
async def test_materialize_derives_key_from_ids(local_store: ObjectStore) -> None:
    data = b"%PDF-1.7 fake"
    await sf.store_source_bytes("t2", "doc-x", data, ext=".pdf")

    # source_ref 가 더 이상 존재하지 않는 legacy 로컬 경로여도 ids 로 키 파생
    local_path, is_temp = await sf.materialize_source(
        "/data/uploads/t2/repo/deadbeef_orig.pdf",
        tenant_id="t2",
        document_id="doc-x",
        ext=".pdf",
    )
    try:
        assert is_temp is True
        assert Path(local_path).read_bytes() == data
    finally:
        sf.cleanup_temp(local_path, is_temp)


@pytest.mark.asyncio
async def test_materialize_existing_local_path_used_as_is(
    local_store: ObjectStore, tmp_path: Path
) -> None:
    f = tmp_path / "real.docx"
    f.write_bytes(b"local")
    local_path, is_temp = await sf.materialize_source(str(f))
    assert is_temp is False
    assert local_path == str(f)
    # is_temp=False 면 cleanup 은 no-op
    sf.cleanup_temp(local_path, is_temp)
    assert f.exists()


@pytest.mark.asyncio
async def test_materialize_missing_raises(local_store: ObjectStore) -> None:
    with pytest.raises(FileNotFoundError):
        await sf.materialize_source("t1/does-not-exist.pdf")

    with pytest.raises(FileNotFoundError):
        # 로컬 부재 + key 미상 + ids 없음
        await sf.materialize_source("nonexistent-local-name")
