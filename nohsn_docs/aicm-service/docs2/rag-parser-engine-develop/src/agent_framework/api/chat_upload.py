"""/agent/chat/upload — 챗 창에서 드롭한 문서를 KMS 파이프라인에 태우는 shim.

P0.1 (2026-04-28): codex P1-4 보안 수정.
- ``phone`` form 제거 + ``DEFAULT_TENANT_UUID`` fallback 제거.
- Bearer 토큰 필수 → ``account_id`` 추출.
- ``X-Tenant-ID`` 헤더 있으면 ``tenant_memberships`` 검증 후 사용.
- 없으면 accounts.personal_tenant_id 사용. 둘 다 없으면 404.

P0.1 hardening (2026-04-28, codex 2차 review): P1/P2 추가 가드.
- P1-1: ``accounts.is_active = false`` 계정 토큰 차단 (JWT replay 방지).
- P1-2: write 경로이므로 ``viewer`` 롤은 거부 (owner/admin/editor/member 만 통과).
- P2-1: 빈 문자열 ``X-Tenant-ID`` 가 personal fallback 으로 흐르지 않게 400.
- P2-5: ``sub`` 가 UUID 가 아니면 401 (DB 쿼리 전에 차단).

Tenant 별 ``__chat_uploads__`` 저장소를 자동 확보 (없으면 생성). 기존 KMS
업로드 API 는 ``repository_id`` 필수라 FE 부담을 줄이기 위해 여기서 resolve +
forward 한다. 인덱싱·중복 검사·보안 검증은 ``upload_document`` 가 그대로
수행하므로 코드 중복 없음.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.api.routers.documents import upload_document
from src.core.database import get_db

router = APIRouter(prefix="/agent/chat", tags=["agent-chat-upload"])

CHAT_UPLOAD_REPO_NAME = "__chat_uploads__"

# write-허용 롤 — viewer 는 read-only 이므로 chat upload 차단.
# 코드베이스 컨벤션: ``tenant_memberships.role`` 은 free-form string(20),
# 실제 사용은 'owner'/'admin'/'member'/'viewer' 4종 (engine.py 기준).
# 'editor' 는 src/core/models/user.py UserRole 에 정의 — 미래 확장 대비 포함.
WRITE_ALLOWED_ROLES = ("owner", "admin", "editor", "member")


def _account_id_from_bearer(authorization: str | None) -> str:
    """Authorization 헤더 → account_id (sub). 실패 시 401.

    P2-5: ``sub`` 가 UUID 가 아니면 DB 쿼리 전에 401 — DB 에 raw string 이
    들어가 ``UndefinedFunction`` 등 내부 오류로 200/500 흐르지 않게 방어.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "empty token")
    try:
        payload = decode_token(token)
    except InvalidToken as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    if payload.get("type") not in (None, "access"):
        raise HTTPException(401, "not an access token")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "token missing subject")
    # P2-5: UUID 검증 — 잘못된 sub 가 raw 로 SQL bind 되지 않게.
    try:
        UUID(str(sub))
    except (ValueError, TypeError) as e:
        raise HTTPException(401, "token subject is not a valid account id") from e
    return str(sub)


async def _ensure_account_active(account_id: str, db: AsyncSession) -> None:
    """P1-1: ``accounts.is_active`` gate.

    JWT 가 발급된 후 운영자가 계정을 ``is_active=false`` 로 soft-disable 한
    경우, 토큰 만료 전까지 (15분~) 무효화되지 않으면 chat upload 로 데이터가
    그대로 들어간다 → 토큰마다 DB lookup 으로 가드.
    """
    row = (
        await db.execute(
            text("SELECT is_active FROM accounts WHERE id = :aid LIMIT 1"),
            {"aid": account_id},
        )
    ).first()
    if not row:
        raise HTTPException(401, "account not found")
    if not row[0]:
        raise HTTPException(401, "account is disabled")


async def _verify_tenant_membership(
    account_id: str, tenant_id: UUID, db: AsyncSession
) -> str:
    """tenant_memberships row 가 있고 role 이 write 허용이면 통과. 아니면 403.

    - row 없음 → 403 ("not a member of this tenant")
    - role 이 viewer (write 불가) → 403 ("role not allowed to upload")

    P1-2: 기존엔 row 존재만 검사 → viewer 도 통과해 chat upload 가능했음.
    """
    row = (
        await db.execute(
            text(
                "SELECT role FROM tenant_memberships "
                "WHERE account_id = :aid AND tenant_id = :tid LIMIT 1"
            ),
            {"aid": account_id, "tid": tenant_id},
        )
    ).first()
    if not row:
        raise HTTPException(403, "not a member of this tenant")
    role = (row[0] or "").lower()
    if role not in WRITE_ALLOWED_ROLES:
        raise HTTPException(403, "role not allowed to upload")
    return role


