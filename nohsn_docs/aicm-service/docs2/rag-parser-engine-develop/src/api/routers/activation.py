"""통합 활성화 API — spec §2.

현실적 제약:
- documents 에 tenant_id 직접 컬럼 없음 → repository_id 필터 지원.
- skill_drafts / connector_credential_pairs 는 tenant_id 직접 필터 가능.
- documents.id / skill_drafts.id = uuid (CAST 필요).
- connector_credential_pairs.id = varchar (CAST 불필요).
- ActivationService 는 sync SQLAlchemy connection 기반 → asyncio.to_thread 로 감싸 async 에서 호출.

라우트 순서:
  정적 경로 (/pending, /stats) 를 동적 (/{type}/{id}, /{type}/{id}/...) 보다 먼저 선언.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from src.agent_framework.activation.service import (
    ActivationService,
    ArtifactNotFound,
    UnknownArtifactType,
)
from src.agent_framework.activation.state import InvalidTransition


router = APIRouter(prefix="/agent/activation", tags=["activation"])


# ---------------------------------------------------------------------------
# Helpers — DB engine / type sets / pydantic bodies
# ---------------------------------------------------------------------------


def _sync_url() -> str:
    return (
        os.environ["DATABASE_URL"]
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg", "postgresql")
    )


def _engine():
    # v1: 요청당 engine 새로 생성 — 프로덕션에선 싱글톤 pool 로 바꿀 것.
    return create_engine(_sync_url())


ArtifactType = Literal[
    "document",
    "crawl_digest",
    "agent_news_report",
    "stock_snapshot",
    "skill_draft",
    "cc_pair",
    "tool_invocation",
]
_DOC_TYPES = {"document", "crawl_digest", "agent_news_report", "stock_snapshot"}


class ApproveBody(BaseModel):
    action: str = "add"
    target_doc_ids: list[str] | None = None
    execution_policy: dict | None = None
    note: str | None = None


class RejectBody(BaseModel):
    reason: str = Field(..., min_length=1)


class ToolInvocationApproveBody(BaseModel):
    """tool_invocation 승인 — note 만 옵션. resume 자체는 별도 SSE 흐름.

    Phase 1.5A Task 8b — secure consume 경로:
    - ``raw_token`` 있으면 ``ToolInvocationStore.consume_token`` 으로 검증
      (sha256 hash + TTL + 5축 binding). JWT 의 tenant/account 와 binding 비교.
    - ``raw_token`` 없으면 *legacy* path (시연 path 호환) — 추후 deprecated.
    """

    note: str | None = None
    raw_token: str | None = None


class DeferBody(BaseModel):
    note: str = ""


class DeactivateBody(BaseModel):
    reason: str = ""


class VerifyBody(BaseModel):
    note: str | None = None


def _summarize_overlap(hits: list[dict]) -> dict:
    bucket = {"duplicate": 0, "supersedes": 0, "conflicts": 0, "complementary": 0}
    for h in hits or []:
        r = h.get("relation")
        if r == "duplicate":
            bucket["duplicate"] += 1
        elif r == "supersedes_existing":
            bucket["supersedes"] += 1
        elif r == "conflicts":
            bucket["conflicts"] += 1
        elif r == "complementary":
            bucket["complementary"] += 1
    return bucket


def _service_call(method_name: str, *args, **kwargs):
    """sync ActivationService 메서드 호출 헬퍼 — asyncio.to_thread 용 closure 반환."""

    def _call():
        eng = _engine()
        conn = eng.connect()
        try:
            svc = ActivationService(db_session=conn)
            return getattr(svc, method_name)(*args, **kwargs)
        finally:
            conn.close()

    return _call


# ---------------------------------------------------------------------------
# Read endpoints — 정적 경로 먼저!
# ---------------------------------------------------------------------------


@router.get("/pending")
def list_pending(
    type: str = Query("all"),
    repository_id: str | None = None,
    tenant_id: str | None = None,  # documents / skill_draft / cc_pair 공통 (Phase 11)
    sort: Literal["newest", "oldest", "confidence"] = "oldest",
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    """pending_review 아티팩트 목록.

    Phase 11: documents 분기도 ``tenant_id`` 직접 필터 지원. ``tenant_id`` 가
    주어지면 우선 사용, 없으면 ``repository_id`` fallback (legacy), 둘 다 없으면
    전체. ``tenant_id`` 와 ``repository_id`` 가 동시 주어지면 둘 다 AND.
    """
    results: list[dict] = []
    eng = _engine()
    order = "ASC" if sort == "oldest" else "DESC"

    with eng.begin() as conn:
        if type in ("all", "document", "crawl_digest", "agent_news_report", "stock_snapshot"):
            params: dict = {"s": "pending_review", "lim": limit, "off": offset}
            dt_clause = ""
            # "document" 는 umbrella — 서브타입 필터 없이 모든 문서. 서브타입(crawl_digest 등)
            # 은 processing_meta.document_type 으로 필터.
            if type in ("crawl_digest", "agent_news_report", "stock_snapshot"):
                dt_clause = (
                    " AND (processing_meta->>'document_type' = :dt "
                    "OR processing_meta->'body'->>'document_type' = :dt)"
                )
                params["dt"] = type
            repo_clause = ""
            if repository_id:
                repo_clause = " AND repository_id = CAST(:rid AS uuid)"
                params["rid"] = repository_id
            tenant_clause_doc = ""
            if tenant_id:
                # Phase 11: documents.tenant_id 직접 필터
                tenant_clause_doc = " AND tenant_id = CAST(:tid AS uuid)"
                params["tid"] = tenant_id
            rows = conn.execute(
                text(
                    f"""
                    SELECT id, repository_id, title, status, processing_meta,
                           created_at, updated_at
                      FROM documents
                     WHERE status=:s {repo_clause} {tenant_clause_doc} {dt_clause}
                     ORDER BY created_at {order}
                     LIMIT :lim OFFSET :off
                    """
                ),
                params,
            ).mappings().all()
            for r in rows:
                meta = r["processing_meta"] or {}
                act = meta.get("activation") or {}
                overlap_rpt = act.get("overlap_report") or {}
                overlap_hits = overlap_rpt.get("hits") or []
                results.append(
                    {
                        "artifact_type": "document",
                        "artifact_id": str(r["id"]),
                        "title": r["title"],
                        "repository_id": str(r["repository_id"]),
                        "status": r["status"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                        "overlap_summary": _summarize_overlap(overlap_hits),
                        "suggested_action": overlap_rpt.get("suggested_action"),
                        "requires_human": overlap_rpt.get("requires_human", False),
                    }
                )

        if type in ("all", "skill_draft"):
            params = {"s": "pending_review", "lim": limit, "off": offset}
            tenant_clause = ""
            if tenant_id:
                tenant_clause = " AND tenant_id = CAST(:tid AS uuid)"
                params["tid"] = tenant_id
            rows = conn.execute(
                text(
                    f"""
                    SELECT id, account_id, tenant_id, processing_meta,
                           created_at, draft_title
                      FROM skill_drafts
                     WHERE status_v2=:s {tenant_clause}
                     ORDER BY created_at {order}
                     LIMIT :lim OFFSET :off
                    """
                ),
                params,
            ).mappings().all()
            for r in rows:
                meta = r["processing_meta"] or {}
                act = meta.get("activation") or {}
                deps = act.get("dependencies") or {}
                results.append(
                    {
                        "artifact_type": "skill_draft",
                        "artifact_id": str(r["id"]),
                        "title": r["draft_title"]
                        or (meta.get("body") or {}).get("name")
                        or "(untitled skill)",
                        "tenant_id": str(r["tenant_id"]) if r["tenant_id"] else None,
                        "status": "pending_review",
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                        "dependency_summary": {
                            "required": len(deps.get("required_connectors") or []),
                            "missing": deps.get("unresolved_apis", 0),
                        },
                        "suggested_action": None,
                        "requires_human": deps.get("unresolved_apis", 0) > 0
                        or deps.get("side_effect_level") != "read_only",
                    }
                )

        if type in ("all", "cc_pair"):
            params = {"s": "pending_review", "lim": limit, "off": offset}
            tenant_clause = ""
            if tenant_id:
                tenant_clause = " AND tenant_id = :tid"
                params["tid"] = tenant_id
            rows = conn.execute(
                text(
                    f"""
                    SELECT id, tenant_id, connector_id, credential_id, status, created_at
                      FROM connector_credential_pairs
                     WHERE status=:s {tenant_clause}
                     ORDER BY created_at {order}
                     LIMIT :lim OFFSET :off
                    """
                ),
                params,
            ).mappings().all()
            for r in rows:
                results.append(
                    {
                        "artifact_type": "cc_pair",
                        "artifact_id": r["id"],
                        "title": f"CC-pair {r['connector_id']}/{r['credential_id']}",
                        "tenant_id": r["tenant_id"],
                        "status": r["status"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                        "requires_human": True,
                    }
                )

    return results


@router.get("/stats")
def stats(
    repository_id: str | None = None,
    tenant_id: str | None = None,
):
    """status 별 document count.

    Phase 11: ``tenant_id`` 직접 필터 추가 — repository_id 와 같이 또는 단독.
    """
    eng = _engine()
    with eng.begin() as conn:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if repository_id:
            clauses.append("repository_id = CAST(:rid AS uuid)")
            params["rid"] = repository_id
        if tenant_id:
            clauses.append("tenant_id = CAST(:tid AS uuid)")
            params["tid"] = tenant_id
        where_extra = (" AND " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            text(
                f"""
                SELECT status, COUNT(*) AS n FROM documents
                 WHERE 1=1 {where_extra}
                 GROUP BY status
                """
            ),
            params,
        ).mappings().all()
    by_status = {r["status"]: r["n"] for r in rows}
    return {
        "pending": by_status.get("pending_review", 0),
        "active": by_status.get("active", 0),
        "archived": by_status.get("archived", 0),
        "rejected": by_status.get("rejected", 0),
        "processing": by_status.get("processing", 0),
        "failed": by_status.get("failed", 0),
    }


# ---------------------------------------------------------------------------
# Phase 3 — Inventory / Quota / Bulk
#
# /pending 은 pending_review 만 본다. /knowledge.html 은 active+archived+rejected
# 까지 통합 관리해야 하므로 별도 inventory 엔드포인트가 필요.
#
# 정적 경로 (/inventory, /inventory/quota, /inventory/bulk) 는 동적
# (/{type}/{id}) 보다 먼저 선언돼야 라우팅 충돌이 없다.
# ---------------------------------------------------------------------------


class BulkBody(BaseModel):
    action: Literal["archive", "reactivate", "delete", "verify"]
    artifact_ids: list[str] = Field(..., min_length=1)


@router.get("/inventory")
def list_inventory(
    status: str | None = None,
    q: str | None = None,
    doc_type: str | None = None,
    sort: Literal["newest", "oldest", "title"] = "newest",
    limit: int = Query(50, le=200),
    offset: int = 0,
    repository_id: str | None = None,
    tenant_id: str | None = None,
):
    """문서 통합 목록 — 모든 status 포함, 검색·필터·정렬·페이징.

    Phase 11: ``tenant_id`` 직접 필터 추가. ``repository_id`` 와 함께 또는 단독.

    응답:
      items: [{id, title, status, document_type, size_bytes, created_at, trust_score}]
      total: 필터 적용된 총 건수 (페이지 무시)
      by_status: {status: count} 전체 분포
      total_size_bytes: 필터 적용된 size 합
    """
    eng = _engine()
    where: list[str] = []
    params: dict[str, Any] = {"lim": limit, "off": offset}
    if status:
        where.append("status = :s")
        params["s"] = status
    if q:
        where.append("title ILIKE :q")
        params["q"] = f"%{q}%"
    if doc_type:
        where.append(
            "(processing_meta->>'document_type' = :dt "
            "OR processing_meta->'body'->>'document_type' = :dt)"
        )
        params["dt"] = doc_type
    if repository_id:
        where.append("repository_id = CAST(:rid AS uuid)")
        params["rid"] = repository_id
    if tenant_id:
        where.append("tenant_id = CAST(:tid AS uuid)")
        params["tid"] = tenant_id
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order_sql = {
        "newest": "ORDER BY created_at DESC",
        "oldest": "ORDER BY created_at ASC",
        "title": "ORDER BY title ASC",
    }[sort]

    with eng.begin() as conn:
        # 메인 페이지 + size
        rows = conn.execute(
            text(
                f"""
                SELECT id, title, status, processing_meta, created_at,
                       OCTET_LENGTH(processing_meta::text) AS size_bytes
                  FROM documents
                  {where_sql}
                  {order_sql}
                  LIMIT :lim OFFSET :off
                """
            ),
            params,
        ).mappings().all()
        # 필터 적용된 total + total_size
        agg = conn.execute(
            text(
                f"""
                SELECT COUNT(*) AS n,
                       COALESCE(SUM(OCTET_LENGTH(processing_meta::text)), 0) AS total_size
                  FROM documents
                  {where_sql}
                """
            ),
            {k: v for k, v in params.items() if k not in ("lim", "off")},
        ).mappings().first()
        # 전체 status 분포 (q/doc_type/status 필터는 빼고 tenant/repo 만 적용)
        status_clauses: list[str] = []
        status_params: dict[str, Any] = {}
        if repository_id:
            status_clauses.append("repository_id = CAST(:rid AS uuid)")
            status_params["rid"] = repository_id
        if tenant_id:
            status_clauses.append("tenant_id = CAST(:tid AS uuid)")
            status_params["tid"] = tenant_id
        status_where = (" WHERE " + " AND ".join(status_clauses)) if status_clauses else ""
        status_rows = conn.execute(
            text(
                f"""
                SELECT status, COUNT(*) AS n FROM documents{status_where}
                 GROUP BY status
                """
            ),
            status_params,
        ).mappings().all()

    items = []
    for r in rows:
        meta = r["processing_meta"] or {}
        act = meta.get("activation") or {}
        doc_type_val = (
            meta.get("document_type")
            or (meta.get("body") or {}).get("document_type")
            or "document"
        )
        items.append(
            {
                "id": str(r["id"]),
                "title": r["title"],
                "status": r["status"],
                "document_type": doc_type_val,
                "size_bytes": r["size_bytes"] or 0,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "trust_score": act.get("trust_score"),
            }
        )
    return {
        "items": items,
        "total": agg["n"] if agg else 0,
        "by_status": {r["status"]: r["n"] for r in status_rows},
        "total_size_bytes": int(agg["total_size"]) if agg else 0,
    }


@router.get("/inventory/quota")
def inventory_quota(
    repository_id: str | None = None,
    tenant_id: str | None = None,
):
    """용량·분포·최근 7일 변동 요약.

    Phase 11: ``tenant_id`` 직접 필터 추가.
    """
    eng = _engine()
    base_clauses: list[str] = []
    params: dict[str, Any] = {}
    if repository_id:
        base_clauses.append("repository_id = CAST(:rid AS uuid)")
        params["rid"] = repository_id
    if tenant_id:
        base_clauses.append("tenant_id = CAST(:tid AS uuid)")
        params["tid"] = tenant_id
    repo_clause = (" WHERE " + " AND ".join(base_clauses)) if base_clauses else ""
    with eng.begin() as conn:
        # 용량 + by_status
        status_rows = conn.execute(
            text(
                f"""
                SELECT status, COUNT(*) AS n,
                       COALESCE(SUM(OCTET_LENGTH(processing_meta::text)), 0) AS size
                  FROM documents{repo_clause}
                 GROUP BY status
                """
            ),
            params,
        ).mappings().all()
        # by_doc_type
        doc_rows = conn.execute(
            text(
                f"""
                SELECT COALESCE(processing_meta->>'document_type',
                                processing_meta->'body'->>'document_type',
                                'document') AS dt,
                       COUNT(*) AS n
                  FROM documents{repo_clause}
                 GROUP BY dt
                """
            ),
            params,
        ).mappings().all()
        # 최근 7일 (tenant/repo 필터 동일 적용)
        recent_where = " WHERE created_at >= NOW() - interval '7 days'"
        if repository_id:
            recent_where += " AND repository_id = CAST(:rid AS uuid)"
        if tenant_id:
            recent_where += " AND tenant_id = CAST(:tid AS uuid)"
        recent_rows = conn.execute(
            text(
                f"""
                SELECT status, COUNT(*) AS n FROM documents
                 {recent_where}
                 GROUP BY status
                """
            ),
            params,
        ).mappings().all()

    by_status = {r["status"]: r["n"] for r in status_rows}
    total_size = sum(int(r["size"] or 0) for r in status_rows)
    recent_map = {r["status"]: r["n"] for r in recent_rows}
    return {
        "total_size_bytes": total_size,
        "by_status": by_status,
        "by_doc_type": {r["dt"]: r["n"] for r in doc_rows},
        "recent_7d": {
            "added": sum(recent_map.values()),
            "activated": recent_map.get("active", 0),
            "rejected": recent_map.get("rejected", 0),
            "archived": recent_map.get("archived", 0),
        },
    }


@router.post("/inventory/bulk")
async def inventory_bulk(
    body: BulkBody,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    """일괄 액션. v1: archive / reactivate / verify 는 ActivationService 경로,
    delete 는 안전상 status='rejected' (soft) 로 매핑.

    응답: {succeeded: N, failed: [{id, error}]}
    """
    succeeded = 0
    failed: list[dict[str, str]] = []

    def _run_one(artifact_id: str) -> tuple[bool, str | None]:
        try:
            eng = _engine()
            conn = eng.connect()
            try:
                svc = ActivationService(db_session=conn)
                if body.action == "archive":
                    svc.deactivate(
                        "document", artifact_id, user_id=x_user_id, reason="bulk_archive"
                    )
                elif body.action == "reactivate":
                    svc.reactivate("document", artifact_id, user_id=x_user_id)
                elif body.action == "verify":
                    svc.verify("document", artifact_id, user_id=x_user_id, note="bulk_verify")
                elif body.action == "delete":
                    # v1: 진짜 삭제 대신 soft reject
                    svc.reject(
                        "document",
                        artifact_id,
                        user_id=x_user_id,
                        reason="bulk_delete",
                    )
                return True, None
            finally:
                conn.close()
        except (UnknownArtifactType, ArtifactNotFound) as e:
            return False, f"not_found: {e}"
        except InvalidTransition as e:
            return False, f"invalid_transition: {e}"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    for aid in body.artifact_ids:
        ok, err = await asyncio.to_thread(_run_one, aid)
        if ok:
            succeeded += 1
        else:
            failed.append({"id": aid, "error": err or "unknown"})
    return {"succeeded": succeeded, "failed": failed}


@router.get("/{artifact_type}/{artifact_id}")
def get_detail(artifact_type: ArtifactType, artifact_id: str):
    eng = _engine()
    with eng.begin() as conn:
        if artifact_type in _DOC_TYPES:
            row = conn.execute(
                text(
                    "SELECT id, title, status, processing_meta, created_at "
                    "FROM documents WHERE id=CAST(:id AS uuid)"
                ),
                {"id": artifact_id},
            ).mappings().first()
        elif artifact_type == "skill_draft":
            row = conn.execute(
                text(
                    "SELECT id, status_v2 AS status, processing_meta, created_at, "
                    "source_user_message, draft_title "
                    "FROM skill_drafts WHERE id=CAST(:id AS uuid)"
                ),
                {"id": artifact_id},
            ).mappings().first()
        elif artifact_type == "cc_pair":
            row = conn.execute(
                text(
                    "SELECT id, connector_id, credential_id, status, processing_meta, "
                    "created_at FROM connector_credential_pairs WHERE id=:id"
                ),
                {"id": artifact_id},
            ).mappings().first()
        else:
            raise HTTPException(
                status_code=400, detail=f"unsupported artifact_type={artifact_type}"
            )
    if row is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    d = dict(row)
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif hasattr(v, "hex") and not isinstance(v, (bytes, bytearray)):
            d[k] = str(v)
    return d


# ---------------------------------------------------------------------------
# tool_invocation resume — 정적(literal) 경로가 동적 generic 보다 먼저 선언돼야
# FastAPI 라우터 매칭이 정확하다. (델타 #5)
# ---------------------------------------------------------------------------


@router.post("/tool_invocation/{invocation_id}/approve")
async def approve_tool_invocation(
    invocation_id: str,
    body: ToolInvocationApproveBody,
    x_user_id: str = Header(..., alias="X-User-Id"),
    authorization: str | None = Header(None),
):
    """pending_confirm 상태 invocation 을 승인 → 'pending_resume' 로 전환.

    Phase 1.5A Task 8b — secure consume:
    - ``Authorization: Bearer <jwt>`` 가 있으면 JWT payload 의
      ``sub`` (account_id) + ``tenant_id`` 를 신뢰원으로 사용한다.
    - ``body.raw_token`` 이 있으면 ``ToolInvocationStore.consume_token`` 으로
      sha256 hash + TTL + 5축 binding 검증 → 통과 시 status='consumed' 로
      일회용 마킹 후 'pending_resume' 로 전환.
    - JWT 도 raw_token 도 없으면 legacy path (시연 path 호환).

    JWT 가 있으면 tenant_id 가 invocation 의 ``bound_tenant_id`` 와 일치해야
    한다 (cross-tenant 위장 차단). DB tenant_memberships 도 조회해 account가
    실제 멤버인지 확인.
    """

    # JWT 디코드 (있으면).
    jwt_payload = None
    if authorization and authorization.startswith("Bearer "):
        # 지연 import — jose 강제 의존 회피.
        try:
            from src.api.auth.jwt_utils import InvalidToken, decode_token

            try:
                payload = decode_token(authorization[7:].strip())
                if payload.get("type") in (None, "access"):
                    jwt_payload = payload
            except InvalidToken:
                jwt_payload = None
        except Exception:
            jwt_payload = None

    raw_token = body.raw_token

    def _approve():
        eng = _engine()
        with eng.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id, status, resume_token, token_hash, "
                    "       bound_tenant_id, bound_account_id, "
                    "       bound_session_id, bound_tool, bound_input_hash, "
                    "       expires_at, input_args, tool_name "
                    "  FROM tool_invocations WHERE id=:i"
                ),
                {"i": invocation_id},
            ).mappings().first()
            if row is None:
                return None
            if row["status"] != "pending_confirm":
                return {"already": row["status"]}

            # Secure path: raw_token + bound_* 컬럼 존재 시 강제 검증.
            secure_path = bool(raw_token and row.get("token_hash"))
            if secure_path:
                # JWT 가 있으면 binding 검증의 신뢰 원천.
                if jwt_payload is not None:
                    jwt_account = jwt_payload.get("sub")
                    jwt_tenant = jwt_payload.get("tenant_id")
                    if not jwt_account or not jwt_tenant:
                        return {"error": "jwt_incomplete"}
                    if str(jwt_tenant) != str(row["bound_tenant_id"]):
                        return {"error": "tenant_mismatch"}
                    if str(jwt_account) != str(row["bound_account_id"]):
                        return {"error": "account_mismatch"}
                    # tenant_membership 검증 — account 가 실제 tenant 멤버인지.
                    member = conn.execute(
                        text(
                            "SELECT 1 FROM tenant_memberships "
                            " WHERE account_id::text = :a "
                            "   AND tenant_id::text = :t "
                            " LIMIT 1"
                        ),
                        {"a": str(jwt_account), "t": str(jwt_tenant)},
                    ).first()
                    if member is None:
                        return {"error": "not_a_tenant_member"}
                    bind_account = str(jwt_account)
                    bind_tenant = str(jwt_tenant)
                else:
                    # JWT 미제공 — legacy 호환 (X-User-Id 헤더). binding 은 row
                    # 에서 가져와 self-consistency 검증만 수행 (TTL + token).
                    bind_account = row["bound_account_id"]
                    bind_tenant = row["bound_tenant_id"]

                # token_hash 검증 — 직접 SQL (consume_token 헬퍼와 동일 의미).
                import hashlib

                token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
                if token_hash != row["token_hash"]:
                    return {"error": "token_invalid"}

                # TTL 검증.
                from datetime import datetime, timezone

                exp = row["expires_at"]
                if exp is None:
                    return {"error": "token_expired"}
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp <= datetime.now(timezone.utc):
                    conn.execute(
                        text(
                            "UPDATE tool_invocations SET status='expired' "
                            " WHERE id=:i AND status='pending_confirm'"
                        ),
                        {"i": invocation_id},
                    )
                    return {"error": "token_expired"}

                # binding mismatch (5축) — JWT 또는 row 자체의 bound_* 값과 일치.
                if (
                    row["bound_tenant_id"] != bind_tenant
                    or row["bound_account_id"] != bind_account
                ):
                    return {"error": "binding_mismatch"}

                # SELECT FOR UPDATE 후 status 전환 — pending_confirm 만 통과.
                # consumed/pending_resume 동시성 이중 클릭 방지: 업데이트의
                # WHERE status='pending_confirm' 조건이 atomic 하다.
                upd = conn.execute(
                    text(
                        "UPDATE tool_invocations "
                        "   SET status='pending_resume', "
                        "       confirmed_by_user=true, "
                        "       confirmed_by_user_id=:u, "
                        "       consumed_at=NOW() "
                        " WHERE id=:i "
                        "   AND status='pending_confirm'"
                    ),
                    {"u": x_user_id, "i": invocation_id},
                )
                if upd.rowcount == 0:
                    return {"error": "race_already_handled"}
                # legacy resume_token 반환 (engine resume SSE 가 이걸로 식별).
                # token_hash 자체는 노출 X.
                return {
                    "status": "pending_resume",
                    "resume_token": row["resume_token"],
                    "secure": True,
                }

            # Legacy path — 시연 path 호환 (deprecated).
            conn.execute(
                text(
                    "UPDATE tool_invocations "
                    "SET status='pending_resume', "
                    "    confirmed_by_user=true, "
                    "    confirmed_by_user_id=:u "
                    "WHERE id=:i"
                ),
                {"u": x_user_id, "i": invocation_id},
            )
            return {"status": "pending_resume", "resume_token": row["resume_token"]}

    res = await asyncio.to_thread(_approve)
    if res is None:
        raise HTTPException(status_code=404, detail="invocation not found")
    if isinstance(res, dict) and "error" in res:
        # 일관된 4xx 매핑.
        err = res["error"]
        if err in ("token_invalid", "token_expired"):
            raise HTTPException(status_code=403, detail=err)
        if err in ("tenant_mismatch", "account_mismatch", "binding_mismatch", "not_a_tenant_member"):
            raise HTTPException(status_code=403, detail=err)
        if err == "jwt_incomplete":
            raise HTTPException(status_code=401, detail=err)
        if err == "race_already_handled":
            raise HTTPException(status_code=409, detail=err)
        raise HTTPException(status_code=400, detail=err)
    return res


@router.post("/tool_invocation/{invocation_id}/reject")
async def reject_tool_invocation(
    invocation_id: str,
    body: RejectBody,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    """pending_confirm/pending_resume 상태 invocation 을 사용자가 거부 → canceled."""

    def _reject():
        eng = _engine()
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE tool_invocations "
                    "SET status='canceled', "
                    "    error=:r, "
                    "    confirmed_by_user=true, "
                    "    confirmed_by_user_id=:u, "
                    "    executed_at=NOW() "
                    "WHERE id=:i "
                    "  AND status IN ('pending_confirm','pending_resume')"
                ),
                {"r": body.reason, "u": x_user_id, "i": invocation_id},
            )
        return {"status": "canceled"}

    return await asyncio.to_thread(_reject)


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------


@router.post("/{artifact_type}/{artifact_id}/approve")
async def approve(
    artifact_type: ArtifactType,
    artifact_id: str,
    body: ApproveBody,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    try:
        return await asyncio.to_thread(
            _service_call(
                "approve",
                artifact_type,
                artifact_id,
                user_id=x_user_id,
                action=body.action,
                target_doc_ids=body.target_doc_ids,
                execution_policy=body.execution_policy,
                note=body.note,
            )
        )
    except (UnknownArtifactType, ArtifactNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{artifact_type}/{artifact_id}/reject")
async def reject(
    artifact_type: ArtifactType,
    artifact_id: str,
    body: RejectBody,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    try:
        return await asyncio.to_thread(
            _service_call(
                "reject",
                artifact_type,
                artifact_id,
                user_id=x_user_id,
                reason=body.reason,
            )
        )
    except (UnknownArtifactType, ArtifactNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{artifact_type}/{artifact_id}/defer")
async def defer(
    artifact_type: ArtifactType,
    artifact_id: str,
    body: DeferBody,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    try:
        return await asyncio.to_thread(
            _service_call(
                "defer",
                artifact_type,
                artifact_id,
                user_id=x_user_id,
                note=body.note,
            )
        )
    except (UnknownArtifactType, ArtifactNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{artifact_type}/{artifact_id}/deactivate")
async def deactivate(
    artifact_type: ArtifactType,
    artifact_id: str,
    body: DeactivateBody,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    try:
        return await asyncio.to_thread(
            _service_call(
                "deactivate",
                artifact_type,
                artifact_id,
                user_id=x_user_id,
                reason=body.reason,
            )
        )
    except (UnknownArtifactType, ArtifactNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{artifact_type}/{artifact_id}/reactivate")
async def reactivate(
    artifact_type: ArtifactType,
    artifact_id: str,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    try:
        return await asyncio.to_thread(
            _service_call(
                "reactivate",
                artifact_type,
                artifact_id,
                user_id=x_user_id,
            )
        )
    except (UnknownArtifactType, ArtifactNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{artifact_type}/{artifact_id}/verify")
async def verify(
    artifact_type: ArtifactType,
    artifact_id: str,
    body: VerifyBody,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    try:
        return await asyncio.to_thread(
            _service_call(
                "verify",
                artifact_type,
                artifact_id,
                user_id=x_user_id,
                note=body.note,
            )
        )
    except (UnknownArtifactType, ArtifactNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e))
