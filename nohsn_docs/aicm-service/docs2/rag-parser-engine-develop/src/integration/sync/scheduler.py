"""동기화 스케줄러 — Cron 기반 주기적 동기화 실행."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.common.logging import get_logger
from src.integration.sync.base import BaseSyncConnector
from src.integration.sync.confluence import ConfluenceConnector
from src.integration.sync.models import (
    RemoteDocumentMeta,
    SyncMappingORM,
    SyncSourceORM,
    SyncSourceType,
    SyncStatus,
)
from src.integration.sync.sharepoint import SharePointConnector

log = get_logger(__name__)


def _create_connector(source: SyncSourceORM) -> BaseSyncConnector:
    """소스 타입에 따른 커넥터 인스턴스 생성."""
    if source.source_type == SyncSourceType.SHAREPOINT.value:
        return SharePointConnector(config=source.config)
    elif source.source_type == SyncSourceType.CONFLUENCE.value:
        return ConfluenceConnector(config=source.config)
    else:
        raise ValueError(f"지원하지 않는 소스 타입: {source.source_type}")


class SyncScheduler:
    """Cron 기반 동기화 스케줄러.

    등록된 동기화 소스를 주기적으로 확인하고,
    cron 표현식에 따라 동기화를 실행한다.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory
        self._running = False
        self._tasks: dict[UUID, asyncio.Task] = {}

    async def start(self) -> None:
        """스케줄러 시작. 배경 루프에서 소스들을 주기적으로 체크."""
        self._running = True
        log.info("sync_scheduler_started")

        while self._running:
            try:
                await self._check_and_dispatch()
            except Exception as e:
                log.error("sync_scheduler_loop_error", error=str(e))

            await asyncio.sleep(30)  # 30초마다 스케줄 체크

    async def stop(self) -> None:
        """스케줄러 중지."""
        self._running = False
        # 실행 중인 태스크 취소
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        log.info("sync_scheduler_stopped")

    async def trigger_sync(self, source_id: UUID) -> str:
        """수동 동기화 트리거."""
        async with self._session_factory() as session:
            source = await session.get(SyncSourceORM, source_id)
            if not source or not source.is_active:
                return "소스를 찾을 수 없거나 비활성 상태입니다."

            if source_id in self._tasks and not self._tasks[source_id].done():
                return "동기화가 이미 실행 중입니다."

            task = asyncio.create_task(self._run_sync(source_id))
            self._tasks[source_id] = task
            return "동기화가 트리거되었습니다."

    async def _check_and_dispatch(self) -> None:
        """활성 소스 중 실행 시간이 된 것을 디스패치."""
        async with self._session_factory() as session:
            stmt = select(SyncSourceORM).where(
                SyncSourceORM.is_active.is_(True),
                SyncSourceORM.last_status != SyncStatus.RUNNING.value,
            )
            result = await session.execute(stmt)
            sources = list(result.scalars().all())

        now = datetime.now(timezone.utc)

        for source in sources:
            # 이미 실행 중이면 스킵
            if source.id in self._tasks and not self._tasks[source.id].done():
                continue

            # cron 스케줄 확인
            if self._should_run(source, now):
                log.info(
                    "sync_dispatch",
                    source_id=str(source.id),
                    name=source.name,
                    source_type=source.source_type,
                )
                task = asyncio.create_task(self._run_sync(source.id))
                self._tasks[source.id] = task

    def _should_run(self, source: SyncSourceORM, now: datetime) -> bool:
        """cron 표현식에 따라 실행 여부 결정."""
        try:
            cron = croniter(source.schedule_cron, source.last_synced_at or now)
            next_run = cron.get_next(datetime)
            # timezone-aware 비교를 위해 변환
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=timezone.utc)
            return now >= next_run
        except (ValueError, KeyError):
            log.warning(
                "invalid_cron_expression",
                source_id=str(source.id),
                cron=source.schedule_cron,
            )
            return False

    async def _run_sync(self, source_id: UUID) -> None:
        """단일 소스 동기화 실행."""
        async with self._session_factory() as session:
            source = await session.get(SyncSourceORM, source_id)
            if not source:
                return

            # 상태를 RUNNING으로 갱신
            await self._update_status(session, source_id, SyncStatus.RUNNING)
            await session.commit()

        connector: BaseSyncConnector | None = None
        try:
            connector = _create_connector(source)
            await connector.authenticate()

            # 증분 동기화 또는 전체 동기화
            if source.last_synced_at:
                changed_docs = await connector.get_changes_since(source.last_synced_at)
            else:
                changed_docs = await connector.list_documents()

            synced_count = await self._process_documents(
                source_id=source_id,
                connector=connector,
                documents=changed_docs,
            )

            async with self._session_factory() as session:
                await self._update_status(
                    session,
                    source_id,
                    SyncStatus.SUCCESS,
                    synced_count=synced_count,
                )
                await session.commit()

            log.info(
                "sync_complete",
                source_id=str(source_id),
                synced_count=synced_count,
            )

        except Exception as e:
            log.error(
                "sync_failed",
                source_id=str(source_id),
                error=str(e),
            )
            async with self._session_factory() as session:
                await self._update_status(
                    session,
                    source_id,
                    SyncStatus.FAILED,
                    error=str(e),
                )
                await session.commit()

        finally:
            if connector:
                await connector.close()
            # 태스크 정리
            self._tasks.pop(source_id, None)

    async def _process_documents(
        self,
        source_id: UUID,
        connector: BaseSyncConnector,
        documents: list[RemoteDocumentMeta],
    ) -> int:
        """변경된 문서를 다운로드하고 AICM 파이프라인에 전달."""
        synced_count = 0

        async with self._session_factory() as session:
            # 기존 매핑 조회
            stmt = select(SyncMappingORM).where(
                SyncMappingORM.sync_source_id == source_id
            )
            result = await session.execute(stmt)
            existing_mappings = {
                m.remote_id: m for m in result.scalars().all()
            }

            for doc in documents:
                try:
                    file_bytes = await connector.download(doc.remote_id)

                    # TODO: AICM 업로드 파이프라인에 전달
                    # document_id = await upload_service.upload(file_bytes, ...)

                    # 매핑 생성 또는 갱신
                    if doc.remote_id in existing_mappings:
                        mapping = existing_mappings[doc.remote_id]
                        mapping.remote_modified_at = doc.modified_at
                        mapping.synced_at = datetime.now(timezone.utc)
                        mapping.remote_name = doc.name
                    else:
                        mapping = SyncMappingORM(
                            sync_source_id=source_id,
                            remote_id=doc.remote_id,
                            remote_name=doc.name,
                            remote_modified_at=doc.modified_at,
                            synced_at=datetime.now(timezone.utc),
                        )
                        session.add(mapping)

                    synced_count += 1

                except Exception as e:
                    log.warning(
                        "sync_document_failed",
                        source_id=str(source_id),
                        remote_id=doc.remote_id,
                        error=str(e),
                    )

            await session.commit()

        return synced_count

    async def _update_status(
        self,
        session: AsyncSession,
        source_id: UUID,
        status: SyncStatus,
        synced_count: int | None = None,
        error: str | None = None,
    ) -> None:
        """소스 동기화 상태 갱신."""
        values: dict = {"last_status": status.value}

        if status in (SyncStatus.SUCCESS, SyncStatus.FAILED):
            values["last_synced_at"] = datetime.now(timezone.utc)

        if synced_count is not None:
            values["total_synced"] = SyncSourceORM.total_synced + synced_count

        if error is not None:
            values["last_error"] = error
        elif status == SyncStatus.SUCCESS:
            values["last_error"] = None

        stmt = (
            update(SyncSourceORM)
            .where(SyncSourceORM.id == source_id)
            .values(**values)
        )
        await session.execute(stmt)
