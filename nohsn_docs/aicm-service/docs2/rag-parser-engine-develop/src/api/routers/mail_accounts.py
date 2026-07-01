"""PR-Z11A — Mail Account CRUD API.

사용자가 IMAP/POP3 메일 계정을 등록/조회/삭제하는 엔드포인트.

원칙:
- 비밀번호는 *서버에 도달 즉시 Fernet 암호화*. DB 에 평문 저장 X.
- GET 응답에 비밀번호 *절대 포함 X* (ciphertext 도 노출 X).
- ``MAIL_CRED_KEY`` env 미설정 시 모든 endpoint 가 503 (Service Unavailable).
- 사용자 본인 계정만 접근 (account_id 격리).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.integration.mail import credentials as mail_creds
# chat_v1 module 의 top-level Depends(get_agent_engine) 는 KMS-only image (agent_framework 누락)
# 에서 모듈 로딩 시점에 FastAPI assertion 으로 폭발. wrapper 로 endpoint 호출 시점까지 import
# 지연. KMS 모드에선 mail_accounts router 자체가 mount 안 되어 wrapper 도 호출되지 않음.
def _get_engine():
    from src.api.routers.chat_v1 import _get_engine as _impl
    return _impl()


def _scope(authorization, x_tenant_id):
    from src.api.routers.chat_v1 import _scope as _impl
    return _impl(authorization, x_tenant_id)


logger = get_logger(__name__)

router = APIRouter()


# ────────────────────────── 요청/응답 schema ──────────────────────────


class MailAccountCreate(BaseModel):
    label: str = Field(default="기본", max_length=64, description="사용자 식별 라벨")
    host: str = Field(..., max_length=255, description="메일 서버 호스트")
    port: int = Field(..., ge=1, le=65535)
    protocol: str = Field(..., pattern="^(imap|imaps|pop3|pop3s)$")
    username: str = Field(..., max_length=255)
    password: str = Field(..., min_length=1, max_length=500)
    poll_interval_seconds: int = Field(default=300, ge=60, le=3600)
    # SMTP — 발송 자격증명 (옵션, 같은 row 에 nullable). 미입력이면 IMAP 전용.
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = Field(default=None, min_length=1, max_length=500)
    smtp_use_tls: bool = True


class MailAccountUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=64)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    protocol: str | None = Field(default=None, pattern="^(imap|imaps|pop3|pop3s)$")
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=500)
    poll_interval_seconds: int | None = Field(default=None, ge=60, le=3600)
    enabled: bool | None = None
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = Field(default=None, min_length=1, max_length=500)
    smtp_use_tls: bool | None = None


class MailAccountOut(BaseModel):
    """비밀번호 절대 포함 X."""

    id: UUID
    label: str
    host: str
    port: int
    protocol: str
    username: str
    last_uid_synced: str | None
    last_polled_at: datetime | None
    poll_interval_seconds: int
    enabled: bool
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    # SMTP — ciphertext 노출 X. 활성 여부와 host/port/username 만 메타로.
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_use_tls: bool | None = None
    smtp_configured: bool = False


class TestConnectionResult(BaseModel):
    success: bool
    detail: str
    server_capabilities: list[str] | None = None


# ────────────────────────── helpers ──────────────────────────


def _require_creds_available() -> None:
    if not mail_creds.is_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "메일 자격증명 암호화 키 (MAIL_CRED_KEY) 미설정. "
                "관리자에게 환경변수 설정 요청 필요."
            ),
        )


# ────────────────────────── endpoints ──────────────────────────


@router.post(
    "/mail-accounts",
    response_model=ApiResponse[MailAccountOut],
    status_code=status.HTTP_201_CREATED,
    summary="메일 계정 등록",
    description=(
        "IMAP/POP3 메일 계정을 등록한다. password 는 서버에서 AES 암호화 후 저장 — "
        "복호화 키는 환경변수 `MAIL_CRED_KEY` 로 관리된다. 호출 시 자동으로 "
        "현재 사용자의 account_id 에 귀속된다."
    ),
    responses={
        201: {"description": "메일 계정 등록 성공"},
        403: {"description": "자격증명 키 미설정 또는 권한 없음"},
        422: {"description": "validation 실패"},
    },
)
async def create_mail_account(
    body: MailAccountCreate,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[MailAccountOut]:
    _require_creds_available()
    aid, _tid = _scope(authorization, x_tenant_id)
    pw_enc = mail_creds.encrypt(body.password)
    db = _get_engine()
    smtp_pw_enc = (
        mail_creds.encrypt(body.smtp_password) if body.smtp_password else None
    )
    async with db.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    INSERT INTO user_mail_accounts
                        (account_id, label, host, port, protocol, username,
                         password_encrypted, poll_interval_seconds,
                         smtp_host, smtp_port, smtp_username,
                         smtp_password_encrypted, smtp_use_tls)
                    VALUES (:aid, :label, :host, :port, :protocol, :user,
                            :pw, :poll,
                            :sh, :sp, :su, :spw, :stls)
                    RETURNING id, label, host, port, protocol, username,
                              last_uid_synced, last_polled_at,
                              poll_interval_seconds, enabled, last_error,
                              created_at, updated_at,
                              smtp_host, smtp_port, smtp_username, smtp_use_tls,
                              (smtp_host IS NOT NULL AND smtp_password_encrypted IS NOT NULL) AS smtp_configured
                    """
                ),
                {
                    "aid": aid,
                    "label": body.label,
                    "host": body.host,
                    "port": body.port,
                    "protocol": body.protocol,
                    "user": body.username,
                    "pw": pw_enc,
                    "poll": body.poll_interval_seconds,
                    "sh": body.smtp_host,
                    "sp": body.smtp_port,
                    "su": body.smtp_username,
                    "spw": smtp_pw_enc,
                    "stls": body.smtp_use_tls,
                },
            )
        ).first()
    logger.info("mail_account_created", account_id=str(aid), host=body.host, smtp=bool(smtp_pw_enc))
    return ApiResponse(data=MailAccountOut(**row._mapping))


