"""문서 처리 코디네이터 -- 대용량 문서의 안정적 순차 처리.

전략:
1. 문서를 MinIO에 스테이징
2. 페이지 범위별 배치 파싱 (기본 20페이지씩)
3. 배치별 세그멘테이션 -> 블럭 생성
4. 체크포인트 저장 (배치 완료마다)
5. 전체 완료 후 KnowledgeCompiler 보강
6. 장애 시 체크포인트에서 재개
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from uuid import UUID

from src.common.logging import get_logger
from src.pipeline.enrichers.knowledge_compiler import KnowledgeCompiler
from src.pipeline.models.block import BlockObject
from src.pipeline.models.document import ProcessingConfig
from src.pipeline.models.parse_result import ParseResult
from src.pipeline.parsers.router import detect_format, select_parser
from src.pipeline.processing.models import ProcessingResult
from src.pipeline.segmenters.base import BaseSegmenter
from src.pipeline.segmenters.fallback_segmenter import FallbackSegmenter
from src.pipeline.segmenters.llm_block_segmenter import LLMBlockSegmenter

log = get_logger(__name__)


class DocumentProcessor:
    """대용량 문서 처리 코디네이터.

    Args:
        config: 파이프라인 설정
        object_store: MinIO 스토리지 (None이면 인메모리 모드)
        llm_client: LLM 클라이언트 (None이면 FallbackSegmenter 사용)
    """

    # 배치 크기 (페이지 수)
    BATCH_SIZE = 20

    def __init__(
        self,
        config: ProcessingConfig,
        object_store: Any | None = None,
        llm_client: object | None = None,
    ) -> None:
        self.config = config
        self._object_store = object_store
        self._llm_client = llm_client
        # 인메모리 폴백 캐시 (object_store 없을 때)
        self._checkpoint_cache: dict[str, dict] = {}
        self._block_cache: dict[str, list[dict]] = {}

    async def process(
        self,
        document_id: UUID,
        tenant_id: UUID,
        repository_id: UUID,
        source_path: str,
        title: str = "",
        source_file_url: str = "",
        parse_map: object | None = None,
        doc_type: str = "",
    ) -> ProcessingResult:
        """문서를 처리한다. 체크포인트가 있으면 이어서 처리.

        Parameters
        ----------
        document_id : UUID
            문서 고유 ID
        tenant_id : UUID
            테넌트 ID
        repository_id : UUID
            저장소 ID
        source_path : str
            원본 파일 경로
        title : str
            문서 제목 (KnowledgeCompiler 에 전달)
        source_file_url : str
            블럭 SourceLocation.file_url 에 채울 URL (T14)
        parse_map : ParseMap | None
            LayoutMapper 가 생성한 표/도표 hint 맵 (T14)
        doc_type : str
            Stage1 에서 감지한 문서 유형 slug (T14)

        Returns
        -------
        ProcessingResult
            블럭 목록, 통계, 오류 포함

        D34 §1: 직접 호출 path (CLI / scripts) 보호용 *방어적 이중 wrap*.
        """
        # D34 §1 — bind_system_scope wrap (방어적 이중 wrap). tenant_id 명시 →
        # write 정책 통과.
        # D35 §1 — tenant_id 누락 (CLI / 잘못된 caller) 시 per-event rebind failure
        # metric inc. UUID 타입이지만 falsy (None / NULL UUID) 방어.
        from src.api.middleware.rls_context import bind_system_scope

        if not tenant_id:
            try:
                from src.common.metrics import (
                    REBIND_SITE_DOCUMENT_PROCESSOR,
                    inc_kms_worker_rebind_failure,
                )

                inc_kms_worker_rebind_failure(REBIND_SITE_DOCUMENT_PROCESSOR, "any")
            except Exception:  # noqa: BLE001
                pass
            # write 시 RLS 정책이 차단 — 본 site 는 metric 만 inc 후 진입.
        # GPT-5 §1 권고: tenant_id None 시 allow_null_tenant=True 명시 — 의도된
        # null-tenant 컨텍스트임을 분명화 (write 는 RLS 정책이 차단).
        if tenant_id:
            async with bind_system_scope(str(tenant_id)):
                return await self._process_inner(
                    document_id, tenant_id, repository_id, source_path,
                    title=title,
                    source_file_url=source_file_url,
                    parse_map=parse_map,
                    doc_type=doc_type,
                )
        else:
            async with bind_system_scope(None, allow_null_tenant=True):
                return await self._process_inner(
                    document_id, tenant_id, repository_id, source_path,
                    title=title,
                    source_file_url=source_file_url,
                    parse_map=parse_map,
                    doc_type=doc_type,
                )

    async def _process_inner(
        self,
        document_id: UUID,
        tenant_id: UUID,
        repository_id: UUID,
        source_path: str,
        title: str = "",
        source_file_url: str = "",
        parse_map: object | None = None,
        doc_type: str = "",
    ) -> ProcessingResult:
        """D34 §1 — bind_system_scope wrap 안에서 실제 로직."""
        start_ts = time.monotonic()
        errors: list[str] = []

        # 1. 체크포인트 확인
        checkpoint = await self._load_checkpoint(document_id)
        if checkpoint:
            log.info(
                "checkpoint_found",
                document_id=str(document_id),
                last_page=checkpoint.get("last_completed_page"),
            )

        # 2. 파싱
        try:
            parse_result = await self._parse_document(source_path)
        except Exception as exc:
            log.error("parse_failed", document_id=str(document_id), error=str(exc))
            return ProcessingResult(
                document_id=document_id,
                total_pages=0,
                processing_mode="single",
                errors=[f"parse_failed: {exc}"],
                elapsed_ms=_elapsed_ms(start_ts),
            )

        # 3. 문서 크기 판단
        total_pages = len(parse_result.pages)
        is_large = total_pages > self.BATCH_SIZE

        log.info(
            "processing_start",
            document_id=str(document_id),
            total_pages=total_pages,
            mode="batch" if is_large else "single",
        )

        # 4. 세그멘테이션
        try:
            if is_large:
                blocks = await self._process_in_batches(
                    parse_result, document_id, checkpoint,
                    source_file_url=source_file_url,
                    parse_map=parse_map,
                    doc_type=doc_type,
                )
            else:
                blocks = await self._process_single(
                    parse_result, document_id,
                    source_file_url=source_file_url,
                    parse_map=parse_map,
                    doc_type=doc_type,
                )
        except Exception as exc:
            log.error("segmentation_failed", document_id=str(document_id), error=str(exc))
            errors.append(f"segmentation_failed: {exc}")
            blocks = []

        # 5. KnowledgeCompiler 보강 (전체 블럭에 대해 1회)
        if blocks:
            try:
                blocks = await self._enrich(blocks, parse_result.raw_text, title)
            except Exception as exc:
                log.warning("enrich_failed", document_id=str(document_id), error=str(exc))
                errors.append(f"enrich_failed: {exc}")

        # 5a. Document Type Classifier (자비스 시나리오 2, 2026-04-28)
        # extractor 후 + embedder 전 — 신규 업로드 문서를 LLM 1회로 의미적 분류해
        # processing_meta + 각 block.metadata 에 document_type 주입. 검색 시간/유형
        # 필터 활용 기반. non-critical: 실패해도 파이프라인 본류 진행.
        if blocks:
            try:
                await self._classify_document_type(
                    document_id=document_id,
                    blocks=blocks,
                    title=title,
                    text_sample=parse_result.raw_text or "",
                    source_path=source_path,
                )
            except Exception as exc:
                log.warning(
                    "document_type_classify_failed",
                    document_id=str(document_id),
                    error=str(exc),
                )

        # 5b. Wave Wire-up Final (KMS-Plus, 2026-04-25):
        #     env flag 기반 qa_pair_extractor + table_normalizer 단계.
        #     호출자 0건이던 모듈을 실 wire — 검색 품질 P0 (Phase 12).
        #     기본값 false → 기존 파이프라인 회귀 0.
        if blocks:
            try:
                blocks = await self._maybe_extract_qa_pairs(blocks)
            except Exception as exc:  # noqa: BLE001
                log.warning("qa_pair_step_failed", document_id=str(document_id), error=str(exc))
                errors.append(f"qa_pair_step_failed: {exc}")
            try:
                blocks = await self._maybe_normalize_tables(blocks)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "table_normalize_step_failed",
                    document_id=str(document_id),
                    error=str(exc),
                )
                errors.append(f"table_normalize_step_failed: {exc}")

        # 6. 체크포인트 정리
        await self._clear_checkpoint(document_id)

        elapsed = _elapsed_ms(start_ts)
        log.info(
            "processing_complete",
            document_id=str(document_id),
            blocks=len(blocks),
            total_pages=total_pages,
            elapsed_ms=elapsed,
        )

        return ProcessingResult(
            document_id=document_id,
            blocks=blocks,
            total_pages=total_pages,
            processing_mode="batch" if is_large else "single",
            errors=errors,
            elapsed_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # 배치 처리
    # ------------------------------------------------------------------

    async def _process_in_batches(
        self,
        parse_result: ParseResult,
        document_id: UUID,
        checkpoint: dict | None,
        source_file_url: str = "",
        parse_map: object | None = None,
        doc_type: str = "",
    ) -> list[BlockObject]:
        """페이지 범위별 배치 처리. 배치마다 체크포인트 저장."""
        all_blocks: list[BlockObject] = []
        start_page = 0

        if checkpoint:
            start_page = checkpoint.get("last_completed_page", 0)
            cached = await self._load_intermediate_blocks(document_id)
            if cached:
                all_blocks = cached
                log.info(
                    "checkpoint_resume",
                    document_id=str(document_id),
                    start_page=start_page,
                    cached_blocks=len(cached),
                )

        pages = parse_result.pages
        total = len(pages)

        for batch_start in range(start_page, total, self.BATCH_SIZE):
            batch_end = min(batch_start + self.BATCH_SIZE, total)
            batch_pages = pages[batch_start:batch_end]

            log.info(
                "batch_processing",
                document_id=str(document_id),
                batch=f"{batch_start + 1}-{batch_end}",
                total=total,
            )

            # 배치 ParseResult 생성
            batch_result = ParseResult(
                pages=batch_pages,
                tables=[t for p in batch_pages for t in p.tables],
                images=[i for p in batch_pages for i in p.images],
                source_file_path=parse_result.source_file_path,
            )

            # 세그멘테이션
            try:
                batch_blocks = await self._segment(
                    batch_result, document_id,
                    source_file_url=source_file_url,
                    parse_map=parse_map,
                    doc_type=doc_type,
                )
                all_blocks.extend(batch_blocks)
            except Exception as exc:
                log.error(
                    "batch_segment_failed",
                    document_id=str(document_id),
                    batch=f"{batch_start + 1}-{batch_end}",
                    error=str(exc),
                )
                # 이 배치를 건너뛰고 계속 진행
                continue

            # 체크포인트 저장
            await self._save_checkpoint(document_id, {
                "last_completed_page": batch_end,
                "block_count": len(all_blocks),
                "total_pages": total,
            })

            # 중간 블럭 저장
            await self._save_intermediate_blocks(document_id, all_blocks)

        # block_index 재정렬
        for i, block in enumerate(all_blocks):
            block.block_index = i

        return all_blocks

    # ------------------------------------------------------------------
    # 단건 처리
    # ------------------------------------------------------------------

    async def _process_single(
        self,
        parse_result: ParseResult,
        document_id: UUID,
        source_file_url: str = "",
        parse_map: object | None = None,
        doc_type: str = "",
    ) -> list[BlockObject]:
        """소규모 문서 단건 처리 (배치 불필요)."""
        blocks = await self._segment(
            parse_result, document_id,
            source_file_url=source_file_url,
            parse_map=parse_map,
            doc_type=doc_type,
        )
        for i, block in enumerate(blocks):
            block.block_index = i
        return blocks

    # ------------------------------------------------------------------
    # 파싱
    # ------------------------------------------------------------------

    async def _parse_document(self, source_path: str) -> ParseResult:
        """파서 라우터를 통해 문서를 파싱한다."""
        fmt = detect_format(source_path)
        parser = select_parser(fmt, source_path)
        result = await parser.parse()
        log.info(
            "document_parsed",
            format=fmt.value,
            pages=len(result.pages),
            tables=len(result.tables),
            images=len(result.images),
        )
        return result

    # ------------------------------------------------------------------
    # 세그멘테이션
    # ------------------------------------------------------------------

    async def _segment(
        self,
        parse_result: ParseResult,
        document_id: UUID,
        source_file_url: str = "",
        parse_map: object | None = None,
        doc_type: str = "",
    ) -> list[BlockObject]:
        """ParseResult 를 블럭으로 분할한다.

        LLM 클라이언트가 있으면 LLMBlockSegmenter (source_file_url/parse_map/doc_type 전달),
        없으면 FallbackSegmenter (기존 인터페이스).
        """
        segmenter = self._create_segmenter()
        if isinstance(segmenter, LLMBlockSegmenter):
            return await segmenter.segment(
                parse_result,
                document_id=document_id,
                parse_map=parse_map,
                source_file_url=source_file_url,
                doc_type=doc_type,
            )
        return await segmenter.segment(parse_result, document_id=document_id, source_file_url=source_file_url)

    def _create_segmenter(self) -> BaseSegmenter:
        """세그멘터 인스턴스를 생성한다."""
        if self._llm_client is not None:
            try:
                return LLMBlockSegmenter(self.config, llm_client=self._llm_client)
            except Exception as exc:
                log.warning("llm_segmenter_init_failed", error=str(exc))

        return FallbackSegmenter(self.config)

    # ------------------------------------------------------------------
    # KnowledgeCompiler 보강
    # ------------------------------------------------------------------

    async def _enrich(
        self,
        blocks: list[BlockObject],
        document_text: str,
        title: str,
    ) -> list[BlockObject]:
        """KnowledgeCompiler 로 블럭을 보강한다."""
        compiler = KnowledgeCompiler(self.config, llm_client=self._llm_client)
        return await compiler.compile(
            blocks=blocks,
            document_text=document_text,
            document_title=title,
        )

    # ------------------------------------------------------------------
    # Document Type Classifier (자비스 시나리오 2, 2026-04-28)
    # ------------------------------------------------------------------

    async def _classify_document_type(
        self,
        *,
        document_id: UUID,
        blocks: list[BlockObject],
        title: str,
        text_sample: str,
        source_path: str,
    ) -> None:
        """문서 유형을 LLM 1회로 분류해 processing_meta + block.metadata 에 저장.

        ``KMS_DOC_TYPE_CLASSIFY_ENABLED=false`` 면 no-op (helper 가 자체 처리).
        DB 저장 실패해도 in-memory block.metadata 는 갱신 — 다운스트림 embed
        worker 가 Qdrant payload 에 포함시킬 수 있음.
        """
        from src.pipeline.enrichers.document_type_classifier import (
            classify_and_store,
            derive_extension,
        )

        result = await classify_and_store(
            document_id=document_id,
            title=title,
            text_sample=text_sample,
            file_extension=derive_extension(source_path),
            llm_client=self._llm_client,
        )
        if not result:
            return

        # 각 block 의 metadata 에도 주입 — Qdrant payload 동기화 시 같이 흘러감.
        doc_type = result.get("document_type")
        if doc_type:
            for block in blocks:
                if block.metadata is None:
                    block.metadata = {}
                block.metadata["document_type"] = doc_type

    # ------------------------------------------------------------------
    # 체크포인트 관리
    # ------------------------------------------------------------------

    async def _save_checkpoint(self, document_id: UUID, data: dict) -> None:
        """체크포인트를 저장한다 (MinIO 또는 인메모리)."""
        key = self._checkpoint_key(document_id)
        try:
            if self._object_store is not None:
                await self._object_store.save_checkpoint(key, data)
            else:
                self._checkpoint_cache[key] = data
            log.debug("checkpoint_saved", document_id=str(document_id), data=data)
        except Exception as exc:
            log.warning("checkpoint_save_failed", document_id=str(document_id), error=str(exc))

    async def _load_checkpoint(self, document_id: UUID) -> dict | None:
        """체크포인트를 로드한다."""
        key = self._checkpoint_key(document_id)
        try:
            if self._object_store is not None:
                return await self._object_store.load_checkpoint(key)
            return self._checkpoint_cache.get(key)
        except Exception as exc:
            log.warning("checkpoint_load_failed", document_id=str(document_id), error=str(exc))
            return None

    async def _clear_checkpoint(self, document_id: UUID) -> None:
        """체크포인트를 삭제한다 (처리 완료 후)."""
        key = self._checkpoint_key(document_id)
        try:
            if self._object_store is not None:
                await self._object_store.delete_checkpoint(key)
            else:
                self._checkpoint_cache.pop(key, None)
            log.debug("checkpoint_cleared", document_id=str(document_id))
        except Exception as exc:
            log.warning("checkpoint_clear_failed", document_id=str(document_id), error=str(exc))

    # ------------------------------------------------------------------
    # 중간 블럭 저장/로드
    # ------------------------------------------------------------------

    async def _save_intermediate_blocks(
        self,
        document_id: UUID,
        blocks: list[BlockObject],
    ) -> None:
        """중간 블럭 목록을 저장한다 (장애 복구용)."""
        key = self._intermediate_key(document_id)
        try:
            serialized = [b.model_dump(mode="json", exclude={"dense_vector", "sparse_vector"}) for b in blocks]
            if self._object_store is not None:
                # ObjectStore.save_intermediate(document_id, stage, data)
                await self._object_store.save_intermediate(
                    str(document_id),
                    "blocked",
                    {"blocks": serialized},
                )
            else:
                self._block_cache[key] = serialized
            log.debug("intermediate_blocks_saved", document_id=str(document_id), count=len(blocks))
        except Exception as exc:
            log.warning(
                "intermediate_blocks_save_failed",
                document_id=str(document_id),
                error=str(exc),
            )

    async def _load_intermediate_blocks(
        self,
        document_id: UUID,
    ) -> list[BlockObject] | None:
        """중간 블럭 목록을 로드한다."""
        key = self._intermediate_key(document_id)
        try:
            if self._object_store is not None:
                # ObjectStore.load_intermediate(document_id, stage)
                payload = await self._object_store.load_intermediate(
                    str(document_id), "blocked"
                )
                raw = payload.get("blocks") if isinstance(payload, dict) else payload
            else:
                raw = self._block_cache.get(key)

            if raw is None:
                return None

            return [BlockObject.model_validate(item) for item in raw]
        except Exception as exc:
            log.warning(
                "intermediate_blocks_load_failed",
                document_id=str(document_id),
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # Wave Wire-up Final — qa_pair_extractor / table_normalizer
    # ------------------------------------------------------------------

    async def _maybe_extract_qa_pairs(
        self, blocks: list[BlockObject]
    ) -> list[BlockObject]:
        """env flag KMS_QA_EXTRACT_ENABLED=true 일 때 본문에서 Q&A 쌍 추출.

        각 block.metadata['qa_pairs'] 에 [{question, answer, confidence}, ...] 추가.
        LLM 미주입/실패 시 silent skip — 파이프라인 안정성 우선.
        """
        if os.environ.get("KMS_QA_EXTRACT_ENABLED", "false").lower() != "true":
            return blocks
        if self._llm_client is None:
            log.info("qa_pair_skipped_no_llm")
            return blocks

        try:
            from src.pipeline.extractors.qa_pair_extractor import QAPairExtractor

            extractor = QAPairExtractor(llm_client=self._llm_client)
        except Exception as exc:  # noqa: BLE001
            log.warning("qa_pair_extractor_init_failed", error=str(exc))
            return blocks

        # 본문 길이가 너무 짧은 블록은 스킵 (Q&A 추출 가치 낮음).
        MIN_TEXT_LEN = 80
        extracted_count = 0
        for block in blocks:
            text = block.content or ""
            if len(text.strip()) < MIN_TEXT_LEN:
                continue
            try:
                pairs = await extractor.extract(text=text, block_id=str(block.id))
            except Exception as exc:  # noqa: BLE001
                log.warning("qa_pair_extract_failed", block_id=str(block.id), error=str(exc))
                continue
            if pairs:
                block.metadata["qa_pairs"] = [
                    {
                        "question": p.question,
                        "answer": p.answer,
                        "confidence": p.confidence,
                    }
                    for p in pairs
                ]
                extracted_count += len(pairs)

        if extracted_count:
            log.info("qa_pairs_extracted", total_pairs=extracted_count, blocks=len(blocks))
        return blocks

    async def _maybe_normalize_tables(
        self, blocks: list[BlockObject]
    ) -> list[BlockObject]:
        """env flag KMS_TABLE_NORMALIZE_ENABLED=true 일 때 raw 표 → markdown 정규화.

        block.metadata['raw_table'] 가 list[list[str]] 형태로 있으면 LLM 으로 정리해
        block.metadata['normalized_table_md'] 에 저장. 검색 품질 향상 목적.
        """
        if os.environ.get("KMS_TABLE_NORMALIZE_ENABLED", "false").lower() != "true":
            return blocks
        if self._llm_client is None:
            log.info("table_normalize_skipped_no_llm")
            return blocks

        try:
            from src.pipeline.extractors.table_normalizer import TableNormalizer

            normalizer = TableNormalizer(llm_client=self._llm_client)
        except Exception as exc:  # noqa: BLE001
            log.warning("table_normalizer_init_failed", error=str(exc))
            return blocks

        normalized_count = 0
        for block in blocks:
            raw = block.metadata.get("raw_table")
            if not raw or not isinstance(raw, list):
                continue
            try:
                md = await normalizer.normalize(raw_table=raw, context=block.content or "")
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "table_normalize_failed", block_id=str(block.id), error=str(exc)
                )
                continue
            if md:
                block.metadata["normalized_table_md"] = md
                normalized_count += 1

        if normalized_count:
            log.info("tables_normalized", count=normalized_count)
        return blocks

    # ------------------------------------------------------------------
    # 키 생성 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _checkpoint_key(document_id: UUID) -> str:
        """체크포인트 스토리지 키."""
        return f"checkpoints/{document_id}/progress.json"

    @staticmethod
    def _intermediate_key(document_id: UUID) -> str:
        """중간 블럭 스토리지 키."""
        return f"checkpoints/{document_id}/blocks.json"


def _elapsed_ms(start: float) -> int:
    """monotonic 시작 시점으로부터 경과 밀리초."""
    return int((time.monotonic() - start) * 1000)
