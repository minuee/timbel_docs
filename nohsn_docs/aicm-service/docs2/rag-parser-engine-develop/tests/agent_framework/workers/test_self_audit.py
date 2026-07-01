"""KMS-Plus PR P9 — self_audit worker unit tests.

LLM 호출은 mock. real engine 의존 부분은 SQLAlchemy fake.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.agent_framework.workers import self_audit


class _FakeConn:
    def __init__(self, recorder: list[dict[str, Any]], rows_to_return: list[Any]):
        self._rec = recorder
        self._rows = rows_to_return

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        # SELECT 인지 INSERT 인지 구분.
        if "SELECT" in sql.upper() and "FROM CHAT_MESSAGES" in sql.upper():
            return _FakeRows(self._rows)
        if "INSERT INTO VERIFICATION_PROPOSALS" in sql.upper():
            self._rec.append({"sql": "insert", "params": params or {}})
            return _FakeRows([])
        return _FakeRows([])


class _FakeRows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeEngine:
    def __init__(self, rows: list[Any]):
        self.rows = rows
        self.recorder: list[dict[str, Any]] = []

    def connect(self):
        return _FakeConn(self.recorder, self.rows)

    def begin(self):
        return _FakeConn(self.recorder, self.rows)

    async def dispose(self):
        return None


async def test_run_self_audit_inserts_proposals_when_llm_returns():
    """LLM 이 proposal 1개 반환 → verification_proposals INSERT 1건."""
    rows = [
        (
            "msg-1",
            "session-A",
            "user",
            "오늘 일정 등록해",
            "schedule.create",
            None,
            None,
            __import__("datetime").datetime(2026, 4, 27, 12, 0, 0),
        ),
        (
            "msg-2",
            "session-A",
            "assistant",
            "(빈 응답)",
            "",
            None,
            None,
            __import__("datetime").datetime(2026, 4, 27, 12, 0, 5),
        ),
    ]
    engine = _FakeEngine(rows)

    sample_yaml = "name: empty_after_schedule\nchat:\n  - user: \"...\"\n"
    audit_llm = AsyncMock(
        return_value={
            "proposals": [
                {
                    "name": "empty_after_schedule",
                    "yaml": sample_yaml,
                    "evidence": {"chat_message_ids": ["msg-2"], "pattern": "2"},
                }
            ]
        }
    )

    inserted = await self_audit.run_self_audit(engine=engine, audit_llm=audit_llm)
    assert inserted == 1
    inserts = [r for r in engine.recorder if r["sql"] == "insert"]
    assert len(inserts) == 1
    params = inserts[0]["params"]
    assert params["yml"].strip().startswith("name:")
    ev = json.loads(params["ev"])
    assert ev["pattern"] == "2"


async def test_run_self_audit_returns_zero_when_no_data():
    engine = _FakeEngine(rows=[])
    audit_llm = AsyncMock(return_value={"proposals": []})
    inserted = await self_audit.run_self_audit(engine=engine, audit_llm=audit_llm)
    assert inserted == 0
    audit_llm.assert_not_awaited()


async def test_run_self_audit_skips_empty_yaml_proposals():
    rows = [
        (
            "msg-1",
            "session-B",
            "user",
            "테스트",
            "",
            None,
            None,
            __import__("datetime").datetime(2026, 4, 27, 12, 0, 0),
        )
    ]
    engine = _FakeEngine(rows)
    audit_llm = AsyncMock(
        return_value={
            "proposals": [
                {"name": "x", "yaml": "", "evidence": {}},  # empty yaml — skip
                {"name": "y", "yaml": "name: ok\n", "evidence": {}},
            ]
        }
    )
    inserted = await self_audit.run_self_audit(engine=engine, audit_llm=audit_llm)
    assert inserted == 1


async def test_run_self_audit_swallows_llm_errors():
    rows = [
        (
            "msg-1",
            "session-C",
            "user",
            "테스트",
            "",
            None,
            None,
            __import__("datetime").datetime(2026, 4, 27, 12, 0, 0),
        )
    ]
    engine = _FakeEngine(rows)

    async def bad_llm(_prompt: str) -> dict[str, Any]:
        raise RuntimeError("upstream down")

    inserted = await self_audit.run_self_audit(engine=engine, audit_llm=bad_llm)
    assert inserted == 0  # cron 자체는 fail 하지 않음


def test_is_enabled_env(monkeypatch):
    monkeypatch.setenv("KMS_SELF_AUDIT_ENABLED", "1")
    assert self_audit.is_enabled() is True
    monkeypatch.setenv("KMS_SELF_AUDIT_ENABLED", "0")
    assert self_audit.is_enabled() is False
    monkeypatch.delenv("KMS_SELF_AUDIT_ENABLED", raising=False)
    assert self_audit.is_enabled() is False