async def _resolve_personal_tenant(
    account_id: str, db: AsyncSession
) -> UUID:
    """accounts.personal_tenant_id 조회 + is_active gate. 없으면 404.

    P1-1: ``is_active = true`` 도 함께 검증해 disabled 계정의 personal tenant
    fallback 도 차단 (``_ensure_account_active`` 와 이중 가드).
    """
    row = (
        await db.execute(
            text(
                "SELECT personal_tenant_id FROM accounts "
                "WHERE id = :aid AND is_active = true LIMIT 1"
            ),
            {"aid": account_id},
        )
    ).first()
    if not row or not row[0]:
        raise HTTPException(404, "account missing personal_tenant_id")
    return UUID(str(row[0]))


async def _get_or_create_chat_repo(db: AsyncSession, tenant_id: UUID) -> UUID:
    """tenant 별 ``__chat_uploads__`` 저장소 확보. 없으면 생성."""
    r = await db.execute(
        text(
            """
            INSERT INTO repositories
              (id, tenant_id, name, description,
               config, search_mode, display_config, llm_config, is_active)
            VALUES
              (gen_random_uuid(), :tid, :name,
               '채팅창에서 업로드된 문서 (자동 생성)',
               '{}'::jsonb, 'hybrid', '{}'::jsonb, '{}'::jsonb, true)
            ON CONFLICT ON CONSTRAINT uq_repositories_tenant_name
              DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        ),
        {"tid": tenant_id, "name": CHAT_UPLOAD_REPO_NAME},
    )
    repo_id = r.scalar_one()
    await db.commit()
    return repo_id


@router.post("/upload", status_code=201)
async def chat_upload(
    file: UploadFile,
    authorization: str | None = Header(None),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """챗 첨부 문서 → KMS 인덱싱 파이프라인 (P0.1 인증 강화).

    1. Authorization Bearer 검증 → account_id (없거나 invalid → 401).
    2. ``accounts.is_active`` 검증 (P1-1) — disabled 계정은 401.
    3. X-Tenant-ID 처리 (P2-1):
       - None  → personal tenant fallback.
       - 빈/공백 → 400 (silent fallback 차단).
       - UUID  → 멤버십 + write role 검증 (실패 시 403).
       - non-UUID → 400.
    4. tenant 전용 ``__chat_uploads__`` repository 확보.
    5. ``upload_document`` 로 forward → validation / 저장 / Kafka emit.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="file.filename required")

    account_id = _account_id_from_bearer(authorization)
    await _ensure_account_active(account_id, db)

    # P2-1: 헤더가 있되 빈 문자열인 경우 personal fallback 으로 흐르지 않게 차단.
    if x_tenant_id is not None:
        cleaned = x_tenant_id.strip()
        if not cleaned:
            raise HTTPException(400, "X-Tenant-ID cannot be empty")
        try:
            tenant_id = UUID(cleaned)
        except (ValueError, AttributeError) as e:
            raise HTTPException(400, f"invalid X-Tenant-ID: {e}") from e
        await _verify_tenant_membership(account_id, tenant_id, db)
    else:
        tenant_id = await _resolve_personal_tenant(account_id, db)

    repo_id = await _get_or_create_chat_repo(db, tenant_id)

    # TODO(KMS-Plus): chat upload duplicate handling — see codex P2-2
    # (force_new=True 가 documents.py 의 race window 와 결합 시 중복 row.)
    # TODO(KMS-Plus): pass user_id to upload_document — see codex P2-3
    # (audit trail 의 user_id=None → account_id 매핑 추가 필요.)
    resp = await upload_document(
        file=file,
        repository_id=repo_id,
        title=None,
        category_ids="[]",
        document_type_id=None,
        config_override=None,
        step_by_step=False,
        force_new=True,  # 같은 파일명 재업로드해도 막히지 않도록
        tenant_id=tenant_id,
        user_id=None,
        db=db,
    )

    # ApiResponse wrapper 는 {success, data} — data 를 펼쳐서 반환
    data = getattr(resp, "data", None) or {}
    return {
        "document_id": data.get("document_id"),
        "status": data.get("status", "processing"),
        "tenant_id": str(tenant_id),
        "repository_id": str(repo_id),
        "filename": file.filename,
        "message": data.get("message", ""),
    }
