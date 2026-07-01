"""Block Worker — aicm.document.parsed 소비 → 블럭 세그멘테이션 → aicm.document.blocked 발행.

use_block_pipeline=True 인 문서에 대해 기존 chunk_worker 대신 동작한다.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any, Optional
from uuid import UUID, uuid4

from src.common.constants import (
    REVIEW_CONFIDENCE_THRESHOLD,
    TOPIC_DOCUMENT_BLOCKED,
    TOPIC_DOCUMENT_FAILED,
    TOPIC_DOCUMENT_PART_BLOCKED,
    TOPIC_DOCUMENT_REVIEW_REQUIRED,
)
from src.common.logging import get_logger
from src.pipeline.enrichers.knowledge_compiler import KnowledgeCompiler
from src.pipeline.models.block import BlockObject, BlockType
from src.pipeline.models.document import ProcessingConfig, SourceLocation
from src.pipeline.models.events import (
    BlockReviewItem,
    DocumentBlockedEvent,
    DocumentParsedEvent,
    DocumentPartBlockedEvent,
    DocumentPartReadyEvent,
    DocumentReviewRequiredEvent,
    ProcessingReport,
    ProcessingStageReport,
)
from src.pipeline.models.parse_result import ParseResult
from src.pipeline.parsers.router import detect_format, select_parser
from src.pipeline.segmenters.fallback_segmenter import FallbackSegmenter
from src.pipeline.segmenters.llm_block_segmenter import LLMBlockSegmenter

# 3-stage LLM pipeline (optional — graceful if not available)
try:
    from src.pipeline.stages.models import StageResult
    from src.pipeline.stages.pipeline import LLMPipeline
    from src.pipeline.stages.llm_client import VisionLLMClient

    _HAS_LLM_PIPELINE = True
except ImportError:
    _HAS_LLM_PIPELINE = False
    VisionLLMClient = None  # type: ignore

# Large document processing (optional — graceful if not available)
try:
    from src.pipeline.processing.document_processor import DocumentProcessor
    from src.pipeline.storage.config import StorageConfig
    from src.pipeline.storage.object_store import ObjectStore

    _HAS_STORAGE = True
except ImportError:
    _HAS_STORAGE = False

from src.pipeline.storage.source_files import (
    cleanup_temp as _cleanup_src_temp,
    ext_from as _src_ext_from,
    materialize_source as _materialize_source,
)

log = get_logger(__name__)

# ------------------------------------------------------------------
# 상수
# ------------------------------------------------------------------
# text 경로 page 렌더 — OOM 방지 위해 cap (앞 50 페이지). 박스형 도표는 보통 문서 앞부분.
_TEXT_PATH_RENDER_PAGE_CAP = 50

# ------------------------------------------------------------------
# MinIO ObjectStore 싱글톤
# ------------------------------------------------------------------
_object_store: ObjectStore | None = None


async def _get_object_store() -> ObjectStore | None:
    """싱글톤 ObjectStore 인스턴스를 반환한다."""
    global _object_store
    if not _HAS_STORAGE:
        return None
    if _object_store is None:
        try:
            config = StorageConfig()
            _object_store = ObjectStore(
                endpoint=config.MINIO_ENDPOINT,
                access_key=config.MINIO_ACCESS_KEY,
                secret_key=config.MINIO_SECRET_KEY,
                secure=config.MINIO_SECURE,
            )
            await _object_store.init()
        except Exception as exc:
            log.warning("minio_init_failed_using_local", error=str(exc))
            return None
    return _object_store


def _get_vision_llm_client() -> object | None:
    """VisionLLMClient 인스턴스를 생성한다 (LayoutMapper용)."""
    if not _HAS_LLM_PIPELINE or VisionLLMClient is None:
        return None

    try:
        from src.common.config import settings

        _vllm_url = settings.VLLM_URL
        _model = settings.VLLM_MODEL

        if not _vllm_url:
            log.warning("vllm_url_not_set_layout_mapper_disabled")
            return None

        return VisionLLMClient(
            api_key="not-needed",
            model=_model,
            base_url=f"{_vllm_url}/v1" if not _vllm_url.endswith("/v1") else _vllm_url,
        )
    except Exception as exc:
        log.warning("vision_llm_client_init_failed", error=str(exc))
        return None


async def handle_document_parsed_for_blocks(
    event: DocumentParsedEvent,
    producer: object,
    config: ProcessingConfig | None = None,
    llm_client: object | None = None,
) -> None:
    """파싱 완료 이벤트를 블럭 파이프라인으로 처리한다.

    1. 원본 파일 재파싱
    2. LLM 기반 블럭 세그멘테이션 (실패 시 폴백)
    3. aicm.document.blocked 이벤트 발행

    Parameters
    ----------
    event : DocumentParsedEvent
    producer : Kafka producer
    config : 처리 설정 오버라이드
    llm_client : LLM 클라이언트 (Anthropic 등)

    D34 §1: 직접 호출 path (bgworker / unit test) 보호용 *방어적 이중 wrap*.
    _dispatch_message 에서 이미 wrap 됐어도 finally 까지 wrap 유지.
    """
    # D34 §1 — bind_system_scope wrap (방어적 이중 wrap). 사전 GPT-5 §5 권고:
    # write-heavy path 이므로 tenant_id 필수 (allow_null_tenant=False). 누락 시
    # fail-fast log + return (조용한 RLS 차단 회피).
    from src.api.middleware.rls_context import bind_system_scope

    _tid = str(getattr(event, "tenant_id", "")) or None
    if not _tid:
        # D35 §1 — per-event rebind failure metric.
        try:
            from src.common.metrics import (
                REBIND_SITE_BLOCK_PARSED,
                inc_kms_worker_rebind_failure,
            )

            inc_kms_worker_rebind_failure(
                REBIND_SITE_BLOCK_PARSED, "aicm.document.parsed"
            )
        except Exception:  # noqa: BLE001
            pass
        log.error(
            "missing_tenant_id",
            document_id=str(getattr(event, "document_id", "")),
            where="block_worker.handle_document_parsed_for_blocks",
        )
        return
    async with bind_system_scope(_tid, allow_null_tenant=False):
        return await _handle_document_parsed_for_blocks_inner(
            event, producer, config=config, llm_client=llm_client
        )


async def _handle_document_parsed_for_blocks_inner(
    event: DocumentParsedEvent,
    producer: object,
    *,
    config: ProcessingConfig | None = None,
    llm_client: object | None = None,
) -> None:
    """D34 §1 — bind_system_scope wrap 안에서 실제 로직."""
    start = time.monotonic()
    proc_config = config or ProcessingConfig(use_block_pipeline=True)

    # 제어 신호 확인 (취소/일시정지)
    from src.pipeline.services.status_updater import get_status_updater

    status_updater = get_status_updater()
    signal = await status_updater.check_control_signal(event.document_id)
    if signal == "cancel":
        log.info("pipeline_cancelled", document_id=str(event.document_id))
        await status_updater.mark_failed(
            event.document_id, "block_segmentation", "사용자에 의해 취소됨"
        )
        return
    if signal == "pause":
        log.info("pipeline_paused", document_id=str(event.document_id))
        return

    log.info(
        "block_worker_start",
        document_id=str(event.document_id),
        page_count=event.page_count,
    )

    # DB 상태 업데이트 (블럭 세그멘테이션 시작) — 폴링 기반 UI 가 단계 갱신 볼 수 있게
    await status_updater.mark_blocking_start(event.document_id)

    # WebSocket 실시간 진행 발행 (블럭 세그멘테이션 시작)
    from src.pipeline.workers.status_publisher import (
        publish_pipeline_failed,
        publish_progress,
        publish_stage_complete,
        publish_stage_start,
    )

    await publish_stage_start(event.document_id, "blocking")

    _local_src = ""
    _src_is_temp = False
    parse_result: ParseResult | None = None
    try:
        # 0) 원본을 MinIO 단일 원천에서 로컬 임시파일로 구체화(재파싱/vision 경로용).
        #    로컬에 이미 있으면 그대로 사용(docker/legacy). store 싱글톤은 _get_object_store 와 공유.
        store = await _get_object_store()
        _local_src, _src_is_temp = await _materialize_source(
            event.source_path,
            tenant_id=str(event.tenant_id),
            document_id=str(event.document_id),
            ext=_src_ext_from(None, getattr(event, "source_format", None)),
        )

        # 1) ParseResult 로드 (캐시 우선, 없으면 재파싱)
        parse_result: ParseResult | None = None
        try:
            from src.pipeline.cache import load_parse_result

            parse_result = await load_parse_result(event.document_id)
            if parse_result:
                log.info("parse_result_loaded_from_cache", document_id=str(event.document_id))
        except Exception:
            pass

        if parse_result is None:
            detected_format = detect_format(_local_src)
            parser = select_parser(detected_format, _local_src)
            parse_result = await parser.parse()
            log.info("parse_result_reparsed", document_id=str(event.document_id))

        # 2) 3단계 LLM 파이프라인 — vision_gate 가 깨짐/스캔/PPT 만 Vision 으로 보냄.
        #    깨끗한 PDF 는 텍스트 세그먼터 경로(아래 fallback)로 빠진다.
        blocks: list[BlockObject] | None = None
        noise_from_filter: list[BlockObject] = []  # 노이즈 블럭 누적 (3-stage + filter)

        from src.pipeline.workers.vision_gate import decide_vision

        vision_decision = decide_vision(parse_result, _local_src)
        log.info(
            "vision_gate_decision",
            document_id=str(event.document_id),
            use_vision=vision_decision.use_vision,
            reason=vision_decision.reason,
            is_ppt=vision_decision.is_ppt,
            broken_ratio=vision_decision.broken_ratio,
            scanned_ratio=vision_decision.scanned_ratio,
            glyph_doubling_runs=vision_decision.glyph_doubling_runs,
        )

        if (
            _HAS_LLM_PIPELINE
            and llm_client is not None
            and vision_decision.use_vision
            and vision_decision.pdf_path
        ):
            try:
                pipeline = LLMPipeline()  # settings에서 VLLM_URL/ANTHROPIC 자동 결정

                stage_result: StageResult = await pipeline.process(
                    pdf_path=vision_decision.pdf_path,
                    is_ppt=vision_decision.is_ppt,
                )

                _vision_file_url = (
                    f"/repos/{event.repository_id}/docs/{event.document_id}"
                )
                blocks = _stage_result_to_blocks(
                    stage_result,
                    event.document_id,
                    parse_result=parse_result,
                    source_file_url=_vision_file_url,
                )

                # 3-stage 노이즈 블럭도 BlockObject로 변환 (is_noise 플래그)
                if stage_result.noise_blocks:
                    stage_noise = _stage_noise_to_blocks(
                        stage_result.noise_blocks,
                        event.document_id,
                        source_file_url=_vision_file_url,
                    )
                    noise_from_filter.extend(stage_noise)

                log.info(
                    "3stage_pipeline_complete",
                    document_id=str(event.document_id),
                    blocks=len(blocks),
                    noise=len(stage_result.noise_blocks),
                    stats=stage_result.stats,
                    is_ppt=vision_decision.is_ppt,
                )
            except Exception as exc:
                log.warning(
                    "3stage_pipeline_failed_fallback",
                    document_id=str(event.document_id),
                    error=str(exc),
                )
                blocks = None  # fallback to old path

        # 2-fallback) LLM 세그멘테이션 (3-stage 실패 시)
        if blocks is None:
            if llm_client is not None:
                segmenter = LLMBlockSegmenter(proc_config, llm_client=llm_client)
            else:
                segmenter = FallbackSegmenter(proc_config)

            # text 경로에서 LayoutMapper 로 ParseMap 구성 (표/도표 hint 용)
            text_parse_map = None
            if llm_client is not None:
                try:
                    from src.pipeline.stages.stage1_5_layout import LayoutMapper

                    _vision_client = _get_vision_llm_client()
                    if _vision_client is None:
                        raise ValueError("VisionLLMClient initialization failed")
                    _layout_mapper = LayoutMapper(_vision_client)
                    _pdf_path_for_layout = (
                        vision_decision.pdf_path
                        or parse_result.source_file_path
                        or _local_src
                    )
                    _page_nums = [p.page_number for p in parse_result.pages]

                    # T14: text 경로에서도 page 이미지 렌더 → vision box detection 활성
                    _page_images_text: dict[int, bytes] = {}
                    if _pdf_path_for_layout and _HAS_LLM_PIPELINE:
                        try:
                            import asyncio as _aio

                            _total_pages_for_layout = len(parse_result.pages)
                            _render_end = min(_TEXT_PATH_RENDER_PAGE_CAP, _total_pages_for_layout)
                            _page_images_text, _ = await _aio.to_thread(
                                LLMPipeline._render_pdf_sync,
                                _pdf_path_for_layout,
                                (1, _render_end),
                            )
                            log.info(
                                "text_path_page_images_rendered",
                                document_id=str(event.document_id),
                                pages=len(_page_images_text),
                                total_pages=_total_pages_for_layout,
                                capped_to=_render_end,
                            )
                        except Exception as _render_exc:
                            log.warning(
                                "text_path_page_render_failed",
                                document_id=str(event.document_id),
                                error=str(_render_exc),
                            )
                            _page_images_text = {}

                    text_parse_map = await _layout_mapper.map(
                        pdf_path=_pdf_path_for_layout,
                        page_images=_page_images_text,
                        page_nums=[p for p in _page_nums if p <= min(_TEXT_PATH_RENDER_PAGE_CAP, len(parse_result.pages))],
                    )
                except Exception as _pm_exc:
                    log.warning("text_path_layout_map_failed", error=str(_pm_exc))
                    text_parse_map = None

            # 공통 인자 준비
            _source_file_url = (
                f"/repos/{event.repository_id}/docs/{event.document_id}"
            )
            _stage1_doc_type = getattr(event, "document_type", "") or ""

            total_pages = len(parse_result.pages)

            if total_pages > 20 and _HAS_STORAGE:
                log.info(
                    "large_document_detected",
                    pages=total_pages,
                    document_id=str(event.document_id),
                )
                try:
                    processor = DocumentProcessor(
                        config=proc_config,
                        object_store=store,
                        llm_client=llm_client,
                    )
                    result = await processor.process(
                        document_id=event.document_id,
                        tenant_id=event.tenant_id,
                        repository_id=event.repository_id,
                        source_path=_local_src,
                        title=event.title if hasattr(event, "title") else "",
                        source_file_url=_source_file_url,
                        parse_map=text_parse_map,
                        doc_type=_stage1_doc_type,
                    )
                    blocks = result.blocks
                except Exception as exc:
                    log.warning("document_processor_failed_fallback", error=str(exc))
                    if isinstance(segmenter, LLMBlockSegmenter):
                        blocks = await segmenter.segment(
                            parse_result,
                            document_id=event.document_id,
                            parse_map=text_parse_map,
                            source_file_url=_source_file_url,
                            doc_type=_stage1_doc_type,
                        )
                    else:
                        blocks = await segmenter.segment(
                            parse_result,
                            document_id=event.document_id,
                            source_file_url=_source_file_url,
                        )
            else:
                if isinstance(segmenter, LLMBlockSegmenter):
                    blocks = await segmenter.segment(
                        parse_result,
                        document_id=event.document_id,
                        parse_map=text_parse_map,
                        source_file_url=_source_file_url,
                        doc_type=_stage1_doc_type,
                    )
                else:
                    blocks = await segmenter.segment(
                        parse_result,
                        document_id=event.document_id,
                        source_file_url=_source_file_url,
                    )

        if not blocks:
            log.warning("block_worker_no_blocks", document_id=str(event.document_id))
            # status 를 failed 로 명시 마킹해서 무한 processing 방지
            try:
                from src.pipeline.services.status_updater import get_status_updater

                await get_status_updater().mark_failed(
                    event.document_id,
                    stage="block",
                    error="블럭이 추출되지 않았습니다 (빈 문서이거나 파싱 실패).",
                )
            except Exception as _exc:
                log.warning("mark_failed_on_no_blocks_failed", error=str(_exc))
            return

        # 블럭 세그멘테이션 단계 완료 — DB 갱신 (enriching 진입 직전)
        await status_updater.mark_blocking_complete(
            event.document_id,
            block_count=len(blocks),
            block_types=dict(Counter(b.block_type.value for b in blocks)),
        )
        await status_updater.mark_enriching_start(event.document_id)

        # 2.4) 노이즈 필터 — Stage 1 document_structure의 noise_patterns 활용
        #      노이즈 블럭은 제거하지 않고 metadata.is_noise=True 플래그로 보존
        noise_from_filter: list[BlockObject] = []
        try:
            from src.pipeline.enrichers.noise_filter import partition_noise_blocks

            noise_patterns = []
            if event.document_structure:
                noise_patterns = event.document_structure.get("noise_patterns", []) or []
            noise_result = partition_noise_blocks(blocks, noise_patterns)
            blocks = noise_result.content_blocks
            noise_from_filter = noise_result.noise_blocks
            # 노이즈 블럭에 메타 플래그 부착
            for nb in noise_from_filter:
                nb.metadata["is_noise"] = True
                nb.metadata["noise_reason"] = nb.metadata.get("noise_reason", "noise_filter")
        except Exception as exc:
            log.warning("noise_filter_failed", error=str(exc))

        # 2.5) 캡션 감지 (표/이미지 블럭) — LLM 우선, regex fallback
        try:
            from src.pipeline.enrichers.caption_detector import CaptionDetector

            detector = CaptionDetector(llm_client=llm_client)
            blocks = await detector.detect_all(blocks)
        except Exception as exc:
            log.warning(
                "caption_detection_failed",
                document_id=str(event.document_id),
                error=str(exc),
            )

        # 3) Knowledge Compilation (LLM 보강) — 느리면 건너뛸 수 있음
        from src.common.config import settings as _cfg
        skip_val = getattr(_cfg, "SKIP_KNOWLEDGE_COMPILER", "false")
        skip_compiler = str(skip_val).lower() in ("true", "1", "yes")
        if skip_compiler:
            log.info("knowledge_compilation_skipped", reason="SKIP_KNOWLEDGE_COMPILER=true")
        else:
          try:
            compiler = KnowledgeCompiler(proc_config, llm_client=llm_client)
            blocks = await compiler.compile(
                blocks=blocks,
                document_text=parse_result.raw_text,
                document_title=event.title if hasattr(event, "title") else "",
            )
          except Exception as exc:
            log.warning(
                "knowledge_compilation_failed",
                document_id=str(event.document_id),
                error=str(exc),
            )

        # Enrichment 단계 완료 — DB 갱신 (embedding 진입 직전, embed_worker 가 이어받음)
        await status_updater.mark_enriching_complete(
            event.document_id,
            enriched_count=len(blocks),
        )

        # 4) 블럭 데이터를 중간 저장소에 저장 (향후 Redis/파일 캐시)
        #    노이즈 블럭은 인덱싱 대상이 아니므로 캐시에는 본문만 저장
        await _store_blocks_intermediate(event.document_id, blocks)

        # LLM segmenter가 metadata.is_noise=True로 표시한 블럭 추출
        llm_noise = [b for b in blocks if b.metadata.get("is_noise")]
        content_only = [b for b in blocks if not b.metadata.get("is_noise")]
        # noise_filter에서 분리된 노이즈 블럭 합산
        all_noise = llm_noise + noise_from_filter

        # 4.1) DB 영속화 — 본문 블럭 + 노이즈 블럭 모두 저장
        try:
            await _persist_blocks_to_db(
                document_id=event.document_id,
                repository_id=event.repository_id,
                blocks=content_only,
                noise_blocks=all_noise,
            )
        except Exception as exc:
            log.warning(
                "blocks_db_persist_skipped",
                document_id=str(event.document_id),
                error=str(exc),
            )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        block_type_counts = dict(Counter(b.block_type.value for b in blocks))

        # 5) 처리 보고서 생성 + 리뷰 체크포인트
        report, review_items = _build_processing_report(
            document_id=event.document_id,
            title=event.title if hasattr(event, "title") else "",
            blocks=blocks,
            block_type_counts=block_type_counts,
            elapsed_ms=elapsed_ms,
            page_count=event.page_count,
        )

        log.info(
            "block_worker_complete",
            document_id=str(event.document_id),
            block_count=len(blocks),
            block_types=block_type_counts,
            review_required=report.review_required,
            review_items=len(review_items),
            avg_confidence=round(report.avg_confidence, 3),
            elapsed_ms=elapsed_ms,
        )

        # WebSocket 실시간 진행 발행 (블럭 세그멘테이션 완료)
        await publish_stage_complete(event.document_id, "blocking")

        # 6) [수정 2026-06-09] 검토 게이트를 "문서 카테고리 유무" 기준으로 변경
        # 이슈 내용: 자동분류 미사용 환경에서 블록 신뢰도(<0.75) 기반 검토가 임베딩을 막아
        #           카테고리 있어도 검색 안 됨(no_category_match).
        # 원인: 게이트가 블록 분류 신뢰도 기준 → 자동분류/카테고리 임베딩에 의존.
        # 수정: 거버넌스(AICM 승인 카테고리 필수, 동일 저장소)에 맞춰 카테고리 유무로 게이트.
        #       카테고리 있으면 임베딩 진행, 없으면 검토 대기(카테고리 지정 필요).
        has_category = await _document_has_category(event.document_id)
        if not has_category:
            # 카테고리 미지정 → pending_review (카테고리 지정 + 승인 필요)
            # [수정 2026-06-09]
            # 이슈 내용: 무카테고리+고신뢰(review_required=false) 문서가 status="processing"에
            #           고착돼 pending_review로 못 넘어가 수정/승인 불가(enriching에서 멈춤).
            # 원인: 임베딩 게이트는 has_category로 바꿨으나 _persist_processing_report 는
            #       여전히 report.review_required(신뢰도 기준)로 status를 정해 불일치.
            # 수정: 무카테고리면 review_required=True 강제 → _persist 가 pending_review 로 전환.
            report.review_required = True
            review_event = DocumentReviewRequiredEvent(
                event_id=uuid4(),
                document_id=event.document_id,
                tenant_id=event.tenant_id,
                repository_id=event.repository_id,
                block_count=len(blocks),
                review_required_blocks=len(review_items),
                auto_approved_blocks=report.auto_approved_count,
                review_reasons=["category_required"],
                processing_report=report.model_dump(mode="json"),
            )
            await _produce_event(producer, TOPIC_DOCUMENT_REVIEW_REQUIRED, review_event)
            log.info(
                "review_checkpoint_triggered",
                document_id=str(event.document_id),
                reason="category_required",
            )
        else:
            # 전체 자동 승인 → 바로 임베딩 진행
            blocked_event = DocumentBlockedEvent(
                event_id=uuid4(),
                document_id=event.document_id,
                tenant_id=event.tenant_id,
                repository_id=event.repository_id,
                block_count=len(blocks),
                block_types=block_type_counts,
                source_path=event.source_path,
            )
            await _produce_event(producer, TOPIC_DOCUMENT_BLOCKED, blocked_event)

        # 7) 처리 보고서를 DB에 저장
        try:
            await _persist_processing_report(event.document_id, report)
        except Exception as exc:
            log.warning("report_persist_error", error=str(exc))

    except Exception as exc:
        log.error(
            "block_worker_failed",
            document_id=str(event.document_id),
            error=str(exc),
        )
        await _produce_failure(producer, event.document_id, "block_segmentation", str(exc))

        # WebSocket 실시간 진행 발행 (블럭 실패)
        await publish_pipeline_failed(event.document_id, "blocking", str(exc))
        raise
    finally:
        # ConvertingParser 가 남긴 임시 PDF 등 정리 (성공/실패 무관)
        try:
            if parse_result is not None and hasattr(parse_result, "cleanup_temp"):
                parse_result.cleanup_temp()
        except Exception:
            pass
        # MinIO 에서 내려받은 임시 원본 정리(로컬 원본은 그대로 둠).
        _cleanup_src_temp(_local_src, _src_is_temp)


# ------------------------------------------------------------------
# StageResult → BlockObject 변환
# ------------------------------------------------------------------


def _stage_result_to_blocks(
    result: StageResult,
    document_id: UUID,
    parse_result: ParseResult | None = None,
    source_file_url: str = "",
) -> list[BlockObject]:
    """StageResult를 BlockObject 리스트로 변환한다.

    parse_result 가 주어지면, image 블럭의 원본 이미지 파일 경로(image_path)를
    페이지 번호 + 등장 순서 기반으로 매핑하여 metadata 에 부착한다.
    이게 있어야 프론트엔드에서 그림을 실제로 표시 가능.

    source_file_url 이 주어지면 SourceLocation.file_url 에 채운다.
    """
    from datetime import datetime

    # 페이지 번호별 원본 이미지 경로 목록
    image_paths_by_page: dict[int, list[str]] = {}
    if parse_result is not None:
        for page in parse_result.pages:
            paths = [img.image_path for img in (page.images or []) if img.image_path]
            if paths:
                image_paths_by_page[page.page_number] = paths
    # 페이지별 이미지 사용 카운터 (LLM 출력 순서대로 매핑)
    image_idx_per_page: dict[int, int] = {}

    blocks: list[BlockObject] = []
    for i, raw in enumerate(result.blocks):
        # type string → BlockType enum
        try:
            block_type = BlockType(raw.type)
        except ValueError:
            block_type = BlockType.PARAGRAPH

        # Classification provenance (Phase A-5)
        provenance = {
            "reasoning": raw.classification_reasoning,
            "confidence": raw.classification_confidence,
            "nature": raw.nature,
            "model": "gemma-4-26b-a4b",
            "classified_at": datetime.utcnow().isoformat(),
            "pipeline_version": "3-stage-v1",
        }

        block = BlockObject(
            id=uuid4(),
            document_id=document_id,
            block_type=block_type,
            content=raw.content,
            block_index=i,
            token_count=len(raw.content),
            source_location=SourceLocation(
                page_number=raw.page,
                file_url=source_file_url or None,
            ),
            metadata={
                k: v
                for k, v in {
                    "table_nl": raw.table_nl,
                    "image_description": raw.image_description,
                    "keywords": raw.keywords,
                    # Ontology fields (Phase A-3 / A-5)
                    "nature": raw.nature,
                    "time_reference": raw.time_reference,
                    "entities": raw.entities,
                    "domain_category_ids": raw.domain_category_ids,
                    "classification_confidence": raw.classification_confidence,
                    "classification_reasoning": raw.classification_reasoning,
                    "validity_status": "active",
                    "classification_provenance": provenance,
                    **raw.properties,
                }.items()
                if v  # 빈 값 제외
            },
        )

        # 표/이미지 전용 필드 매핑
        if raw.table_nl:
            block.table_markdown = raw.content  # 원본은 markdown 형태
        if raw.image_description:
            block.image_description = raw.image_description

        # 이미지 블럭 → 원본 이미지 파일 경로 매핑 (페이지 번호 + 순서)
        if block_type == BlockType.IMAGE:
            page_num = raw.page or 0
            paths_for_page = image_paths_by_page.get(page_num, [])
            seen = image_idx_per_page.get(page_num, 0)
            if seen < len(paths_for_page):
                img_path = paths_for_page[seen]
                block.image_path = img_path  # BlockObject 모델 필드
                block.metadata["image_path"] = img_path  # 프론트가 metadata.image_path 로 조회
                image_idx_per_page[page_num] = seen + 1

        block.compute_hash()
        blocks.append(block)

    return blocks


def _stage_noise_to_blocks(
    noise_blocks: list,
    document_id: UUID,
    source_file_url: str = "",
) -> list[BlockObject]:
    """StageResult.noise_blocks (RawBlock) 를 BlockObject 리스트로 변환한다.

    이 블럭들은 is_noise=True 로 DB에 저장되며, 검색 인덱스에는 포함되지 않는다.
    """
    blocks: list[BlockObject] = []
    for i, raw in enumerate(noise_blocks):
        block = BlockObject(
            id=uuid4(),
            document_id=document_id,
            block_type=BlockType.PARAGRAPH,
            content=raw.content,
            block_index=9000 + i,  # 본문 블럭 뒤에 배치
            token_count=len(raw.content),
            source_location=SourceLocation(
                page_number=raw.page,
                file_url=source_file_url or None,
            ),
            metadata={
                "is_noise": True,
                "noise_reason": raw.reason or "3-stage pipeline noise",
            },
        )
        block.compute_hash()
        blocks.append(block)
    return blocks


# ------------------------------------------------------------------
# 캡션 감지
# ------------------------------------------------------------------
_CAPTION_PATTERN = re.compile(
    r"(그림|Figure|Fig\.|표|Table|사진|Photo|도표|Chart)\s*[\d]+[.:\s]*(.*)",
    re.IGNORECASE,
)


def _detect_captions(blocks: list[BlockObject], parse_result: ParseResult) -> list[BlockObject]:
    """표/이미지 블럭의 전후 텍스트에서 캡션을 감지한다."""
    for i, block in enumerate(blocks):
        if block.block_type not in (BlockType.TABLE, BlockType.IMAGE):
            continue

        # 직전/직후 블럭에서 캡션 패턴 검색
        for neighbor_idx in [i - 1, i + 1]:
            if 0 <= neighbor_idx < len(blocks):
                neighbor = blocks[neighbor_idx]
                content = neighbor.content.strip()
                # 짧은 텍스트 + 캡션 패턴
                if len(content) < 200:
                    m = _CAPTION_PATTERN.match(content)
                    if m:
                        block.metadata["caption"] = content
                        block.metadata["caption_source"] = "neighbor_block"
                        break

    return blocks


# ------------------------------------------------------------------
# DB 영속화
# ------------------------------------------------------------------
async def _persist_blocks_to_db(
    document_id: UUID,
    repository_id: UUID,
    blocks: list[BlockObject],
    noise_blocks: list[BlockObject] | None = None,
) -> None:
    """블럭을 PostgreSQL에 저장한다.

    Args:
        document_id: 문서 ID
        repository_id: 저장소 ID
        blocks: 본문 블럭 (is_noise=false)
        noise_blocks: 노이즈 블럭 (is_noise=true, 검색 인덱스 제외)
    """
    try:
        from sqlalchemy import delete

        from src.core.database import async_session_factory
        from src.core.models.block import Block

        # OCRResult repr 정리 — 파서 버그로 원시 데이터가 content에 포함된 경우 방어
        import re as _re
        _ocr_pattern = _re.compile(
            r"OCRResult\(texts=\[([^\]]*)\],\s*tables=\[[^\]]*\],\s*confidence=[^,]*,\s*has_content=[^,]*,\s*engine_used='[^']*'\)"
        )
        all_blocks_with_flag: list[tuple[BlockObject, bool]] = [
            (b, False) for b in blocks
        ] + [
            (b, True) for b in (noise_blocks or [])
        ]

        for b, _ in all_blocks_with_flag:
            if b.content and "OCRResult(" in b.content:
                def _extract_texts(m):
                    raw = m.group(1)
                    texts = _re.findall(r"'([^']*)'", raw)
                    return "\n".join(texts).strip() if texts else ""
                b.content = _ocr_pattern.sub(_extract_texts, b.content).strip()
                if b.content:
                    b.compute_hash()

        # 중복 hash 제거 (uq_blocks_document_hash 제약 보호)
        # 같은 내용 블럭이 여러 번 나올 때 (표 중복, 반복 캡션 등) 첫 번째만 유지
        seen_hashes: set[str] = set()
        unique_blocks: list[tuple[BlockObject, bool]] = []
        for b, is_noise in all_blocks_with_flag:
            h = b.block_hash or ""
            if h and h in seen_hashes:
                log.debug("skip_duplicate_hash", block_hash=h[:16], doc_id=str(document_id))
                continue
            if h:
                seen_hashes.add(h)
            unique_blocks.append((b, is_noise))

        async with async_session_factory() as session:
            # greenlet contextvar 전파 불안정 대비 — 세션 시작 직후 명시 SET LOCAL.
            # begin 이벤트(_rls_set_session_vars)가 greenlet 안에서 contextvar를
            # 읽지 못하는 경우를 방어.
            from src.api.middleware.rls_context import get_rls_context
            from sqlalchemy import text as _text
            _rls_ctx = get_rls_context()
            if _rls_ctx and _rls_ctx.scope:
                await session.execute(
                    _text("SELECT set_config('app.current_scope', :v, true)"),
                    {"v": _rls_ctx.scope},
                )
                if _rls_ctx.tenant_id:
                    await session.execute(
                        _text("SELECT set_config('app.current_tenant_id', :v, true)"),
                        {"v": _rls_ctx.tenant_id},
                    )

            # 기존 블럭 삭제 (재처리 시)
            await session.execute(
                delete(Block).where(Block.document_id == document_id)
            )

            # 새 블럭 저장
            for b, is_noise in unique_blocks:
                db_block = Block(
                    id=b.id,
                    document_id=b.document_id,
                    repository_id=repository_id,
                    block_type=b.block_type.value,
                    content=b.content,
                    block_index=b.block_index,
                    block_hash=b.block_hash,
                    token_count=b.token_count,
                    source_location=b.source_location.model_dump() if b.source_location else {},
                    meta_info=b.metadata,
                    is_noise=is_noise,
                    # Ontology columns (Phase A-5)
                    nature=b.metadata.get("nature"),
                    time_reference=b.metadata.get("time_reference"),
                    entities=b.metadata.get("entities"),
                    domain_category_ids=[
                        c.get("id", "") for c in b.metadata.get("domain_category_ids", [])
                    ] if b.metadata.get("domain_category_ids") else None,
                    validity_status=b.metadata.get("validity_status", "active"),
                    classification_provenance=b.metadata.get("classification_provenance"),
                )
                session.add(db_block)

            await session.commit()
            content_count = sum(1 for _, n in unique_blocks if not n)
            noise_count = sum(1 for _, n in unique_blocks if n)
            log.info(
                "blocks_persisted_to_db",
                document_id=str(document_id),
                content_count=content_count,
                noise_count=noise_count,
                total=len(unique_blocks),
            )
    except Exception as exc:
        import traceback as _tb
        log.error(
            "blocks_db_persist_failed",
            error=str(exc),
            traceback=_tb.format_exc(),
            document_id=str(document_id),
        )
        # DB 저장 실패해도 캐시에는 남아있으므로 파이프라인 계속 진행


# ------------------------------------------------------------------
# 중간 저장소 (향후 Redis/파일 캐시로 교체)
# ------------------------------------------------------------------
_block_cache: dict[str, list[BlockObject]] = {}


async def _store_blocks_intermediate(document_id: object, blocks: list[BlockObject]) -> None:
    """블럭 데이터를 Redis에 저장한다. 실패 시 인메모리 캐시 fallback."""
    key = f"aicm:blocks:{document_id}"

    # Serialize blocks (벡터 제외 — 크기 최적화)
    data = [b.model_dump(exclude={"dense_vector", "sparse_vector"}) for b in blocks]

    try:
        import redis.asyncio as aioredis

        from src.common.config import settings

        r = aioredis.from_url(settings.REDIS_URL)
        import json

        await r.set(key, json.dumps(data, default=str), ex=1800)  # 30분 TTL
        await r.aclose()
        log.info("blocks_cached_redis", document_id=str(document_id), count=len(blocks))
        return
    except Exception as exc:
        log.warning("redis_block_cache_failed", error=str(exc))

    # Fallback: in-memory
    _block_cache[str(document_id)] = blocks


def _sanitize_source_location(sl_raw: dict | None) -> dict:
    """D47 §C — DB/Redis 에서 읽은 source_location 의 *bad data* 를 sanitize.

    문제: heading_path 에 None 원소가 포함되면 pydantic SourceLocation 이 전체 dict
    검증 실패 → load_blocks_from_cache 가 *모든 블럭* 을 못 읽음 → 문서 stuck.

    해결: heading_path 의 None / 비-str / 빈 문자열 원소를 사전 제거.
    """
    if not sl_raw:
        return {}
    sl_clean = dict(sl_raw)
    hp = sl_clean.get("heading_path")
    if isinstance(hp, list):
        cleaned: list[str] = []
        for h in hp:
            if h is None:
                continue
            s = str(h).strip()
            if s:
                cleaned.append(s)
        sl_clean["heading_path"] = cleaned
    elif hp is not None:
        # 비-list 면 빈 list 로 normalize.
        sl_clean["heading_path"] = []
    return sl_clean


async def load_blocks_from_cache(document_id: object) -> list[BlockObject]:
    """Redis에서 블럭을 로드한다. 없으면 DB에서 조회."""
    key = f"aicm:blocks:{document_id}"

    # 1. Redis
    try:
        import redis.asyncio as aioredis

        from src.common.config import settings

        r = aioredis.from_url(settings.REDIS_URL)
        import json

        data = await r.get(key)
        await r.aclose()
        if data:
            items = json.loads(data)
            # D47 §C — heading_path None 원소 사전 sanitize (재처리 호환).
            sanitized_count = 0
            for item in items:
                sl = item.get("source_location") if isinstance(item, dict) else None
                if sl:
                    cleaned = _sanitize_source_location(sl)
                    if cleaned != sl:
                        item["source_location"] = cleaned
                        sanitized_count += 1
            if sanitized_count:
                log.info(
                    "blocks_sanitized_redis",
                    document_id=str(document_id),
                    count=sanitized_count,
                )
            blocks = [BlockObject.model_validate(item) for item in items]
            log.info("blocks_loaded_redis", document_id=str(document_id), count=len(blocks))
            return blocks
    except Exception as exc:
        log.warning(
            "redis_block_load_failed",
            document_id=str(document_id),
            error=str(exc),
        )

    # 2. In-memory fallback
    cached = _block_cache.get(str(document_id), [])
    if cached:
        log.info("blocks_loaded_memory", document_id=str(document_id), count=len(cached))
        return cached

    # 3. DB fallback — load from blocks table
    try:
        from uuid import UUID

        from sqlalchemy import select

        from src.core.database import async_session_factory
        from src.core.models.block import Block

        doc_id = UUID(str(document_id)) if not isinstance(document_id, UUID) else document_id

        async with async_session_factory() as session:
            stmt = select(Block).where(Block.document_id == doc_id).order_by(Block.block_index)
            result = await session.execute(stmt)
            db_blocks = result.scalars().all()

            if db_blocks:
                # D47 §C — DB 의 source_location 도 sanitize.
                # 더불어 *블럭별* try/except 로 1건 실패가 전체 무산 막음.
                blocks: list[BlockObject] = []
                bad_blocks = 0
                for b in db_blocks:
                    try:
                        sl_dict = _sanitize_source_location(b.source_location or {})
                        blocks.append(
                            BlockObject(
                                id=b.id,
                                document_id=b.document_id,
                                block_type=b.block_type,
                                content=b.content,
                                block_index=b.block_index,
                                block_hash=b.block_hash,
                                token_count=b.token_count or 0,
                                source_location=SourceLocation(**sl_dict),
                                metadata=b.meta_info or {},
                            )
                        )
                    except Exception as block_exc:  # noqa: BLE001
                        bad_blocks += 1
                        log.warning(
                            "db_block_validation_skip",
                            document_id=str(document_id),
                            block_index=getattr(b, "block_index", -1),
                            error=str(block_exc),
                        )
                if bad_blocks:
                    log.warning(
                        "db_blocks_partial_load",
                        document_id=str(document_id),
                        loaded=len(blocks),
                        skipped=bad_blocks,
                    )
                log.info("blocks_loaded_db", document_id=str(document_id), count=len(blocks))
                return blocks
    except Exception as exc:
        log.warning(
            "db_block_load_failed",
            document_id=str(document_id),
            error=str(exc),
        )

    return []


# ------------------------------------------------------------------
# Kafka 유틸
# ------------------------------------------------------------------
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


async def _document_has_category(document_id: object) -> bool:
    """문서에 카테고리가 1개 이상 연결돼 있는지 확인한다.

    [수정 2026-06-09]
    이슈 내용: 자동분류(CategoryMapper) 미사용 + 카테고리 임베딩 부재로 모든 문서가
              no_category_match 검토에 걸려 임베딩되지 않아 검색 불가.
    원인: 검토 게이트가 블록 분류 신뢰도(<0.75) 기준이라 카테고리가 있어도 막히고,
          없어도 자동분류로 채우지 못함(category embedding write/read 불일치).
    수정: 거버넌스(AICM 승인 시 카테고리 필수, 동일 저장소 공유)에 맞춰 검토 게이트를
          "문서 카테고리 유무"로 변경. 그 판정에 사용. 조회 실패 시 안전하게 검토 대기(False).
    """
    try:
        from sqlalchemy import text

        from src.core.database import async_session_factory

        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT 1 FROM document_categories WHERE document_id = :did LIMIT 1"),
                {"did": str(document_id)},
            )
            return result.first() is not None
    except Exception as exc:
        log.warning(
            "document_has_category_check_failed",
            document_id=str(document_id),
            error=str(exc),
        )
        return False


async def _produce_failure(
    producer: object,
    document_id: object,
    stage: str,
    error: str,
) -> None:
    """실패 이벤트를 발행한다."""
    import json as _json

    try:
        from aiokafka import AIOKafkaProducer

        if isinstance(producer, AIOKafkaProducer):
            payload = _json.dumps(
                {"document_id": str(document_id), "stage": stage, "error": error}
            ).encode("utf-8")
            await producer.send_and_wait(TOPIC_DOCUMENT_FAILED, value=payload)
    except ImportError:
        log.warning("aiokafka_not_available_failure_event_skipped")


# ------------------------------------------------------------------
# 처리 보고서 생성
# ------------------------------------------------------------------


def _build_processing_report(
    document_id: UUID,
    title: str,
    blocks: list[BlockObject],
    block_type_counts: dict,
    elapsed_ms: int,
    page_count: int = 0,
) -> tuple[ProcessingReport, list[BlockReviewItem]]:
    """블럭 리스트에서 처리 보고서와 리뷰 항목을 생성한다.

    각 블럭의 confidence를 확인하여:
    - >= 0.75: auto_approved
    - < 0.75: review_required (사유와 함께 리뷰 항목에 추가)
    """
    review_items: list[BlockReviewItem] = []
    confidences: list[float] = []
    nature_counts: dict[str, int] = {}
    confidence_grades = {"solid": 0, "good": 0, "caution": 0, "low": 0}

    for block in blocks:
        meta = block.metadata or {}
        confidence = meta.get("classification_confidence", 1.0)
        if isinstance(confidence, str):
            try:
                confidence = float(confidence)
            except (ValueError, TypeError):
                confidence = 0.5
        confidences.append(confidence)

        nature = meta.get("nature", "unknown")
        nature_counts[nature] = nature_counts.get(nature, 0) + 1

        # 신뢰도 등급 분류
        if confidence >= 0.9:
            confidence_grades["solid"] += 1
        elif confidence >= 0.75:
            confidence_grades["good"] += 1
        elif confidence >= 0.6:
            confidence_grades["caution"] += 1
        else:
            confidence_grades["low"] += 1

        # 리뷰 필요 여부 판단
        if confidence < REVIEW_CONFIDENCE_THRESHOLD:
            reason = _determine_review_reason(block, confidence)
            review_items.append(
                BlockReviewItem(
                    block_id=block.id,
                    block_type=block.block_type.value,
                    content_preview=block.content[:200],
                    confidence=round(confidence, 3),
                    nature=nature,
                    review_reason=reason,
                    classification_reasoning=meta.get("classification_reasoning"),
                    suggested_alternatives=meta.get("domain_category_ids", []),
                    page_number=(
                        block.source_location.page_number
                        if block.source_location else None
                    ),
                )
            )

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    report = ProcessingReport(
        document_id=document_id,
        document_title=title,
        total_pages=page_count,
        stages=[
            ProcessingStageReport(
                stage="segmentation",
                status="completed",
                duration_ms=elapsed_ms,
                output_summary={
                    "block_count": len(blocks),
                    "block_types": block_type_counts,
                },
            ),
        ],
        total_duration_ms=elapsed_ms,
        total_blocks=len(blocks),
        block_type_distribution=block_type_counts,
        nature_distribution=nature_counts,
        confidence_distribution=confidence_grades,
        avg_confidence=round(avg_conf, 3),
        review_required=len(review_items) > 0,
        review_items=review_items,
        auto_approved_count=len(blocks) - len(review_items),
    )

    return report, review_items


def _determine_review_reason(block: BlockObject, confidence: float) -> str:
    """리뷰가 필요한 구체적 사유를 결정한다."""
    meta = block.metadata or {}

    if confidence < 0.4:
        return "very_low_confidence"

    if not meta.get("nature"):
        return "nature_unclassified"

    if not meta.get("domain_category_ids"):
        return "no_category_match"

    if block.block_type == BlockType.PARAGRAPH and len(block.content) < 30:
        return "short_ambiguous_block"

    return "low_confidence"


async def _persist_processing_report(document_id: UUID, report: ProcessingReport) -> None:
    """처리 보고서를 문서의 processing_meta에 병합 저장한다."""
    try:
        import json as _json

        from sqlalchemy import text

        from src.core.database import async_session_factory

        report_data = report.model_dump(mode="json")
        new_status = "pending_review" if report.review_required else "processing"

        async with async_session_factory() as session:
            await session.execute(
                text(
                    "UPDATE documents "
                    "SET processing_meta = COALESCE(processing_meta, '{}') || CAST(:patch AS jsonb), "
                    "    status = :status "
                    "WHERE id = :did"
                ),
                {"did": str(document_id), "patch": _json.dumps(report_data), "status": new_status},
            )
            await session.commit()
            log.info(
                "processing_report_persisted",
                document_id=str(document_id),
                review_required=report.review_required,
            )
    except Exception as exc:
        log.warning("processing_report_persist_failed", error=str(exc))


# ====================================================================
# 대용량 문서 파트 처리 — split_worker가 생성한 sub-PDF를 처리
# ====================================================================


async def handle_document_part_ready(
    event: DocumentPartReadyEvent,
    producer: Any,
    llm_client: object | None = None,
) -> None:
    """분할된 파트(sub-PDF)를 처리한다.

    1. MinIO에서 sub-PDF 다운로드
    2. 파싱
    3. LLM 세그멘테이션
    4. 블럭 결과를 MinIO에 저장
    5. DocumentPartBlockedEvent 발행

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
                REBIND_SITE_BLOCK_PART_READY,
                inc_kms_worker_rebind_failure,
            )

            inc_kms_worker_rebind_failure(
                REBIND_SITE_BLOCK_PART_READY, "aicm.document.part_ready"
            )
        except Exception:  # noqa: BLE001
            pass
        log.error(
            "missing_tenant_id",
            document_id=str(getattr(event, "document_id", "")),
            where="block_worker.handle_document_part_ready",
        )
        return
    async with bind_system_scope(_tid, allow_null_tenant=False):
        return await _handle_document_part_ready_inner(
            event, producer, llm_client=llm_client
        )


