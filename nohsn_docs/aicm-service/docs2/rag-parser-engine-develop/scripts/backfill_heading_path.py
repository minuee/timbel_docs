# scripts/backfill_heading_path.py
"""기존 문서 blocks.source_location.heading_path 백필.

신규 업로드는 block_worker(heading_propagator)로 자동 채워지나, 배포 전 등록 문서는
heading_path가 비어 있다. 블럭을 로드 → propagate_heading_paths → DB 업데이트.
재임베딩 불요(검색 결과 단계 surface는 Task 1). 사용:
    python scripts/backfill_heading_path.py --repository-id <uuid> [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json

import asyncpg

from src.common.config import settings
from src.pipeline.models.block import BlockObject
from src.pipeline.enrichers.heading_propagator import propagate_heading_paths


def _jl(v):
    if v is None:
        return {}
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return {}


async def backfill(repository_id: str, dry_run: bool) -> None:
    dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    doc_ids = [r["id"] for r in await conn.fetch(
        "SELECT id FROM documents WHERE repository_id=$1", repository_id)]
    total = 0
    for doc_id in doc_ids:
        rows = await conn.fetch(
            """SELECT id, document_id, block_type, content, block_index,
                      source_location, metadata, properties
               FROM blocks WHERE document_id=$1 ORDER BY block_index""", doc_id)
        if not rows:
            continue
        blocks = [BlockObject.model_validate({
            "id": str(r["id"]), "document_id": str(r["document_id"]),
            "block_type": r["block_type"], "content": r["content"] or "",
            "block_index": r["block_index"], "source_location": _jl(r["source_location"]),
            "metadata": _jl(r["metadata"]), "properties": _jl(r["properties"]),
        }) for r in rows]
        propagate_heading_paths(blocks)
        for b in blocks:
            hp = [h for h in (b.source_location.heading_path or []) if h]
            if not hp:
                continue
            total += 1
            if dry_run:
                continue
            await conn.execute(
                "UPDATE blocks SET source_location=jsonb_set("
                "coalesce(source_location,'{}'::jsonb),'{heading_path}',$2::jsonb),"
                " updated_at=now() WHERE id=$1",
                b.id, json.dumps(hp, ensure_ascii=False))
    await conn.close()
    print(f"[backfill] repo={repository_id} docs={len(doc_ids)} blocks_with_path={total} dry_run={dry_run}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repository-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(backfill(args.repository_id, args.dry_run))


if __name__ == "__main__":
    main()
