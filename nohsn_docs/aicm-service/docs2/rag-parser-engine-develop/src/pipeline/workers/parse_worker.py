"""Parse Worker -- aicm.document.uploaded 소비 -> 파서 실행 -> aicm.document.parsed 발행."""

from __future__ import annotations

import json
import re
import time
from uuid import uuid4

from src.common.constants import (
    TOPIC_DOCUMENT_FAILED,
    TOPIC_DOCUMENT_PARSED,
    TOPIC_DOCUMENT_SPLIT,
)
from src.common.logging import get_logger
from src.pipeline.models.document import DocumentFormat, DocumentObject
from src.pipeline.models.events import (
    DocumentParsedEvent,
    DocumentSplitEvent,
    DocumentUploadedEvent,
)
from src.pipeline.models.parse_result import ParseResult
from src.pipeline.parsers.router import detect_format, select_parser
from src.pipeline.processors.difficulty import evaluate_difficulty
from src.pipeline.storage.source_files import (
    build_source_key,
    cleanup_temp,
    ext_from,
    materialize_source,
)

log = get_logger(__name__)


async def handle_document_uploaded(
    event: DocumentUploadedEvent,
    producer: object,
) -> None:
    """문서 업로드 이벤트를 처리한다.

    1. 포맷 감지 + 파서 선택
    2. 파싱 실행
    3. 난이도 평가
    4. aicm.document.parsed 이벤트 발행

    Parameters
    ----------
    event : DocumentUploadedEvent
    producer : Kafka producer (aiokafka.AIOKafkaProducer)
    """
    start = time.monotonic()

    # Stage A/B (KMS-Plus): agent_* 타입 문서는 블록 파이프라인을 건너뛴다.
    # - agent_skill: YAML 스킬 정의 (Stage A)
    # - agent_schedule/diary/news_sub/reminder: 개인 데이터 structured storage (Stage B-2~5)
    # processing_meta 에 구조화 JSON 이 저장되고 loader/tool 이 직접 조회하므로
    # 파싱/블록/임베딩 모두 불필요. 시드·tool 경로는 Kafka 이벤트를 쏘지 않아
    # 본 체크는 안전망(이벤트가 어딘가에서 새어나와도 초기 단계에서 차단).
    try:
        from src.pipeline.services.agent_skill_check import is_agent_skill_document

        if await is_agent_skill_document(event.document_id):
            log.info(
                "pipeline_skipped_agent_doctype",
                document_id=str(event.document_id),
                reason="document_type in AGENT_SKIP_DOC_TYPES — KMS Plus Stage A/B",
            )
            return
    except Exception as skip_check_err:  # noqa: BLE001
        # 체크 실패해도 기존 파이프라인 진행 (fail-open — 기존 동작 보존)
        log.warning(
            "agent_skill_check_failed",
            document_id=str(event.document_id),
            error=str(skip_check_err),
        )

    # 제어 신호 확인 (취소/일시정지)
    from src.pipeline.services.status_updater import get_status_updater

    status_updater = get_status_updater()
    signal = await status_updater.check_control_signal(event.document_id)
    if signal == "cancel":
        log.info("pipeline_cancelled", document_id=str(event.document_id))
        await status_updater.mark_failed(event.document_id, "parsing", "사용자에 의해 취소됨")
        return
    if signal == "pause":
        log.info("pipeline_paused", document_id=str(event.document_id))
        return

    log.info(
        "parse_worker_start",
        document_id=str(event.document_id),
        source_format=event.source_format.value,
    )

    # DB 상태 업데이트 (파싱 시작)
    await status_updater.mark_parsing_start(event.document_id)

    # WebSocket 실시간 진행 발행
    from src.pipeline.workers.status_publisher import publish_progress, publish_stage_start

    await publish_stage_start(event.document_id, "parsing")

    _local_src = ""
    _src_is_temp = False
    try:
        # 0) 원본을 MinIO 단일 원천에서 로컬 임시파일로 구체화(로컬 존재 시 그대로 사용).
        #    EKS 에서 api·worker pod 가 /data/uploads 를 공유하지 않아 발생하던
        #    "원본 파일 없음" parsing 실패를 근본 해소한다.
        _local_src, _src_is_temp = await materialize_source(
            event.source_path,
            tenant_id=str(event.tenant_id),
            document_id=str(event.document_id),
            ext=ext_from(None, event.source_format),
        )

        # 1) 포맷 감지 + 파서 선택
        detected_format = detect_format(_local_src)
        parser = select_parser(detected_format, _local_src)

        # 2) 파싱
        parse_result: ParseResult = await parser.parse()

        # 2.5) LLM 기반 파싱 후처리 (노이즈 제거, 단어 복원, 컬럼 재정렬)
        parse_result = await _postprocess_parse_result(
            event.document_id, parse_result
        )

        # 2.6) ParseResult 캐싱 (다운스트림 워커 재파싱 방지)
        try:
            from src.pipeline.cache import cache_parse_result

            await cache_parse_result(event.document_id, parse_result)
        except Exception:
            pass  # 캐시 실패는 non-critical

        # 2.7) 미리보기 PDF 보장 (IMAGE/TXT/HTML/MARKDOWN — office 는 ConvertingParser 가 이미 처리).
        #      실패해도 파이프라인 차단 X. 프론트 PDF 뷰어가 자동으로 이 파일을 서빙한다.
        try:
            from src.pipeline.parsers.preview_pdf import ensure_preview_pdf

            preview_path = await ensure_preview_pdf(_local_src, event.source_format)
            if preview_path:
                parse_result.metadata["preview_pdf_path"] = preview_path
        except Exception as exc:
            log.debug("preview_pdf_ensure_failed", error=str(exc))

        # 3) 난이도 평가
        difficulty, score, factors = evaluate_difficulty(parse_result)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "parse_worker_complete",
            document_id=str(event.document_id),
            pages=len(parse_result.pages),
            tables=len(parse_result.tables),
            images=len(parse_result.images),
            difficulty=difficulty.value,
            score=score,
            elapsed_ms=elapsed_ms,
        )

        # 3.5) LLM 문서 구조 분석 (문서 종류 파악 + 파싱 전략)
        structure_info = await _analyze_document_structure(parse_result)
        if structure_info:
            parse_result.metadata["document_structure"] = structure_info

        # DB 상태 업데이트 (파싱 완료)
        await status_updater.mark_parsing_complete(
            document_id=event.document_id,
            page_count=len(parse_result.pages),
            table_count=len(parse_result.tables),
            image_count=len(parse_result.images),
            difficulty=difficulty.value,
            difficulty_score=score,
        )

        # WebSocket 실시간 진행 발행 (파싱 완료)
        from src.pipeline.workers.status_publisher import publish_stage_complete

        await publish_stage_complete(event.document_id, "parsing")

        # 3.9) ParseResult 캐싱 (다운스트림 워커의 재파싱 방지)
        await _cache_parse_result(event.document_id, parse_result)

        # 4) 결과 이벤트 발행
        total_pages = len(parse_result.pages)
        is_pdf = (
            event.source_format == DocumentFormat.PDF
            or (event.source_path.lower().endswith(".pdf") if event.source_path else False)
        )

        # 대용량 PDF → 파일 레벨 분할
        if is_pdf and total_pages > 20:
            from src.pipeline.workers.split_worker import calculate_page_ranges

            # LLM 기반 동적 배치 크기: 문서 복잡도에 따라 조정
            # document_structure의 document_type과 난이도 score를 활용
            batch_size = 20  # 기본값
            if structure_info:
                doc_type = structure_info.get("document_type", "")
                # 법률/계약서/메뉴얼 등 구조화된 문서는 큰 배치 (의미 단위가 큼)
                if doc_type in ("legal", "contract", "manual", "specification"):
                    batch_size = 30
                # 논문/학술 문서는 작은 배치 (조밀한 정보)
                elif doc_type in ("academic", "research", "paper"):
                    batch_size = 15
            # 난이도 기반 조정
            if difficulty.value == "high":
                batch_size = max(10, batch_size - 10)  # 어려운 문서는 작게
            elif difficulty.value == "low":
                batch_size = min(40, batch_size + 10)  # 쉬운 문서는 크게

            page_ranges = calculate_page_ranges(total_pages, batch_size=batch_size)
            log.info(
                "split_strategy_determined",
                document_id=str(event.document_id),
                total_pages=total_pages,
                batch_size=batch_size,
                num_parts=len(page_ranges),
                document_type=structure_info.get("document_type") if structure_info else None,
                difficulty=difficulty.value,
            )

            # 원본은 업로드 시점에 이미 MinIO 단일 원천에 저장돼 있다 → canonical object key 를
            # split_worker 에 전달한다(별도 재업로드 불필요, 키 규약 통일).
            minio_key = build_source_key(
                str(event.tenant_id),
                str(event.document_id),
                ext_from(None, event.source_format),
            )

            split_event = DocumentSplitEvent(
                event_id=uuid4(),
                document_id=event.document_id,
                tenant_id=event.tenant_id,
                repository_id=event.repository_id,
                total_pages=total_pages,
                total_parts=len(page_ranges),
                page_ranges=page_ranges,
                source_path=event.source_path,
                minio_source_key=minio_key,
                difficulty=difficulty,
                document_type=structure_info.get("document_type") if structure_info else None,
                document_structure=structure_info,
            )
            await _produce_event(producer, TOPIC_DOCUMENT_SPLIT, split_event)
            log.info(
                "document_split_triggered",
                document_id=str(event.document_id),
                total_pages=total_pages,
                total_parts=len(page_ranges),
            )
        else:
            # 기존 흐름: 소규모 문서 또는 비-PDF
            parsed_event = DocumentParsedEvent(
                event_id=uuid4(),
                document_id=event.document_id,
                tenant_id=event.tenant_id,
                repository_id=event.repository_id,
                difficulty=difficulty,
                page_count=total_pages,
                table_count=len(parse_result.tables),
                image_count=len(parse_result.images),
                raw_text_length=len(parse_result.raw_text),
                source_path=event.source_path,
                document_type=structure_info.get("document_type") if structure_info else None,
                document_structure=structure_info,
            )
            await _produce_event(producer, TOPIC_DOCUMENT_PARSED, parsed_event)

    except Exception as exc:
        log.error(
            "parse_worker_failed",
            document_id=str(event.document_id),
            error=str(exc),
        )
        await status_updater.mark_failed(event.document_id, "parsing", str(exc))
        await _produce_failure(producer, event.document_id, "parsing", str(exc))

        # WebSocket 실시간 진행 발행 (파싱 실패)
        from src.pipeline.workers.status_publisher import publish_pipeline_failed

        await publish_pipeline_failed(event.document_id, "parsing", str(exc))
        raise
    finally:
        # MinIO 에서 내려받은 임시 원본 정리(로컬 원본은 그대로 둠).
        cleanup_temp(_local_src, _src_is_temp)


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


