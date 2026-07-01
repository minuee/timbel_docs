"""KMS SOP search tool — Phase 1.5B-β SOP RAG core.

agent.sop_repo_ids 에 매칭되는 SOP markdown chunks 를 Qdrant collection
``sop_v1_{tenant_id}`` 에서 검색해 반환한다.

Spec 참조:
- ``docs/superpowers/specs/2026-05-06-agent-guardrails-and-dynamic-sop-design.md``
  Task 11 (kms_sop.search)
- ``docs/superpowers/plans/2026-05-07-master-plan-phase-1.5.md`` §B-2 β

설계 원칙:
- evidence (kms_rag) 와 분리: SOP 는 *교육용 instruction*. SOP 가 권한 부여 X.
- per-tenant Qdrant collection 으로 격리 — alembic 변경 없이 동적 생성.
- SearchService 의 일반 collection 과 분리 — sop 전용 chunk schema 사용.

Round 2 (plan_orchestrator 통합) 시 ``FEATURE_SOP_RAG`` flag 로 활성화.
이번 PR (Round 1) 은 *코드만 존재*, 실 호출 경로 변경 X.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.common.logging import get_logger

log = get_logger(__name__)


# Qdrant collection naming — per-tenant SOP RAG.
# 형식: sop_v1_{tenant_id}. tenant_slug 가 아닌 *uuid 직격* 로 충돌 회피.
SOP_COLLECTION_PREFIX = "sop_v1_"


def build_sop_collection_name(tenant_id: UUID | str) -> str:
    """SOP 전용 Qdrant collection 이름. tenant 별 격리.

    UUID hyphen 은 Qdrant collection 이름 규칙 (영숫자/언더스코어/하이픈) 에서
    허용되지만 일관성을 위해 underscore 로 정규화한다.
    """
    raw = str(tenant_id).replace("-", "_")
    return f"{SOP_COLLECTION_PREFIX}{raw}"


class KMSSopTool:
    """``kms_sop.search`` tool — agent 의 SOP repo chunks 검색.

    Tool registry 호출 규약: ``async (args: dict) -> dict``.

    Args:
        query (str): 검색 쿼리 (필수)
        agent_id (str|UUID): SOP repo lookup 대상 agent (필수)
        top_k (int): 반환 chunk 수 (기본 5, 최대 20)
        tenant_id (str|UUID): collection 결정용 (선택 — agent.tenant_id 로 fallback)

    Returns:
        ``{success: bool, chunks: [{text, score, repo_id, document_id, chunk_index, heading?}], total: int}``

        실패 시 ``{success: false, chunks: [], error: str}``.

    Notes:
        - agent.sop_repo_ids 가 비면 즉시 빈 결과 — error 아님.
        - Qdrant collection 이 없으면 빈 결과 (graceful degrade — indexer 가 아직 안 돈 상태).
        - embedding fn 은 ``src.search.embedding_proxy.create_embedding_fn`` 재사용.
    """

    # 모듈 레벨 캐시 — embedding_fn / qdrant client 를 재사용.
    _embedding_fn: Any = None
    _qdrant_client: Any = None
    _embedding_lock = asyncio.Lock()
    _qdrant_lock = asyncio.Lock()

    def __init__(self) -> None:
        # Stateless — 모듈 캐시만 사용.
        pass

    # --- private helpers -------------------------------------------------

    async def _get_embedding_fn(self) -> Any:
        """BGE-M3 embedding fn 지연 초기화 (proxy 또는 local)."""
        if KMSSopTool._embedding_fn is not None:
            return KMSSopTool._embedding_fn
        async with KMSSopTool._embedding_lock:
            if KMSSopTool._embedding_fn is None:
                try:
                    from src.search.embedding_proxy import create_embedding_fn

                    KMSSopTool._embedding_fn = create_embedding_fn()
                except Exception as exc:
                    log.error("kms_sop_embedding_init_failed", error=str(exc))
                    KMSSopTool._embedding_fn = None
        return KMSSopTool._embedding_fn

    async def _get_qdrant_client(self) -> Any:
        """AsyncQdrantClient 지연 초기화 — settings.QDRANT_URL 사용."""
        if KMSSopTool._qdrant_client is not None:
            return KMSSopTool._qdrant_client
        async with KMSSopTool._qdrant_lock:
            if KMSSopTool._qdrant_client is None:
                try:
                    from qdrant_client import AsyncQdrantClient

                    from src.common.config import settings

                    KMSSopTool._qdrant_client = AsyncQdrantClient(
                        url=settings.QDRANT_URL,
                        api_key=settings.QDRANT_API_KEY or None,
                        prefer_grpc=False,
                        timeout=15,
                    )
                except Exception as exc:
                    log.error("kms_sop_qdrant_init_failed", error=str(exc))
                    KMSSopTool._qdrant_client = None
        return KMSSopTool._qdrant_client

    async def _load_agent_sop_meta(
        self, agent_id: UUID
    ) -> tuple[list[UUID], UUID | None]:
        """agent.sop_repo_ids + agent.tenant_id 조회.

        DetachedInstanceError 회피 — 명시적으로 select 한 컬럼만 추출.
        """
        try:
            from src.core.database import async_session_factory
            from src.core.models.agent import Agent
        except Exception as exc:
            log.error("kms_sop_db_import_failed", error=str(exc))
            return [], None

        try:
            async with async_session_factory() as sess:
                row = (
                    await sess.execute(
                        select(Agent.sop_repo_ids, Agent.tenant_id).where(
                            Agent.id == agent_id
                        )
                    )
                ).first()
        except Exception as exc:
            log.warning(
                "kms_sop_agent_lookup_failed",
                agent_id=str(agent_id),
                error=str(exc),
            )
            return [], None

        if not row:
            return [], None
        sop_repo_ids = list(row[0] or [])
        tenant_id = row[1]
        return sop_repo_ids, tenant_id

    async def _load_sop_doc_ids(
        self, sop_repo_ids: list[UUID], agent_id: UUID | None = None
    ) -> list[str]:
        """sop_repo_ids + agent_documents (mode='sop') 의 UNION → SOP doc ids.

        옵션 Y v2 (2026-05-07): agent_documents 를 UNION 으로 합쳐 partial backfill
        에서도 회귀 0 (GPT-5 P0). 기존 sop_repo_ids 경로 유지.

        조건:
        - documents.is_sop = true, OR
        - 소속 library_folders.kind = 'sop', OR
        - agent_documents.mode = 'sop' (옵션 Y v2 추가)

        repo 안에 SOP 와 일반 매뉴얼이 섞인 경우 매뉴얼이 SOP 검색 결과에 끼지
        않도록 좁힌다. agent_documents 가 채워진 경우 그 매핑이 권위.

        Returns:
            doc_id (UUID 문자열) list. 매칭 doc 없으면 빈 리스트.
        """
        # sop_repo_ids 와 agent_id 둘 다 비면 결과 없음.
        if not sop_repo_ids and not agent_id:
            return []
        try:
            from sqlalchemy import text as _text

            from src.core.database import async_session_factory
        except Exception as exc:
            log.error("kms_sop_doc_filter_db_import_failed", error=str(exc))
            return []

        doc_ids: set[str] = set()
        try:
            async with async_session_factory() as sess:
                # 1. 기존 sop_repo_ids 경로 (회귀 0).
                # B7 (2026-05-07) — ANY(CAST(:ids AS uuid[])) 명시. asyncpg
                # 자동 변환 의존 제거. 빈 list 는 if not sop_repo_ids 가드로
                # 단락 (3-value logic NULL 회피 — GPT-5 P1).
                if sop_repo_ids:
                    rows = (
                        await sess.execute(
                            _text(
                                """
                                SELECT DISTINCT d.id::text
                                FROM documents d
                                LEFT JOIN library_folders f
                                  ON f.id = d.folder_id
                                WHERE d.repository_id = ANY(CAST(:repo_ids AS uuid[]))
                                  AND d.status = 'active'
                                  AND (
                                    d.is_sop = true
                                    OR (f.kind = 'sop')
                                  )
                                """
                            ),
                            {"repo_ids": [str(r) for r in sop_repo_ids]},
                        )
                    ).fetchall()
                    doc_ids.update(r[0] for r in rows)

                # 2. agent_documents (mode='sop') 경로 (옵션 Y v2).
                if agent_id:
                    rows2 = (
                        await sess.execute(
                            _text(
                                """
                                SELECT DISTINCT d.id::text
                                FROM agent_documents ad
                                JOIN documents d ON d.id = ad.document_id
                                WHERE ad.agent_id = :aid
                                  AND ad.mode = 'sop'
                                  AND d.status = 'active'
                                """
                            ),
                            {"aid": str(agent_id)},
                        )
                    ).fetchall()
                    doc_ids.update(r[0] for r in rows2)
        except Exception as exc:
            log.warning("kms_sop_doc_filter_failed", error=str(exc))
            return []
        return list(doc_ids)

    # --- main entry ------------------------------------------------------

    async def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"success": False, "chunks": [], "error": "empty query"}

        # agent_id 필수 — SOP 는 agent 별 격리 검색.
        agent_id_raw = args.get("agent_id")
        if not agent_id_raw:
            return {
                "success": False,
                "chunks": [],
                "error": "agent_id required",
            }
        try:
            agent_id = UUID(str(agent_id_raw))
        except (ValueError, TypeError):
            return {
                "success": False,
                "chunks": [],
                "error": "invalid agent_id",
            }

        # top_k clamp — 1..20 (destructive force 시 20).
        try:
            top_k_raw = int(args.get("top_k", 5) or 5)
        except (ValueError, TypeError):
            top_k_raw = 5
        top_k = max(1, min(top_k_raw, 20))

        # agent.sop_repo_ids 로드.
        sop_repo_ids, agent_tenant_id = await self._load_agent_sop_meta(agent_id)
        # 옵션 Y v2: sop_repo_ids 비어도 agent_documents 채워졌을 수 있음 — 후속
        # _load_sop_doc_ids 에서 union 처리. 단, agent_tenant_id 가 있으면 진행.
        if not sop_repo_ids and agent_tenant_id is None:
            log.debug(
                "kms_sop_search_no_repos",
                agent_id=str(agent_id),
            )
            return {
                "success": True,
                "chunks": [],
                "total": 0,
                "summary": "agent.sop_repo_ids 가 비어 있음",
            }

        # tenant_id — caller override 우선, 없으면 agent.tenant_id.
        caller_tenant = args.get("tenant_id")
        try:
            effective_tenant_id = (
                UUID(str(caller_tenant)) if caller_tenant else agent_tenant_id
            )
        except (ValueError, TypeError):
            effective_tenant_id = agent_tenant_id
        if effective_tenant_id is None:
            return {
                "success": False,
                "chunks": [],
                "error": "tenant_id not resolvable",
            }

        collection = build_sop_collection_name(effective_tenant_id)

        # B2 (2026-05-07) — tenant assertion (GPT-5 P1, 2026-05-07 v2).
        # collection 이름이 sop_v1_{normalized_tenant_uuid} 형식 일치 강제 검증.
        # build_sop_collection_name 의 결정적 결과와 일치 + 형식 regex 일치.
        # 누군가 effective_tenant_id 를 외부에서 변조해 다른 tenant 의 collection
        # 에 접근하려 시도해도 차단 (UUID 형식 + 정확 일치).
        expected_collection = (
            f"{SOP_COLLECTION_PREFIX}"
            f"{str(effective_tenant_id).replace('-', '_')}"
        )
        # UUID underscore 형식: 8_4_4_4_12 (32 hex + 4 underscore).
        _tenant_uuid_re = re.compile(
            r"^sop_v1_[0-9a-f]{8}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        if collection != expected_collection or not _tenant_uuid_re.match(
            collection
        ):
            log.error(
                "kms_sop_collection_tenant_mismatch",
                collection=collection,
                expected=expected_collection,
                tenant_id=str(effective_tenant_id),
            )
            return {
                "success": False,
                "chunks": [],
                "error": "collection tenant mismatch (격리 위반)",
            }

        # embedding.
        emb_fn = await self._get_embedding_fn()
        if emb_fn is None:
            return {
                "success": False,
                "chunks": [],
                "error": "embedding service unavailable",
            }
        try:
            dense, _sparse = await emb_fn(query)
        except Exception as exc:
            log.warning("kms_sop_embed_failed", error=str(exc))
            return {
                "success": False,
                "chunks": [],
                "error": f"embed failed: {exc}",
            }
        if not dense:
            return {
                "success": False,
                "chunks": [],
                "error": "empty embedding",
            }

        # Qdrant search — repo_id payload filter (sop_repo_ids).
        client = await self._get_qdrant_client()
        if client is None:
            return {
                "success": False,
                "chunks": [],
                "error": "qdrant unavailable",
            }

        # alembic 068 — *진짜 SOP* 만 추림 (is_sop=true OR folder.kind='sop').
        # 옵션 Y v2 (2026-05-07): agent_documents (mode='sop') UNION 추가.
        # 매뉴얼/FAQ/glossary 가 sop_repo_ids 안에 함께 있어도 SOP 검색에는 끼지 않게.
        sop_doc_ids = await self._load_sop_doc_ids(sop_repo_ids, agent_id=agent_id)
        if not sop_doc_ids:
            log.debug(
                "kms_sop_no_classified_docs",
                agent_id=str(agent_id),
                sop_repo_count=len(sop_repo_ids),
            )
            return {
                "success": True,
                "chunks": [],
                "total": 0,
                "summary": (
                    "분류된 SOP doc 없음 (is_sop=true / folder.kind='sop' 매칭 0)"
                ),
            }

        try:
            from qdrant_client.http.models import (
                FieldCondition,
                Filter,
                MatchAny,
            )

            # B2 (2026-05-07) — repo_id 제약 제거 (GPT-5 P1).
            # _load_sop_doc_ids 가 이미 SOP 적격 doc 만 산출:
            # - sop_repo_ids 의 (is_sop=true OR folder.kind='sop') AND
            # - agent_documents.mode='sop' (mapping)
            # → document_id 단일 must 로 좁히면 sop_repo_ids 안/밖 무관 적격
            #   doc 만 hit. agent_documents 매핑 doc 의 repo 가 밖에 있어도 hit.
            # 격리: collection 자체 (sop_v1_{tenant_id}) 가 담당 — 위에서
            # tenant assertion 강제.
            flt = Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchAny(any=sop_doc_ids),
                    ),
                ]
            )
            hits = await client.search(
                collection_name=collection,
                query_vector=dense,
                limit=top_k,
                query_filter=flt,
                with_payload=True,
            )
        except Exception as exc:
            # collection 미존재 / Qdrant 오류 — graceful empty.
            log.info(
                "kms_sop_search_failed_or_missing",
                collection=collection,
                error=str(exc)[:200],
            )
            return {
                "success": True,
                "chunks": [],
                "total": 0,
                "summary": "SOP 인덱스 없음 또는 검색 실패",
            }

        chunks: list[dict[str, Any]] = []
        for h in hits:
            payload = getattr(h, "payload", None) or {}
            chunks.append(
                {
                    "text": str(payload.get("text") or "")[:2000],
                    "score": float(getattr(h, "score", 0.0) or 0.0),
                    "repo_id": str(payload.get("repo_id") or ""),
                    "document_id": str(payload.get("document_id") or ""),
                    "chunk_index": int(payload.get("chunk_index") or 0),
                    "heading": str(payload.get("heading") or ""),
                }
            )

        return {
            "success": True,
            "chunks": chunks,
            "total": len(chunks),
            "summary": f"SOP 검색 결과 {len(chunks)}건",
        }