@router.get(
    "/mail-accounts",
    response_model=ApiResponse[list[MailAccountOut]],
    summary="내 메일 계정 목록",
    description=(
        "현재 사용자가 등록한 메일 계정 목록을 created_at 오름차순으로 반환한다. "
        "password 등 자격증명은 응답에 포함되지 않으며, `smtp_configured` flag 로 "
        "SMTP 설정 여부만 노출한다."
    ),
    responses={200: {"description": "메일 계정 배열 (빈 배열도 정상)"}},
)
async def list_mail_accounts(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[list[MailAccountOut]]:
    _require_creds_available()
    aid, _tid = _scope(authorization, x_tenant_id)
    db = _get_engine()
    async with db.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, label, host, port, protocol, username,
                           last_uid_synced, last_polled_at,
                           poll_interval_seconds, enabled, last_error,
                           created_at, updated_at,
                           smtp_host, smtp_port, smtp_username, smtp_use_tls,
                           (smtp_host IS NOT NULL AND smtp_password_encrypted IS NOT NULL) AS smtp_configured
                    FROM user_mail_accounts
                    WHERE account_id = :aid
                    ORDER BY created_at ASC
                    """
                ),
                {"aid": aid},
            )
        ).all()
    return ApiResponse(
        data=[MailAccountOut(**r._mapping) for r in rows]
    )


@router.patch(
    "/mail-accounts/{account_id}",
    response_model=ApiResponse[MailAccountOut],
    summary="메일 계정 수정",
    description=(
        "메일 계정의 일부 필드를 수정한다. None 으로 전달된 필드는 무시 — "
        "값이 있는 필드만 UPDATE 된다. `password` / `smtp_password` 는 평문 입력 "
        "후 서버에서 재암호화. 본인 소유 계정만 수정 가능 (account_id 일치 확인)."
    ),
    responses={
        200: {"description": "수정 성공"},
        400: {"description": "변경할 필드가 없음"},
        404: {"description": "메일 계정을 찾을 수 없음"},
    },
)
async def update_mail_account(
    account_id: UUID,
    body: MailAccountUpdate,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[MailAccountOut]:
    _require_creds_available()
    aid, _tid = _scope(authorization, x_tenant_id)
    updates: dict = {}
    for field in (
        "label", "host", "port", "protocol", "username",
        "poll_interval_seconds", "enabled",
        "smtp_host", "smtp_port", "smtp_username", "smtp_use_tls",
    ):
        v = getattr(body, field, None)
        if v is not None:
            updates[field] = v
    if body.password:
        updates["password_encrypted"] = mail_creds.encrypt(body.password)
    if body.smtp_password:
        updates["smtp_password_encrypted"] = mail_creds.encrypt(body.smtp_password)
    if not updates:
        raise HTTPException(400, "변경할 필드가 없습니다")
    set_clause = ", ".join(f"{k} = :{k}" for k in updates) + ", updated_at = NOW()"
    params = {**updates, "id": account_id, "aid": aid}
    db = _get_engine()
    async with db.begin() as conn:
        row = (
            await conn.execute(
                text(
                    f"""
                    UPDATE user_mail_accounts
                       SET {set_clause}
                     WHERE id = :id AND account_id = :aid
                    RETURNING id, label, host, port, protocol, username,
                              last_uid_synced, last_polled_at,
                              poll_interval_seconds, enabled, last_error,
                              created_at, updated_at,
                              smtp_host, smtp_port, smtp_username, smtp_use_tls,
                              (smtp_host IS NOT NULL AND smtp_password_encrypted IS NOT NULL) AS smtp_configured
                    """
                ),
                params,
            )
        ).first()
    if row is None:
        raise HTTPException(404, "메일 계정을 찾을 수 없습니다")
    logger.info("mail_account_updated", account_id=str(aid), id=str(account_id))
    return ApiResponse(data=MailAccountOut(**row._mapping))


@router.delete(
    "/mail-accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="메일 계정 삭제",
    description=(
        "메일 계정을 영구 삭제한다 (hard delete). 본인 소유 계정만 삭제 가능. "
        "삭제 후 동기화된 메일 (email_processing_log) 은 그대로 보존되지만, "
        "이후 sync 는 불가."
    ),
    responses={
        204: {"description": "삭제 성공 (no content)"},
        404: {"description": "메일 계정을 찾을 수 없음"},
    },
)
async def delete_mail_account(
    account_id: UUID,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> None:
    _require_creds_available()
    aid, _tid = _scope(authorization, x_tenant_id)
    db = _get_engine()
    async with db.begin() as conn:
        result = await conn.execute(
            text(
                "DELETE FROM user_mail_accounts WHERE id = :id AND account_id = :aid"
            ),
            {"id": account_id, "aid": aid},
        )
    if result.rowcount == 0:
        raise HTTPException(404, "메일 계정을 찾을 수 없습니다")
    logger.info("mail_account_deleted", account_id=str(aid), id=str(account_id))


@router.post(
    "/mail-accounts/{account_id}/test",
    response_model=ApiResponse[TestConnectionResult],
    summary="메일 계정 연결 테스트",
)
async def test_mail_account(
    account_id: UUID,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[TestConnectionResult]:
    """IMAP/POP3 인증만 검증. 메일 fetch X — capabilities 만 확인 후 연결 닫음."""
    _require_creds_available()
    aid, _tid = _scope(authorization, x_tenant_id)
    db = _get_engine()
    async with db.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT host, port, protocol, username, password_encrypted
                    FROM user_mail_accounts
                    WHERE id = :id AND account_id = :aid
                    """
                ),
                {"id": account_id, "aid": aid},
            )
        ).first()
    if row is None:
        raise HTTPException(404, "메일 계정을 찾을 수 없습니다")

    from src.integration.mail.client import test_connection
    try:
        password = mail_creds.decrypt(row.password_encrypted)
    except (ValueError, TypeError) as e:
        raise HTTPException(500, f"자격증명 복호화 실패: {e}") from e

    try:
        caps = await test_connection(
            host=row.host,
            port=row.port,
            protocol=row.protocol,
            username=row.username,
            password=password,
        )
        return ApiResponse(
            data=TestConnectionResult(
                success=True,
                detail="인증 OK",
                server_capabilities=caps,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "mail_account_test_failed",
            account_id=str(aid),
            id=str(account_id),
            error_type=type(exc).__name__,
        )
        return ApiResponse(
            data=TestConnectionResult(
                success=False,
                detail=str(exc),
            )
        )
    finally:
        # 평문 비밀번호 즉시 폐기
        password = None


# ── 수동 동기화 (P11-19) ─────────────────────────────────────────────


class SyncResult(BaseModel):
    success: bool
    polled: int = 0
    ok: int = 0
    failed: int = 0
    detail: str | None = None


@router.post(
    "/mail-accounts/{mail_account_id}/sync",
    response_model=ApiResponse[SyncResult],
    summary="단일 메일 계정 즉시 동기화 (수동)",
    description=(
        "지정된 메일 계정의 신규 메일을 즉시 가져와 처리한다. "
        "백그라운드 mail_mirror_worker 의 polling 주기를 기다리지 않고 수동 트리거. "
        "성공 시 SyncResult.success=True 와 함께 처리 요약을 반환."
    ),
    responses={
        200: {"description": "동기화 결과 (success / 처리 건수 / 에러 detail)"},
        503: {"description": "메일 미러 워커가 활성화되지 않음"},
    },
)
async def sync_mail_account(
    mail_account_id: UUID,
    request: "Request",  # type: ignore[name-defined]
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[SyncResult]:
    _require_creds_available()
    aid, _tid = _scope(authorization, x_tenant_id)
    worker = getattr(request.app.state, "mail_mirror_worker", None)
    if worker is None:
        raise HTTPException(503, "메일 미러 워커가 활성화되지 않았습니다")
    res = await worker.poll_account_now(
        mail_account_id=mail_account_id, account_id=aid
    )
    if res.get("success"):
        return ApiResponse(
            data=SyncResult(success=True, polled=1, ok=1, detail=res.get("summary"))
        )
    return ApiResponse(
        data=SyncResult(
            success=False,
            polled=1,
            ok=0,
            failed=1,
            detail=str(res.get("error") or "동기화 실패"),
        )
    )


@router.post(
    "/mail-accounts/sync-all",
    response_model=ApiResponse[SyncResult],
    summary="내 모든 활성 메일 계정 일괄 동기화",
    description=(
        "현재 사용자가 등록한 *활성* 메일 계정 전체를 일괄 동기화한다. "
        "enabled=false 인 계정은 skip. 응답의 polled/ok/failed 카운트로 "
        "각 계정 처리 결과를 확인할 수 있다."
    ),
    responses={
        200: {"description": "일괄 동기화 결과"},
        503: {"description": "메일 미러 워커가 활성화되지 않음"},
    },
)
async def sync_all_mail_accounts(
    request: "Request",  # type: ignore[name-defined]
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[SyncResult]:
    _require_creds_available()
    aid, _tid = _scope(authorization, x_tenant_id)
    worker = getattr(request.app.state, "mail_mirror_worker", None)
    if worker is None:
        raise HTTPException(503, "메일 미러 워커가 활성화되지 않았습니다")
    res = await worker.poll_all_for_account_now(account_id=aid)
    return ApiResponse(
        data=SyncResult(
            success=bool(res.get("success")),
            polled=int(res.get("polled") or 0),
            ok=int(res.get("ok") or 0),
            failed=int(res.get("failed") or 0),
            detail=str(res.get("error") or "") or None,
        )
    )
