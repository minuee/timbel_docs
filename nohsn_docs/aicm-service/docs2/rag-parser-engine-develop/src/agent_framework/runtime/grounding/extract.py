"""L1 — block 단위 시점/버전 라벨 LLM 추출.

lazy 패턴: ``feedback.build_grounding_context`` 가 retrieval 시 index 없는 block 만
호출. 결과는 ``block_extraction_index`` 에 영속 (재시작 후에도 누적).

LLM 실패 시 graceful degradation: ``effective_date=None`` + ``confidence=0`` 로 upsert.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import structlog

from src.agent_framework.llm.json_parse import extract_json

log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_labels.md"


@dataclass
class ExtractionResult:
    block_id: str
    tenant_id: str
    effective_date: date | None
    version_label: str | None
    topic_keywords: list[str]
    confidence: float
    raw_response: dict[str, Any]
    extractor_model: str


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _parse_date(raw: Any) -> date | None:
    if not raw:
        return None
    s = str(raw).strip()
    if not s or s.lower() in {"null", "none"}:
        return None
    # ISO YYYY-MM-DD or variants
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


async def extract_temporal_labels(
    *,
    block_id: str,
    tenant_id: str,
    block_text: str,
    llm_client: Any,
    extractor_model: str = "gpt-5.5",
) -> ExtractionResult:
    """block 텍스트에서 effective_date / version_label / topic_keywords 추출.

    LLM 실패 시 confidence=0 인 graceful 결과 반환 (호출자가 upsert 후 ranking 에 영향 X).
    """
    prompt = _load_prompt()
    system = "JSON 형식으로만 응답."
    user = f"{prompt}\n\n## block_text\n\n{block_text[:3000]}"

    raw_response: dict[str, Any] = {}
    parsed: dict[str, Any] | None = None
    try:
        raw = await llm_client.complete(system, user, response_format="json_object")
        parsed = extract_json(raw)
        if isinstance(parsed, dict):
            raw_response = parsed
    except Exception as e:  # noqa: BLE001
        log.warning("extract_labels_llm_failed", error=str(e), block_id=block_id)

    effective_date = _parse_date((parsed or {}).get("effective_date"))
    version_label = (parsed or {}).get("version_label")
    if version_label is not None:
        version_label = str(version_label).strip() or None
    topic_keywords_raw = (parsed or {}).get("topic_keywords") or []
    topic_keywords = [str(t).strip() for t in topic_keywords_raw if str(t).strip()][:8]
    confidence = float((parsed or {}).get("confidence") or 0.0)
    confidence = max(0.0, min(1.0, confidence))

    return ExtractionResult(
        block_id=block_id,
        tenant_id=tenant_id,
        effective_date=effective_date,
        version_label=version_label,
        topic_keywords=topic_keywords,
        confidence=confidence,
        raw_response=raw_response,
        extractor_model=extractor_model,
    )


async def upsert_extraction(conn: Any, result: ExtractionResult) -> None:
    """SQLAlchemy AsyncConnection 으로 block_extraction_index 에 upsert."""
    from sqlalchemy import text

    sql = text("""
        INSERT INTO block_extraction_index
          (block_id, tenant_id, effective_date, version_label, topic_keywords,
           confidence, raw_response, extracted_at, extractor_model)
        VALUES
          (cast(:block_id as uuid), cast(:tenant_id as uuid), :effective_date,
           :version_label, :topic_keywords, :confidence,
           cast(:raw_response as jsonb), NOW(), :extractor_model)
        ON CONFLICT (block_id) DO UPDATE SET
          tenant_id = EXCLUDED.tenant_id,
          effective_date = EXCLUDED.effective_date,
          version_label = EXCLUDED.version_label,
          topic_keywords = EXCLUDED.topic_keywords,
          confidence = EXCLUDED.confidence,
          raw_response = EXCLUDED.raw_response,
          extracted_at = NOW(),
          extractor_model = EXCLUDED.extractor_model
    """)
    await conn.execute(sql, {
        "block_id": result.block_id,
        "tenant_id": result.tenant_id,
        "effective_date": result.effective_date,
        "version_label": result.version_label,
        "topic_keywords": result.topic_keywords,
        "confidence": result.confidence,
        "raw_response": json.dumps(result.raw_response, ensure_ascii=False),
        "extractor_model": result.extractor_model,
    })
