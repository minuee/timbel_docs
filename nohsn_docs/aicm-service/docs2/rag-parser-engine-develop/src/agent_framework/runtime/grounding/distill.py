"""L2 — 두 block 간 관계 LLM 정제 (supersedes/conflicts/duplicate/complementary).

lazy 패턴: top-K block 페어 중 relations 미존재만 LLM 호출. confidence ≥ 0.85 만 active
ranking 영향, 그 미만은 raw 만 보관.

호출자: ``feedback.build_grounding_context`` (top-K 후 관계 검토).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from src.agent_framework.llm.json_parse import extract_json

log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "distill_relations.md"

_VALID_RELATIONS = {"supersedes", "conflicts", "duplicate", "complementary"}


@dataclass
class RelationResult:
    from_block_id: str
    to_block_id: str
    relation: str  # one of _VALID_RELATIONS
    confidence: float
    reasoning: str


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


async def distill_pair(
    *,
    block_a: dict[str, Any],
    block_b: dict[str, Any],
    llm_client: Any,
) -> RelationResult | None:
    """두 block 의 관계 판단. 무관·실패 시 None.

    block_a/b 키: block_id, text, effective_date, topic_keywords (옵션).
    """
    prompt = _load_prompt()
    system = "JSON 형식으로만 응답."
    user = (
        f"{prompt}\n\n"
        f"## block_a\n```json\n"
        f"{_format_block(block_a)}\n```\n\n"
        f"## block_b\n```json\n"
        f"{_format_block(block_b)}\n```\n"
    )
    parsed: dict[str, Any] | None = None
    try:
        raw = await llm_client.complete(system, user, response_format="json_object")
        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            parsed = None
    except Exception as e:  # noqa: BLE001
        log.warning("distill_relations_llm_failed", error=str(e))

    if not parsed or not parsed.get("is_related"):
        return None
    relation = str(parsed.get("relation") or "").strip()
    if relation not in _VALID_RELATIONS:
        return None
    confidence = float(parsed.get("confidence") or 0.0)
    confidence = max(0.0, min(1.0, confidence))

    # supersedes 시 newer_block 가 from_block, older 가 to_block.
    newer = parsed.get("newer_block_id")
    if relation == "supersedes" and newer:
        if str(newer) == str(block_b.get("block_id")):
            from_id, to_id = str(block_b["block_id"]), str(block_a["block_id"])
        else:
            from_id, to_id = str(block_a["block_id"]), str(block_b["block_id"])
    else:
        from_id, to_id = str(block_a["block_id"]), str(block_b["block_id"])

    return RelationResult(
        from_block_id=from_id,
        to_block_id=to_id,
        relation=relation,
        confidence=confidence,
        reasoning=str(parsed.get("reasoning") or "")[:500],
    )


def _format_block(b: dict[str, Any]) -> str:
    import json
    safe = {
        "block_id": str(b.get("block_id", "")),
        "text": str(b.get("text", ""))[:1500],
        "effective_date": (str(b["effective_date"]) if b.get("effective_date") else None),
        "topic_keywords": b.get("topic_keywords") or [],
    }
    return json.dumps(safe, ensure_ascii=False, indent=2)


async def upsert_relation(conn: Any, r: RelationResult) -> None:
    """block_relations 에 upsert. UNIQUE (from, to, relation) 으로 dedup."""
    from sqlalchemy import text

    sql = text("""
        INSERT INTO block_relations
          (from_block_id, to_block_id, relation, confidence, distilled_at, reasoning)
        VALUES
          (cast(:f as uuid), cast(:t as uuid), :rel, :conf, NOW(), :reason)
        ON CONFLICT (from_block_id, to_block_id, relation) DO UPDATE SET
          confidence = EXCLUDED.confidence,
          distilled_at = NOW(),
          reasoning = EXCLUDED.reasoning
    """)
    await conn.execute(sql, {
        "f": r.from_block_id,
        "t": r.to_block_id,
        "rel": r.relation,
        "conf": r.confidence,
        "reason": r.reasoning,
    })


async def fetch_relations_for_blocks(
    conn: Any,
    block_ids: list[str],
) -> list[dict[str, Any]]:
    """주어진 block_ids 의 관계 일괄 조회 (active confidence ≥ 0.85 만)."""
    if not block_ids:
        return []
    from sqlalchemy import text

    sql = text("""
        SELECT from_block_id::text AS from_block_id,
               to_block_id::text AS to_block_id,
               relation, confidence, reasoning
        FROM block_relations
        WHERE (from_block_id = ANY(cast(:ids as uuid[]))
            OR to_block_id = ANY(cast(:ids as uuid[])))
          AND confidence >= 0.85
    """)
    rows = (await conn.execute(sql, {"ids": block_ids})).all()
    return [dict(r._mapping) for r in rows]
