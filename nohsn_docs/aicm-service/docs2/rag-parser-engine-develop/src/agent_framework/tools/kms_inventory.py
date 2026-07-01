"""KMS Inventory Summary tool — internal, no external connector.

직접 DB 쿼리 후 한국어 자연어 응답 templating. side_effect_level=read_only
이므로 Phase 3 의 kms_inventory_summary skill 에서 ExecutionPolicy 가드 없이 호출.

사용처:
- kms_inventory_summary skill 의 ``tool: kms_inventory.get_summary``
- login_brief 의 inventory 첨부 (선택적)
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text


def get_summary(
    *,
    db_conn: Any,
    tenant_id: str | None = None,
    repository_id: str | None = None,
    personal_tenant_id: str | None = None,
) -> dict[str, Any]:
    """문서 by_status·총 용량·최근 7일 변동 + 한국어 요약 문자열.

    Args:
      db_conn: SQLAlchemy sync Connection.
      tenant_id: tool_args 에서 들어오나 v1 에선 documents 테이블에 직접 컬럼이
        없어 무시 (repository_id 가 실질 필터).
      repository_id: 특정 repository 로 필터 시.
      personal_tenant_id: 동일 — 향후 tenant 별 분리 시 사용.

    Returns:
      {
        "summary_ko": "활성 문서 4,234건 (총 142 MB), 승인 대기 432건. ...",
        "raw": {by_status, total_size_bytes, recent_7d}
      }
    """
    where_clause = ""
    params: dict[str, Any] = {}
    tid = tenant_id or personal_tenant_id
    where_parts: list[str] = []
    if repository_id:
        where_parts.append("repository_id = CAST(:rid AS uuid)")
        params["rid"] = repository_id
    if tid:
        where_parts.append("tenant_id = CAST(:tid AS uuid)")
        params["tid"] = tid
    if where_parts:
        where_clause = "WHERE " + " AND ".join(where_parts)

    # 1) by_status count + total size
    rows = (
        db_conn.execute(
            text(
                f"""
                SELECT status, COUNT(*) AS n,
                       COALESCE(SUM(OCTET_LENGTH(processing_meta::text)), 0) AS size
                  FROM documents
                  {where_clause}
                 GROUP BY status
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    by_status = {r["status"]: int(r["n"]) for r in rows}
    total_size = sum(int(r["size"] or 0) for r in rows)

    # P11-17 — block count (검색 인덱스 단위). active document 의 active block.
    block_total = 0
    block_indexed = 0
    if tid:
        row = db_conn.execute(
            text(
                """
                SELECT
                  COUNT(*) FILTER (WHERE b.validity_status = 'active') AS total,
                  COUNT(*) FILTER (WHERE b.validity_status = 'active'
                                     AND b.is_indexed = true) AS indexed
                  FROM blocks b
                  JOIN documents d ON d.id = b.document_id
                 WHERE d.tenant_id = CAST(:tid AS uuid)
                   AND d.status = 'active'
                """
                + (" AND d.repository_id = CAST(:rid AS uuid)" if repository_id else "")
            ),
            params,
        ).first()
        if row:
            block_total = int(row[0] or 0)
            block_indexed = int(row[1] or 0)

    # 2) 최근 7일 추가
    recent_where = "WHERE created_at >= NOW() - interval '7 days'"
    if repository_id:
        recent_where += " AND repository_id = CAST(:rid AS uuid)"
    recent_rows = (
        db_conn.execute(
            text(
                f"""
                SELECT status, COUNT(*) AS n FROM documents
                 {recent_where}
                 GROUP BY status
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    recent_7d = {r["status"]: int(r["n"]) for r in recent_rows}

    # 3) 한국어 요약
    active = by_status.get("active", 0)
    pending = by_status.get("pending_review", 0)
    archived = by_status.get("archived", 0)
    mb = total_size / (1024 * 1024) if total_size else 0
    added_recent = sum(recent_7d.values())
    summary = (
        f"현재 활성 문서 {active:,}건 (총 {mb:.0f} MB), "
        f"승인 대기 {pending:,}건, 아카이브 {archived:,}건입니다. "
        f"지난 7일간 {added_recent:,}건이 새로 추가되었습니다."
    )
    if block_total:
        summary += (
            f" 활성 블록은 {block_total:,}개"
            + (
                f" (검색 색인 {block_indexed:,}개)"
                if block_indexed and block_indexed != block_total
                else ""
            )
            + "입니다."
        )
    return {
        "summary_ko": summary,
        "raw": {
            "by_status": by_status,
            "total_size_bytes": total_size,
            "recent_7d": recent_7d,
            "blocks": block_total,
            "indexed_blocks": block_indexed,
        },
    }


def list_documents(
    *,
    db_conn: Any,
    tenant_id: str | None = None,
    personal_tenant_id: str | None = None,
    repository_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """문서 실제 row 목록 — title / status / size / updated_at / repository.

    "리스트 보여줘", "상세 정보", "어떤 문서들 있어?" 류 질의용.
    summary 와 다른 점: aggregate counts 가 아니라 *각 문서 한 줄씩*.

    Args:
      tenant_id 또는 personal_tenant_id: 둘 중 하나 필수.
      repository_id: 특정 repo 로 필터.
      status: 'active' / 'pending_review' / 'archived' / None (전체).
              None 이면 active + pending_review 우선 (사용자 관심 큰 status).
      limit: 최대 row 수 (default 20).
    """
    tid = tenant_id or personal_tenant_id
    if tid is None:
        return {
            "summary_ko": "tenant 가 지정되지 않아 문서 목록을 조회하지 못했습니다.",
            "items": [],
        }

    where_parts = ["d.tenant_id = CAST(:tid AS uuid)"]
    params: dict[str, Any] = {"tid": tid, "lim": int(limit)}
    if repository_id:
        where_parts.append("d.repository_id = CAST(:rid AS uuid)")
        params["rid"] = repository_id
    if status:
        where_parts.append("d.status = :status")
        params["status"] = status
    else:
        where_parts.append("d.status IN ('active', 'pending_review')")
    where_clause = "WHERE " + " AND ".join(where_parts)

    rows = (
        db_conn.execute(
            text(
                f"""
                SELECT d.id, d.title, d.status,
                       OCTET_LENGTH(d.processing_meta::text) AS size_bytes,
                       d.updated_at, d.created_at,
                       r.name AS repository_name,
                       dt.name AS doc_type
                  FROM documents d
                  LEFT JOIN repositories r ON r.id = d.repository_id
                  LEFT JOIN document_types dt ON dt.id = d.document_type_id
                  {where_clause}
                  ORDER BY d.updated_at DESC NULLS LAST
                  LIMIT :lim
                """
            ),
            params,
        )
        .mappings()
        .all()
    )

    # 전체 카운트 (limit 초과 여부 안내용)
    total_row = db_conn.execute(
        text(
            f"""
            SELECT COUNT(*) FROM documents d
            {where_clause}
            """
        ),
        {k: v for k, v in params.items() if k != "lim"},
    ).first()
    total = int(total_row[0]) if total_row and total_row[0] is not None else 0

    items: list[dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "id": str(r["id"]),
                "title": r["title"] or "(제목 없음)",
                "status": r["status"],
                "size_bytes": int(r["size_bytes"] or 0),
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "repository_name": r["repository_name"],
                "doc_type": r["doc_type"],
            }
        )

    if not items:
        summary = "조건에 맞는 문서가 없습니다."
    else:
        shown = len(items)
        more = total - shown
        head = f"문서 {total:,}건 중 {shown:,}건 표시"
        if more > 0:
            head += f" (+{more:,}건 더 있음)"
        summary = head + "."

    return {
        "summary_ko": summary,
        "items": items,
        "total": total,
        "shown": len(items),
    }
