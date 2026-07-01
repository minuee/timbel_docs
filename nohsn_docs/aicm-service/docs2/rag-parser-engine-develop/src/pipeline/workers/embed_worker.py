"""Embed Worker -- 임베딩 + Qdrant upsert -> aicm.document.indexed 발행.

- 청크 파이프라인: aicm.document.chunked 소비
- 블럭 파이프라인: aicm.document.blocked 소비
Phase 2: Contextual Retrieval + Metadata Extraction 보강 연동.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional
from uuid import uuid4

from src.common.constants import (
    QDRANT_COLLECTION_PREFIX,
    TOPIC_DOCUMENT_FAILED,
    TOPIC_DOCUMENT_INDEXED,
)
from src.common.logging import get_logger
from src.pipeline.chunkers.semantic import SemanticChunker
from src.pipeline.embedders.batch import BatchEmbeddingProcessor
from src.pipeline.embedders.bge_m3 import BGEM3Embedder
from src.pipeline.models.block import BlockObject
from src.pipeline.models.document import ChunkObject, ProcessingConfig
from src.pipeline.models.events import (
    DocumentBlockedEvent,
    DocumentChunkedEvent,
    DocumentIndexedEvent,
)
from src.pipeline.models.parse_result import ParseResult
from src.pipeline.parsers.router import detect_format, select_parser

log = get_logger(__name__)

_STRIKETHROUGH_RE = re.compile(r"~~.+?~~")


def _strip_strikethrough(text: str) -> str:
    """마크다운 취소선(~~text~~) 구간을 제거한다. 취소선 = 삭제 의도이므로 임베딩/검색에서 제외."""
    if "~~" not in text:
        return text
    return re.sub(r" {2,}", " ", _STRIKETHROUGH_RE.sub("", text)).strip()


async def handle_document_chunked(
    event: DocumentChunkedEvent,
    producer: object,
    config: ProcessingConfig | None = None,
    qdrant_client: Optional[Any] = None,
) -> None:
    """청킹 완료 이벤트를 처리한다.

    1. 청크 재로드 (파일에서 다시 파싱+청킹 -- 향후 중간 저장소 연동)
    2. Contextual Retrieval 적용 (config.contextual_retrieval=True 인 경우)
    3. Metadata Extraction 적용 (config.auto_metadata=True 인 경우)
    4. BGE-M3 배치 임베딩
    5. Qdrant upsert
    6. aicm.document.indexed 이벤트 발행

    Parameters
    ----------
    event : DocumentChunkedEvent
    producer : Kafka producer
    config : 처리 설정 오버라이드
    qdrant_client : Qdrant 클라이언트 (옵션)
    """
    start = time.monotonic()

    # 제어 신호 확인 (취소/일시정지)
    from src.pipeline.services.status_updater import get_status_updater

    status_updater = get_status_updater()
    signal = await status_updater.check_control_signal(event.document_id)
    if signal == "cancel":
        log.info("pipeline_cancelled", document_id=str(event.document_id))
        await status_updater.mark_failed(event.document_id, "embedding", "사용자에 의해 취소됨")
        return
    if signal == "pause":
        log.info("pipeline_paused", document_id=str(event.document_id))
        return

    log.info(
        "embed_worker_start",
        document_id=str(event.document_id),
        chunk_count=event.chunk_count,
    )

    # DB 상태 업데이트 (임베딩 시작)
    await status_updater.mark_embedding_start(event.document_id)

    # WebSocket 실시간 진행 발행 (임베딩 시작)
    from src.pipeline.workers.status_publisher import (
        publish_pipeline_complete,
        publish_pipeline_failed,
        publish_progress,
        publish_stage_complete,
        publish_stage_start,
    )

    await publish_stage_start(event.document_id, "embedding")

    # D46-v3 §6 — per-stage observability helper imports (NoOp fallback safe).
    from src.common.metrics import (
        inc_kms_pipeline_stage_count,
        inc_kms_pipeline_stage_failure,
        observe_kms_pipeline_stage_duration,
    )

    try:
        # 1) 청크 재로드 — D46-v3 §6 stage="reload".
        proc_config = config or ProcessingConfig()
        inc_kms_pipeline_stage_count("reload")
        _t = time.monotonic()
        try:
            detected_format = detect_format(event.source_path)
            parser = select_parser(detected_format, event.source_path)
            parse_result: ParseResult = await parser.parse()

            chunker = SemanticChunker(proc_config)
            chunks: list[ChunkObject] = await chunker.chunk(
                parse_result.pages,
                source_file_path=parse_result.source_file_path,
                source_file_url=f"/repos/{event.repository_id}/docs/{event.document_id}",
                document_id=str(event.document_id),
            )
        except Exception as exc:
            inc_kms_pipeline_stage_failure("reload", type(exc).__name__)
            raise
        _elapsed_reload = time.monotonic() - _t
        observe_kms_pipeline_stage_duration("reload", _elapsed_reload)
        log.info(
            "embed_stage_reload_complete",
            document_id=str(event.document_id),
            chunk_count=len(chunks),
            elapsed_ms=int(_elapsed_reload * 1000),
        )

        if not chunks:
            log.warning("embed_worker_no_chunks", document_id=str(event.document_id))
            return

        # 2) Contextual Retrieval 적용 — D46-v3 §6 stage="contextual".
        if proc_config.contextual_retrieval:
            inc_kms_pipeline_stage_count("contextual")
            _t = time.monotonic()
            try:
                chunks = await _apply_contextual_retrieval(chunks, parse_result)
            except Exception as exc:
                inc_kms_pipeline_stage_failure("contextual", type(exc).__name__)
                raise
            _elapsed = time.monotonic() - _t
            observe_kms_pipeline_stage_duration("contextual", _elapsed)
            log.info(
                "embed_stage_contextual_complete",
                document_id=str(event.document_id),
                chunk_count=len(chunks),
                elapsed_ms=int(_elapsed * 1000),
            )

        # 3) Metadata Extraction 적용 — D46-v3 §6 stage="metadata".
        if proc_config.auto_metadata:
            inc_kms_pipeline_stage_count("metadata")
            _t = time.monotonic()
            try:
                chunks = await _apply_metadata_extraction(chunks)
            except Exception as exc:
                inc_kms_pipeline_stage_failure("metadata", type(exc).__name__)
                raise
            _elapsed = time.monotonic() - _t
            observe_kms_pipeline_stage_duration("metadata", _elapsed)
            log.info(
                "embed_stage_metadata_complete",
                document_id=str(event.document_id),
                chunk_count=len(chunks),
                elapsed_ms=int(_elapsed * 1000),
            )

        # 4) 배치 임베딩 — D46-v3 §6 stage="embedding".
        inc_kms_pipeline_stage_count("embedding")
        _t = time.monotonic()
        try:
            embedder = BGEM3Embedder()
            batch_processor = BatchEmbeddingProcessor(
                embedder=embedder,
                batch_size=proc_config.embedding_batch_size,
            )

            # Contextual Retrieval 이 활성화된 경우 prefix+content 를 임베딩에 사용
            if proc_config.contextual_retrieval:
                from src.pipeline.enrichers.contextual_retrieval import ContextualRetriever

                # 임시로 content 를 prefix+content 로 교체하여 임베딩
                original_contents: list[str] = []
                for chunk in chunks:
                    original_contents.append(chunk.content)
                    chunk.content = ContextualRetriever.get_embedding_text(chunk)

                chunks = await batch_processor.embed_chunks(chunks)

                # 원본 content 복원
                for i, chunk in enumerate(chunks):
                    chunk.content = original_contents[i]
            else:
                chunks = await batch_processor.embed_chunks(chunks)
        except Exception as exc:
            inc_kms_pipeline_stage_failure("embedding", type(exc).__name__)
            raise
        _elapsed_embed = time.monotonic() - _t
        observe_kms_pipeline_stage_duration("embedding", _elapsed_embed)
        log.info(
            "embed_stage_embedding_complete",
            document_id=str(event.document_id),
            chunk_count=len(chunks),
            elapsed_ms=int(_elapsed_embed * 1000),
        )

        # 5) Qdrant upsert — D46-v3 §6 stage="qdrant".
        inc_kms_pipeline_stage_count("qdrant")
        _t = time.monotonic()
        try:
            collection_name = _build_collection_name(
                str(event.tenant_id), str(event.repository_id)
            )
            indexed_count = await _qdrant_upsert(qdrant_client, collection_name, chunks)
        except Exception as exc:
            inc_kms_pipeline_stage_failure("qdrant", type(exc).__name__)
            raise
        _elapsed_qdrant = time.monotonic() - _t
        observe_kms_pipeline_stage_duration("qdrant", _elapsed_qdrant)
        log.info(
            "embed_stage_qdrant_complete",
            document_id=str(event.document_id),
            indexed_count=indexed_count,
            collection_name=collection_name,
            elapsed_ms=int(_elapsed_qdrant * 1000),
        )

        # 임베딩 0건 가드 — 청크는 있으나 qdrant 벡터가 0건이면 완료(pending_review)로
        # 승격 시 승인가능인데 검색 불가가 되므로 failed 로 처리한다.
        if indexed_count == 0:
            log.warning(
                "embed_worker_zero_indexed",
                document_id=str(event.document_id),
                chunk_count=len(chunks),
            )
            await status_updater.mark_failed(
                event.document_id,
                "embedding",
                f"임베딩 0건 — 벡터 미생성(청크 {len(chunks)}건, qdrant upsert 0)",
            )
            try:
                await publish_pipeline_failed(
                    event.document_id, "embedding", "zero_vectors_indexed"
                )
            except Exception as exc:
                log.debug("publish_pipeline_failed_failed", error=str(exc))
            return

        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "embed_worker_complete",
            document_id=str(event.document_id),
            indexed=indexed_count,
            collection=collection_name,
            elapsed_ms=elapsed_ms,
            contextual_retrieval=proc_config.contextual_retrieval,
            auto_metadata=proc_config.auto_metadata,
        )

        # 6) 결과 이벤트 발행
        indexed_event = DocumentIndexedEvent(
            event_id=uuid4(),
            document_id=event.document_id,
            tenant_id=event.tenant_id,
            repository_id=event.repository_id,
            indexed_count=indexed_count,
            collection_name=collection_name,
        )
        await _produce_event(producer, TOPIC_DOCUMENT_INDEXED, indexed_event)

        # DB 상태 업데이트 (임베딩 완료 → active)
        await status_updater.mark_embedding_complete(
            document_id=event.document_id,
            indexed_count=indexed_count,
            collection_name=collection_name,
        )

        # WebSocket 실시간 진행 발행 (임베딩 완료 + 파이프라인 완료)
        await publish_stage_complete(event.document_id, "embedding")
        await publish_pipeline_complete(event.document_id)

    except Exception as exc:
        log.error(
            "embed_worker_failed",
            document_id=str(event.document_id),
            error=str(exc),
        )
        await status_updater.mark_failed(event.document_id, "embedding", str(exc))
        await _produce_failure(producer, event.document_id, "embedding", str(exc))

        # WebSocket 실시간 진행 발행 (임베딩 실패)
        await publish_pipeline_failed(event.document_id, "embedding", str(exc))
        raise


async def _apply_contextual_retrieval(
    chunks: list[ChunkObject], parse_result: ParseResult
) -> list[ChunkObject]:
    """Contextual Retrieval 을 적용한다."""
    try:
        from src.pipeline.enrichers.contextual_retrieval import ContextualRetriever

        retriever = ContextualRetriever()
        chunks = await retriever.enrich(
            chunks=chunks,
            document_text=parse_result.raw_text,
            document_title=parse_result.metadata.get("title", ""),
        )
        log.info("contextual_retrieval_applied", chunk_count=len(chunks))
    except Exception as exc:
        log.warning("contextual_retrieval_failed_continuing", error=str(exc))

    return chunks


async def _apply_metadata_extraction(
    chunks: list[ChunkObject],
) -> list[ChunkObject]:
    """Metadata Extraction 을 적용한다."""
    try:
        from src.pipeline.enrichers.metadata_extractor import MetadataExtractor

        extractor = MetadataExtractor()
        chunks = await extractor.extract(chunks)
        log.info("metadata_extraction_applied", chunk_count=len(chunks))
    except Exception as exc:
        log.warning("metadata_extraction_failed_continuing", error=str(exc))

    return chunks


def _build_collection_name(tenant_id: str, repository_id: str) -> str:
    """Qdrant 컬렉션 네이밍 규칙: aicm_{tenant}_{repo}_chunks."""
    t = tenant_id.replace("-", "")[:12]
    r = repository_id.replace("-", "")[:12]
    return f"{QDRANT_COLLECTION_PREFIX}_{t}_{r}_chunks"


async def _qdrant_upsert(
    client: Optional[Any],
    collection_name: str,
    chunks: list[ChunkObject],
) -> int:
    """Qdrant 에 벡터를 upsert 한다."""
    if client is None:
        try:
            from qdrant_client import QdrantClient
            from src.common.config import settings
            client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=getattr(settings, 'QDRANT_API_KEY', None) or None,
                timeout=30,
            )
        except Exception as exc:
            # client 생성 실패 = 인프라 장애. 0 반환 시 "완료"로 승격돼 0벡터+승인가능이
            # 되므로, 예외를 올려 실패/재시도 경로로 보낸다.
            log.warning("qdrant_client_creation_failed", error=str(exc))
            raise

    try:
        from qdrant_client.models import PointStruct, SparseVector

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

            # Phase 2: 추출된 메타데이터를 payload 에 포함
            if chunk.extracted_metadata:
                payload["extracted_metadata"] = chunk.extracted_metadata
                # 키워드를 별도 필드로 추가 (필터링용)
                if "keywords" in chunk.extracted_metadata:
                    payload["keywords"] = chunk.extracted_metadata["keywords"]
                if "entities" in chunk.extracted_metadata:
                    payload["entities"] = chunk.extracted_metadata["entities"]
                if "topic" in chunk.extracted_metadata:
                    payload["topic"] = chunk.extracted_metadata["topic"]

            # Phase 2: contextual_prefix 를 payload 에 포함
            if chunk.contextual_prefix:
                payload["contextual_prefix"] = chunk.contextual_prefix

            vectors: dict[str, Any] = {"dense": chunk.dense_vector}

            # Sparse vector 포함 (하이브리드 검색 지원)
            if chunk.sparse_vector:
                sparse_indices = list(chunk.sparse_vector.keys())
                sparse_values = list(chunk.sparse_vector.values())
                vectors["sparse"] = SparseVector(
                    indices=sparse_indices, values=sparse_values
                )

            points.append(
                PointStruct(
                    id=str(chunk.id),
                    vector=vectors,
                    payload=payload,
                )
            )

        if not points:
            return 0

        # Qdrant upsert (동기 클라이언트) -- 대용량 문서 타임아웃 방지 위해 소배치 분할
        import asyncio
        from src.common.config import settings

        _UPSERT_BATCH = settings.QDRANT_UPSERT_BATCH_SIZE if hasattr(settings, "QDRANT_UPSERT_BATCH_SIZE") else 128
        for _i in range(0, len(points), _UPSERT_BATCH):
            _batch = points[_i:_i + _UPSERT_BATCH]
            await asyncio.to_thread(
                client.upsert,
                collection_name=collection_name,
                points=_batch,
            )

        log.info(
            "qdrant_upsert_complete",
            collection=collection_name,
            points=len(points),
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


async def _produce_failure(
    producer: object,
    document_id: object,
    stage: str,
    error: str,
) -> None:
    """실패 이벤트를 발행한다."""
    import json

    try:
        from aiokafka import AIOKafkaProducer

        if isinstance(producer, AIOKafkaProducer):
            payload = json.dumps(
                {
                    "document_id": str(document_id),
                    "stage": stage,
                    "error": error,
                }
            ).encode("utf-8")
            await producer.send_and_wait(TOPIC_DOCUMENT_FAILED, value=payload)
    except ImportError:
        log.warning("aiokafka_not_available_failure_event_skipped")


# ===================================================================
# 블럭 파이프라인 (specs/06)
# ===================================================================


async def handle_document_blocked(
    event: DocumentBlockedEvent,
    producer: object,
    config: ProcessingConfig | None = None,
    qdrant_client: Optional[Any] = None,
    llm_client: object | None = None,
    tenant_slug: str = "",
) -> None:
    """블럭 세그멘테이션 완료 이벤트를 처리한다.

    1. 캐시에서 블럭 로드
    2. Knowledge Compiler 적용
    3. BGE-M3 배치 임베딩
    4. Qdrant upsert (테넌트 단일 컬렉션)
    5. aicm.document.indexed 이벤트 발행
    """
    start = time.monotonic()
    proc_config = config or ProcessingConfig(use_block_pipeline=True)

    # 제어 신호 확인 (취소/일시정지)
    from src.pipeline.services.status_updater import get_status_updater

    status_updater = get_status_updater()
    signal = await status_updater.check_control_signal(event.document_id)
    if signal == "cancel":
        log.info("pipeline_cancelled", document_id=str(event.document_id))
        await status_updater.mark_failed(
            event.document_id, "block_embedding", "사용자에 의해 취소됨"
        )
        return
    if signal == "pause":
        log.info("pipeline_paused", document_id=str(event.document_id))
        return

    log.info(
        "embed_worker_block_start",
        document_id=str(event.document_id),
        block_count=event.block_count,
    )

    # DB 상태 업데이트 (임베딩 시작)
    await status_updater.mark_embedding_start(event.document_id)

    # WebSocket 실시간 진행 발행 (임베딩 시작)
    from src.pipeline.workers.status_publisher import (
        publish_pipeline_complete,
        publish_pipeline_failed,
        publish_progress,
        publish_stage_complete,
        publish_stage_start,
    )

    await publish_stage_start(event.document_id, "embedding")

    try:
        # 1) 블럭 로드
        from src.pipeline.workers.block_worker import load_blocks_from_cache

        blocks = await load_blocks_from_cache(event.document_id)
        if not blocks:
            # D47 §A — 옛 버그: 여기서 silent return → status='processing' 영원히 stuck.
            # 이제 명시적으로 failed 마킹 + publish_pipeline_failed 송출.
            # 원인 자체는 별도 §B 에서 차단 — 여기는 *어떤 이유로든 빈 list* 면 fail.
            log.warning(
                "embed_worker_no_blocks_in_cache",
                document_id=str(event.document_id),
                block_count_hint=event.block_count,
            )
            await status_updater.mark_failed(
                event.document_id,
                "embedding",
                f"블럭 캐시 로드 실패 — 예상 {event.block_count}건, 실제 0건",
            )
            try:
                await publish_pipeline_failed(
                    event.document_id, "embedding", "blocks_unavailable"
                )
            except Exception as exc:
                log.debug("publish_pipeline_failed_failed", error=str(exc))
            return

        # 2) Knowledge Compiler — block_worker에서 이미 수행됨. 여기서 중복 호출하지 않음.
        # (이전 코드가 block_worker + embed_worker 양쪽에서 compile()을 호출하여
        #  LLM 작업이 2배로 실행되고 블럭이 중복 생성되는 버그가 있었음)

        # 2.5) 노이즈 블럭 제외 (is_noise=True 블럭은 인덱싱하지 않음)
        blocks = [b for b in blocks if not b.metadata.get("is_noise")]
        if not blocks:
            # D47 §A — 동일 — 노이즈 필터 후 0건도 failed 마킹.
            log.warning("embed_worker_no_content_blocks", document_id=str(event.document_id))
            await status_updater.mark_failed(
                event.document_id,
                "embedding",
                "노이즈 필터 후 0건 — 모든 블럭이 is_noise=True",
            )
            try:
                await publish_pipeline_failed(
                    event.document_id, "embedding", "all_blocks_noise"
                )
            except Exception as exc:
                log.debug("publish_pipeline_failed_failed", error=str(exc))
            return

        # 2.6) 취소선(~~text~~) 제거 — 삭제 의도 반영. DB 원문은 유지, 임베딩/payload만 정리.
        for b in blocks:
            b.content = _strip_strikethrough(b.content)

        # 3) 배치 임베딩
        embedder = BGEM3Embedder()
        batch_processor = BatchEmbeddingProcessor(
            embedder=embedder,
            batch_size=proc_config.embedding_batch_size,
        )

        # 3.5-pre) 문서 제목 선조회 — 임베딩 입력에 [문서제목 > 섹션] 컨텍스트 prepend 용
        document_title, repository_name = await _get_document_meta(
            event.document_id, event.repository_id
        )

        # 임베딩 텍스트 준비 (문서 컨텍스트 prefix + contextual_prefix + content)
        embedding_texts = [
            _embedding_text_with_context(b, document_title) for b in blocks
        ]
        results = await batch_processor.embed_texts(embedding_texts)

        for block, result in zip(blocks, results):
            block.dense_vector = result.dense
            block.sparse_vector = result.sparse

        # 3.4) 의미 중복 제거 (BGE-M3 임베딩 기반 near-dup)
        try:
            from src.pipeline.enrichers.semantic_deduper import deduplicate_by_embedding

            blocks = deduplicate_by_embedding(blocks)
        except Exception as exc:
            log.debug("semantic_dedup_failed", error=str(exc))

        # 3.5) 문서 카테고리 조회 (Qdrant/ES payload에 포함; 제목/저장소명은 위에서 선조회)
        category_ids = await _get_document_category_ids(event.document_id)
        # 실제 DB status 를 읽어 payload 로 전달 (하드코딩 "processing" 이 active 를 덮는 사고 방지).
        # 일반 흐름에서는 "processing" 이지만, 재처리 시 active/pending_review 상태에서 파이프라인이
        # 다시 돌 수도 있으므로 항상 DB 의 실제 값을 신뢰한다.
        current_doc_status = await _get_document_status(event.document_id)

        # 4) Qdrant upsert (테넌트 단일 컬렉션) — 컬렉션 자동 생성
        # tenant_slug를 DB에서 조회 (전달받지 못한 경우)
        slug_for_collection = tenant_slug
        if not slug_for_collection:
            try:
                from src.core.database import async_session_factory
                from sqlalchemy import text
                async with async_session_factory() as _sess:
                    _r = await _sess.execute(
                        text("SELECT slug FROM tenants WHERE id = :tid"),
                        {"tid": str(event.tenant_id)},
                    )
                    _row = _r.fetchone()
                    slug_for_collection = _row[0] if _row else str(event.tenant_id)
            except Exception:
                slug_for_collection = str(event.tenant_id)
        try:
            from src.core.services.qdrant_collection_manager import ensure_block_collection

            await ensure_block_collection(slug_for_collection)
        except Exception as exc:
            log.warning("ensure_block_collection_failed", error=str(exc))

        collection_name = _build_tenant_collection_name(slug_for_collection)
        indexed_count = await _qdrant_upsert_blocks(
            qdrant_client,
            collection_name,
            blocks,
            repository_id=str(event.repository_id),
            category_ids=category_ids,
            document_title=document_title,
            repository_name=repository_name,
            document_status=current_doc_status,
            # Lucas-KMS Phase 2 T2.5 — payload-level tenant isolation 이중 안전망.
            tenant_id=str(event.tenant_id),
            tenant_slug=slug_for_collection,
        )

        # 4.5) ES 인덱스 자동 생성 (존재하지 않으면 미리 생성)
        try:
            from src.search.hybrid.es_keyword import ESKeywordSearcher, build_block_es_index_name

            es_index_name = build_block_es_index_name(slug_for_collection)
            searcher = ESKeywordSearcher()
            await searcher.ensure_block_index(es_index_name)
        except Exception:
            log.warning("es_ensure_block_index_failed", tenant_slug=slug_for_collection)

        # Elasticsearch 블럭 인덱싱 (키워드 검색용)
        es_indexed = await _es_index_blocks(
            blocks=blocks,
            tenant_slug=slug_for_collection,
            repository_id=str(event.repository_id),
            category_ids=category_ids,
            document_title=document_title,
            repository_name=repository_name,
            document_status=current_doc_status,
            # Lucas-KMS Phase 2 T2.6 — payload-level tenant isolation 이중 안전망.
            tenant_id=str(event.tenant_id),
        )

        # 임베딩 0건 가드 — 블록은 있으나 qdrant 벡터가 0건이면(client 장애/dense 누락 등)
        # 완료(pending_review)로 승격 시 승인가능인데 검색 불가가 되므로 failed 로 처리한다.
        if indexed_count == 0:
            log.warning(
                "embed_worker_zero_indexed",
                document_id=str(event.document_id),
                block_count=len(blocks),
            )
            await status_updater.mark_failed(
                event.document_id,
                "embedding",
                f"임베딩 0건 — 벡터 미생성(블록 {len(blocks)}건, qdrant upsert 0)",
            )
            try:
                await publish_pipeline_failed(
                    event.document_id, "embedding", "zero_vectors_indexed"
                )
            except Exception as exc:
                log.debug("publish_pipeline_failed_failed", error=str(exc))
            return

        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "embed_worker_block_complete",
            document_id=str(event.document_id),
            indexed=indexed_count,
            es_indexed=es_indexed,
            collection=collection_name,
            elapsed_ms=elapsed_ms,
        )

        # 5) 결과 이벤트 발행
        indexed_event = DocumentIndexedEvent(
            event_id=uuid4(),
            document_id=event.document_id,
            tenant_id=event.tenant_id,
            repository_id=event.repository_id,
            indexed_count=indexed_count,
            collection_name=collection_name,
        )
        await _produce_event(producer, TOPIC_DOCUMENT_INDEXED, indexed_event)

        # DB 상태 업데이트 (임베딩 완료 → active)
        await status_updater.mark_embedding_complete(
            document_id=event.document_id,
            indexed_count=indexed_count,
            collection_name=collection_name,
        )

        # WebSocket 실시간 진행 발행 (임베딩 완료 + 파이프라인 완료)
        await publish_stage_complete(event.document_id, "embedding")
        await publish_pipeline_complete(event.document_id)

    except Exception as exc:
        log.error(
            "embed_worker_block_failed",
            document_id=str(event.document_id),
            error=str(exc),
        )
        await status_updater.mark_failed(event.document_id, "block_embedding", str(exc))
        await _produce_failure(producer, event.document_id, "block_embedding", str(exc))

        # WebSocket 실시간 진행 발행 (임베딩 실패)
        await publish_pipeline_failed(event.document_id, "block_embedding", str(exc))
        raise


def _build_tenant_collection_name(tenant_slug: str) -> str:
    """테넌트 단일 Qdrant 컬렉션 네이밍 규칙: aicm_{tenant_slug}_blocks."""
    return f"{QDRANT_COLLECTION_PREFIX}_{tenant_slug}_blocks"


async def _qdrant_upsert_blocks(
    client: Optional[Any],
    collection_name: str,
    blocks: list[BlockObject],
    repository_id: str = "",
    category_ids: list[str] | None = None,
    document_title: str = "",
    repository_name: str = "",
    document_status: str = "processing",
    tenant_id: str = "",
    tenant_slug: str = "",
) -> int:
    """블럭을 Qdrant 에 upsert 한다 (repository_id, category_ids payload 포함).

    Lucas-KMS Phase 2 T2.5 — payload 에 tenant_id 가 반드시 채워져야 한다.
    누락 시 cross-tenant 누수 위험 → 즉시 ``ValueError`` 발생 (fail-fast).
    """
    # T2.5 — tenant_id 누락 시 fail-fast (cross-tenant 누수 방어).
    # legacy 호환 경로 (인덱싱 stage 가 tenant_id 안 넘기는 곳) 가 없는지 회귀로 보장.
    if not tenant_id:
        raise ValueError(
            "qdrant_upsert_blocks_missing_tenant_id: "
            f"collection={collection_name!r} — tenant_id 누락은 cross-tenant 누수 위험."
        )
    if client is None:
        try:
            from qdrant_client import QdrantClient
            from src.common.config import settings
            client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=getattr(settings, 'QDRANT_API_KEY', None) or None,
                timeout=30,
            )
        except Exception as exc:
            # client 생성 실패 = 인프라 장애. 0 반환 시 "완료"로 승격돼 0벡터+승인가능이
            # 되므로, 예외를 올려 실패/재시도 경로로 보낸다.
            log.warning("qdrant_client_creation_failed", error=str(exc))
            raise

    try:
        from qdrant_client.models import PointStruct, SparseVector

        # 멱등성: 같은 document_id 의 기존 point 를 먼저 삭제한다.
        # 파이프라인 재실행/중복 이벤트 시 block.id(uuid4) 가 매번 새로 생성돼 Qdrant 에
        # 중복 point 가 쌓이던 문제(검색 결과 동일 청크 중복) 방지. 정상 1회 처리 시엔 무해.
        if blocks:
            import asyncio as _aio
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            _doc_id = str(blocks[0].document_id)
            try:
                await _aio.to_thread(
                    client.delete,
                    collection_name=collection_name,
                    points_selector=Filter(
                        must=[FieldCondition(key="document_id", match=MatchValue(value=_doc_id))]
                    ),
                )
            except Exception as _exc:
                log.warning("qdrant_idempotent_delete_failed", document_id=_doc_id, error=str(_exc))

        points: list[PointStruct] = []
        for block in blocks:
            if block.dense_vector is None:
                continue

            payload: dict[str, Any] = {
                # Lucas-KMS Phase 2 T2.5 — payload-level tenant isolation 이중 안전망.
                # collection naming 만으로 부족, search 시 must filter tenant_id 와 짝.
                "tenant_id": tenant_id,
                "tenant_slug": tenant_slug,
                "document_id": str(block.document_id),
                "repository_id": repository_id,
                "document_title": document_title,
                "repository_name": repository_name,
                "block_type": block.block_type.value,
                "block_index": block.block_index,
                "content": block.content,
                "token_count": block.token_count,
                "source_location": block.source_location.model_dump(),
                "metadata": block.metadata,
                "category_ids": category_ids or [],
                "document_status": document_status,
            }

            # Ontology fields (Phase A-3)
            payload["nature"] = block.metadata.get("nature", "")
            payload["time_resolved"] = (
                block.metadata.get("time_reference", {}).get("resolved", "")
            )
            payload["speakers"] = (
                block.metadata.get("entities", {}).get("speakers", [])
            )
            payload["entities_people"] = (
                block.metadata.get("entities", {}).get("people", [])
            )
            payload["entities_orgs"] = (
                block.metadata.get("entities", {}).get("orgs", [])
            )
            payload["validity_status"] = block.metadata.get("validity_status", "active")
            payload["domain_category_ids"] = [
                c.get("id", "") for c in block.metadata.get("domain_category_ids", [])
            ]
            payload["classification_confidence"] = block.metadata.get(
                "classification_confidence", 0.0
            )

            # QNA 블럭: 질문(qna_title)을 section_title 로 노출.
            # content 는 답변이므로 검색 결과/인용에 질문이 함께 표시되도록 한다.
            # (SearchHit.section_title -> source_formatter/prompt_templates [출처: {doc_title} > {section_title}])
            _qna_title = block.metadata.get("qna_title")
            if _qna_title:
                payload["section_title"] = _qna_title

            # 표 전용 필드
            if block.table_markdown:
                payload["table_markdown"] = block.table_markdown
            if block.table_headers:
                payload["table_headers"] = block.table_headers

            # 이미지 전용 필드
            if block.image_description:
                payload["image_description"] = block.image_description
            if block.ocr_text:
                payload["ocr_text"] = block.ocr_text
            if block.image_path:
                payload["image_path"] = block.image_path

            # 보강 데이터
            if block.extracted_metadata:
                payload["extracted_metadata"] = block.extracted_metadata
                if "keywords" in block.extracted_metadata:
                    payload["keywords"] = block.extracted_metadata["keywords"]
                if "entities" in block.extracted_metadata:
                    payload["entities"] = block.extracted_metadata["entities"]
                if "topic" in block.extracted_metadata:
                    payload["topic"] = block.extracted_metadata["topic"]

            if block.contextual_prefix:
                payload["contextual_prefix"] = block.contextual_prefix

            vectors: dict[str, Any] = {"dense": block.dense_vector}

            # Sparse vector 포함 (하이브리드 검색 지원)
            if block.sparse_vector:
                sparse_indices = list(block.sparse_vector.keys())
                sparse_values = list(block.sparse_vector.values())
                vectors["sparse"] = SparseVector(
                    indices=sparse_indices, values=sparse_values
                )

            points.append(
                PointStruct(
                    id=str(block.id),
                    vector=vectors,
                    payload=payload,
                )
            )

        if not points:
            return 0

        # Qdrant upsert -- 대용량 문서 타임아웃 방지 위해 소배치 분할
        import asyncio
        from src.common.config import settings

        _UPSERT_BATCH = settings.QDRANT_UPSERT_BATCH_SIZE if hasattr(settings, "QDRANT_UPSERT_BATCH_SIZE") else 128
        for _i in range(0, len(points), _UPSERT_BATCH):
            _batch = points[_i:_i + _UPSERT_BATCH]
            await asyncio.to_thread(
                client.upsert,
                collection_name=collection_name,
                points=_batch,
            )

        log.info(
            "qdrant_block_upsert_complete",
            collection=collection_name,
            points=len(points),
        )
        return len(points)

    except ImportError:
        log.warning("qdrant_client_not_installed")
        return 0
    except Exception as exc:
        log.error("qdrant_block_upsert_failed", error=str(exc))
        raise


async def _es_index_blocks(
    blocks: list[BlockObject],
    tenant_slug: str,
    repository_id: str,
    category_ids: list[str] | None = None,
    document_title: str = "",
    repository_name: str = "",
    document_status: str = "processing",
    tenant_id: str = "",
) -> int:
    """블럭을 Elasticsearch 에 인덱싱한다 (키워드 검색용).

    실패해도 파이프라인 전체를 중단하지 않는다.

    Lucas-KMS Phase 2 T2.6 — ES payload 에 tenant_id 가 반드시 채워져야 한다.
    누락 시 fail-fast (qdrant_upsert_blocks 와 동일 패턴). cross-tenant 누수
    위험 차단.
    """
    # T2.6 — tenant_id 누락 시 fail-fast (cross-tenant 누수 방어).
    # legacy 호환 경로 (인덱싱 stage 가 tenant_id 안 넘기는 곳) 가 없는지 회귀로 보장.
    if not tenant_id:
        raise ValueError(
            "es_index_blocks_missing_tenant_id: "
            f"tenant_slug={tenant_slug!r} — tenant_id 누락은 cross-tenant 누수 위험."
        )
    try:
        from src.search.hybrid.es_keyword import ESKeywordSearcher, build_block_es_index_name

        es_index_name = build_block_es_index_name(tenant_slug)
        searcher = ESKeywordSearcher()

        # 멱등성: 같은 document_id 의 기존 ES 블록을 먼저 삭제(Qdrant 와 동일 이유, 중복 인덱싱 방지).
        if blocks:
            try:
                from elasticsearch import AsyncElasticsearch
                from src.common.config import settings as _settings
                _doc_id = str(blocks[0].document_id)
                _es = AsyncElasticsearch(hosts=[_settings.ELASTICSEARCH_URL])
                await _es.delete_by_query(
                    index=es_index_name,
                    body={"query": {"bool": {"must": [
                        {"term": {"document_id": _doc_id}},
                        {"term": {"tenant_id": tenant_id}},
                    ]}}},
                    ignore=[404],
                    refresh=True,
                )
                await _es.close()
            except Exception as _exc:
                log.warning("es_idempotent_delete_failed", error=str(_exc))

        es_docs: list[dict[str, Any]] = []
        for block in blocks:
            if not block.content:
                continue

            doc: dict[str, Any] = {
                # Lucas-KMS Phase 2 T2.6 — payload tenant_id (이중 안전망).
                "tenant_id": tenant_id,
                "block_id": str(block.id),
                "document_id": str(block.document_id),
                "repository_id": repository_id,
                "document_title": document_title,
                "repository_name": repository_name,
                "block_type": block.block_type.value,
                "content": block.content,
                "block_index": block.block_index,
                "document_status": document_status,
                "keywords": (
                    block.extracted_metadata.get("keywords", [])
                    if block.extracted_metadata
                    else []
                ),
                "entities": (
                    block.extracted_metadata.get("entities", [])
                    if block.extracted_metadata
                    else []
                ),
                "source_location": block.source_location.model_dump(),
                "metadata": block.metadata,
                "category_ids": category_ids or [],
            }
            # QNA 블럭: 질문(qna_title)을 section_title 로 인덱싱 (키워드 매칭 + 결과 표시).
            _qna_title = block.metadata.get("qna_title")
            if _qna_title:
                doc["section_title"] = _qna_title
            es_docs.append(doc)

        if not es_docs:
            return 0

        indexed = await searcher.index_blocks(
            es_index_name, es_docs, expected_tenant_id=tenant_id
        )
        log.info(
            "es_block_indexing_complete",
            tenant_slug=tenant_slug,
            es_index=es_index_name,
            indexed=indexed,
        )
        return indexed
    except Exception as exc:
        log.warning("es_block_indexing_failed_continuing", error=str(exc))
        return 0


# 임베딩 입력 컨텍스트 prefix 용 문서 확장자 집합(제목 정리용 — 구조적 상수, 도메인 키워드 아님)
_DOC_EXTENSIONS = {
    ".docx", ".doc", ".pdf", ".hwp", ".hwpx",
    ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".md",
}


def _clean_doc_title(title) -> str:
    """문서 제목에서 파일 확장자를 제거한다. None/빈값 안전."""
    if not title:
        return ""
    t = str(title).strip()
    root, ext = os.path.splitext(t)
    if ext.lower() in _DOC_EXTENSIONS:
        return root.strip()
    return t


def _embedding_text_with_context(block, document_title: str) -> str:
    """블록 임베딩 입력 앞에 [문서제목 > 섹션] 컨텍스트를 결정적으로 prepend.

    표(table) 등 본문에 문서명이 없는 블록도 제품 특정 질의에 매칭되게 한다.
    저장 블록/payload/검색 반환/rerank 텍스트는 불변(임베딩 입력만 변경).
    contextual_prefix(LLM 맥락)가 이미 있으면 이중 문서맥락 회피 위해 skip.
    제목/섹션이 모두 없으면 원본 embedding_text() 그대로 반환.
    """
    base = block.embedding_text()
    if getattr(block, "contextual_prefix", None):
        return base
    title = _clean_doc_title(document_title)
    heading_path = getattr(block.source_location, "heading_path", None) or []
    section = " > ".join(h for h in heading_path if h)
    if title and section:
        prefix = f"{title} > {section}"
    elif title:
        prefix = title
    elif section:
        prefix = section
    else:
        return base
    return f"{prefix}\n\n{base}"


async def _get_document_meta(
    document_id: object, repository_id: object
) -> tuple[str, str]:
    """문서 제목과 저장소 이름을 DB에서 조회한다."""
    doc_title = ""
    repo_name = ""
    try:
        from sqlalchemy import text

        from src.core.database import async_session_factory

        async with async_session_factory() as session:
            # 문서 제목
            r = await session.execute(
                text("SELECT title FROM documents WHERE id = :did"),
                {"did": str(document_id)},
            )
            row = r.fetchone()
            if row and row[0]:
                doc_title = row[0]

            # 저장소 이름
            r2 = await session.execute(
                text("SELECT name FROM repositories WHERE id = :rid"),
                {"rid": str(repository_id)},
            )
            row2 = r2.fetchone()
            if row2 and row2[0]:
                repo_name = row2[0]
    except Exception as exc:
        log.debug("document_meta_lookup_failed", error=str(exc))

    return doc_title, repo_name


async def _get_document_category_ids(document_id: object) -> list[str]:
    """문서에 매핑된 카테고리 ID 목록을 조회한다."""
    try:
        from sqlalchemy import text

        from src.core.database import async_session_factory

        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT category_id FROM document_categories WHERE document_id = :doc_id"),
                {"doc_id": str(document_id)},
            )
            return [str(row[0]) for row in result.fetchall()]
    except Exception as exc:
        log.debug("category_lookup_failed", error=str(exc))
        return []


async def _get_document_status(document_id: object) -> str:
    """문서의 현재 DB status 를 조회한다. 실패/미존재 시 'processing' 으로 폴백."""
    try:
        from sqlalchemy import text

        from src.core.database import async_session_factory

        async with async_session_factory() as session:
            r = await session.execute(
                text("SELECT status FROM documents WHERE id = :did"),
                {"did": str(document_id)},
            )
            row = r.fetchone()
            return row[0] if row and row[0] else "processing"
    except Exception as exc:
        log.debug("document_status_lookup_failed", error=str(exc))
        return "processing"