# ------------------------------------------------------------------
# LLM 파싱 후처리
# ------------------------------------------------------------------


async def _postprocess_parse_result(
    document_id: object, parse_result: ParseResult
) -> ParseResult:
    """LLM 기반 파싱 후처리를 실행한다.

    노이즈 제거, 단어 분리 복원, 멀티컬럼 재정렬을 수행한다.
    비핵심 기능이므로 실패 시 원본을 그대로 반환한다.

    3페이지 미만 문서는 스킵한다 (휴리스틱 노이즈 제거로 충분).
    """
    try:
        from src.pipeline.enrichers.parse_postprocessor import ParsePostprocessor

        # 원본 텍스트 보존 (메타데이터에 저장)
        original_raw_text = parse_result.raw_text
        original_page_texts = {
            page.page_number: page.text for page in parse_result.pages
        }

        postprocessor = ParsePostprocessor()
        result = await postprocessor.process(parse_result)

        # 원본 텍스트를 메타데이터에 보존
        if result.raw_text != original_raw_text:
            result.metadata["original_raw_text"] = original_raw_text[:10000]
            result.metadata["postprocessed"] = True
            log.info(
                "parse_postprocessor_applied",
                document_id=str(document_id),
                original_length=len(original_raw_text),
                cleaned_length=len(result.raw_text),
            )
        else:
            result.metadata["postprocessed"] = False

        return result
    except Exception as exc:
        log.warning(
            "parse_postprocessor_failed",
            document_id=str(document_id),
            error=str(exc),
        )
        return parse_result


