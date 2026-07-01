"""Daily LLM-driven self-audit — surface suspicious patterns in chat_messages.trace.

KMS-Plus PR P9. 매일 03:00 cron. 어제 24h 의 chat_messages + trace JSONB 를
회수, LLM "의심 패턴 발견기" prompt 로 점검 → ``verification_proposals`` 에
yaml draft INSERT. admin 이 dashboard 에서 검토 후 promote → ``verification_
scenarios`` 활성화.

memory rule: rule/regex 금지. 패턴 발견은 전적으로 LLM 에 위임 (자비스
패턴 — feedback_llm_driven_everywhere.md). 이 워커는 데이터를 가져와
prompt 를 호출하고 결과를 DB 에 적재하는 컨베이어 역할만 함.

env::

    KMS_SELF_AUDIT_ENABLED=1   # cron 등록 여부
    KMS_SELF_AUDIT_HOURS=24    # 회수 윈도우 (default 24)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.common.config import settings
from src.common.logging import get_logger


log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Prompt — 패턴 우선 (case enum 없음). 사용자가 발견한 패턴 7종을 원리로 표현.
# ---------------------------------------------------------------------------

AUDIT_PROMPT = """당신은 챗봇 시스템의 회귀 패턴 발견기입니다. 아래 JSON 은 어제
24시간 동안의 chat_messages 의 trace + 응답 본문 + intent/skill 활성 기록
입니다.

다음 패턴 원리 중 하나라도 발견되면 회귀 시나리오 후보로 보고하세요:

1. sticky 잔존 — 한 skill 이 활성된 후 무관한 발화에 그 skill 이 sticky 하게 남는 경우
2. 빈 응답 — assistant body 가 비어있거나 placeholder 만 있는 경우
3. tool 성공 vs 본문 불일치 — tool_call 은 성공했는데 사용자에게 안내 본문이 없는 경우
4. 의도 모순 — trace 에 "skill 활성: X" 와 "intent: _no_skills_available" 가 동시 출현
5. 중복 등록 — 같은 의도에 같은 entity 로 두 번 이상 INSERT 한 경우
6. citation 마커 mismatch — 본문 [N] 마커와 citations payload 번호가 안 맞는 경우
7. cross-feature 단절 — 메일 처리 후 일정/일기 등 자연스러운 후속 turn 이
   원래 컨텍스트를 잃는 경우

각 발견 패턴마다 회귀 시나리오 yaml draft 를 생성하세요. 형식:

```yaml
name: <짧은 이름>
references: ["chat_messages.id 1", "chat_messages.id 2"]
chat:
  - user: "<발화 1>"
    expect:
      <key>: <value>
  - user: "<발화 2>"
    expect:
      <key>: <value>
```

발견 없으면 `proposals: []` 반환.

trace JSON:
{trace_json}

출력은 반드시 다음 JSON 스키마만:
{{
  "proposals": [
    {{
      "name": "<이름>",
      "yaml": "<위 yaml 문자열>",
      "evidence": {{"chat_message_ids": ["..."], "pattern": "1~7 중 하나", "summary": "..."}}
    }}
  ]
}}
"""


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------


async def fetch_recent_trace(
    engine: AsyncEngine, hours: int = 24
) -> list[dict[str, Any]]:
    """``chat_messages`` 에서 hours 시간 내 row 회수.

    schema 가 환경마다 다를 수 있어 column 누락은 NULL 로 진행.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with engine.connect() as conn:
        # COALESCE 로 누락 가능 column 보호.
        try:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id::text, session_id::text, role, "
                        "       COALESCE(content, '') AS content, "
                        "       COALESCE(intent, '') AS intent, "
                        "       trace, structured_blocks, created_at "
                        "FROM chat_messages "
                        "WHERE created_at >= :cutoff "
                        "ORDER BY session_id, created_at"
                    ),
                    {"cutoff": cutoff},
                )
            ).fetchall()
        except Exception as e:  # noqa: BLE001
            log.warning("self_audit_fetch_failed", error=str(e))
            return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r[0],
                "session_id": r[1],
                "role": r[2],
                "content": r[3] or "",
                "intent": r[4] or "",
                "trace": r[5],
                "structured_blocks": r[6],
                "created_at": r[7].isoformat() if r[7] else None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# LLM call — gemma-4 / qwen 어느 쪽이든 동작하도록 OpenAI 호환 SDK 사용.
# 실패하면 빈 결과 — cron 자체는 절대 fail 하지 않게.
# ---------------------------------------------------------------------------


