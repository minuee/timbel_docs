"""Merge Worker — 분할된 파트의 블럭을 통합.

각 파트의 block_worker가 완료되면 DocumentPartBlockedEvent를 발행한다.
이 워커는 모든 파트가 완료되었는지 추적하고,
완료 시 블럭을 통합 → KnowledgeCompiler 보강 → DB 저장 → DocumentBlockedEvent 발행.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any
from uuid import uuid4

from src.common.constants import TOPIC_DOCUMENT_BLOCKED
from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject
from src.pipeline.models.events import (
    DocumentBlockedEvent,
    DocumentPartBlockedEvent,
)
from src.pipeline.processing.split_tracker import SplitTracker
from src.pipeline.storage.config import StorageConfig
from src.pipeline.storage.object_store import ObjectStore

log = get_logger(__name__)


# D46-v3 §3-b — merge_worker race retry (ValueError 매칭 + 최종 raise).
# transient: split_worker 가 split_job 을 Redis 에 등록하기 전 part_blocked 가
# 먼저 도착하는 race (cold-start / 큐 백프레셔 시 ~수초). 그 외 ValueError
# (논리 오류) 는 즉시 raise.
# 멱등성: SplitTracker.mark_part_completed 는 이미 완료된 part_index 재호출 시
# completed_parts 에 append 하지 않음 (split_tracker.py:94 `if part_index not in ...`).
# Redis 저장만 idempotent 재발생 — 본 retry 가 중복 호출해도 데이터 손실 0.
_MERGE_RETRY_DELAYS_SEC = [0.3, 0.6, 1.2, 2.4, 4.8, 8.0, 12.0]  # 7 retries, 누적 ~29s + jitter
_MERGE_TRANSIENT_PATTERN = "Split job not found"


async def _try_mark_part_completed_with_retry(
    tracker: SplitTracker,
    document_id: Any,
    part_index: int,
    doc_id_str: str,
) -> Any:
    """D46-v3 §3-b — merge race transient retry.

    - "Split job not found" ValueError 만 transient 로 분류 (split_worker 등록 지연 race).
    - 그 외 ValueError (논리 오류, 메시지 미일치) → 즉시 raise.
    - 8 attempts (initial + 7 retry), exponential backoff + jitter, 누적 ~30s.
    - 최종 실패 시 raise → 상위 DLQHandler.handle_with_retry (main.py:790) 가
      3 회 재시도 (5s/25s/125s) 후 TOPIC_DOCUMENT_DLQ publish + DB persist.
      silent drop 0.
    """
    last_exc: ValueError | None = None
    attempts = [0.0] + _MERGE_RETRY_DELAYS_SEC
    for attempt_idx, delay in enumerate(attempts):
        if delay > 0:
            jitter = random.uniform(0, delay * 0.2)
            await asyncio.sleep(delay + jitter)
        try:
            return await tracker.mark_part_completed(document_id, part_index)
        except ValueError as ve:
            msg = str(ve)
            if _MERGE_TRANSIENT_PATTERN not in msg:
                # 논리 오류 → 즉시 raise (재시도 무의미).
                log.error(
                    "merge_part_non_transient_value_error",
                    document_id=doc_id_str,
                    part_index=part_index,
                    error=msg,
                )
                raise
            last_exc = ve
            try:
                from src.common.metrics import inc_kms_pipeline_merge_part_retry

                inc_kms_pipeline_merge_part_retry()
            except Exception:  # noqa: BLE001 — metrics 미초기화 방어.
                pass
            log.warning(
                "merge_part_retry",
                document_id=doc_id_str,
                part_index=part_index,
                attempt=attempt_idx + 1,
                delay_sec=delay,
                error=msg,
            )
            continue
    # 8 attempts 누적 ~30s 후에도 실패 → raise (silent return 금지).
    log.error(
        "merge_part_retry_exhausted",
        document_id=doc_id_str,
        part_index=part_index,
        attempts=len(attempts),
    )
    assert last_exc is not None
    raise last_exc


async def handle_document_part_blocked(
    event: DocumentPartBlockedEvent,
    producer: Any,
    llm_client: object | None = None,
) -> None:
    """파트 블럭 완료 이벤트를 처리한다.

    모든 파트가 완료되면 블럭을 통합하고 최종 이벤트를 발행한다.

    D34 §1: 직접 호출 path 보호용 *방어적 이중 wrap*.
    """
    # D34 §1 — bind_system_scope wrap (방어적 이중 wrap). 사전 GPT-5 §5 권고:
    # write-heavy path (allow_null_tenant=False).
    from src.api.middleware.rls_context import bind_system_scope

    _tid = str(getattr(event, "tenant_id", "")) or None
    if not _tid:
        # D35 §1 — per-event rebind failure metric.
        try:
            from src.common.metrics import (
                REBIND_SITE_MERGE_PART_BLOCKED,
                inc_kms_worker_rebind_failure,
            )

            inc_kms_worker_rebind_failure(
                REBIND_SITE_MERGE_PART_BLOCKED, "aicm.document.part_blocked"
            )
        except Exception:  # noqa: BLE001
            pass
        log.error(
            "missing_tenant_id",
            document_id=str(getattr(event, "document_id", "")),
            where="merge_worker.handle_document_part_blocked",
        )
        return
    async with bind_system_scope(_tid, allow_null_tenant=False):
        return await _handle_document_part_blocked_inner(
            event, producer, llm_client=llm_client
        )


async def _handle_document_part_blocked_inner(
    event: DocumentPartBlockedEvent,
    producer: Any,
    *,
    llm_client: object | None = None,
) -> None:
    """D34 §1 — bind_system_scope wrap 안에서 실제 로직."""
    doc_id = str(event.document_id)

    log.info(
        "merge_worker_part_received",
        document_id=doc_id,
        part_index=event.part_index,
        total_parts=event.total_parts,
        block_count=event.block_count,
    )

    # 1) SplitTracker에서 파트 완료 기록 — D46-v3 §3-b: transient retry + 최종 raise.
    tracker = SplitTracker()
    try:
        job = await _try_mark_part_completed_with_retry(
            tracker, event.document_id, event.part_index, doc_id
        )
    except ValueError:
        # 8 retry 누적 ~30s 후에도 split_job 미발견 → 상위 DLQHandler 트리거.
        # silent return 금지 — 상위에서 3회 재시도 (5s/25s/125s) 후 DLQ publish.
        log.error("merge_worker_split_job_missing_after_retry", document_id=doc_id)
        await tracker.close()
        raise

    completed = len(job.completed_parts)
    total = job.total_parts
    log.info(
        "merge_worker_progress",
        document_id=doc_id,
        completed=f"{completed}/{total}",
        failed=len(job.failed_parts),
    )

    # 아직 모든 파트가 완료되지 않았으면 대기
    if not tracker.is_complete(job):
        await tracker.close()
        return

    # ================================================================
    # 모든 파트 완료 → 머지 시작
    # ================================================================
    merge_start = time.monotonic()
    log.info("merge_worker_start", document_id=doc_id, total_parts=total)

    # 2) MinIO에서 모든 파트의 블럭 로드
    cfg = StorageConfig()
    store = ObjectStore(
        endpoint=cfg.MINIO_ENDPOINT,
        access_key=cfg.MINIO_ACCESS_KEY,
        secret_key=cfg.MINIO_SECRET_KEY,
        secure=cfg.MINIO_SECURE,
    )
    await store.init()

    all_blocks: list[BlockObject] = []
    for part_idx in sorted(job.completed_parts):
        blocks_key = f"{doc_id}/parts/part_{part_idx:03d}/blocks"
        raw = await store.load_intermediate(doc_id, f"parts/part_{part_idx:03d}/blocks")
        if raw is None:
            log.warning(
                "merge_worker_missing_part_blocks",
                document_id=doc_id,
                part_index=part_idx,
            )
            continue

        blocks_data = raw.get("blocks", [])
        for bd in blocks_data:
            try:
                block = BlockObject.model_validate(bd)
                all_blocks.append(block)
            except Exception as exc:
                log.warning(
                    "merge_worker_block_parse_error",
                    document_id=doc_id,
                    part_index=part_idx,
                    error=str(exc),
                )

    if not all_blocks:
        log.error("merge_worker_no_blocks", document_id=doc_id)
        await tracker.close()
        return

    # 3) block_index 재정렬
    for i, block in enumerate(all_blocks):
        block.block_index = i

    # 4) 경계 중복 제거 (인접 파트 경계에서 동일 block_hash)
    deduped: list[BlockObject] = []
    seen_hashes: set[str] = set()
    for block in all_blocks:
        h = block.block_hash or ""
        if h and h in seen_hashes:
            log.debug("merge_dedup_removed", block_hash=h[:16])
            continue
        if h:
            seen_hashes.add(h)
        deduped.append(block)

    all_blocks = deduped
    for i, block in enumerate(all_blocks):
        block.block_index = i

    # 5) 전체 문서 KnowledgeCompiler (선택적)
    from src.common.config import settings as _cfg

    skip_val = getattr(_cfg, "SKIP_KNOWLEDGE_COMPILER", "false")
    skip_compiler = str(skip_val).lower() in ("true", "1", "yes")

    if not skip_compiler and llm_client is not None:
        try:
            from src.pipeline.enrichers.knowledge_compiler import KnowledgeCompiler
            from src.pipeline.models.document import ProcessingConfig

            proc_config = ProcessingConfig()
            compiler = KnowledgeCompiler(proc_config, llm_client=llm_client)
            document_text = "\n\n".join(b.content for b in all_blocks if b.content)

            all_blocks = await compiler.compile(
                blocks=all_blocks,
                document_text=document_text,
                document_title="",
            )
        except Exception as exc:
            log.warning(
                "merge_knowledge_compilation_failed",
                document_id=doc_id,
                error=str(exc),
            )

    # 5b) Document Type Classifier (자비스 시나리오 2, 2026-04-28)
    # extractor 후 + embedder 전. 신규 업로드의 의미적 유형을 LLM 1회로 분류해
    # processing_meta.document_type_classification + 각 block.metadata 에 주입.
    # non-critical: 실패해도 파이프라인 본류는 그대로 진행.
    if llm_client is not None and all_blocks:
        try:
            from src.pipeline.enrichers.document_type_classifier import (
                classify_and_store,
                derive_extension,
            )

            doc_text_sample = "\n\n".join(
                b.content for b in all_blocks[:5] if b.content
            )
            cls_result = await classify_and_store(
                document_id=event.document_id,
                title="",  # merge_worker 에는 title 컨텍스트가 없음 — DB 에서 읽도록 future 개선
                text_sample=doc_text_sample,
                file_extension=derive_extension(getattr(job, "source_path", "")),
                llm_client=llm_client,
            )
            if cls_result and cls_result.get("document_type"):
                doc_type = cls_result["document_type"]
                for block in all_blocks:
                    if block.metadata is None:
                        block.metadata = {}
                    block.metadata["document_type"] = doc_type
        except Exception as exc:
            log.warning(
                "merge_document_type_classify_failed",
                document_id=doc_id,
                error=str(exc),
            )

    # 6) DB 영속화
    try:
        from src.pipeline.workers.block_worker import _persist_blocks_to_db

        await _persist_blocks_to_db(
            document_id=event.document_id,
            repository_id=event.repository_id,
            blocks=all_blocks,
        )
    except Exception as exc:
        log.error(
            "merge_db_persist_failed",
            document_id=doc_id,
            error=str(exc),
        )

    # 7) Redis 캐시
    try:
        from src.pipeline.workers.block_worker import _store_blocks_intermediate

        await _store_blocks_intermediate(event.document_id, all_blocks)
    except Exception as exc:
        log.warning("merge_cache_failed", error=str(exc))

    # 8) 블럭 타입 통계
    block_types: dict[str, int] = {}
    for block in all_blocks:
        bt = block.block_type.value
        block_types[bt] = block_types.get(bt, 0) + 1

    # 9) DocumentBlockedEvent 발행 (기존 embed_worker가 소비)
    blocked_event = DocumentBlockedEvent(
        event_id=uuid4(),
        document_id=event.document_id,
        tenant_id=event.tenant_id,
        repository_id=event.repository_id,
        block_count=len(all_blocks),
        block_types=block_types,
        source_path=job.source_path,
    )
    await producer.send_and_wait(
        TOPIC_DOCUMENT_BLOCKED,
        value=blocked_event.model_dump_json().encode(),
    )

    # 10) Split job 완료 마킹
    await tracker.mark_merged(event.document_id)
    await tracker.close()

    elapsed_ms = int((time.monotonic() - merge_start) * 1000)
    log.info(
        "merge_worker_complete",
        document_id=doc_id,
        total_blocks=len(all_blocks),
        block_types=block_types,
        elapsed_ms=elapsed_ms,
    )
