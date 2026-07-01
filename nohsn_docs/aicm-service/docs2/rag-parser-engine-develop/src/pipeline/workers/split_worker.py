"""Split Worker — 대용량 PDF를 페이지 범위별로 분할.

parse_worker가 >20 페이지 PDF를 감지하면 DocumentSplitEvent를 발행하고,
이 워커가 소비하여 sub-PDF를 생성 → MinIO에 업로드 → 파트별 이벤트 발행.
"""

from __future__ import annotations

import io
from typing import Any
from uuid import uuid4

from src.common.constants import TOPIC_DOCUMENT_PART_READY
from src.common.logging import get_logger
from src.pipeline.models.events import DocumentPartReadyEvent, DocumentSplitEvent
from src.pipeline.processing.split_tracker import SplitJob, SplitTracker
from src.pipeline.storage.config import StorageConfig
from src.pipeline.storage.object_store import ObjectStore

log = get_logger(__name__)

_SPLIT_BATCH_SIZE = 20  # 페이지/파트


def calculate_page_ranges(total_pages: int, batch_size: int = _SPLIT_BATCH_SIZE) -> list[list[int]]:
    """총 페이지 수를 기반으로 페이지 범위 목록을 계산한다.

    Returns:
        [[1, 20], [21, 40], [41, 55]] 형태
    """
    ranges: list[list[int]] = []
    for start in range(1, total_pages + 1, batch_size):
        end = min(start + batch_size - 1, total_pages)
        ranges.append([start, end])
    return ranges


async def handle_document_split(
    event: DocumentSplitEvent,
    producer: Any,
) -> None:
    """대용량 문서를 파트별로 분할하고 각 파트 이벤트를 발행한다."""
    doc_id = str(event.document_id)
    log.info(
        "split_worker_start",
        document_id=doc_id,
        total_pages=event.total_pages,
        total_parts=event.total_parts,
    )

    # 1) ObjectStore 초기화
    cfg = StorageConfig()
    store = ObjectStore(
        endpoint=cfg.MINIO_ENDPOINT,
        access_key=cfg.MINIO_ACCESS_KEY,
        secret_key=cfg.MINIO_SECRET_KEY,
        secure=cfg.MINIO_SECURE,
    )
    await store.init()

    # 2) 원본 PDF 로드 (MinIO 또는 로컬)
    pdf_bytes: bytes | None = None
    if event.minio_source_key:
        pdf_bytes = await store.download_bytes(
            cfg.MINIO_DOCUMENT_BUCKET, event.minio_source_key
        )
    if pdf_bytes is None and event.source_path:
        import os
        if os.path.exists(event.source_path):
            with open(event.source_path, "rb") as f:
                pdf_bytes = f.read()

    if pdf_bytes is None:
        log.error("split_worker_no_source", document_id=doc_id)
        return

    # 3) pypdfium2로 페이지별 분할
    try:
        import pypdfium2 as pdfium
    except ImportError:
        log.error("pypdfium2_not_installed")
        return

    src_pdf = pdfium.PdfDocument(pdf_bytes)

    # 4) SplitJob 생성
    tracker = SplitTracker()
    job = SplitJob(
        document_id=event.document_id,
        tenant_id=event.tenant_id,
        repository_id=event.repository_id,
        total_parts=event.total_parts,
        page_ranges=event.page_ranges,
        minio_source_key=event.minio_source_key,
        source_path=event.source_path,
        status="processing",
    )
    await tracker.create_job(job)

    # 5) 매니페스트 저장
    await store.save_intermediate(
        doc_id,
        "split/manifest",
        job.model_dump(mode="json"),
    )

    # 6) 각 파트를 sub-PDF로 분할 → MinIO 업로드 → 이벤트 발행
    for i, page_range in enumerate(event.page_ranges):
        page_start, page_end = page_range[0], page_range[1]
        part_key = f"{doc_id}/split/part_{i:03d}.pdf"

        try:
            # pypdfium2로 페이지 범위 추출 (0-based index)
            new_pdf = pdfium.PdfDocument.new()
            page_indices = list(range(page_start - 1, page_end))
            new_pdf.import_pages(src_pdf, page_indices)

            buf = io.BytesIO()
            new_pdf.save(buf)
            part_bytes = buf.getvalue()
            new_pdf.close()

            # MinIO에 업로드
            await store.upload_bytes(
                cfg.MINIO_INTERMEDIATE_BUCKET,
                part_key,
                part_bytes,
                content_type="application/pdf",
            )

            # 파트 이벤트 발행
            part_event = DocumentPartReadyEvent(
                event_id=uuid4(),
                document_id=event.document_id,
                part_id=uuid4(),
                tenant_id=event.tenant_id,
                repository_id=event.repository_id,
                part_index=i,
                total_parts=event.total_parts,
                page_start=page_start,
                page_end=page_end,
                minio_part_key=part_key,
                difficulty=event.difficulty,
                document_type=event.document_type,
                document_structure=event.document_structure,
                source_path=event.source_path,
            )

            await producer.send_and_wait(
                TOPIC_DOCUMENT_PART_READY,
                value=part_event.model_dump_json().encode(),
            )

            log.info(
                "split_part_created",
                document_id=doc_id,
                part_index=i,
                pages=f"{page_start}-{page_end}",
                size_kb=len(part_bytes) // 1024,
            )

        except Exception as exc:
            log.error(
                "split_part_failed",
                document_id=doc_id,
                part_index=i,
                error=str(exc),
            )
            await tracker.mark_part_failed(event.document_id, i)

    src_pdf.close()
    await tracker.close()

    log.info(
        "split_worker_complete",
        document_id=doc_id,
        total_parts=event.total_parts,
    )
