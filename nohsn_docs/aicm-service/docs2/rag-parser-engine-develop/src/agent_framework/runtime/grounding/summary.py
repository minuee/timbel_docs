"""L3 — tenant+repo 단위 도메인 요약 (LLM 이 신본 매핑 작성).

lazy + stale TTL: ``feedback.build_grounding_context`` 가 missing 또는 24h+ 경과 시 refresh.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from src.agent_framework.llm.json_parse import extract_json

log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "domain_summary.md"


@dataclass
class SummaryResult:
    tenant_id: str
    repository_id: str | None
    summary_text: str
    source_block_count: int
    generator_model: str


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


async def refresh_domain_summary(
    *,
    tenant_id: str,
    repository_id: str | None,
    tenant_kind: str | None,
    blocks: list[dict[str, Any]],
    llm_client: Any,
    generator_model: str = "gpt-5.5",
) -> SummaryResult | None:
    """blocks 를 보고 LLM 이 도메인 요약 작성. 빈 blocks 또는 LLM 실패 시 None."""
    if not blocks:
        return None
    prompt = _load_prompt()
    system = "JSON 형식으로만 응답."
    payload_blocks = [
        {
            "block_id": str(b.get("block_id", "")),
            "title": str(b.get("title", ""))[:120],
            "heading": str(b.get("heading", ""))[:120],
            "snippet": str(b.get("snippet", ""))[:600],
            "effective_date": str(b["effective_date"]) if b.get("effective_date") else None,
            "version_label": b.get("version_label"),
            "relations": b.get("relations") or [],
        }
        for b in blocks[:30]
    ]
    import json as _json
    user = (
        f"{prompt}\n\n## tenant_kind\n{tenant_kind or '(unknown)'}\n\n"
        f"## blocks\n```json\n{_json.dumps(payload_blocks, ensure_ascii=False, indent=2)}\n```"
    )
    try:
        raw = await llm_client.complete(system, user, response_format="json_object")
        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            return None
        summary_text = str(parsed.get("summary_text") or "").strip()
        if not summary_text:
            return None
        return SummaryResult(
            tenant_id=tenant_id,
            repository_id=repository_id,
            summary_text=summary_text[:4000],
            source_block_count=int(parsed.get("source_block_count") or len(blocks)),
            generator_model=generator_model,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("domain_summary_llm_failed", error=str(e), tenant_id=tenant_id)
        return None


async def fetch_summary(
    conn: Any,
    tenant_id: str,
    repository_id: str | None,
    stale_after_seconds: int = 24 * 3600,
) -> dict[str, Any] | None:
    """캐시 hit 면 dict, miss/stale 이면 None.

    repository_id NULL 매칭 시 ``IS NOT DISTINCT FROM`` 사용.
    """
    from sqlalchemy import text

    sql = text("""
        SELECT id::text AS id, summary_text, source_block_count,
               generated_at, generator_model
        FROM domain_knowledge_summary
        WHERE tenant_id = cast(:tid as uuid)
          AND repository_id IS NOT DISTINCT FROM cast(:rid as uuid)
        LIMIT 1
    """)
    row = (await conn.execute(sql, {"tid": tenant_id, "rid": repository_id})).first()
    if not row:
        return None
    rec = dict(row._mapping)
    gen_at = rec.get("generated_at")
    if gen_at is None:
        return None
    if isinstance(gen_at, datetime):
        age = (datetime.now(timezone.utc) - gen_at.astimezone(timezone.utc)).total_seconds()
        if age > stale_after_seconds:
            return None
    return rec


async def upsert_summary(conn: Any, s: SummaryResult) -> None:
    from sqlalchemy import text

    sql = text("""
        INSERT INTO domain_knowledge_summary
          (tenant_id, repository_id, summary_text, source_block_count,
           generated_at, generator_model)
        VALUES
          (cast(:tid as uuid), cast(:rid as uuid), :stext, :cnt, NOW(), :model)
        ON CONFLICT (tenant_id, repository_id) DO UPDATE SET
          summary_text = EXCLUDED.summary_text,
          source_block_count = EXCLUDED.source_block_count,
          generated_at = NOW(),
          generator_model = EXCLUDED.generator_model
    """)
    await conn.execute(sql, {
        "tid": s.tenant_id,
        "rid": s.repository_id,
        "stext": s.summary_text,
        "cnt": s.source_block_count,
        "model": s.generator_model,
    })
