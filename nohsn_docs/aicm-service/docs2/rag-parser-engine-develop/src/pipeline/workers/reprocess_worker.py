"""Reprocess Worker -- 문서 재처리 (기존 청크 삭제 -> 새 파이프라인 실행).

Phase 2 Task B-8.
"""

from __future__ import annotations

import time
from typing import Any, Optional
from uuid import UUID, uuid4

from src.common.constants import (
    QDRANT_COLLECTION_PREFIX,
    TOPIC_DOCUMENT_FAILED,
    TOPIC_DOCUMENT_INDEXED,
)
from src.common.logging import get_logger
from src.pipeline.chunkers.semantic import SemanticChunker
from src.pipeline.chunkers.strategy import ChunkStrategySelector
from src.pipeline.chunkers.table_chunker import TableChunker
from src.pipeline.embedders.batch import BatchEmbeddingProcessor
from src.pipeline.embedders.bge_m3 import BGEM3Embedder
from src.pipeline.models.document import (
    ChunkObject,
    DocumentObject,
    ProcessingConfig,
)
from src.pipeline.models.events import DocumentIndexedEvent
from src.pipeline.models.parse_result import ParseResult, TableContent
from src.pipeline.parsers.router import detect_format, select_parser

log = get_logger(__name__)


async def handle_reprocess(
    document_id: UUID,
    tenant_id: UUID,
    repository_id: UUID,
    source_path: str,
    config: ProcessingConfig | None = None,
    qdrant_client: Optional[Any] = None,
    producer: Optional[object] = None,
) -> dict[str, Any]:
    """문서를 재처리한다.

    1. 기존 Qdrant 청크 삭제
    2. 파서 실행
    3. 청킹 전략 선택 + 실행
    4. LLM 보강 (contextual retrieval, metadata extraction)
    5. 임베딩 + Qdrant upsert
    6. 결과 이벤트 발행

    Parameters
    ----------
    document_id : UUID
    tenant_id : UUID
    repository_id : UUID
    source_path : str
        원본 파일 경로
    config : ProcessingConfig | None
    qdrant_client : Qdrant 클라이언트 (옵션)
    producer : Kafka producer (옵션)

    Returns
    -------
    dict
        재처리 결과 요약
    """
    start = time.monotonic()
    proc_config = config or ProcessingConfig()

    log.info(
        "reprocess_start",
        document_id=str(document_id),
        source_path=source_path,
    )

    # 1) 기존 청크 삭제
    collection_name = _build_collection_name(str(tenant_id), str(repository_id))
    deleted_count = await _delete_existing_chunks(
        qdrant_client, collection_name, str(document_id)
    )

    # 2) 파서 실행
    detected_format = detect_format(source_path)
    parser = select_parser(detected_format, source_path)
    parse_result: ParseResult = await parser.parse()

    # 3) 청킹 실행
    all_chunks: list[ChunkObject] = []

    # 텍스트 청킹
    chunker = SemanticChunker(proc_config)
    text_chunks = await chunker.chunk(
        parse_result.pages,
        source_file_path=parse_result.source_file_path,
        source_file_url=f"/repos/{repository_id}/docs/{document_id}",
        document_id=str(document_id),
    )
    all_chunks.extend(text_chunks)

    # 표 청킹 (Table 3-Layer)
    if parse_result.tables:
        table_chunker = TableChunker(proc_config)
        for table in parse_result.tables:
            table_chunks = await table_chunker.chunk(
                table,
                document_id=str(document_id),
                source_file_path=parse_result.source_file_path,
            )
            all_chunks.extend(table_chunks)

    if not all_chunks:
        log.warning("reprocess_no_chunks", document_id=str(document_id))
        return {
            "document_id": str(document_id),
            "status": "no_chunks",
            "deleted": deleted_count,
            "indexed": 0,
        }

    # 4) LLM 보강
    if proc_config.contextual_retrieval:
        try:
            from src.pipeline.enrichers.contextual_retrieval import ContextualRetriever

            retriever = ContextualRetriever()
            all_chunks = await retriever.enrich(
                chunks=all_chunks,
                document_text=parse_result.raw_text,
                document_title=parse_result.metadata.get("title", ""),
            )
        except Exception as exc:
            log.warning("reprocess_contextual_retrieval_failed", error=str(exc))

    if proc_config.auto_metadata:
        try:
            from src.pipeline.enrichers.metadata_extractor import MetadataExtractor

            extractor = MetadataExtractor()
            all_chunks = await extractor.extract(all_chunks)
        except Exception as exc:
            log.warning("reprocess_metadata_extraction_failed", error=str(exc))

    # 5) 임베딩 + Qdrant upsert
    embedder = BGEM3Embedder()
    batch_processor = BatchEmbeddingProcessor(
        embedder=embedder,
        batch_size=proc_config.embedding_batch_size,
    )

    # Contextual Retrieval prefix 를 임베딩에 반영
    if proc_config.contextual_retrieval:
        from src.pipeline.enrichers.contextual_retrieval import ContextualRetriever

        original_contents: list[str] = []
        for chunk in all_chunks:
            original_contents.append(chunk.content)
            chunk.content = ContextualRetriever.get_embedding_text(chunk)

        all_chunks = await batch_processor.embed_chunks(all_chunks)

        for i, chunk in enumerate(all_chunks):
            chunk.content = original_contents[i]
    else:
        all_chunks = await batch_processor.embed_chunks(all_chunks)

    indexed_count = await _qdrant_upsert(qdrant_client, collection_name, all_chunks)

    elapsed_ms = int((time.monotonic() - start) * 1000)

    log.info(
        "reprocess_complete",
        document_id=str(document_id),
        deleted=deleted_count,
        indexed=indexed_count,
        elapsed_ms=elapsed_ms,
    )

    # 6) 이벤트 발행
    if producer:
        indexed_event = DocumentIndexedEvent(
            event_id=uuid4(),
            document_id=document_id,
            tenant_id=tenant_id,
            repository_id=repository_id,
            indexed_count=indexed_count,
            collection_name=collection_name,
        )
        await _produce_event(producer, TOPIC_DOCUMENT_INDEXED, indexed_event)

    return {
        "document_id": str(document_id),
        "status": "completed",
        "deleted": deleted_count,
        "indexed": indexed_count,
        "elapsed_ms": elapsed_ms,
    }


