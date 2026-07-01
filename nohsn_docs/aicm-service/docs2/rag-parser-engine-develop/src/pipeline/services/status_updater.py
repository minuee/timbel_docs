"""파이프라인 상태 업데이터 — 각 단계에서 Document.status + processing_meta 를 DB에 반영.

문제: 기존 워커들은 Kafka 이벤트만 발행하고 DB를 직접 업데이트하지 않아서,
프론트엔드에서 폴링하면 항상 'processing' 만 표시되었다.

이 서비스가 각 파이프라인 단계 전후에 호출되어:
1. Document.status 를 세부 단계로 업데이트 (parsing → chunking → embedding → active)
2. Document.processing_meta 에 단계별 정보를 누적 저장
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from src.common.constants import (
    DOC_STATUS_ACTIVE,
    DOC_STATUS_ARCHIVED,
    DOC_STATUS_FAILED,
    DOC_STATUS_PENDING_REVIEW,
    DOC_STATUS_PROCESSING,
    STAGE_CHUNKING,
    STAGE_COMPLETED,
    STAGE_EMBEDDING,
    STAGE_FAILED,
    STAGE_PARSING,
    STAGE_UPLOADED,
)
from src.common.logging import get_logger

log = get_logger(__name__)


class PipelineStatusUpdater:
    """파이프라인 진행 상태를 DB에 실시간 반영한다.

    각 워커에서 단계 시작/완료 시 호출한다.
    DB 세션을 직접 생성하여 워커의 Kafka 처리와 독립적으로 커밋한다.
    """

    async def update_stage(
        self,
        document_id: UUID,
        stage: str,
        status: str = DOC_STATUS_PROCESSING,
        meta_update: dict[str, Any] | None = None,
        preserve_active: bool = True,
    ) -> None:
        """문서의 파이프라인 단계와 메타데이터를 업데이트한다.

        Parameters
        ----------
        document_id : UUID
            대상 문서 ID
        stage : str
            현재 단계 (parsing, chunking, embedding, completed, failed)
        status : str
            문서 상태 (processing, active, failed)
        meta_update : dict
            processing_meta 에 병합할 데이터
        preserve_active : bool
            True 이면 현재 DB 가 active 인 경우 status 덮어쓰지 않음 (meta 만 갱신).
            파이프라인이 재처리(active→processing→...)될 때는 호출측이 별도로 status 를
            active 밖으로 먼저 바꿔놔야 한다. 기본 True — embedding 완료가 실수로
            active 를 pending_review 로 강등시키는 사고 방지.
        """
        try:
            import json as _json

            from sqlalchemy import text

            from src.core.database import async_session_factory

            # JSONB merge로 기존 필드를 보존하면서 업데이트
            patch: dict[str, Any] = {
                "current_stage": stage,
                f"stage_{stage}_at": time.time(),
            }
            if meta_update:
                patch.update(meta_update)

            # 총 처리 시간 계산이 필요하면 현재 meta에서 start_time 조회
            if stage in (STAGE_COMPLETED, STAGE_FAILED):
                async with async_session_factory() as session:
                    result = await session.execute(
                        text("SELECT processing_meta FROM documents WHERE id = :did"),
                        {"did": str(document_id)},
                    )
                    row = result.fetchone()
                    current_meta = (row[0] if row else None) or {}
                    start_time = current_meta.get("stage_parsing_at") or current_meta.get("started_at")
                    if start_time:
                        patch["total_time_ms"] = int((time.time() - start_time) * 1000)

            # SQL: active 강등 방지 + archived(삭제) 부활 방지 가드.
            # - preserve_active=True 이고 새 status 가 active 가 아니면, 현재 DB 가 active 인
            #   문서는 status 를 바꾸지 않고 meta 만 갱신한다.
            # - archived 는 터미널(삭제) 상태 — 진행/지연 워커가 늦게 완료 신호를 보내도
            #   archived 를 벗어나지 못하게 항상 보존한다(write-after-delete 부활 방지).
            if preserve_active and status != DOC_STATUS_ACTIVE:
                sql = (
                    "UPDATE documents "
                    "SET status = CASE WHEN status IN ('active', 'archived') THEN status ELSE :status END, "
                    "    processing_meta = COALESCE(processing_meta, '{}') || CAST(:patch AS jsonb) "
                    "WHERE id = :did"
                )
            else:
                sql = (
                    "UPDATE documents "
                    "SET status = CASE WHEN status = 'archived' THEN status ELSE :status END, "
                    "    processing_meta = COALESCE(processing_meta, '{}') || CAST(:patch AS jsonb) "
                    "WHERE id = :did"
                )

            async with async_session_factory() as session:
                await session.execute(
                    text(sql),
                    {"did": str(document_id), "status": status, "patch": _json.dumps(patch)},
                )
                await session.commit()

                log.info(
                    "pipeline_status_updated",
                    document_id=str(document_id),
                    stage=stage,
                    status=status,
                    preserve_active=preserve_active,
                )

        except ImportError:
            log.warning("database_not_available_status_update_skipped")
        except Exception as exc:
            # 상태 업데이트 실패가 파이프라인을 중단시키면 안 됨
            log.warning(
                "pipeline_status_update_failed",
                document_id=str(document_id),
                stage=stage,
                error=str(exc),
            )

    async def update_progress(
        self,
        document_id: UUID,
        stage: str,
        progress_percent: int,
        stage_detail: str = "",
    ) -> None:
        """파이프라인 진행률 업데이트.

        Parameters
        ----------
        document_id : UUID
            대상 문서 ID
        stage : str
            현재 단계 (parsing, chunking, embedding 등)
        progress_percent : int
            진행률 (0-100)
        stage_detail : str
            사람이 읽을 수 있는 설명
        """
        await self.update_stage(
            document_id,
            stage=stage,
            meta_update={
                "progress_percent": max(0, min(100, progress_percent)),
                "stage_detail": stage_detail,
            },
        )

    async def mark_stage_complete(
        self,
        document_id: UUID,
        stage: str,
        elapsed_ms: int,
    ) -> None:
        """스테이지 완료 기록.

        Parameters
        ----------
        document_id : UUID
            대상 문서 ID
        stage : str
            완료된 스테이지 이름
        elapsed_ms : int
            소요 시간 (밀리초)
        """
        try:
            import json as _json

            from sqlalchemy import text

            from src.core.database import async_session_factory

            async with async_session_factory() as session:
                # stages_completed 배열에 새 항목 추가 (JSONB 연산)
                result = await session.execute(
                    text("SELECT processing_meta FROM documents WHERE id = :did"),
                    {"did": str(document_id)},
                )
                row = result.fetchone()
                current_meta = (row[0] if row else None) or {}

                stages_completed: list[dict[str, Any]] = current_meta.get(
                    "stages_completed", []
                )
                stages_completed.append(
                    {
                        "name": stage,
                        "elapsed_ms": elapsed_ms,
                        "completed_at": time.time(),
                    }
                )

                patch: dict[str, Any] = {
                    "stages_completed": stages_completed,
                }

                await session.execute(
                    text(
                        "UPDATE documents "
                        "SET processing_meta = COALESCE(processing_meta, '{}') || CAST(:patch AS jsonb) "
                        "WHERE id = :did"
                    ),
                    {"did": str(document_id), "patch": _json.dumps(patch)},
                )
                await session.commit()

                log.info(
                    "stage_complete_recorded",
                    document_id=str(document_id),
                    stage=stage,
                    elapsed_ms=elapsed_ms,
                )
        except Exception as exc:
            log.warning(
                "mark_stage_complete_failed",
                document_id=str(document_id),
                stage=stage,
                error=str(exc),
            )

    async def mark_parsing_start(self, document_id: UUID) -> None:
        """파싱 시작."""
        await self.update_stage(
            document_id,
            stage=STAGE_PARSING,
            meta_update={"started_at": time.time()},
        )

    async def mark_parsing_complete(
        self,
        document_id: UUID,
        page_count: int = 0,
        table_count: int = 0,
        image_count: int = 0,
        difficulty: str = "",
        difficulty_score: float = 0.0,
    ) -> None:
        """파싱 완료."""
        await self.update_stage(
            document_id,
            stage=STAGE_PARSING,
            meta_update={
                "page_count": page_count,
                "table_count": table_count,
                "image_count": image_count,
                "difficulty": difficulty,
                "difficulty_score": difficulty_score,
                "parsing_complete": True,
            },
        )

    async def mark_chunking_start(self, document_id: UUID) -> None:
        """청킹/블럭 세그멘테이션 시작."""
        await self.update_stage(document_id, stage=STAGE_CHUNKING)

    async def mark_chunking_complete(
        self,
        document_id: UUID,
        chunk_count: int = 0,
        strategy: str = "",
        block_types: dict | None = None,
    ) -> None:
        """청킹/블럭 세그멘테이션 완료."""
        meta: dict[str, Any] = {
            "chunk_count": chunk_count,
            "chunking_strategy": strategy,
            "chunking_complete": True,
        }
        if block_types:
            meta["block_types"] = block_types
        await self.update_stage(document_id, stage=STAGE_CHUNKING, meta_update=meta)

    async def mark_blocking_start(self, document_id: UUID) -> None:
        """블럭 세그멘테이션(3-stage LLM) 시작."""
        await self.update_stage(document_id, stage="blocking")

    async def mark_blocking_complete(
        self,
        document_id: UUID,
        block_count: int = 0,
        block_types: dict | None = None,
    ) -> None:
        """블럭 세그멘테이션 완료.

        pipeline-status 엔드포인트가 blocking_complete 또는 total_blocks>0 로 완료 판단.
        """
        meta: dict[str, Any] = {
            "blocking_complete": True,
            "total_blocks": block_count,
        }
        if block_types:
            meta["block_types"] = block_types
        await self.update_stage(document_id, stage="blocking", meta_update=meta)

    async def mark_enriching_start(self, document_id: UUID) -> None:
        """Knowledge Compiler/Enricher 시작 (캡션·메타데이터·온톨로지 LLM 보강)."""
        await self.update_stage(document_id, stage="enriching")

    async def mark_enriching_complete(
        self,
        document_id: UUID,
        enriched_count: int = 0,
    ) -> None:
        """Enrichment 완료."""
        await self.update_stage(
            document_id,
            stage="enriching",
            meta_update={
                "enriching_complete": True,
                "enriched_count": enriched_count,
            },
        )

    async def mark_embedding_start(self, document_id: UUID) -> None:
        """임베딩 시작."""
        await self.update_stage(document_id, stage=STAGE_EMBEDDING)

    async def mark_embedding_complete(
        self,
        document_id: UUID,
        indexed_count: int = 0,
        collection_name: str = "",
    ) -> None:
        """임베딩 완료 → pending_review 로 전환 (단, 이미 active 면 active 유지).

        preserve_active=True 이므로 update_stage 가 active 문서를 강등하지 않는다.
        인덱스 payload 는 update_stage 직후의 실제 DB status 를 읽어 그에 맞춰 동기화
        (active 그대로 유지인 경우에도 payload 가 pending_review 로 잘못 덮이지 않도록).
        """
        await self.update_stage(
            document_id,
            stage="pending_review",
            status=DOC_STATUS_PENDING_REVIEW,
            meta_update={
                "indexed_count": indexed_count,
                "collection_name": collection_name,
                "embedding_complete": True,
                "current_stage": "pending_review",
            },
            preserve_active=True,
        )
        # 인덱스 payload 를 실제 DB status 로 동기화 (active 보존 케이스 포함)
        try:
            from sqlalchemy import text

            from src.core.database import async_session_factory
            from src.search.payload_sync import sync_document_status

            async with async_session_factory() as _sess:
                row = await _sess.execute(
                    text("SELECT status FROM documents WHERE id = :did"),
                    {"did": str(document_id)},
                )
                current_status = row.scalar() or DOC_STATUS_PENDING_REVIEW
                await sync_document_status(document_id, current_status, _sess)
        except Exception as _exc:
            log.warning(
                "mark_embedding_complete_payload_sync_failed",
                document_id=str(document_id),
                error=str(_exc),
            )

    async def check_control_signal(self, document_id: UUID) -> str | None:
        """파이프라인 제어 신호를 확인한다.

        삭제(archived)된 문서는 진행/지연 워커가 artifact(qdrant/ES/DB)를 재생성하거나
        문서를 부활시키지 못하도록 'cancel' 로 취급한다(write-after-delete 방지).

        Returns
        -------
        str | None
            'cancel', 'pause', 또는 None
        """
        try:
            from sqlalchemy import text

            from src.core.database import async_session_factory

            async with async_session_factory() as session:
                result = await session.execute(
                    text(
                        "SELECT status, processing_meta->>'control_signal' "
                        "FROM documents WHERE id = :did"
                    ),
                    {"did": str(document_id)},
                )
                row = result.fetchone()
                doc_status = row[0] if row else None
                signal = row[1] if row else None
                # 삭제된 문서는 명시적 control_signal 이 없어도 cancel 로 중단시킨다.
                if doc_status == DOC_STATUS_ARCHIVED:
                    signal = "cancel"
                if signal:
                    log.info(
                        "control_signal_detected",
                        document_id=str(document_id),
                        signal=signal,
                    )
                return signal
        except Exception as exc:
            log.warning(
                "control_signal_check_failed",
                document_id=str(document_id),
                error=str(exc),
            )
            return None

    async def mark_failed(
        self,
        document_id: UUID,
        stage: str,
        error: str,
    ) -> None:
        """파이프라인 실패."""
        await self.update_stage(
            document_id,
            stage=STAGE_FAILED,
            status=DOC_STATUS_FAILED,
            meta_update={
                "failed_stage": stage,
                "error_message": error[:500],
            },
        )


# 싱글톤 인스턴스
_status_updater: PipelineStatusUpdater | None = None


def get_status_updater() -> PipelineStatusUpdater:
    """PipelineStatusUpdater 싱글톤을 반환한다."""
    global _status_updater
    if _status_updater is None:
        _status_updater = PipelineStatusUpdater()
    return _status_updater