async def _handle_document_part_ready_inner(
    event: DocumentPartReadyEvent,
    producer: Any,
    *,
    llm_client: object | None = None,
) -> None:
    """D34 §1 — bind_system_scope wrap 안에서 실제 로직."""
    doc_id = str(event.document_id)
    start = time.monotonic()

    log.info(
        "block_worker_part_start",
        document_id=doc_id,
        part_index=event.part_index,
        total_parts=event.total_parts,
        pages=f"{event.page_start}-{event.page_end}",
    )

    try:
        # 1) MinIO에서 sub-PDF 다운로드
        from src.pipeline.storage.config import StorageConfig
        from src.pipeline.storage.object_store import ObjectStore

        cfg = StorageConfig()
        store = ObjectStore(
            endpoint=cfg.MINIO_ENDPOINT,
            access_key=cfg.MINIO_ACCESS_KEY,
            secret_key=cfg.MINIO_SECRET_KEY,
            secure=cfg.MINIO_SECURE,
        )
        await store.init()

        part_bytes = await store.download_bytes(
            cfg.MINIO_INTERMEDIATE_BUCKET, event.minio_part_key
        )
        if part_bytes is None:
            log.error(
                "block_worker_part_no_source",
                document_id=doc_id,
                part_index=event.part_index,
            )
            return

        # 2) 임시 파일에 저장 후 파싱
        import os as _os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(part_bytes)
            tmp_path = tmp.name

        try:
            from src.pipeline.parsers.router import select_parser
            from src.pipeline.models.document import DocumentFormat

            parser = select_parser(DocumentFormat.PDF, tmp_path)
            parse_result = await parser.parse()

            # 3) vision_gate — 깨짐/스캔/PPT 시 3-stage Vision, 아니면 텍스트 세그먼터
            from src.pipeline.workers.vision_gate import decide_vision

            vision_decision = decide_vision(parse_result, tmp_path)
            log.info(
                "vision_gate_part_decision",
                document_id=doc_id,
                part_index=event.part_index,
                use_vision=vision_decision.use_vision,
                reason=vision_decision.reason,
                broken_ratio=vision_decision.broken_ratio,
                glyph_doubling_runs=vision_decision.glyph_doubling_runs,
                scanned_ratio=vision_decision.scanned_ratio,
            )

            proc_config = ProcessingConfig()
            blocks: list[BlockObject] = []
            _part_file_url = (
                f"/repos/{event.repository_id}/docs/{event.document_id}"
            )
            _stage1_doc_type = getattr(event, "document_type", "") or ""

            if (
                _HAS_LLM_PIPELINE
                and llm_client is not None
                and vision_decision.use_vision
            ):
                try:
                    pipeline = LLMPipeline()
                    stage_result = await pipeline.process(
                        pdf_path=tmp_path,
                        is_ppt=vision_decision.is_ppt,
                    )
                    blocks = _stage_result_to_blocks(
                        stage_result,
                        event.document_id,
                        parse_result=parse_result,
                        source_file_url=_part_file_url,
                    )
                    log.info(
                        "3stage_pipeline_part_complete",
                        document_id=doc_id,
                        part_index=event.part_index,
                        blocks=len(blocks),
                        noise=len(stage_result.noise_blocks),
                    )
                except Exception as exc:
                    log.warning(
                        "3stage_pipeline_part_failed_fallback",
                        document_id=doc_id,
                        part_index=event.part_index,
                        error=str(exc),
                    )
                    blocks = []  # fallback to text segmenter below

            # 3-fallback) 텍스트 세그먼터 (Vision 미사용 또는 실패 시)
            if not blocks:
                if llm_client is not None:
                    # T15: text 경로에서도 LayoutMapper 로 ParseMap 구성 (표/도표 hint)
                    _part_parse_map = None
                    try:
                        from src.pipeline.stages.stage1_5_layout import LayoutMapper

                        _vision_client = _get_vision_llm_client()
                        if _vision_client is None:
                            raise ValueError("VisionLLMClient initialization failed")
                        _layout_mapper = LayoutMapper(_vision_client)
                        _part_total_pages = len(parse_result.pages)
                        _part_render_end = min(_TEXT_PATH_RENDER_PAGE_CAP, _part_total_pages)
                        _part_page_images: dict[int, bytes] = {}
                        if _HAS_LLM_PIPELINE:
                            try:
                                import asyncio as _aio

                                _part_page_images, _ = await _aio.to_thread(
                                    LLMPipeline._render_pdf_sync,
                                    tmp_path,
                                    (1, _part_render_end),
                                )
                                log.info(
                                    "part_text_path_page_images_rendered",
                                    document_id=doc_id,
                                    part_index=event.part_index,
                                    pages=len(_part_page_images),
                                    total_pages=_part_total_pages,
                                )
                            except Exception as _render_exc:
                                log.warning(
                                    "part_text_path_page_render_failed",
                                    document_id=doc_id,
                                    part_index=event.part_index,
                                    error=str(_render_exc),
                                )
                                _part_page_images = {}
                        _part_parse_map = await _layout_mapper.map(
                            pdf_path=tmp_path,
                            page_images=_part_page_images,
                            page_nums=list(range(1, _part_render_end + 1)),
                        )
                    except Exception as _pm_exc:
                        log.warning(
                            "part_text_path_layout_map_failed",
                            document_id=doc_id,
                            part_index=event.part_index,
                            error=str(_pm_exc),
                        )
                        _part_parse_map = None

                    try:
                        from src.pipeline.segmenters.llm_block_segmenter import LLMBlockSegmenter

                        segmenter = LLMBlockSegmenter(proc_config, llm_client=llm_client)
                        blocks = await segmenter.segment(
                            parse_result,
                            document_id=event.document_id,
                            parse_map=_part_parse_map,
                            source_file_url=_part_file_url,
                            doc_type=_stage1_doc_type,
                        )
                    except Exception as exc:
                        log.warning(
                            "block_worker_part_llm_failed",
                            part_index=event.part_index,
                            error=str(exc),
                        )

            if not blocks:
                from src.pipeline.segmenters.fallback_segmenter import FallbackSegmenter

                segmenter_fb = FallbackSegmenter(proc_config)
                blocks = await segmenter_fb.segment(
                    parse_result, document_id=event.document_id,
                    source_file_url=_part_file_url,
                )
        finally:
            # 임시 sub-PDF 정리 (Vision 처리 완료 후)
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass

        # 4) 페이지 번호 보정 (원본 문서 기준)
        # #79 fix — block 별로 source_location 을 분리해 page_offset 누적 적용 방지.
        # 과거: _split_block_on_qna_patterns 의 shallow copy 가 source_location 을
        # 공유해 같은 객체에 += page_offset 이 N 회 적용 → page_number 폭주 (예: 73 → 253).
        # 방어선: mutation 전에 *모든* block 의 source_location 을 de-alias.
        # GPT-5.5 verdict — sl_id 가 처음 등장한 block 도 다음 iter 에서 같은 sl 을
        # 가리키는 block 이 발견되기 *전에* mutate 되므로, 처음 등장 block 도 분리해야 함.
        # 가장 안전한 방식 = 모든 block 마다 무조건 깊은 복사 (cost 미미).
        page_offset = event.page_start - 1
        for block in blocks:
            block.document_id = event.document_id
            if block.source_location and block.source_location.page_number:
                try:
                    block.source_location = block.source_location.model_copy(deep=True)
                except Exception:
                    import copy as _cp
                    block.source_location = _cp.deepcopy(block.source_location)
                block.source_location.page_number += page_offset

        # 5) 블럭 결과를 MinIO에 저장
        blocks_data = {
            "blocks": [b.model_dump(mode="json") for b in blocks],
            "part_index": event.part_index,
            "page_start": event.page_start,
            "page_end": event.page_end,
        }
        await store.save_intermediate(
            doc_id,
            f"parts/part_{event.part_index:03d}/blocks",
            blocks_data,
        )

        # 6) 블럭 타입 통계
        block_types: dict[str, int] = {}
        for block in blocks:
            bt = block.block_type.value
            block_types[bt] = block_types.get(bt, 0) + 1

        # 7) DocumentPartBlockedEvent 발행
        part_blocked_event = DocumentPartBlockedEvent(
            event_id=uuid4(),
            document_id=event.document_id,
            part_id=event.part_id,
            tenant_id=event.tenant_id,
            repository_id=event.repository_id,
            part_index=event.part_index,
            total_parts=event.total_parts,
            block_count=len(blocks),
            block_types=block_types,
            minio_blocks_key=f"{doc_id}/parts/part_{event.part_index:03d}/blocks.json",
            page_start=event.page_start,
            page_end=event.page_end,
        )
        await _produce_event(producer, TOPIC_DOCUMENT_PART_BLOCKED, part_blocked_event)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "block_worker_part_complete",
            document_id=doc_id,
            part_index=event.part_index,
            block_count=len(blocks),
            block_types=block_types,
            elapsed_ms=elapsed_ms,
        )

    except Exception as exc:
        log.error(
            "block_worker_part_failed",
            document_id=doc_id,
            part_index=event.part_index,
            error=str(exc),
        )
        # SplitTracker에 실패 기록
        try:
            from src.pipeline.processing.split_tracker import SplitTracker

            tracker = SplitTracker()
            await tracker.mark_part_failed(event.document_id, event.part_index)
            await tracker.close()
        except Exception:
            pass
        raise