# ------------------------------------------------------------------
# LLM 문서 구조 분석
# ------------------------------------------------------------------


async def _analyze_document_structure(parse_result: ParseResult) -> dict | None:
    """LLM으로 문서 구조를 분석한다 (문서 종류, 섹션 구성, 언어).

    비핵심 기능이므로 실패 시 None을 반환하고 파이프라인을 차단하지 않는다.
    """
    try:
        from src.pipeline.prompts.document_structure import build_structure_analysis_prompt

        # 문서 앞부분 미리보기 (3000자)
        text_preview = parse_result.raw_text[:3000]
        headings = parse_result.metadata.get("headings", [])

        prompt = build_structure_analysis_prompt(text_preview, headings)

        # LLM 호출 (LLMRouter 사용)
        response_text = await _call_structure_llm(prompt)
        if not response_text:
            return None

        # JSON 파싱
        cleaned = response_text.strip()
        if "```" in cleaned:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]

        result = json.loads(cleaned)
        log.info(
            "document_structure_analyzed",
            document_type=result.get("document_type"),
            language=result.get("language"),
        )
        return result
    except Exception as exc:
        log.warning("document_structure_analysis_failed", error=str(exc))
    return None


async def _call_structure_llm(prompt: str) -> str | None:
    """구조 분석용 LLM 호출. LLMRouter를 통해 라우팅한다."""
    try:
        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router

        request = LLMRequest(
            prompt=prompt,
            system_prompt="문서 구조 분석 전문가. JSON만 출력.",
            max_tokens=500,
            temperature=0.1,
            response_format="json",
        )
        response = await llm_router.route(LLMTask.DOCUMENT_STRUCTURE, request)
        text = response.text

        # Strip thinking tags if present (Qwen)
        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
        return text.strip() or None
    except Exception as exc:
        log.debug("structure_llm_call_failed", error=str(exc))
    return None


# ------------------------------------------------------------------
# ParseResult 캐싱
# ------------------------------------------------------------------


async def _cache_parse_result(document_id: object, parse_result: ParseResult) -> None:
    """ParseResult를 MinIO에 캐싱한다 (다운스트림 워커의 재파싱 방지).

    비핵심 기능이므로 실패 시 경고만 남기고 파이프라인을 차단하지 않는다.
    """
    try:
        from src.pipeline.storage.object_store import ObjectStore

        store = ObjectStore()
        await store.init()
        await store.save_intermediate(
            document_id=str(document_id),
            stage="parsed",
            data=parse_result.model_dump(),
        )
        log.info("parse_result_cached", document_id=str(document_id))
    except Exception as exc:
        log.debug("parse_result_cache_failed", error=str(exc))
