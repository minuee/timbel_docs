"""AgentDocumentService — agent x document 매핑 관리 (옵션 Y v2).

Phase 3 (2026-05-07). agent 별 SOP/지식자료 분류를 *문서 단위* 로 관리한다.

설계 원칙:
- agent.tenant_id 와 document.tenant_id 가 일치해야 link 허용 (DB 트리거가 강제).
- 모든 method 가 tenant 격리 검증 (호출 측 tenant_id == row.tenant_id).
- ensure_default_folder() 는 멱등 — UNIQUE(owner_agent_id) 위에서 ON CONFLICT
  로 race 차단 (GPT-5 P1).
- 빈 매핑 → retrieval 은 옛 repo_ids fallback 자동 (회귀 0).
"""

from __future__ import annotations

import re
from typing import Iterable
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.core.models.agent_document import AgentDocument
from src.core.models.document import Document
from src.core.models.library_folder import LibraryFolder

log = get_logger(__name__)


_SLUG_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _slugify(name: str) -> str:
    s = _SLUG_RE.sub("_", (name or "").strip().lower())
    return s.strip("_") or "agent"


class AgentDocumentService:
    """agent x document 매핑 + default folder 관리."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # tenant 검증
    # ------------------------------------------------------------------

    async def _resolve_agent_tenant(self, agent_id: UUID) -> UUID:
        row = (
            await self.db.execute(
                text("SELECT tenant_id FROM agents WHERE id = :aid"),
                {"aid": agent_id},
            )
        ).first()
        if not row:
            raise ValueError(f"agent {agent_id} not found")
        return row[0]

    async def _verify_tenant_match(
        self, *, agent_id: UUID, tenant_id: UUID
    ) -> None:
        agent_tenant = await self._resolve_agent_tenant(agent_id)
        if agent_tenant != tenant_id:
            raise PermissionError(
                f"agent {agent_id} does not belong to tenant {tenant_id}"
            )

    async def _verify_documents_in_tenant(
        self, *, document_ids: list[UUID], tenant_id: UUID
    ) -> list[UUID]:
        """tenant 안 존재 여부 검증. cross-tenant 차단 → 누락된 doc id list 반환.

        GPT-5 P1 fix: ARRAY[uuid] cast 명시 — 드라이버별 ANY 바인딩 unknown
        type 회피.
        """
        if not document_ids:
            return []
        rows = (
            await self.db.execute(
                text(
                    "SELECT id FROM documents "
                    "WHERE id = ANY(CAST(:ids AS uuid[])) AND tenant_id = :tid"
                ),
                {"ids": [str(d) for d in document_ids], "tid": tenant_id},
            )
        ).fetchall()
        found = {r[0] for r in rows}
        return [d for d in document_ids if d not in found]

    # ------------------------------------------------------------------
    # list / link / unlink / set_mode
    # ------------------------------------------------------------------

    async def list_for_agent(
        self,
        *,
        agent_id: UUID,
        tenant_id: UUID,
        mode: str | None = None,
    ) -> list[dict]:
        """agent 의 매핑 + 결합된 document 메타 반환."""
        await self._verify_tenant_match(agent_id=agent_id, tenant_id=tenant_id)
        # GPT-5 P0/P1: tenant 이중 필터 (방어적) — 트리거 비활성/우회 시에도 누수 0.
        # 가시성 (status='active' / 미삭제) 필터.
        params: dict = {"aid": agent_id, "tid": tenant_id}
        mode_clause = ""
        if mode is not None:
            if mode not in ("sop", "kms"):
                raise ValueError("mode must be 'sop' or 'kms'")
            mode_clause = " AND ad.mode = :mode"
            params["mode"] = mode

        rows = (
            await self.db.execute(
                text(
                    f"""
                    SELECT ad.id, ad.document_id, ad.mode, ad.source,
                           ad.created_at, d.title, d.status, d.source_format,
                           d.repository_id, d.folder_id, d.is_sop,
                           d.processing_meta, d.created_by, d.created_at AS doc_created_at
                      FROM agent_documents ad
                      JOIN documents d ON d.id = ad.document_id
                     WHERE ad.agent_id = :aid
                       AND ad.tenant_id = :tid
                       AND d.tenant_id = :tid
                       AND d.status NOT IN ('archived','deleted'){mode_clause}
                     ORDER BY ad.created_at DESC
                    """
                ),
                params,
            )
        ).fetchall()
        return [
            {
                "id": str(r[0]),
                "document_id": str(r[1]),
                "mode": r[2],
                "source": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
                "title": r[5],
                "status": r[6],
                "source_format": r[7],
                "repository_id": str(r[8]) if r[8] else None,
                "folder_id": str(r[9]) if r[9] else None,
                "is_sop": r[10],
                "size_bytes": (
                    (r[11] or {}).get("size_bytes")
                    or (r[11] or {}).get("file_size")
                ),
                "created_by": str(r[12]) if r[12] else None,
                "doc_created_at": r[13].isoformat() if r[13] else None,
            }
            for r in rows
        ]

    async def link_bulk(
        self,
        *,
        agent_id: UUID,
        tenant_id: UUID,
        document_ids: list[UUID],
        mode: str,
        source: str = "shared",
    ) -> dict:
        """다중 link — UPSERT (mode 변경은 명시적 set_mode 사용).

        ON CONFLICT (agent_id, document_id) DO NOTHING 으로 race 멱등.
        cross-tenant doc 은 "missing" 으로 보고 (404 동등 — 정보 누출 차단).
        """
        if mode not in ("sop", "kms"):
            raise ValueError("mode must be 'sop' or 'kms'")
        if source not in ("shared", "uploaded"):
            raise ValueError("source must be 'shared' or 'uploaded'")
        await self._verify_tenant_match(agent_id=agent_id, tenant_id=tenant_id)

        # cross-tenant 차단 — 같은 tenant 안 doc 만 link.
        missing = await self._verify_documents_in_tenant(
            document_ids=document_ids, tenant_id=tenant_id
        )
        ok_ids = [d for d in document_ids if d not in missing]
        if not ok_ids:
            return {"linked": 0, "missing": len(missing)}

        values = [
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "document_id": did,
                "mode": mode,
                "source": source,
            }
            for did in ok_ids
        ]
        stmt = (
            pg_insert(AgentDocument)
            .values(values)
            .on_conflict_do_nothing(index_elements=["agent_id", "document_id"])
        )
        result = await self.db.execute(stmt)
        await self.db.flush()

        log.info(
            "agent_documents_link_bulk",
            agent_id=str(agent_id),
            tenant_id=str(tenant_id),
            attempted=len(ok_ids),
            inserted=result.rowcount or 0,
            missing=len(missing),
            mode=mode,
            source=source,
        )
        return {
            "linked": result.rowcount or 0,
            "missing": len(missing),
            "attempted": len(ok_ids),
        }

    async def unlink(
        self,
        *,
        agent_id: UUID,
        tenant_id: UUID,
        document_id: UUID,
    ) -> bool:
        await self._verify_tenant_match(agent_id=agent_id, tenant_id=tenant_id)
        # GPT-5 P0: ad.tenant_id=:tid 이중 필터 (방어적).
        result = await self.db.execute(
            text(
                "DELETE FROM agent_documents "
                "WHERE agent_id = :aid AND document_id = :did "
                "  AND tenant_id = :tid"
            ),
            {"aid": agent_id, "did": document_id, "tid": tenant_id},
        )
        await self.db.flush()
        deleted = (result.rowcount or 0) > 0
        log.info(
            "agent_documents_unlink",
            agent_id=str(agent_id),
            document_id=str(document_id),
            deleted=deleted,
        )
        return deleted

    async def set_mode(
        self,
        *,
        agent_id: UUID,
        tenant_id: UUID,
        document_id: UUID,
        mode: str,
    ) -> bool:
        if mode not in ("sop", "kms"):
            raise ValueError("mode must be 'sop' or 'kms'")
        await self._verify_tenant_match(agent_id=agent_id, tenant_id=tenant_id)
        # GPT-5 P0: ad.tenant_id=:tid 이중 필터.
        result = await self.db.execute(
            text(
                "UPDATE agent_documents SET mode = :mode, updated_at = now() "
                "WHERE agent_id = :aid AND document_id = :did "
                "  AND tenant_id = :tid"
            ),
            {"aid": agent_id, "did": document_id, "mode": mode, "tid": tenant_id},
        )
        await self.db.flush()
        updated = (result.rowcount or 0) > 0
        log.info(
            "agent_documents_set_mode",
            agent_id=str(agent_id),
            document_id=str(document_id),
            mode=mode,
            updated=updated,
        )
        return updated

    # ------------------------------------------------------------------
    # default folder 자동 보장
    # ------------------------------------------------------------------

    async def ensure_default_folder(
        self,
        *,
        agent_id: UUID,
        tenant_id: UUID,
        repository_id: UUID,
        agent_name: str | None = None,
    ) -> UUID:
        """agent 의 default folder 를 멱등하게 보장한다.

        race 시: UNIQUE(owner_agent_id) WHERE NOT NULL 위반 → ON CONFLICT 로
        기존 row 의 id 반환 (GPT-5 P1).
        """
        await self._verify_tenant_match(agent_id=agent_id, tenant_id=tenant_id)

        # 1. agents.default_folder_id 가 이미 있고 살아있으면 그대로.
        row = (
            await self.db.execute(
                text(
                    """
                    SELECT a.default_folder_id, lf.id
                      FROM agents a
                      LEFT JOIN library_folders lf
                             ON lf.id = a.default_folder_id
                     WHERE a.id = :aid
                    """
                ),
                {"aid": agent_id},
            )
        ).first()
        if row and row[0] and row[1]:
            return row[0]

        # 2. owner_agent_id 로 이미 만들어진 folder 가 있는지 확인.
        existing = (
            await self.db.execute(
                text(
                    "SELECT id FROM library_folders "
                    "WHERE owner_agent_id = :aid LIMIT 1"
                ),
                {"aid": agent_id},
            )
        ).first()
        if existing:
            folder_id = existing[0]
            # agents.default_folder_id 채우기.
            await self.db.execute(
                text(
                    "UPDATE agents SET default_folder_id = :fid, updated_at = now() "
                    "WHERE id = :aid"
                ),
                {"fid": folder_id, "aid": agent_id},
            )
            await self.db.flush()
            return folder_id

        # 3. 신규 생성 — INSERT ... ON CONFLICT (UNIQUE(owner_agent_id)) DO NOTHING.
        folder_name = f"{agent_name or 'agent'} 자료"
        # 같은 부모 안 같은 이름 unique constraint 회피 — agent 자동 폴더는 root 직속.
        # 우연한 동명 폴더 충돌 시 suffix.
        base_name = folder_name
        suffix = 2
        new_folder_id: UUID | None = None
        while True:
            try:
                ins = (
                    await self.db.execute(
                        text(
                            """
                            INSERT INTO library_folders
                                (id, tenant_id, repository_id, parent_folder_id,
                                 name, kind, owner_agent_id, created_by,
                                 created_at, updated_at)
                            VALUES
                                (gen_random_uuid(), :tid, :rid, NULL,
                                 :name, 'manual', :aid, NULL, now(), now())
                            ON CONFLICT (owner_agent_id) WHERE owner_agent_id IS NOT NULL
                              DO NOTHING
                            RETURNING id
                            """
                        ),
                        {
                            "tid": tenant_id,
                            "rid": repository_id,
                            "name": folder_name,
                            "aid": agent_id,
                        },
                    )
                ).first()
                if ins:
                    new_folder_id = ins[0]
                    break
                # ON CONFLICT 발생 — 다른 트랜잭션이 이미 생성. lookup.
                ex = (
                    await self.db.execute(
                        text(
                            "SELECT id FROM library_folders "
                            "WHERE owner_agent_id = :aid LIMIT 1"
                        ),
                        {"aid": agent_id},
                    )
                ).first()
                if ex:
                    new_folder_id = ex[0]
                    break
                # 정말 드문 케이스 — 동일 이름 충돌. suffix 증가 후 재시도.
                folder_name = f"{base_name}_{suffix}"
                suffix += 1
                if suffix > 50:
                    raise RuntimeError(
                        "ensure_default_folder: failed to allocate unique name"
                    )
            except Exception as exc:
                # name 충돌 시 unique violation 가능 — suffix 올려서 재시도.
                msg = str(exc).lower()
                if "uq_library_folders_parent_name" in msg or "duplicate" in msg:
                    folder_name = f"{base_name}_{suffix}"
                    suffix += 1
                    if suffix > 50:
                        raise
                    continue
                raise

        if not new_folder_id:
            raise RuntimeError("ensure_default_folder: no folder id resolved")

        # agents.default_folder_id 채우기.
        await self.db.execute(
            text(
                "UPDATE agents SET default_folder_id = :fid, updated_at = now() "
                "WHERE id = :aid"
            ),
            {"fid": new_folder_id, "aid": agent_id},
        )
        await self.db.flush()

        log.info(
            "agent_default_folder_created",
            agent_id=str(agent_id),
            folder_id=str(new_folder_id),
            folder_name=folder_name,
            repository_id=str(repository_id),
        )
        return new_folder_id

    # ------------------------------------------------------------------
    # retrieval helper — Phase 4 RAG 분기에서 사용
    # ------------------------------------------------------------------

    async def count_summary(
        self,
        *,
        agent_id: UUID,
        tenant_id: UUID,
    ) -> dict:
        """OverviewTab chip 의 진실 source — agent 단위 sop/kms doc count.

        UNION semantics:
        - sop = agent_documents.mode='sop' (mapping)
              ∪ documents IN sop_repo_ids WHERE (is_sop=true OR folder.kind='sop')
        - kms = agent_documents.mode='kms' (mapping)
              ∪ documents IN (primary∪fallback) WHERE NOT (is_sop OR folder.kind='sop')

        ROW_NUMBER mapping 우선 dedupe — 같은 doc 이 mapping 과 repo_inferred 양쪽
        에 잡히면 mapping 권위. mapping 이 다른 mode 로 잡힌 doc 은 repo_inferred
        에서 제외해 sop+kms = total disjoint 보장 (GPT-5 P0).

        cross-tenant 격리 — 호출자 tenant_id 와 agent.tenant_id 일치 검증 +
        모든 join 에 d.tenant_id=:tid / f.tenant_id=:tid (GPT-5 P0).

        repo_ids 는 *서버* 가 agent_id+tenant_id 로 직접 조회 — payload 신뢰 X
        (cross-tenant 누수 방지).

        Returns:
            ``{
              "sop": int, "kms": int, "total": int,
              "by_source": {
                "sop_mapping": int, "sop_repo_inferred": int,
                "kms_mapping": int, "kms_repo_inferred": int,
              },
            }``
        """
        await self._verify_tenant_match(agent_id=agent_id, tenant_id=tenant_id)

        # 1. agent 의 repo_ids 를 *server* 에서 직접 조회 (GPT-5 P0).
        agent_row = (
            await self.db.execute(
                text(
                    """
                    SELECT a.sop_repo_ids, a.primary_repo_ids, a.fallback_repo_ids
                      FROM agents a
                     WHERE a.id = :aid AND a.tenant_id = :tid
                    """
                ),
                {"aid": agent_id, "tid": tenant_id},
            )
        ).first()
        if not agent_row:
            raise ValueError(f"agent {agent_id} not found in tenant {tenant_id}")

        sop_repos_raw = list(agent_row[0] or [])
        primary_repos_raw = list(agent_row[1] or [])
        fallback_repos_raw = list(agent_row[2] or [])

        # 2. repo_ids 도 tenant 검증 — repositories.tenant_id=:tid 만 살림 (방어).
        all_repo_ids = list(
            {*sop_repos_raw, *primary_repos_raw, *fallback_repos_raw}
        )
        valid_repo_ids: set = set()
        if all_repo_ids:
            valid_rows = (
                await self.db.execute(
                    text(
                        """
                        SELECT id FROM repositories
                         WHERE id = ANY(CAST(:ids AS uuid[]))
                           AND tenant_id = :tid
                           AND is_active = true
                        """
                    ),
                    {
                        "ids": [str(r) for r in all_repo_ids],
                        "tid": tenant_id,
                    },
                )
            ).fetchall()
            valid_repo_ids = {r[0] for r in valid_rows}

        sop_repos = [r for r in sop_repos_raw if r in valid_repo_ids]
        kms_repos_set = {*primary_repos_raw, *fallback_repos_raw}
        kms_repos = [r for r in kms_repos_set if r in valid_repo_ids]

        # 3. UNION + ROW_NUMBER dedupe (mapping 권위) + disjoint 보장.
        # repo_inferred 에서 다른 mode 로 mapping 된 doc 은 제외해 sop+kms=total.
        sql = text(
            """
            WITH sop_raw AS (
              -- mapping 권위
              SELECT d.id AS doc_id, 'mapping' AS src
                FROM agent_documents ad
                JOIN documents d ON d.id = ad.document_id
               WHERE ad.agent_id = :aid AND ad.tenant_id = :tid
                 AND ad.mode = 'sop'
                 AND d.tenant_id = :tid
                 AND d.status = 'active'
              UNION ALL
              -- repo_inferred (sop_repo_ids 의 is_sop OR folder.kind='sop')
              -- 단, 다른 mode(kms) 로 mapping 된 doc 은 제외 (disjoint 보장).
              SELECT d.id AS doc_id, 'repo_inferred' AS src
                FROM documents d
                LEFT JOIN library_folders f
                  ON f.id = d.folder_id AND f.tenant_id = :tid
               WHERE d.tenant_id = :tid
                 AND d.repository_id = ANY(CAST(:sop_repos AS uuid[]))
                 AND d.status = 'active'
                 AND (d.is_sop = true OR f.kind = 'sop')
                 AND NOT EXISTS (
                   SELECT 1 FROM agent_documents ad2
                    WHERE ad2.agent_id = :aid
                      AND ad2.tenant_id = :tid
                      AND ad2.document_id = d.id
                      AND ad2.mode = 'kms'
                 )
            ), sop_ranked AS (
              SELECT doc_id, src,
                     ROW_NUMBER() OVER (
                       PARTITION BY doc_id
                       ORDER BY CASE src WHEN 'mapping' THEN 0 ELSE 1 END
                     ) AS rnk
                FROM sop_raw
            ), kms_raw AS (
              SELECT d.id AS doc_id, 'mapping' AS src
                FROM agent_documents ad
                JOIN documents d ON d.id = ad.document_id
               WHERE ad.agent_id = :aid AND ad.tenant_id = :tid
                 AND ad.mode = 'kms'
                 AND d.tenant_id = :tid
                 AND d.status = 'active'
              UNION ALL
              SELECT d.id AS doc_id, 'repo_inferred' AS src
                FROM documents d
                LEFT JOIN library_folders f
                  ON f.id = d.folder_id AND f.tenant_id = :tid
               WHERE d.tenant_id = :tid
                 AND d.repository_id = ANY(CAST(:kms_repos AS uuid[]))
                 AND d.status = 'active'
                 -- GPT-5 P0 (3-value logic): NOT(true OR NULL)=NULL → exclude.
                 -- d.is_sop=false AND f.kind IS DISTINCT FROM 'sop' 로 NULL 안전.
                 AND COALESCE(d.is_sop, false) = false
                 AND (f.kind IS DISTINCT FROM 'sop')
                 AND NOT EXISTS (
                   SELECT 1 FROM agent_documents ad2
                    WHERE ad2.agent_id = :aid
                      AND ad2.tenant_id = :tid
                      AND ad2.document_id = d.id
                      AND ad2.mode = 'sop'
                 )
            ), kms_ranked AS (
              SELECT doc_id, src,
                     ROW_NUMBER() OVER (
                       PARTITION BY doc_id
                       ORDER BY CASE src WHEN 'mapping' THEN 0 ELSE 1 END
                     ) AS rnk
                FROM kms_raw
            )
            SELECT
              (SELECT COUNT(*) FROM sop_ranked WHERE rnk = 1) AS sop_total,
              (SELECT COUNT(*) FROM kms_ranked WHERE rnk = 1) AS kms_total,
              (SELECT COUNT(*) FROM sop_ranked WHERE rnk = 1 AND src='mapping') AS sop_mapping,
              (SELECT COUNT(*) FROM sop_ranked WHERE rnk = 1 AND src='repo_inferred') AS sop_repo_inferred,
              (SELECT COUNT(*) FROM kms_ranked WHERE rnk = 1 AND src='mapping') AS kms_mapping,
              (SELECT COUNT(*) FROM kms_ranked WHERE rnk = 1 AND src='repo_inferred') AS kms_repo_inferred
            """
        )
        row = (
            await self.db.execute(
                sql,
                {
                    "aid": agent_id,
                    "tid": tenant_id,
                    "sop_repos": [str(r) for r in sop_repos],
                    "kms_repos": [str(r) for r in kms_repos],
                },
            )
        ).first()
        if not row:
            return {
                "sop": 0,
                "kms": 0,
                "total": 0,
                "by_source": {
                    "sop_mapping": 0,
                    "sop_repo_inferred": 0,
                    "kms_mapping": 0,
                    "kms_repo_inferred": 0,
                },
            }
        sop_total = int(row[0] or 0)
        kms_total = int(row[1] or 0)
        return {
            "sop": sop_total,
            "kms": kms_total,
            "total": sop_total + kms_total,
            "by_source": {
                "sop_mapping": int(row[2] or 0),
                "sop_repo_inferred": int(row[3] or 0),
                "kms_mapping": int(row[4] or 0),
                "kms_repo_inferred": int(row[5] or 0),
            },
        }

    async def get_document_ids_by_mode(
        self,
        *,
        agent_id: UUID,
        mode: str,
        tenant_id: UUID | None = None,
    ) -> list[UUID]:
        """Phase 4 RAG retrieval 분기 helper.

        agent_documents 가 비면 빈 list 반환 → 호출 측 repo_ids fallback (회귀 0).
        tenant_id 주어지면 이중 필터 (GPT-5 P0).
        """
        if mode not in ("sop", "kms"):
            raise ValueError("mode must be 'sop' or 'kms'")
        if tenant_id is not None:
            rows = (
                await self.db.execute(
                    text(
                        "SELECT document_id FROM agent_documents "
                        "WHERE agent_id = :aid AND mode = :mode AND tenant_id = :tid"
                    ),
                    {"aid": agent_id, "mode": mode, "tid": tenant_id},
                )
            ).fetchall()
        else:
            rows = (
                await self.db.execute(
                    text(
                        "SELECT document_id FROM agent_documents "
                        "WHERE agent_id = :aid AND mode = :mode"
                    ),
                    {"aid": agent_id, "mode": mode},
                )
            ).fetchall()
        return [r[0] for r in rows]