def _build_collection_name(tenant_id: str, repository_id: str) -> str:
    """Qdrant 컬렉션 네이밍 규칙."""
    t = tenant_id.replace("-", "")[:12]
    r = repository_id.replace("-", "")[:12]
    return f"{QDRANT_COLLECTION_PREFIX}_{t}_{r}_chunks"


async def _delete_existing_chunks(
    client: Optional[Any],
    collection_name: str,
    document_id: str,
) -> int:
    """기존 문서의 Qdrant 청크를 삭제한다."""
    if client is None:
        log.warning("qdrant_client_not_configured_skipping_delete")
        return 0

    try:
        import asyncio

        from qdrant_client.models import FieldCondition, Filter, MatchValue

        delete_filter = Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id),
                )
            ]
        )

        result = await asyncio.to_thread(
            client.delete,
            collection_name=collection_name,
            points_selector=delete_filter,
        )

        log.info(
            "qdrant_chunks_deleted",
            collection=collection_name,
            document_id=document_id,
        )
        return 1  # 삭제 성공

    except ImportError:
        log.warning("qdrant_client_not_installed")
        return 0
    except Exception as exc:
        log.error("qdrant_delete_failed", error=str(exc))
        return 0


async def _qdrant_upsert(
    client: Optional[Any],
    collection_name: str,
    chunks: list[ChunkObject],
) -> int:
    """Qdrant 에 벡터를 upsert 한다."""
    if client is None:
        log.warning("qdrant_client_not_configured_skipping_upsert")
        return 0

    try:
        import asyncio

        from qdrant_client.models import PointStruct

        points: list[PointStruct] = []
        for chunk in chunks:
            if chunk.dense_vector is None:
                continue

            payload: dict[str, Any] = {
                "document_id": str(chunk.document_id),
                "section_id": str(chunk.section_id) if chunk.section_id else None,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "token_count": chunk.token_count,
                "source_location": chunk.source_location.model_dump(),
                "metadata": chunk.metadata,
            }

            if chunk.extracted_metadata:
                payload["extracted_metadata"] = chunk.extracted_metadata
                if "keywords" in chunk.extracted_metadata:
                    payload["keywords"] = chunk.extracted_metadata["keywords"]
                if "entities" in chunk.extracted_metadata:
                    payload["entities"] = chunk.extracted_metadata["entities"]
                if "topic" in chunk.extracted_metadata:
                    payload["topic"] = chunk.extracted_metadata["topic"]

            if chunk.contextual_prefix:
                payload["contextual_prefix"] = chunk.contextual_prefix

            vectors: dict[str, Any] = {"dense": chunk.dense_vector}

            points.append(
                PointStruct(
                    id=str(chunk.id),
                    vector=vectors,
                    payload=payload,
                )
            )

        if not points:
            return 0

        await asyncio.to_thread(
            client.upsert,
            collection_name=collection_name,
            points=points,
        )

        return len(points)

    except ImportError:
        log.warning("qdrant_client_not_installed")
        return 0
    except Exception as exc:
        log.error("qdrant_upsert_failed", error=str(exc))
        raise


async def _produce_event(producer: object, topic: str, event: object) -> None:
    """Kafka 이벤트를 발행한다."""
    try:
        from aiokafka import AIOKafkaProducer

        if isinstance(producer, AIOKafkaProducer):
            value = event.model_dump_json().encode("utf-8")  # type: ignore[union-attr]
            await producer.send_and_wait(topic, value=value)
            log.info("event_produced", topic=topic)
    except ImportError:
        log.warning("aiokafka_not_available_event_skipped", topic=topic)
