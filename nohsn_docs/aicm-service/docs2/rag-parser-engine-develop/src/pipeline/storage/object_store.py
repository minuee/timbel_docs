"""MinIO/S3 호환 오브젝트 스토리지 클라이언트.

버킷 구조:
- aicm-documents/       원본 문서 파일
- aicm-intermediate/    중간 처리 결과 (ParseResult JSON, 블럭 캐시)
- aicm-images/          추출된 이미지

MinIO SDK는 동기 전용이므로 asyncio.to_thread로 래핑한다.
MinIO 미접속 시 로컬 파일시스템으로 폴백한다.
"""

from __future__ import annotations

import asyncio
import io
import json
import mimetypes
import os
import shutil
import tempfile
from pathlib import Path

import structlog

from src.common.storage_tenant import (
    minio_key as _tenant_minio_key,
)
from src.pipeline.storage.config import StorageConfig, storage_config

try:
    from minio import Minio
    from minio.error import S3Error

    _MINIO_AVAILABLE = True
except ImportError:
    _MINIO_AVAILABLE = False

logger = structlog.get_logger(__name__)


class ObjectStore:
    """MinIO/S3 호환 오브젝트 스토리지 클라이언트.

    MinIO에 연결할 수 없으면 로컬 파일시스템으로 자동 폴백한다.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool | None = None,
        config: StorageConfig | None = None,
    ) -> None:
        """ObjectStore 초기화.

        Args:
            endpoint: MinIO 엔드포인트 (host:port).
            access_key: MinIO access key.
            secret_key: MinIO secret key.
            secure: TLS 사용 여부.
            config: StorageConfig 인스턴스. 개별 파라미터보다 우선하지 않음.
        """
        cfg = config or storage_config
        self._endpoint = endpoint or cfg.MINIO_ENDPOINT
        self._access_key = access_key or cfg.MINIO_ACCESS_KEY
        self._secret_key = secret_key or cfg.MINIO_SECRET_KEY
        self._secure = secure if secure is not None else cfg.MINIO_SECURE

        self._document_bucket = cfg.MINIO_DOCUMENT_BUCKET
        self._intermediate_bucket = cfg.MINIO_INTERMEDIATE_BUCKET
        self._image_bucket = cfg.MINIO_IMAGE_BUCKET

        self._client: Minio | None = None
        self._use_local_fallback = False
        self._local_base = Path(tempfile.gettempdir()) / "aicm-storage"

    @property
    def document_bucket(self) -> str:
        """원본 문서 버킷명."""
        return self._document_bucket

    @property
    def use_local_fallback(self) -> bool:
        """MinIO 미접속으로 로컬 폴백 중인지 여부."""
        return self._use_local_fallback

    # ------------------------------------------------------------------
    # 초기화
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """버킷 생성 (없으면). 앱 시작 시 1회 호출."""
        if not _MINIO_AVAILABLE:
            logger.warning(
                "minio 패키지 미설치. 로컬 파일시스템 폴백 사용.",
                fallback_path=str(self._local_base),
            )
            self._use_local_fallback = True
            self._ensure_local_dirs()
            return

        try:
            self._client = Minio(
                self._endpoint,
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=self._secure,
            )
            for bucket in [
                self._document_bucket,
                self._intermediate_bucket,
                self._image_bucket,
            ]:
                exists = await asyncio.to_thread(self._client.bucket_exists, bucket)
                if not exists:
                    await asyncio.to_thread(self._client.make_bucket, bucket)
                    logger.info("버킷 생성 완료", bucket=bucket)
                else:
                    logger.debug("버킷 이미 존재", bucket=bucket)

            logger.info("MinIO 연결 성공", endpoint=self._endpoint)

        except Exception as exc:
            logger.warning(
                "MinIO 연결 실패. 로컬 파일시스템 폴백 사용.",
                endpoint=self._endpoint,
                error=str(exc),
                fallback_path=str(self._local_base),
            )
            self._client = None
            self._use_local_fallback = True
            self._ensure_local_dirs()

    def _ensure_local_dirs(self) -> None:
        """로컬 폴백용 디렉토리 생성."""
        for bucket in [
            self._document_bucket,
            self._intermediate_bucket,
            self._image_bucket,
        ]:
            (self._local_base / bucket).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 문서 업로드/다운로드
    # ------------------------------------------------------------------

    async def upload_document(
        self,
        tenant_id: str,
        document_id: str,
        file_path: str,
        content_type: str = "",
    ) -> str:
        """로컬 파일을 MinIO에 업로드.

        Args:
            tenant_id: 테넌트 ID.
            document_id: 문서 ID.
            file_path: 로컬 파일 경로.
            content_type: MIME 타입. 비어있으면 자동 감지.

        Returns:
            object key (버킷 내 경로).
        """
        if not content_type:
            content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        ext = Path(file_path).suffix
        object_key = f"{tenant_id}/{document_id}{ext}"

        if self._use_local_fallback:
            return await self._local_upload_file(
                self._document_bucket, object_key, file_path
            )

        await asyncio.to_thread(
            self._client.fput_object,  # type: ignore[union-attr]
            self._document_bucket,
            object_key,
            file_path,
            content_type=content_type,
        )
        logger.info(
            "문서 업로드 완료",
            bucket=self._document_bucket,
            key=object_key,
            size_mb=round(os.path.getsize(file_path) / 1024 / 1024, 2),
        )
        return object_key

    async def download_to_temp(self, object_key: str) -> str:
        """MinIO에서 임시 파일로 다운로드.

        Args:
            object_key: 오브젝트 키 (버킷 내 경로).

        Returns:
            임시 파일 경로.
        """
        ext = Path(object_key).suffix
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="aicm_")
        os.close(tmp_fd)

        if self._use_local_fallback:
            src = self._local_base / self._document_bucket / object_key
            if src.exists():
                shutil.copy2(str(src), tmp_path)
            else:
                raise FileNotFoundError(f"로컬 폴백 파일 없음: {src}")
            return tmp_path

        await asyncio.to_thread(
            self._client.fget_object,  # type: ignore[union-attr]
            self._document_bucket,
            object_key,
            tmp_path,
        )
        logger.debug("임시 파일 다운로드 완료", key=object_key, tmp_path=tmp_path)
        return tmp_path

    # ------------------------------------------------------------------
    # 바이트 업로드/다운로드
    # ------------------------------------------------------------------

    async def upload_bytes(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        """바이트 데이터 업로드.

        Args:
            bucket: 대상 버킷.
            key: 오브젝트 키.
            data: 바이트 데이터.
            content_type: MIME 타입.
        """
        if self._use_local_fallback:
            dest = self._local_base / bucket / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return

        stream = io.BytesIO(data)
        await asyncio.to_thread(
            self._client.put_object,  # type: ignore[union-attr]
            bucket,
            key,
            stream,
            length=len(data),
            content_type=content_type,
        )

    async def download_bytes(
        self,
        bucket: str,
        key: str,
    ) -> bytes | None:
        """바이트 데이터 다운로드. 없으면 None.

        Args:
            bucket: 대상 버킷.
            key: 오브젝트 키.

        Returns:
            바이트 데이터 또는 None.
        """
        if self._use_local_fallback:
            src = self._local_base / bucket / key
            if src.exists():
                return src.read_bytes()
            return None

        try:
            response = await asyncio.to_thread(
                self._client.get_object,  # type: ignore[union-attr]
                bucket,
                key,
            )
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:
            if _MINIO_AVAILABLE and isinstance(exc, S3Error) and exc.code == "NoSuchKey":
                return None
            logger.warning("오브젝트 다운로드 실패", bucket=bucket, key=key, error=str(exc))
            return None

    # ------------------------------------------------------------------
    # 중간 처리 결과 (intermediate)
    # ------------------------------------------------------------------

    async def save_intermediate(
        self,
        document_id: str,
        stage: str,
        data: dict,
        tenant_id: str | None = None,
    ) -> None:
        """중간 처리 결과를 JSON으로 저장.

        Args:
            document_id: 문서 ID.
            stage: 처리 단계 ("parsed", "blocked", "enriched").
            data: 저장할 딕셔너리 데이터.
            tenant_id: 테넌트 ID (Phase 2.7 격리). 제공 시 key 에
                ``{tenant_id}/`` prefix. None 이면 기존 legacy key 사용
                (backward compat).
        """
        if tenant_id:
            key = _tenant_minio_key(tenant_id, document_id, f"{stage}.json")
        else:
            key = f"{document_id}/{stage}.json"
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        await self.upload_bytes(
            self._intermediate_bucket,
            key,
            payload,
            content_type="application/json",
        )
        logger.debug(
            "중간 결과 저장",
            document_id=document_id,
            stage=stage,
            size=len(payload),
            tenant_scoped=bool(tenant_id),
        )

    async def load_intermediate(
        self,
        document_id: str,
        stage: str,
        tenant_id: str | None = None,
    ) -> dict | None:
        """중간 처리 결과 로드. 없으면 None (재처리 필요).

        tenant_id 가 제공되면 tenant-scoped key 를 먼저 시도하고, miss 시 legacy
        key 로 fallback (운영 중 마이그레이션 호환).

        Args:
            document_id: 문서 ID.
            stage: 처리 단계.
            tenant_id: 테넌트 ID (Phase 2.7 격리). 선택.

        Returns:
            딕셔너리 데이터 또는 None.
        """
        raw: bytes | None = None
        if tenant_id:
            scoped_key = _tenant_minio_key(tenant_id, document_id, f"{stage}.json")
            raw = await self.download_bytes(self._intermediate_bucket, scoped_key)
        if raw is None:
            legacy_key = f"{document_id}/{stage}.json"
            raw = await self.download_bytes(self._intermediate_bucket, legacy_key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("중간 결과 JSON 파싱 실패", document_id=document_id, stage=stage)
            return None

    # ------------------------------------------------------------------
    # 체크포인트
    # ------------------------------------------------------------------

    async def save_checkpoint(
        self,
        document_id: str,
        checkpoint: dict,
        tenant_id: str | None = None,
    ) -> None:
        """처리 체크포인트 저장 (현재 페이지, 블럭 수 등).

        Args:
            document_id: 문서 ID.
            checkpoint: 체크포인트 데이터.
            tenant_id: 테넌트 ID (Phase 2.7 격리). 선택.
        """
        if tenant_id:
            key = _tenant_minio_key(tenant_id, document_id, "checkpoint.json")
        else:
            key = f"{document_id}/checkpoint.json"
        payload = json.dumps(checkpoint, ensure_ascii=False, default=str).encode("utf-8")
        await self.upload_bytes(
            self._intermediate_bucket,
            key,
            payload,
            content_type="application/json",
        )
        logger.debug("체크포인트 저장", document_id=document_id, tenant_scoped=bool(tenant_id))

    async def load_checkpoint(
        self,
        document_id: str,
        tenant_id: str | None = None,
    ) -> dict | None:
        """체크포인트 로드. 없으면 None (처음부터 처리).

        tenant_id 가 제공되면 tenant-scoped key 를 먼저 시도하고, miss 시
        legacy key 로 fallback.

        Args:
            document_id: 문서 ID.
            tenant_id: 테넌트 ID (Phase 2.7 격리). 선택.

        Returns:
            체크포인트 딕셔너리 또는 None.
        """
        raw: bytes | None = None
        if tenant_id:
            scoped_key = _tenant_minio_key(tenant_id, document_id, "checkpoint.json")
            raw = await self.download_bytes(self._intermediate_bucket, scoped_key)
        if raw is None:
            legacy_key = f"{document_id}/checkpoint.json"
            raw = await self.download_bytes(self._intermediate_bucket, legacy_key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("체크포인트 JSON 파싱 실패", document_id=document_id)
            return None

    # ------------------------------------------------------------------
    # 정리
    # ------------------------------------------------------------------

    async def delete_intermediate(
        self,
        document_id: str,
        tenant_id: str | None = None,
    ) -> None:
        """문서의 모든 중간 데이터 삭제 (처리 완료 후).

        tenant_id 가 제공되면 ``{tenant_id}/{document_id}/`` prefix 도 삭제.
        legacy prefix (``{document_id}/``) 는 항상 함께 삭제하여 마이그레이션
        잔존 파일도 정리.

        Args:
            document_id: 문서 ID.
            tenant_id: 테넌트 ID (Phase 2.7 격리). 선택.
        """
        prefixes: list[str] = []
        if tenant_id:
            prefixes.append(f"{tenant_id}/{document_id}/")
        prefixes.append(f"{document_id}/")

        if self._use_local_fallback:
            for prefix in prefixes:
                target = self._local_base / self._intermediate_bucket / prefix.rstrip("/")
                if target.exists():
                    shutil.rmtree(str(target))
                    logger.debug(
                        "중간 데이터 로컬 삭제", document_id=document_id, prefix=prefix
                    )
            return

        total_deleted = 0
        try:
            for prefix in prefixes:
                objects = await asyncio.to_thread(
                    lambda p=prefix: list(
                        self._client.list_objects(  # type: ignore[union-attr]
                            self._intermediate_bucket,
                            prefix=p,
                            recursive=True,
                        )
                    )
                )
                for obj in objects:
                    await asyncio.to_thread(
                        self._client.remove_object,  # type: ignore[union-attr]
                        self._intermediate_bucket,
                        obj.object_name,
                    )
                total_deleted += len(objects)
            logger.info(
                "중간 데이터 삭제 완료",
                document_id=document_id,
                deleted_count=total_deleted,
                tenant_scoped=bool(tenant_id),
            )
        except Exception as exc:
            logger.warning(
                "중간 데이터 삭제 실패", document_id=document_id, error=str(exc)
            )

    async def _delete_objects_by_prefix(
        self,
        bucket: str,
        prefixes: list[str],
    ) -> int:
        """버킷에서 prefix 목록에 매칭되는 모든 object 를 삭제하고 삭제 수를 반환.

        파일형 prefix(``{tenant}/{doc}`` → ``{tenant}/{doc}.docx``)와
        디렉토리형 prefix(``{tenant}/{doc}/`` → 이미지들) 를 모두 처리한다.
        """
        if self._use_local_fallback:
            for prefix in prefixes:
                target = self._local_base / bucket / prefix.rstrip("/")
                if target.is_dir():
                    shutil.rmtree(str(target), ignore_errors=True)
                elif target.parent.exists():
                    for f in target.parent.glob(target.name + "*"):
                        try:
                            f.unlink()
                        except OSError:
                            pass
            return 0

        total = 0
        try:
            for prefix in prefixes:
                objects = await asyncio.to_thread(
                    lambda p=prefix: list(
                        self._client.list_objects(  # type: ignore[union-attr]
                            bucket, prefix=p, recursive=True
                        )
                    )
                )
                for obj in objects:
                    await asyncio.to_thread(
                        self._client.remove_object,  # type: ignore[union-attr]
                        bucket,
                        obj.object_name,
                    )
                total += len(objects)
        except Exception as exc:
            logger.warning(
                "object_prefix_delete_failed", bucket=bucket, error=str(exc)
            )
        return total

    async def delete_document_objects(
        self,
        document_id: str,
        tenant_id: str | None = None,
    ) -> None:
        """문서의 모든 MinIO object(원본+이미지+중간물)를 완전 삭제한다.

        문서 삭제 시 호출. 복원 UI 가 없어 hard delete 가 맞다(2026-06-16 결정).
        향후 복원 기능 도입 시 휴지통/retention 패턴으로 전환 필요.
        object key 규약: document=``{tenant}/{doc}{ext}``,
        image/intermediate=``{tenant}/{doc}/...`` (legacy: tenant prefix 없음).
        """
        # 1) 중간 산출물
        await self.delete_intermediate(document_id, tenant_id)

        # 2) 원본 문서 (document_bucket)
        doc_prefixes: list[str] = []
        if tenant_id:
            doc_prefixes.append(f"{tenant_id}/{document_id}")
        doc_prefixes.append(f"{document_id}")
        n_doc = await self._delete_objects_by_prefix(self._document_bucket, doc_prefixes)

        # 3) 이미지 (image_bucket)
        img_prefixes: list[str] = []
        if tenant_id:
            img_prefixes.append(f"{tenant_id}/{document_id}/")
        img_prefixes.append(f"{document_id}/")
        n_img = await self._delete_objects_by_prefix(self._image_bucket, img_prefixes)

        logger.info(
            "document_objects_deleted",
            document_id=document_id,
            documents=n_doc,
            images=n_img,
            tenant_scoped=bool(tenant_id),
        )

    # ------------------------------------------------------------------
    # 이미지
    # ------------------------------------------------------------------

    async def upload_image(
        self,
        document_id: str,
        image_name: str,
        image_data: bytes,
        tenant_id: str | None = None,
    ) -> str:
        """추출 이미지를 MinIO에 저장.

        Args:
            document_id: 문서 ID.
            image_name: 이미지 파일명.
            image_data: 이미지 바이트 데이터.
            tenant_id: 테넌트 ID (Phase 2.7 격리). 제공 시 key 에
                ``{tenant_id}/`` prefix.

        Returns:
            object key (버킷 내 경로).
        """
        if tenant_id:
            key = _tenant_minio_key(tenant_id, document_id, image_name)
        else:
            key = f"{document_id}/{image_name}"
        content_type = mimetypes.guess_type(image_name)[0] or "image/png"

        await self.upload_bytes(
            self._image_bucket,
            key,
            image_data,
            content_type=content_type,
        )
        logger.debug(
            "이미지 업로드 완료",
            document_id=document_id,
            image=image_name,
            size_kb=round(len(image_data) / 1024, 1),
            tenant_scoped=bool(tenant_id),
        )
        return key

    # ------------------------------------------------------------------
    # 로컬 폴백 헬퍼
    # ------------------------------------------------------------------

    async def _local_upload_file(
        self,
        bucket: str,
        key: str,
        file_path: str,
    ) -> str:
        """로컬 폴백: 파일 복사."""
        dest = self._local_base / bucket / key
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _copy() -> None:
            shutil.copy2(file_path, str(dest))

        await asyncio.to_thread(_copy)
        logger.debug("로컬 폴백 파일 업로드", bucket=bucket, key=key)
        return key
