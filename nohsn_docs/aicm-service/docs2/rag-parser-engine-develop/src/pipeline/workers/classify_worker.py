"""Classify Worker — aicm.document.parsed 소비 → LLM 자동 분류 → processing_meta.auto_classification.

Stage B-Core-4 (KMS-Plus).

블럭 파이프라인(block_worker)과 **병렬**로 동작한다 — classify 는 document 의
domain/category/tags 를 한 번 LLM 에 물어보는 side-effect 작업이라서
파이프라인 크리티컬 패스에 있지 않다. 실패해도 blocking/embedding 은
그대로 진행된다.

영구 저장 위치:
    documents.processing_meta.auto_classification = {
        category_guess, domain, tags, suggested_repository_name,
        suggested_document_type, confidence, rationale,
        analyzed_at  # ISO timestamp
    }

Feature flag:
    환경변수 AGENT_AUTO_CLASSIFY=on|off (default on).  off 면 no-op.

교체 전략:
    본 워커는 pipeline composition 만 담당하고, 실제 분류 로직은
    ``src.agent_framework.classifier.document_classifier.DocumentClassifier`` 에
    있다.  future: fine-tuned 분류기로 DocumentClassifier 만 교체하면 된다.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

from src.common.logging import get_logger
from src.pipeline.models.events import DocumentParsedEvent

log = get_logger(__name__)

# text sample 상한 — LLM 프롬프트 크기 제어. _analyze_document_structure 와 동일.
_MAX_TEXT_SAMPLE = 3000


def _is_enabled() -> bool:
    """feature flag 읽기 — off/false/0 이면 비활성."""
    value = os.environ.get("AGENT_AUTO_CLASSIFY", "on").strip().lower()
    return value not in ("off", "false", "0", "no", "disabled")


async def handle_document_parsed_for_classify(
    event: DocumentParsedEvent,
    *,
    classifier: Any = None,
    db_session_factory: Any = None,
) -> Optional[dict]:
    """DocumentParsedEvent 를 받아 auto_classification 을 만들어 DB 에 병합한다.

    **non-critical**: 모든 예외를 내부에서 삼키고 fallback 저장 또는 skip 한다.
    파이프라인 본류가 영향받지 않는다.

    Parameters
    ----------
    event : DocumentParsedEvent
    classifier : DocumentClassifier | None
        테스트 override 용.  None 이면 지연 초기화 (VLLMAdapter + DocumentClassifier).
    db_session_factory : async callable | None
        테스트 override 용.  None 이면 ``src.core.database.async_session`` 사용.

    Returns
    -------
    dict | None
        저장된 auto_classification dict (성공).  skip/실패 시 ``None``.
    """
    if not _is_enabled():
        log.info(
            "classify_worker_skipped_disabled",
            document_id=str(event.document_id),
        )
        return None

    # 문서 로드 — 제목 + (가능하면) parse cache 에서 text sample
    title, text_sample = await _load_document_sample(event)
    if not title and not text_sample:
        log.warning(
            "classify_worker_no_content",
            document_id=str(event.document_id),
        )
        return None

    # 힌트 추출 — document_structure 에 이미 document_type 이 있으면 domain hint 로.
    hints: dict = {}
    if event.document_type:
        hints["rule_based_domain"] = event.document_type

    # 분류기 확보
    if classifier is None:
        try:
            classifier = _build_default_classifier()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "classify_worker_classifier_init_failed",
                document_id=str(event.document_id),
                error=str(exc),
            )
            return None

    try:
        result = await classifier.classify(
            title=title,
            text_sample=text_sample[:_MAX_TEXT_SAMPLE],
            hints=hints,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "classify_worker_classify_failed",
            document_id=str(event.document_id),
            error=str(exc),
        )
        return None

    if not isinstance(result, dict):
        log.warning(
            "classify_worker_bad_result_type",
            document_id=str(event.document_id),
            got=type(result).__name__,
        )
        return None

    # 저장
    result["analyzed_at"] = datetime.utcnow().isoformat() + "Z"
    saved = await _persist(event, result, db_session_factory=db_session_factory)
    if saved:
        log.info(
            "classify_worker_done",
            document_id=str(event.document_id),
            domain=result.get("domain"),
            confidence=result.get("confidence"),
            tag_count=len(result.get("tags") or []),
        )
    return result


# ---------------------------------------------------------------------- helpers


async def _load_document_sample(
    event: DocumentParsedEvent,
) -> tuple[str, str]:
    """제목 + 본문 앞부분을 로드한다.

    우선순위:
    1. parse cache 에서 ParseResult.raw_text + documents.title
    2. 캐시 실패 시 빈 text_sample + title only (제목만 분류)
    """
    title = ""
    # 제목 — DB 에서 (간단 조회)
    try:
        from src.core.database import async_session_factory
        from src.core.models.document import Document
        from sqlalchemy import select

        async with async_session_factory() as session:
            row = await session.execute(
                select(Document.title).where(Document.id == event.document_id)
            )
            title = (row.scalar_one_or_none() or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.debug("classify_worker_title_load_failed", error=str(exc))

    # 본문 샘플 — parse cache
    text_sample = ""
    try:
        from src.pipeline.cache import load_parse_result

        parse_result = await load_parse_result(event.document_id)
        if parse_result is not None:
            text_sample = getattr(parse_result, "raw_text", "") or ""
    except Exception as exc:  # noqa: BLE001
        log.debug("classify_worker_parse_cache_load_failed", error=str(exc))

    return title, text_sample


async def _persist(
    event: DocumentParsedEvent,
    result: dict,
    *,
    db_session_factory: Any = None,
) -> bool:
    """processing_meta.auto_classification 에 병합 저장.

    Returns True on success, False on persist failure (logged).
    """
    try:
        if db_session_factory is None:
            from src.core.database import async_session_factory as _default_factory

            db_session_factory = _default_factory

        from src.core.services.document_service import DocumentService

        async with db_session_factory() as session:
            svc = DocumentService(session)
            await svc.update_processing_meta(
                event.document_id,
                processing_meta={"auto_classification": result},
            )
            await session.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "classify_worker_persist_failed",
            document_id=str(event.document_id),
            error=str(exc),
        )
        return False


def _build_default_classifier() -> Any:
    """프로덕션 default DocumentClassifier (VLLMAdapter + json mode)."""
    from src.agent_framework.classifier.document_classifier import DocumentClassifier
    from src.agent_framework.llm.vllm_adapter import VLLMAdapter

    return DocumentClassifier(llm_client=VLLMAdapter())
