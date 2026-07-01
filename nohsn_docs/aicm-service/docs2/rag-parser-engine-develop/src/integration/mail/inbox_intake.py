"""PR-Z11A — 미러링된 이메일 1통 처리 (KMS 저장 + 분류 + log INSERT).

호출 경로:
    ``MailMirrorWorker._poll_due_accounts()``
        → fetch_new() → process_email() per mail
            → _create_inbound_document() (KMS 저장)
            → EmailClassifier.classify() (LLM 1콜)
            → INSERT INTO email_processing_log

원칙:
- 액션 (schedule.create / todo / reminder) 호출 *X*. 사용자 confirm 단계에서
  frontend 가 inbox API agent (E2) 를 통해 호출. 여기선 *분류 + 로그 + 저장* 만.
- 한 메일 처리 실패가 다른 메일 처리를 막지 않음 (상위 worker 에서 try/except).
- 사용자별 ``email-inbox`` repository 자동 생성. ``__chat_uploads__`` 패턴 참조.
- ``_create_inbound_document`` 는 webhook 라우터에서 재사용 — DB 세션 + stub
  APIKeyRecord 주입 (인증 우회: api key id 검증은 라우터 레벨이고, 헬퍼 자체는
  allowed_repository_ids 만 본다).

테스트: ``tests/integration/mail/test_inbox_intake.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.common.logging import get_logger
from src.integration.mail.classifier import (
    ClassificationResult,
    EmailClassifier,
)

log = get_logger(__name__)


EMAIL_INBOX_REPO_NAME = "email-inbox"
EMAIL_INBOX_REPO_DESC = "메일함 — 등록된 메일 계정에서 자동 미러링된 이메일"


# ---------------------------------------------------------------------------
# Repository helper — tenant 별 email-inbox 저장소
# ---------------------------------------------------------------------------


async def get_or_create_email_inbox_repo(
    db_engine: AsyncEngine, tenant_id: UUID
) -> UUID:
    """사용자별 ``email-inbox`` repository 확보. 없으면 생성. ``chat_uploads`` 패턴 참조.

    UNIQUE 제약 ``uq_repositories_tenant_name`` 활용 — race-safe.
    """
    async with db_engine.begin() as conn:
        row = await conn.execute(
            text(
                """
                INSERT INTO repositories
                  (id, tenant_id, name, description,
                   config, search_mode, display_config, llm_config, is_active)
                VALUES
                  (gen_random_uuid(), :tid, :name, :desc,
                   '{}'::jsonb, 'hybrid', '{}'::jsonb, '{}'::jsonb, true)
                ON CONFLICT ON CONSTRAINT uq_repositories_tenant_name
                  DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """
            ),
            {"tid": tenant_id, "name": EMAIL_INBOX_REPO_NAME, "desc": EMAIL_INBOX_REPO_DESC},
        )
        repo_id = row.scalar_one()
    return UUID(str(repo_id))


# ---------------------------------------------------------------------------
# KMS document save — webhook helper 재사용 (auth 우회 stub APIKeyRecord)
# ---------------------------------------------------------------------------


def _build_stub_api_key(tenant_id: UUID) -> Any:
    """``_create_inbound_document`` 가 ``api_key_record.allowed_repository_ids`` 만
    참조하므로, 그 필드만 노출하는 lightweight stub 으로 충분.
    Pydantic 검증 우회 — duck typing.
    """

    class _Stub:
        def __init__(self) -> None:
            self.id = uuid4()
            self.tenant_id = tenant_id
            self.allowed_repository_ids = None  # 모든 repo 허용

    return _Stub()


# ---------------------------------------------------------------------------
# Main entry — process_email
# ---------------------------------------------------------------------------


async def process_email(
    *,
    account_id: UUID,
    fetched_email: Any,
    mail_account_id: UUID,
    db_engine: AsyncEngine,
    classifier: EmailClassifier,
    tenant_id: UUID | None = None,
) -> dict[str, Any]:
    """단일 메일 처리: KMS 저장 + LLM 분류 + log INSERT.

    Args:
        account_id: 사용자 account.id (= user_mail_accounts.account_id)
        fetched_email: ``client.FetchedEmail`` 인스턴스
        mail_account_id: ``user_mail_accounts.id``
        db_engine: SQLAlchemy AsyncEngine
        classifier: ``EmailClassifier`` 인스턴스 (LLM 주입됨)
        tenant_id: KMS 저장 대상 tenant. 미지정 시 ``account_id`` 를 그대로 사용
            (Stage B 의 personal_tenant_id == account_id 동기화 가정).

    Returns:
        ``{"document_id": UUID|None, "log_id": UUID, "classification": dict}``
    """
    # 1) 분류 (LLM 1콜) — 실패해도 fallback 결과 항상 반환
    try:
        classification: ClassificationResult = await classifier.classify(fetched_email)
    except Exception as exc:  # noqa: BLE001
        # classifier 자체가 fail-soft 라 여기로 안 와야 정상이지만 방어.
        log.warning("inbox_intake_classify_unexpected_error", error=str(exc))
        classification = EmailClassifier._fallback(  # type: ignore[attr-defined]
            f"(분류기 예외: {type(exc).__name__})"
        )

    classification_dict = classification.to_dict()

    # ★ message_id dedup — 같은 메일이 multi-worker / 재 polling 으로 중복
    # log row 만들지 않게. 단, log 만 있고 documents row 가 사라진 경우 (사용자
    # 일괄 cleanup 후 재 polling) 에는 *재처리 허용* 후 log.document_id 업데이트.
    # P11-19 (2026-05-06).
    msg_id = getattr(fetched_email, "message_id", None)
    existing_log_id: UUID | None = None
    if msg_id:
        try:
            async with db_engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            """
                            SELECT l.id, l.document_id, d.id IS NOT NULL AS doc_exists
                              FROM email_processing_log l
                              LEFT JOIN documents d ON d.id = l.document_id
                             WHERE l.account_id = :aid AND l.message_id = :mid
                             LIMIT 1
                            """
                        ),
                        {"aid": account_id, "mid": msg_id[:500]},
                    )
                ).first()
                if row and row.doc_exists:
                    log.debug(
                        "inbox_intake_dedup_skip",
                        account_id=str(account_id),
                        existing_log_id=str(row.id),
                        message_id=msg_id[:60],
                    )
                    return {
                        "document_id": row.document_id,
                        "log_id": UUID(str(row.id)),
                        "classification": classification_dict,
                        "duplicate": True,
                    }
                if row:
                    # log 는 있는데 doc 이 사라진 케이스 — 재처리 후 log update.
                    existing_log_id = UUID(str(row.id))
                    log.info(
                        "inbox_intake_orphan_log_repair",
                        account_id=str(account_id),
                        log_id=str(row.id),
                        message_id=msg_id[:60],
                    )
        except Exception as exc:  # noqa: BLE001
            log.debug("inbox_intake_dedup_check_failed", error=str(exc))

    # 2) KMS 저장 — tenant_id 가 *진짜 tenants.id* 일 때만 시도. 없으면 skip.
    #    이전 버그: account_id 폴백 → repositories_tenant_id_fkey 위반 로그 spam.
    document_id: UUID | None = None
    if tenant_id is not None:
        try:
            document_id = await _save_to_kms(
                tenant_id=tenant_id,
                fetched_email=fetched_email,
                db_engine=db_engine,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "inbox_intake_kms_save_failed",
                account_id=str(account_id),
                mail_account_id=str(mail_account_id),
                uid=getattr(fetched_email, "uid", None),
                error=str(exc),
            )
    else:
        log.debug(
            "inbox_intake_kms_save_skipped_no_tenant",
            account_id=str(account_id),
            mail_account_id=str(mail_account_id),
        )

    # 3) log INSERT or UPDATE (orphan repair 시 기존 row 의 document_id 갱신)
    if existing_log_id is not None and document_id is not None:
        try:
            async with db_engine.begin() as conn:
                await conn.execute(
                    text(
                        """
                        UPDATE email_processing_log
                           SET document_id = :did
                         WHERE id = :id
                        """
                    ),
                    {"did": document_id, "id": existing_log_id},
                )
            log_id = existing_log_id
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "inbox_intake_orphan_log_update_failed",
                error=str(exc),
                log_id=str(existing_log_id),
            )
            log_id = existing_log_id  # 그래도 같은 id 사용
    else:
        log_id = await _insert_processing_log(
            db_engine=db_engine,
            account_id=account_id,
            mail_account_id=mail_account_id,
            document_id=document_id,
            fetched_email=fetched_email,
            classification_dict=classification_dict,
            trust_score=classification.trust_score,
        )

    log.info(
        "email_processed",
        account_id=str(account_id),
        mail_account_id=str(mail_account_id),
        document_id=str(document_id) if document_id else None,
        log_id=str(log_id),
        category=classification.category,
        trust=classification.trust_score,
    )

    return {
        "document_id": document_id,
        "log_id": log_id,
        "classification": classification_dict,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _save_to_kms(
    *,
    tenant_id: UUID,
    fetched_email: Any,
    db_engine: AsyncEngine,
) -> UUID | None:
    """KMS 저장 — webhook_inbound._create_inbound_document 재사용.

    별도 AsyncSession 을 직접 만들어 헬퍼에 주입 (worker context 라 FastAPI
    의존성 주입 경로가 없음).
    """
    # 지연 import — circular 회피 + classifier 모듈만 쓰는 사용자는 불필요한
    # 라우터 import 비용을 안 치르도록.
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    from src.api.routers.webhook_inbound import (
        InboundDocumentPayload,
        _create_inbound_document,
    )

    repo_id = await get_or_create_email_inbox_repo(db_engine, tenant_id)

    body_text = (getattr(fetched_email, "body_text", None) or "").strip()
    if not body_text:
        # HTML-only — classifier 가 prompt 용으론 이미 변환했지만 KMS 저장은 별도.
        body_html = getattr(fetched_email, "body_html", None)
        if body_html:
            try:
                from src.integration.mail.classifier import _html_to_text

                body_text = _html_to_text(body_html).strip()
            except Exception:  # noqa: BLE001
                body_text = body_html  # 최후 — raw 그대로
    if not body_text:
        body_text = "(빈 본문)"

    # 첨부 — client._extract_attachments 에서 추출됨. metadata 에는 *경량 meta*
    # 만 싣고 (filename/content_type/size_bytes/content_id), 실제 base64 페이로드는
    # 별도 키 ``_attachment_payloads`` 에 임시 저장. 향후 OCR 파이프라인이 그
    # 키를 소비. 현재 단계에서는 documents.processing_meta 에 같이 들어가지만,
    # 다음 단계에서 별도 storage (MinIO/disk) 로 옮길 수 있도록 키 prefix 분리.
    raw_attachments = getattr(fetched_email, "attachments", None) or []
    attachments_meta: list[dict[str, Any]] = []
    attachment_payloads: list[dict[str, Any]] = []
    for att in raw_attachments:
        # dict | dataclass 모두 허용 — 안전 추출.
        if isinstance(att, dict):
            filename = att.get("filename") or ""
            content_type = att.get("content_type") or ""
            size_bytes = int(att.get("size_bytes") or 0)
            content_id = att.get("content_id") or ""
            data_b64 = att.get("data_base64") or ""
        else:
            filename = getattr(att, "filename", "") or ""
            content_type = getattr(att, "content_type", "") or ""
            size_bytes = int(getattr(att, "size_bytes", 0) or 0)
            content_id = getattr(att, "content_id", "") or ""
            data_b64 = getattr(att, "data_base64", "") or ""
        attachments_meta.append(
            {
                "filename": filename,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "content_id": content_id,
            }
        )
        # 페이로드는 별도 키. 향후 OCR 파이프라인이 소비.
        attachment_payloads.append(
            {
                "filename": filename,
                "content_type": content_type,
                "content_id": content_id,
                "data_base64": data_b64,
            }
        )

    metadata = {
        "title": getattr(fetched_email, "subject", None) or "(제목 없음)",
        "subject": getattr(fetched_email, "subject", None) or "",
        "from_address": getattr(fetched_email, "from_address", None) or "",
        "from_domain": getattr(fetched_email, "from_domain", None) or "",
        "to_address": getattr(fetched_email, "to_address", None) or "",
        "date_iso": getattr(fetched_email, "date_iso", None) or "",
        "message_id": getattr(fetched_email, "message_id", None) or "",
        "uid": getattr(fetched_email, "uid", None) or "",
        "raw_size": int(getattr(fetched_email, "raw_size", 0) or 0),
        # webhook_inbound 의 _create_inbound_document 가 processing_meta.body.{text,
        # html, headers, to} 에 정규화 저장 → inbox detail 이 그대로 읽음.
        "body_html": getattr(fetched_email, "body_html", None) or None,
        "headers": getattr(fetched_email, "headers", None) or None,
    }
    if attachments_meta:
        # 경량 meta 는 항상 metadata 에. UI/검색이 읽을 수 있는 키.
        metadata["attachments_meta"] = attachments_meta
        # base64 페이로드 — _ prefix 로 *내부 임시* 임을 표시. 향후 OCR pipeline
        # 이 소비 후 별도 저장소로 옮기면 이 키는 비울 것.
        metadata["_attachment_payloads"] = attachment_payloads

    payload = InboundDocumentPayload(
        source_type="email",
        content=body_text[:500_000],  # webhook 스키마 max_length 안전 truncate
        metadata=metadata,
        repository_id=repo_id,
    )

    api_key_stub = _build_stub_api_key(tenant_id)

    Session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        try:
            doc_id = await _create_inbound_document(
                tenant_id=tenant_id,
                payload=payload,
                db=db,
                api_key_record=api_key_stub,
            )
            await db.commit()
            return UUID(str(doc_id))
        except Exception:
            await db.rollback()
            raise


async def _insert_processing_log(
    *,
    db_engine: AsyncEngine,
    account_id: UUID,
    mail_account_id: UUID,
    document_id: UUID | None,
    fetched_email: Any,
    classification_dict: dict[str, Any],
    trust_score: float | None,
) -> UUID:
    """``email_processing_log`` 한 행 INSERT. id 반환."""
    log_id = uuid4()

    received_at: datetime | None = None
    date_iso = getattr(fetched_email, "date_iso", None)
    if date_iso:
        try:
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(date_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            received_at = dt
        except Exception:  # noqa: BLE001
            received_at = None

    subject = (getattr(fetched_email, "subject", None) or "")[:500]
    from_address = (getattr(fetched_email, "from_address", None) or "")[:255]
    from_domain = (getattr(fetched_email, "from_domain", None) or "")[:255]
    message_id = (getattr(fetched_email, "message_id", None) or "")[:500]

    import json as _json

    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO email_processing_log
                  (id, account_id, mail_account_id, document_id,
                   message_id, from_address, from_domain, subject,
                   received_at, classification, trust_score,
                   actions_taken, processed_at)
                VALUES
                  (:id, :aid, :maid, :did,
                   :mid, :fa, :fd, :subj,
                   :recv, CAST(:cls AS JSONB), :trust,
                   '[]'::jsonb, NOW())
                """
            ),
            {
                "id": log_id,
                "aid": account_id,
                "maid": mail_account_id,
                "did": document_id,
                "mid": message_id or None,
                "fa": from_address or None,
                "fd": from_domain or None,
                "subj": subject or None,
                "recv": received_at,
                "cls": _json.dumps(classification_dict, ensure_ascii=False),
                "trust": trust_score,
            },
        )
    return log_id