async def _call_audit_llm(prompt: str) -> dict[str, Any]:
    """LLM 호출. 실패 시 ``{}`` 반환 (cron 멈추지 않게)."""
    try:
        import openai
    except Exception:  # noqa: BLE001
        log.warning("self_audit_no_openai_sdk")
        return {}
    base_url = getattr(settings, "VLLM_URL", None) or "http://vllm:8000/v1"
    model = getattr(settings, "VLLM_MODEL", None) or "kms-deep"
    api_key = getattr(settings, "VLLM_API_KEY", None) or "dummy"
    client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=60.0)
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "JSON 만 반환. 다른 텍스트 금지.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=2048,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("self_audit_llm_call_failed", error=str(e))
        return {}
    txt = resp.choices[0].message.content if resp.choices else ""
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except (ValueError, json.JSONDecodeError):
        log.warning("self_audit_llm_bad_json", preview=txt[:200])
        return {}


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


SIZE_CAP = 100 * 1024  # 100 KB cap on prompt payload (LLM context budget).
TURNS_PER_SESSION = 20  # 세션당 turn 캡 — 긴 세션 1개가 다 차지하지 않게.


async def run_self_audit(
    engine: AsyncEngine | None = None,
    *,
    audit_llm: Any | None = None,
    hours: int | None = None,
) -> int:
    """Daily 03:00 cron entry. INSERT 된 proposal 개수 반환.

    Parameters
    ----------
    engine : AsyncEngine, optional
        주입 가능 — 미주입 시 ``settings.DATABASE_URL`` 로 새 engine 생성.
    audit_llm : callable(prompt: str) -> dict, optional
        LLM 호출 함수 주입 (테스트용 mock). 미주입 시 ``_call_audit_llm``.
    hours : int, optional
        회수 윈도우. 미주입 시 ``KMS_SELF_AUDIT_HOURS`` 또는 24.
    """
    own_engine = False
    if engine is None:
        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        own_engine = True

    try:
        win = (
            hours
            if hours is not None
            else int(os.environ.get("KMS_SELF_AUDIT_HOURS", "24"))
        )
        trace_data = await fetch_recent_trace(engine, hours=win)
        if not trace_data:
            log.info("self_audit_no_data", hours=win)
            return 0

        # Group by session.
        sessions: dict[str, list[dict[str, Any]]] = {}
        for msg in trace_data:
            sid = msg["session_id"] or "_no_session"
            sessions.setdefault(sid, []).append(msg)

        # Truncate big sessions and limit total payload size.
        payload: list[dict[str, Any]] = []
        total_size = 0
        for sid, msgs in sessions.items():
            piece = {"session_id": sid, "messages": msgs[:TURNS_PER_SESSION]}
            s = json.dumps(piece, ensure_ascii=False, default=str)
            if total_size + len(s) > SIZE_CAP:
                break
            payload.append(piece)
            total_size += len(s)

        prompt = AUDIT_PROMPT.format(
            trace_json=json.dumps(payload, ensure_ascii=False, default=str)
        )

        llm = audit_llm or _call_audit_llm
        try:
            result = await llm(prompt)
        except Exception as e:  # noqa: BLE001
            log.warning("self_audit_llm_unhandled", error=str(e))
            result = {}

        proposals = result.get("proposals") if isinstance(result, dict) else None
        if not isinstance(proposals, list):
            proposals = []

        inserted = 0
        async with engine.begin() as conn:
            for p in proposals:
                if not isinstance(p, dict):
                    continue
                yaml_text = p.get("yaml", "") or ""
                if not yaml_text.strip():
                    continue
                evidence = p.get("evidence", {})
                if not isinstance(evidence, dict):
                    evidence = {"raw": str(evidence)}
                try:
                    await conn.execute(
                        text(
                            "INSERT INTO verification_proposals "
                            "(id, source, suggested_yaml, evidence, status) "
                            "VALUES (gen_random_uuid(), 'self_audit', :yml, "
                            "        CAST(:ev AS JSONB), 'proposed')"
                        ),
                        {
                            "yml": yaml_text,
                            "ev": json.dumps(evidence, ensure_ascii=False),
                        },
                    )
                    inserted += 1
                except Exception as e:  # noqa: BLE001
                    log.warning("self_audit_insert_failed", error=str(e))

        log.info(
            "self_audit_completed",
            sessions=len(sessions),
            messages=len(trace_data),
            proposals_inserted=inserted,
        )
        return inserted
    finally:
        if own_engine:
            await engine.dispose()


def is_enabled() -> bool:
    return os.environ.get("KMS_SELF_AUDIT_ENABLED", "").lower() in (
        "1",
        "true",
        "yes",
    )
