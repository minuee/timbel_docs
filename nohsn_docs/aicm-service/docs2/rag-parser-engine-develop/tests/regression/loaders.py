"""Load scenarios — yaml file + DB ``verification_scenarios`` (PR P9).

yaml 형식 두 가지 모두 수용 (legacy + 신형):

legacy::

    chat:
      - user: "..."
        expect: {...}

신형::

    steps:
      - type: chat
        user: "..."
      - type: http
        method: POST
        path: /...

memory rule: 패턴 우선, 사례 enum X — yaml 은 패턴(시나리오) 표현이지
하드코드 사례 enum 이 아님.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .types import ChatStep, HttpStep, Scenario


SCENARIOS_DIR = Path(__file__).parent / "scenarios"


def _parse_http_block(h: dict[str, Any]) -> HttpStep:
    """yaml ``http:`` 항목 1개 → HttpStep."""
    req = h.get("request", h)
    return HttpStep(
        method=req.get("method", "GET"),
        path=req["path"],
        headers=req.get("headers", {}) or {},
        json_body=req.get("json"),
        file=req.get("file"),
        auth_account=req.get("auth_account"),
        tenant=req.get("tenant"),
        expect=h.get("expect", {}) or {},
    )


def _parse_chat_block(c: dict[str, Any]) -> ChatStep:
    """yaml ``chat:`` 항목 1개 → ChatStep."""
    return ChatStep(
        user=c["user"],
        tenant=c.get("tenant", "personal"),
        account=c.get("account", "demo-admin"),
        expect=c.get("expect", {}) or {},
    )


def _scenario_from_doc(doc: dict[str, Any], default_name: str) -> Scenario:
    name = doc.get("name", default_name)
    refs = doc.get("references", []) or []
    steps: list[HttpStep | ChatStep] = []

    # 신형 통합 ``steps:`` (type 으로 분기)
    for s in doc.get("steps", []) or []:
        t = s.get("type")
        if t == "http":
            steps.append(_parse_http_block(s))
        elif t == "chat":
            steps.append(_parse_chat_block(s))
        elif "user" in s:
            # legacy: chat 으로 추정
            steps.append(_parse_chat_block(s))
        elif "path" in s:
            steps.append(_parse_http_block(s))

    # legacy: top-level ``http:`` 와 ``chat:`` 분리.
    for h in doc.get("http", []) or []:
        steps.append(_parse_http_block(h))
    for c in doc.get("chat", []) or []:
        steps.append(_parse_chat_block(c))

    return Scenario(name=name, references=list(refs), steps=steps)


def load_yaml_scenarios() -> list[Scenario]:
    out: list[Scenario] = []
    if not SCENARIOS_DIR.exists():
        return out
    for f in sorted(SCENARIOS_DIR.glob("*.yaml")):
        try:
            with f.open(encoding="utf-8") as fh:
                doc = yaml.safe_load(fh)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        out.append(_scenario_from_doc(doc, default_name=f.stem))
    return out


async def load_db_scenarios(engine: Any) -> list[Scenario]:
    """``verification_scenarios`` 테이블에서 yaml_text 를 읽어 Scenario 로 변환."""
    from sqlalchemy import text

    out: list[Scenario] = []
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id::text, name, yaml_text FROM verification_scenarios")
            )
        ).fetchall()
    for _id, name, yaml_text in rows:
        if not yaml_text:
            continue
        try:
            doc = yaml.safe_load(yaml_text)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        out.append(_scenario_from_doc(doc, default_name=name or _id))
    return out
