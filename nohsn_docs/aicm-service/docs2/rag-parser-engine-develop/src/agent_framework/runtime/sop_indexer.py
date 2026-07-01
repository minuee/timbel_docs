"""SOP 임베딩 인덱스 빌더 — Phase 1.5B-β.

KMS document 의 markdown chunks → BGE-M3 → Qdrant ``sop_v1_{tenant_id}`` upsert.

호출 시점:
- Agent 등록/업데이트 시 ``sop_repo_ids`` 가 변경되면 background task 로 trigger.
- 운영자 수동 실행 (CLI / admin endpoint) 도 가능.

설계 원칙:
- alembic 변경 X — Qdrant collection 동적 생성 (recreate_collection).
- chunk 분리: markdown heading (## / ###) 기준 + 500-1000 token 단위 split.
  (token 은 char-len heuristic 4 char/token — BGE-M3 tokenizer 호출 회피).
- payload schema: {repo_id, document_id, chunk_index, heading, text, tags?}
- best-effort idempotent — 동일 chunk hash 재upsert 시 동일 point id.

Round 1: 코드만 존재. background trigger 와이어업은 Round 2.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.agent_framework.tools.kms_sop import build_sop_collection_name
from src.common.logging import get_logger

log = get_logger(__name__)


# BGE-M3 dense dim — 1024.
_DENSE_DIM = 1024
# chunk 크기 정책 — char heuristic (4 char ≈ 1 token).
_TARGET_CHARS = 800 * 4   # ≈ 800 tokens
_MIN_CHARS = 200           # 너무 짧은 chunk 는 다음 chunk 와 merge.
_MAX_CHARS = 1000 * 4      # ≈ 1000 tokens — 절대 상한.

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class SopChunkPayload:
    """Qdrant point payload."""

    repo_id: str
    document_id: str
    chunk_index: int
    heading: str
    text: str
    # markdown 의 H2 섹션명 (failure_response_patterns 같은 anchor).
    section: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "heading": self.heading,
            "text": self.text,
            "section": self.section,
        }


def split_markdown_by_heading(
    markdown: str,
    *,
    target_chars: int = _TARGET_CHARS,
    min_chars: int = _MIN_CHARS,
    max_chars: int = _MAX_CHARS,
) -> list[tuple[str, str, str]]:
    """markdown → ``[(section_h2, heading, body), ...]``.

    H2/H3 헤딩으로 우선 분할. 각 leaf 는 target_chars 근처로 잘림.
    leaf 가 max_chars 초과 시 줄 단위로 강제 split.

    Returns:
        ``[(section_h2_title, immediate_heading, body_text), ...]``
        body 는 heading 자체를 포함하지 않음 (heading 은 별도 필드).
    """
    if not markdown:
        return []

    lines = markdown.splitlines()
    # 누적 stack: (level, title, [body lines]).
    out: list[tuple[str, str, str]] = []
    cur_h2 = ""
    cur_heading = ""
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_lines
        if not cur_lines and not cur_heading:
            return
        body_text = "\n".join(cur_lines).strip()
        if not body_text and not cur_heading:
            cur_lines = []
            return
        # body 가 max_chars 초과 시 단순 split.
        if len(body_text) <= max_chars:
            out.append((cur_h2, cur_heading, body_text))
        else:
            # paragraph (\n\n) 기준 우선, 그게 안 되면 char window.
            paras = [p.strip() for p in re.split(r"\n\s*\n", body_text) if p.strip()]
            buf = ""
            for p in paras:
                if not buf:
                    buf = p
                elif len(buf) + len(p) + 2 <= target_chars:
                    buf = f"{buf}\n\n{p}"
                else:
                    out.append((cur_h2, cur_heading, buf))
                    buf = p
            if buf:
                out.append((cur_h2, cur_heading, buf))
        cur_lines = []

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            # H1 은 문서 제목 — section/heading 갱신 X 단순 무시.
            if level == 1:
                continue
            # H2/H3 갱신 시 flush.
            flush()
            if level == 2:
                cur_h2 = title
                cur_heading = title
            else:  # H3+
                cur_heading = title
            continue
        cur_lines.append(line)
    flush()

    # 너무 짧은 leaf 는 인접 leaf 와 merge (heading 보존).
    merged: list[tuple[str, str, str]] = []
    for sec, head, body in out:
        if merged and len(body) < min_chars:
            psec, phead, pbody = merged[-1]
            new_body = f"{pbody}\n\n## {head}\n{body}" if head else f"{pbody}\n\n{body}"
            if len(new_body) <= max_chars:
                merged[-1] = (psec, phead, new_body)
                continue
        merged.append((sec, head, body))
    return merged


def _stable_point_id(
    document_id: UUID, chunk_index: int, body_sha: str
) -> str:
    """idempotent point id — 같은 (doc, idx, body) 면 같은 id.

    Qdrant 는 UUID 또는 unsigned int 만 허용. UUID5 (ns=URL) 사용.
    """
    import uuid as _uuid

    seed = f"{document_id}:{chunk_index}:{body_sha[:16]}"
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, seed))


async def _ensure_collection(client: Any, collection: str, *, dim: int = _DENSE_DIM) -> None:
    """collection 미존재 시 생성. 존재하면 noop."""
    from qdrant_client.http.exceptions import UnexpectedResponse
    from qdrant_client.http.models import Distance, VectorParams

    try:
        await client.get_collection(collection_name=collection)
        return
    except (UnexpectedResponse, Exception):
        # 미존재 또는 기타 — 생성 시도.
        pass

    try:
        await client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        log.info("sop_collection_created", collection=collection, dim=dim)
    except Exception as exc:
        log.warning(
            "sop_collection_create_failed",
            collection=collection,
            error=str(exc),
        )


async def _load_documents_for_repos(
    repo_ids: list[UUID],
) -> list[tuple[UUID, UUID, str, str]]:
    """repo_ids 안의 active documents → ``[(doc_id, repo_id, title, markdown), ...]``.

    markdown 은 sections 의 ``content`` 를 heading + body 로 reconstruct.
    """
    from src.core.database import async_session_factory
    from src.core.models.document import Document, Section

    if not repo_ids:
        return []

    async with async_session_factory() as sess:
        # documents 조회.
        rows = (
            await sess.execute(
                select(Document.id, Document.repository_id, Document.title)
                .where(Document.repository_id.in_(repo_ids))
                .where(Document.status == "active")
            )
        ).all()
        if not rows:
            return []

        docs: list[tuple[UUID, UUID, str, str]] = []
        for doc_id, repo_id, title in rows:
            # sections — section_order 정렬.
            sec_rows = (
                await sess.execute(
                    select(Section.title, Section.content, Section.level)
                    .where(Section.document_id == doc_id)
                    .order_by(Section.section_order.asc())
                )
            ).all()
            md_parts: list[str] = []
            if title:
                md_parts.append(f"# {title}")
            for s_title, s_content, s_level in sec_rows:
                level = max(1, min(int(s_level or 2), 6))
                hashes = "#" * (level + 1) if level == 1 else "#" * level
                if s_title:
                    md_parts.append(f"{hashes} {s_title}")
                if s_content:
                    md_parts.append(s_content)
            markdown = "\n\n".join(md_parts).strip()
            docs.append((doc_id, repo_id, title or "", markdown))
        return docs


async def build_index(
    tenant_id: UUID,
    repo_ids: list[UUID],
    *,
    qdrant_client: Any = None,
    embedding_fn: Any = None,
    docs_loader: Any = None,
) -> dict[str, Any]:
    """SOP 인덱스 빌드.

    Args:
        tenant_id: collection 결정 (``sop_v1_{tenant_id}``).
        repo_ids: 대상 repo IDs (보통 agent.sop_repo_ids).
        qdrant_client: 테스트 주입용. None 이면 lazy init.
        embedding_fn: 테스트 주입용. None 이면 ``create_embedding_fn`` 호출.
        docs_loader: ``async (repo_ids) -> [(doc_id, repo_id, title, markdown), ...]``.
            None 이면 default DB loader.

    Returns:
        ``{collection, doc_count, chunk_count, upserted, errors}``.
    """
    from qdrant_client.http.models import PointStruct

    collection = build_sop_collection_name(tenant_id)
    stats: dict[str, Any] = {
        "collection": collection,
        "doc_count": 0,
        "chunk_count": 0,
        "upserted": 0,
        "errors": [],
    }

    if not repo_ids:
        log.info("sop_index_build_skipped_no_repos", tenant_id=str(tenant_id))
        return stats

    # 의존성 lazy init.
    if qdrant_client is None:
        try:
            from qdrant_client import AsyncQdrantClient

            from src.common.config import settings

            qdrant_client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                prefer_grpc=False,
                timeout=30,
            )
        except Exception as exc:
            stats["errors"].append(f"qdrant init: {exc}")
            return stats

    if embedding_fn is None:
        try:
            from src.search.embedding_proxy import create_embedding_fn

            embedding_fn = create_embedding_fn()
        except Exception as exc:
            stats["errors"].append(f"embedding init: {exc}")
            return stats

    if docs_loader is None:
        docs_loader = _load_documents_for_repos

    # collection ensure.
    await _ensure_collection(qdrant_client, collection)

    # docs load.
    try:
        docs = await docs_loader(repo_ids)
    except Exception as exc:
        stats["errors"].append(f"docs load: {exc}")
        return stats

    stats["doc_count"] = len(docs)

    points: list[Any] = []
    for doc_id, repo_id, _title, markdown in docs:
        chunks = split_markdown_by_heading(markdown)
        if not chunks:
            continue
        for idx, (section_h2, heading, body) in enumerate(chunks):
            text_for_embed = (
                f"## {heading}\n{body}" if heading else body
            ).strip()
            if not text_for_embed:
                continue
            try:
                dense, _sparse = await embedding_fn(text_for_embed)
            except Exception as exc:
                stats["errors"].append(f"embed doc={doc_id} idx={idx}: {exc}")
                continue
            if not dense:
                continue
            body_sha = hashlib.sha256(text_for_embed.encode("utf-8")).hexdigest()
            point_id = _stable_point_id(doc_id, idx, body_sha)
            payload = SopChunkPayload(
                repo_id=str(repo_id),
                document_id=str(doc_id),
                chunk_index=idx,
                heading=heading,
                text=text_for_embed[:2000],
                section=section_h2,
            ).to_dict()
            points.append(
                PointStruct(id=point_id, vector=dense, payload=payload)
            )
    stats["chunk_count"] = len(points)

    # upsert in batches of 64.
    batch = 64
    for i in range(0, len(points), batch):
        slab = points[i : i + batch]
        try:
            await qdrant_client.upsert(collection_name=collection, points=slab)
            stats["upserted"] += len(slab)
        except Exception as exc:
            stats["errors"].append(f"upsert batch {i}: {exc}")

    log.info(
        "sop_index_build_done",
        tenant_id=str(tenant_id),
        collection=collection,
        doc_count=stats["doc_count"],
        chunk_count=stats["chunk_count"],
        upserted=stats["upserted"],
        errors=len(stats["errors"]),
    )
    return stats


async def trigger_reindex_background(tenant_id: UUID, repo_ids: list[UUID]) -> None:
    """fire-and-forget — agent CRUD 후 비동기 호출용.

    실 호출 와이어업은 Round 2 (router 의 background_tasks). 여기는 helper.
    """
    try:
        await build_index(tenant_id, repo_ids)
    except Exception as exc:  # noqa: BLE001
        log.warning("sop_index_background_failed", error=str(exc))
