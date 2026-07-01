"""원본 파일(source file)의 MinIO 단일 원천(single source of truth) 헬퍼.

배경: KMS는 본래 업로드 원본을 로컬 FS(`/data/uploads`)에만 저장하고 워커가
같은 경로를 읽었다. docker 단일호스트(공유 volume)에선 동작하나, K8S(EKS)에선
api pod와 워커 pod가 분리돼 로컬 경로가 공유되지 않아 parsing 단계가
"원본 파일 없음"으로 실패한다.

해결: 원본을 **MinIO document_bucket 단일 원천**으로 저장한다.
- 쓰기: 업로드 수신 시 `store_source_bytes`로 `{tenant_id}/{document_id}{ext}` 키에 저장.
- 읽기: 워커/엔드포인트가 `materialize_source`로 로컬 임시파일에 내려받아 처리 후 폐기.
  로컬 경로가 실제로 존재하면(docker/legacy) 다운로드 없이 그대로 사용한다.

`source_file`(DB 컬럼) / `source_path`(이벤트 필드) 는 신규 업로드부터 이
**object key** 를 담는다. 기존 로컬 절대경로 값은 `materialize_source` 가
"로컬 존재 시 그대로" 분기로 하위호환 처리한다.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

import structlog

from src.pipeline.storage.config import StorageConfig
from src.pipeline.storage.object_store import ObjectStore

logger = structlog.get_logger(__name__)

# 워커/엔드포인트 프로세스당 ObjectStore 싱글톤 (init 1회).
_store: ObjectStore | None = None


async def get_object_store() -> ObjectStore:
    """초기화된 ObjectStore 싱글톤을 반환한다."""
    global _store
    if _store is None:
        cfg = StorageConfig()
        _store = ObjectStore(
            endpoint=cfg.MINIO_ENDPOINT,
            access_key=cfg.MINIO_ACCESS_KEY,
            secret_key=cfg.MINIO_SECRET_KEY,
            secure=cfg.MINIO_SECURE,
        )
        await _store.init()
    return _store


def build_source_key(tenant_id: str, document_id: str, ext: str = "") -> str:
    """원본 object key 를 생성한다: ``{tenant_id}/{document_id}{ext}``.

    `delete_document_objects` / `ObjectStore.upload_document` 와 동일 규약.

    Args:
        tenant_id: 테넌트 ID.
        document_id: 문서 ID.
        ext: 확장자(점 포함/미포함 모두 허용). 빈 값이면 확장자 없음.
    """
    if ext and not ext.startswith("."):
        ext = f".{ext}"
    return f"{tenant_id}/{document_id}{ext}"


def _looks_like_object_key(ref: str) -> bool:
    """문자열이 (로컬 절대경로가 아닌) MinIO object key 형태인지 판별.

    object key 규약은 ``{tenant}/{doc}{ext}`` — '/' 로 시작하지 않고 '\\' 를
    포함하지 않으며 드라이브 문자가 없다. OS 비의존으로 판별한다(워커=Linux,
    개발/테스트=Windows 양쪽에서 일관).
    """
    if not ref:
        return False
    # 로컬 경로 배제: POSIX 절대(/...), Windows(\\... 또는 역슬래시 포함, C:...)
    if ref.startswith("/") or ref.startswith("\\"):
        return False
    if "\\" in ref:
        return False
    if len(ref) >= 2 and ref[1] == ":":  # Windows drive 경로 (C:...)
        return False
    return "/" in ref


async def store_source_bytes(
    tenant_id: str,
    document_id: str,
    data: bytes,
    ext: str = "",
    content_type: str = "",
) -> str:
    """원본 바이트를 MinIO document_bucket 에 저장하고 object key 를 반환한다.

    Args:
        tenant_id: 테넌트 ID.
        document_id: 문서 ID.
        data: 원본 파일 바이트.
        ext: 확장자(예: ``.docx``).
        content_type: MIME 타입. 비면 확장자로 추정.

    Returns:
        저장된 object key (``source_file`` / 이벤트 ``source_path`` 에 기록).
    """
    store = await get_object_store()
    key = build_source_key(tenant_id, document_id, ext)
    if not content_type:
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    await store.upload_bytes(store.document_bucket, key, data, content_type=content_type)
    logger.info(
        "source_stored_minio",
        key=key,
        size_bytes=len(data),
        local_fallback=store.use_local_fallback,
    )
    return key


async def materialize_source(
    source_ref: str | None,
    *,
    tenant_id: str | None = None,
    document_id: str | None = None,
    ext: str = "",
) -> tuple[str, bool]:
    """원본을 로컬 경로로 구체화한다.

    우선순위:
    1. ``source_ref`` 가 실제 존재하는 로컬 파일이면 그대로 사용(docker/legacy).
    2. ``source_ref`` 가 object key 형태면 그 키로 MinIO 다운로드.
    3. 그 외(빈 값/존재하지 않는 legacy 경로)면 ``tenant_id``/``document_id``/``ext``
       로 canonical key 를 만들어 다운로드.

    Args:
        source_ref: ``source_file``/``source_path`` 값(object key 또는 로컬 경로).
        tenant_id: canonical key 파생용.
        document_id: canonical key 파생용.
        ext: canonical key 파생용 확장자.

    Returns:
        (local_path, is_temp). ``is_temp`` 가 True 면 호출자가 처리 후 삭제해야 함.

    Raises:
        FileNotFoundError: MinIO/로컬 어디에도 원본이 없을 때.
    """
    if source_ref and os.path.exists(source_ref):
        return source_ref, False

    if _looks_like_object_key(source_ref or ""):
        key = source_ref  # type: ignore[assignment]
    elif tenant_id and document_id:
        key = build_source_key(tenant_id, document_id, ext)
    else:
        raise FileNotFoundError(
            f"원본을 찾을 수 없습니다(로컬 부재, key 미상): ref={source_ref!r}"
        )

    store = await get_object_store()
    tmp_path = await store.download_to_temp(key)
    logger.debug("source_materialized", key=key, tmp_path=tmp_path)
    return tmp_path, True


def cleanup_temp(local_path: str, is_temp: bool) -> None:
    """materialize_source 가 만든 임시파일을 정리한다(is_temp=True 일 때만)."""
    if is_temp and local_path:
        try:
            os.unlink(local_path)
        except OSError:
            pass


def ext_from(filename: str | None, source_format: str | None = None) -> str:
    """파일명/포맷에서 확장자(점 포함)를 도출한다."""
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix
    if source_format:
        return f".{source_format.lstrip('.')}"
    return ""


__all__ = [
    "get_object_store",
    "build_source_key",
    "store_source_bytes",
    "materialize_source",
    "cleanup_temp",
    "ext_from",
]
