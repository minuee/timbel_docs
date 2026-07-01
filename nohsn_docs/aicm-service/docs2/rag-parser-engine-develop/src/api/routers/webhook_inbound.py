"""인바운드 Webhook 라우터 — 외부에서 AICM으로 문서 업로드.

외부 시스템(캘린더, 이메일, Slack, 커스텀 등)에서 API Key 인증 기반으로
문서를 AICM에 푸시할 수 있는 엔드포인트를 제공한다.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.core.database import get_db
from src.integration.api_gateway.auth import verify_api_key
from src.integration.api_gateway.models import APIKeyRecord

logger = get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------

VALID_SOURCE_TYPES = {"calendar", "email", "slack", "custom"}
MAX_BULK_SIZE = 50


class InboundDocumentPayload(BaseModel):
    """단일 인바운드 문서 페이로드."""

    source_type: Literal["calendar", "email", "slack", "custom"] = Field(
        ..., description="문서 출처 유형"
    )
    content: str = Field(
        ..., min_length=1, max_length=500_000, description="문서 본문 텍스트"
    )
    metadata: dict = Field(
        default_factory=dict, description="추가 메타데이터 (제목, 작성자 등)"
    )
    repository_id: UUID | None = Field(
        default=None, description="대상 저장소 ID (미지정 시 기본 저장소)"
    )


class InboundDocumentResponse(BaseModel):
    """인바운드 문서 처리 응답."""

    document_id: UUID
    estimated_processing_time: str = Field(
        default="30~120초", description="예상 처리 시간"
    )


class BulkInboundRequest(BaseModel):
    """벌크 인바운드 문서 요청."""

    documents: list[InboundDocumentPayload] = Field(
        ..., min_length=1, max_length=MAX_BULK_SIZE
    )


class BulkInboundResponseItem(BaseModel):
    """벌크 인바운드 개별 문서 결과."""

    index: int
    document_id: UUID | None = None
    error: str | None = None


class BulkInboundResponse(BaseModel):
    """벌크 인바운드 응답."""

    total: int
    succeeded: int
    failed: int
    results: list[BulkInboundResponseItem]
    estimated_processing_time: str = Field(default="1~5분")


# ---------------------------------------------------------------------------
# 헬퍼: 문서 생성 + 파이프라인 큐잉
# ---------------------------------------------------------------------------


async def _create_inbound_document(
    tenant_id: UUID,
    payload: InboundDocumentPayload,
    db: AsyncSession,
    api_key_record: APIKeyRecord,
) -> UUID:
    """인바운드 문서를 DB에 생성하고 파이프라인 큐에 등록한다."""
    doc_id = uuid4()

    # 저장소 결정: payload에 명시되었으면 사용, 아니면 테넌트 기본 저장소
    repo_id = payload.repository_id

    if repo_id is not None:
        # API Key에 allowed_repository_ids가 설정된 경우 접근 제한 확인
        if (
            api_key_record.allowed_repository_ids
            and repo_id not in api_key_record.allowed_repository_ids
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"이 API Key는 저장소 {repo_id}에 접근 권한이 없습니다.",
            )

    # 문서 제목 결정
    title = payload.metadata.get("title") or payload.metadata.get("subject")
    if not title:
        title = f"[{payload.source_type}] 인바운드 문서 {doc_id.hex[:8]}"

    try:
        from src.core.models.document import Document

        # 저장소가 미지정이면 테넌트 첫 번째 저장소 사용
        if repo_id is None:
            from src.core.models.repository import Repository

            stmt = (
                select(Repository)
                .where(Repository.tenant_id == tenant_id)
                .order_by(Repository.created_at.asc())
                .limit(1)
            )
            result = await db.execute(stmt)
            default_repo = result.scalar_one_or_none()
            if default_repo is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="테넌트에 저장소가 없습니다. 먼저 저장소를 생성하세요.",
                )
            repo_id = default_repo.id

        # payload.metadata 에 body_html / headers / to_address 같은 본문 보조
        # 정보가 있을 수 있음 — inbox detail 의 body_text/body_html/headers 가
        # processing_meta.body.{text/html/headers/to} 에서 읽으므로 같은
        # 구조로 정규화.
        body_html_meta = payload.metadata.pop("body_html", None) if isinstance(payload.metadata, dict) else None
        headers_meta = payload.metadata.pop("headers", None) if isinstance(payload.metadata, dict) else None
        to_address_meta = (
            payload.metadata.pop("to_address", None) if isinstance(payload.metadata, dict) else None
        )

        # B1 (병렬) 산출물: 첨부 base64 페이로드. 본 라우터에서는 vision OCR
        # 후 본문(body.text + body.ocr_text)에 합성하고 metadata 에서 제거.
        attachment_payloads = (
            payload.metadata.pop("_attachment_payloads", None)
            if isinstance(payload.metadata, dict)
            else None
        )

        body_block: dict[str, Any] = {"text": payload.content}
        if body_html_meta:
            body_block["html"] = body_html_meta
        if headers_meta:
            body_block["headers"] = headers_meta
        if to_address_meta:
            body_block["to"] = to_address_meta

        # ── 첨부 이미지 OCR (vLLM gemma-4-31b vision + sha256 cache) ──
        ocr_results: list[dict] = []
        if attachment_payloads and isinstance(attachment_payloads, list):
            try:
                from src.integration.mail.email_ocr import (
                    ocr_email_attachments,
                    render_ocr_block,
                )

                ocr_results = await ocr_email_attachments(attachment_payloads)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "inbound_email_ocr_failed",
                    document_id=str(doc_id),
                    error=str(exc),
                )
                ocr_results = []

            if ocr_results:
                body_block["ocr_text"] = ocr_results
                # 본문이 비었거나 매우 짧으면 OCR 결과를 본문 자리에 합성 →
                # downstream classifier 가 빈 본문 메일도 분류 가능.
                ocr_block_text = render_ocr_block(ocr_results)
                current_text = str(body_block.get("text") or "").strip()
                if ocr_block_text and len(current_text) < 40:
                    merged = (
                        f"{current_text}\n\n{ocr_block_text}".strip()
                        if current_text
                        else ocr_block_text
                    )
                    body_block["text"] = merged
                    # payload.content 도 같은 본문으로 끌어올려 파이프라인 큐가 OCR
                    # 본문을 사용하게 한다.
                    payload.content = merged[:500_000]
                logger.info(
                    "inbound_email_ocr_attached",
                    document_id=str(doc_id),
                    image_count=len(ocr_results),
                    cached=sum(1 for r in ocr_results if r.get("cached")),
                )

        doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            repository_id=repo_id,
            title=title,
            source_file=f"inbound/{payload.source_type}/{doc_id.hex[:8]}.txt",
            source_format="text",
            status="draft",
            processing_meta={
                "source_type": payload.source_type,
                "inbound": True,
                "content_length": len(payload.content),
                "body": body_block,
                **payload.metadata,
            },
        )
        db.add(doc)
        await db.flush()

        logger.info(
            "inbound_document_created",
            document_id=str(doc_id),
            tenant_id=str(tenant_id),
            source_type=payload.source_type,
            content_length=len(payload.content),
        )

    except HTTPException:
        raise
    except ImportError:
        # Document 모델 없는 경우 — 스텁 생성
        logger.warning(
            "document_model_unavailable_stub_created",
            document_id=str(doc_id),
        )
    except Exception as exc:
        logger.error(
            "inbound_document_creation_failed",
            document_id=str(doc_id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"문서 생성 실패: {exc}",
        )

    # 파이프라인 큐에 등록 (비동기, 실패해도 문서는 생성됨)
    try:
        from src.pipeline.workers.task_queue import enqueue_parse_task

        await enqueue_parse_task(
            document_id=doc_id,
            tenant_id=tenant_id,
            content=payload.content,
            source_type=payload.source_type,
        )
        logger.info("inbound_document_enqueued", document_id=str(doc_id))
    except ImportError:
        logger.debug("parse_worker_not_available", document_id=str(doc_id))
    except Exception as exc:
        logger.warning(
            "inbound_document_enqueue_failed",
            document_id=str(doc_id),
            error=str(exc),
        )

    return doc_id


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.post(
    "/webhooks/inbound/{api_key_id}",
    response_model=ApiResponse[InboundDocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="인바운드 Webhook — 단일 문서 업로드",
)
async def inbound_webhook_single(
    api_key_id: UUID,
    payload: InboundDocumentPayload,
    api_key: APIKeyRecord = Depends(verify_api_key("inbound")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InboundDocumentResponse]:
    """외부 시스템에서 인증된 API Key로 단일 문서를 AICM에 푸시한다.

    - source_type: calendar, email, slack, custom
    - content: 문서 본문 텍스트
    - metadata: 추가 메타데이터 (title, author 등)
    - repository_id: 대상 저장소 (미지정 시 테넌트 기본 저장소)
    """
    # api_key_id 경로 파라미터와 실제 인증된 키 ID 검증
    if str(api_key.id) != str(api_key_id):
        logger.warning(
            "inbound_webhook_key_mismatch",
            path_key_id=str(api_key_id),
            auth_key_id=str(api_key.id),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key ID가 인증된 키와 일치하지 않습니다.",
        )

    doc_id = await _create_inbound_document(
        tenant_id=api_key.tenant_id,
        payload=payload,
        db=db,
        api_key_record=api_key,
    )

    return ApiResponse(
        data=InboundDocumentResponse(
            document_id=doc_id,
            estimated_processing_time="30~120초",
        )
    )


@router.post(
    "/webhooks/inbound/bulk/{api_key_id}",
    response_model=ApiResponse[BulkInboundResponse],
    status_code=status.HTTP_201_CREATED,
    summary="인바운드 Webhook — 벌크 문서 업로드",
)
async def inbound_webhook_bulk(
    api_key_id: UUID,
    body: BulkInboundRequest,
    api_key: APIKeyRecord = Depends(verify_api_key("inbound")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[BulkInboundResponse]:
    """외부 시스템에서 인증된 API Key로 여러 문서를 동시에 AICM에 푸시한다.

    최대 50건/request. 개별 문서 실패 시에도 나머지는 처리된다.
    """
    # api_key_id 경로 파라미터와 실제 인증된 키 ID 검증
    if str(api_key.id) != str(api_key_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key ID가 인증된 키와 일치하지 않습니다.",
        )

    if len(body.documents) > MAX_BULK_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"최대 {MAX_BULK_SIZE}건까지 업로드할 수 있습니다.",
        )

    results: list[BulkInboundResponseItem] = []
    succeeded = 0
    failed = 0

    for idx, payload in enumerate(body.documents):
        try:
            doc_id = await _create_inbound_document(
                tenant_id=api_key.tenant_id,
                payload=payload,
                db=db,
                api_key_record=api_key,
            )
            results.append(BulkInboundResponseItem(index=idx, document_id=doc_id))
            succeeded += 1
        except HTTPException as exc:
            results.append(
                BulkInboundResponseItem(index=idx, error=exc.detail)
            )
            failed += 1
        except Exception as exc:
            logger.error(
                "bulk_inbound_item_failed",
                index=idx,
                error=str(exc),
            )
            results.append(
                BulkInboundResponseItem(index=idx, error=str(exc))
            )
            failed += 1

    logger.info(
        "inbound_webhook_bulk_completed",
        tenant_id=str(api_key.tenant_id),
        total=len(body.documents),
        succeeded=succeeded,
        failed=failed,
    )

    return ApiResponse(
        data=BulkInboundResponse(
            total=len(body.documents),
            succeeded=succeeded,
            failed=failed,
            results=results,
            estimated_processing_time=f"{max(1, succeeded // 2)}~{max(1, succeeded)}분",
        )
    )
