"""D29 §4 (#161) — schedule_alert.owner_agent_id inheritance 단위 test.

검증:
- _detect_schedule_columns 가 owner_agent_id 컬럼 존재 시 cols 에 추가
- _list_upcoming_for_account 가 owner_agent_id 가 있을 때 SELECT + return
- legacy fixture (컬럼 없음) — 회귀 0 + None forward
- feed_event source 에 owner_agent_id forward
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# _detect_schedule_columns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_columns_owner_agent_id_present():
    """owner_agent_id 컬럼 존재 → cols['owner_agent_col'] = 'owner_agent_id'."""
    from src.agent_framework.workers.schedule_alert import _detect_schedule_columns

    cols_in_table = ["id", "starts_at", "title", "account_id", "owner_agent_id"]

    fake_result = MagicMock()
    fake_result.all = MagicMock(return_value=[(c,) for c in cols_in_table])

    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock(return_value=fake_result)

    class _CM:
        async def __aenter__(self_):
            return fake_conn
        async def __aexit__(self_, *a):
            return False

    fake_eng = MagicMock()
    fake_eng.connect = MagicMock(return_value=_CM())

    cols = await _detect_schedule_columns(fake_eng)
    assert cols is not None
    assert cols["owner_agent_col"] == "owner_agent_id"
    assert cols["when"] == "starts_at"
    assert cols["title"] == "title"
    assert cols["scope_col"] == "account_id"


@pytest.mark.asyncio
async def test_detect_columns_owner_agent_id_absent():
    """owner_agent_id 컬럼 없음 → cols 에 미포함 (회귀 0)."""
    from src.agent_framework.workers.schedule_alert import _detect_schedule_columns

    cols_in_table = ["id", "starts_at", "title", "account_id"]  # no owner_agent_id

    fake_result = MagicMock()
    fake_result.all = MagicMock(return_value=[(c,) for c in cols_in_table])

    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock(return_value=fake_result)

    class _CM:
        async def __aenter__(self_):
            return fake_conn
        async def __aexit__(self_, *a):
            return False

    fake_eng = MagicMock()
    fake_eng.connect = MagicMock(return_value=_CM())

    cols = await _detect_schedule_columns(fake_eng)
    assert cols is not None
    assert "owner_agent_col" not in cols  # legacy fixture 안전


# ---------------------------------------------------------------------------
# _list_upcoming_for_account — SQL 변형 검증
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_upcoming_includes_owner_agent_id_when_col_present():
    from src.agent_framework.workers.schedule_alert import _list_upcoming_for_account

    aid = uuid4()
    schedule_id = uuid4()
    owner_aid = uuid4()
    when_ts = datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc)

    fake_result = MagicMock()
    fake_result.all = MagicMock(return_value=[(schedule_id, "회의", when_ts, owner_aid)])

    fake_conn = MagicMock()
    captured_sql: dict = {}

    async def _exec(sql, params):
        captured_sql["text"] = str(sql)
        captured_sql["params"] = params
        return fake_result

    fake_conn.execute = _exec

    class _CM:
        async def __aenter__(self_):
            return fake_conn
        async def __aexit__(self_, *a):
            return False

    fake_eng = MagicMock()
    fake_eng.connect = MagicMock(return_value=_CM())

    cols = {
        "when": "starts_at",
        "title": "title",
        "scope_col": "account_id",
        "owner_agent_col": "owner_agent_id",
    }
    items = await _list_upcoming_for_account(
        fake_eng,
        aid,
        cols,
        datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc),
    )

    # SQL 에 owner_agent_id 컬럼 포함
    assert "owner_agent_id" in captured_sql["text"]
    # item 에 owner_agent_id forward
    assert items[0]["owner_agent_id"] == str(owner_aid)
    assert items[0]["title"] == "회의"


@pytest.mark.asyncio
async def test_list_upcoming_no_owner_agent_id_when_col_absent():
    """legacy schema (owner_agent_col 없음) → SQL 에 미포함, item 에 미포함."""
    from src.agent_framework.workers.schedule_alert import _list_upcoming_for_account

    aid = uuid4()
    schedule_id = uuid4()
    when_ts = datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc)

    fake_result = MagicMock()
    fake_result.all = MagicMock(return_value=[(schedule_id, "회의", when_ts)])

    fake_conn = MagicMock()
    captured_sql: dict = {}

    async def _exec(sql, params):
        captured_sql["text"] = str(sql)
        return fake_result

    fake_conn.execute = _exec

    class _CM:
        async def __aenter__(self_):
            return fake_conn
        async def __aexit__(self_, *a):
            return False

    fake_eng = MagicMock()
    fake_eng.connect = MagicMock(return_value=_CM())

    cols = {
        "when": "starts_at",
        "title": "title",
        "scope_col": "account_id",
    }
    items = await _list_upcoming_for_account(
        fake_eng,
        aid,
        cols,
        datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc),
    )

    # SQL 에 owner_agent_id 미포함
    assert "owner_agent_id" not in captured_sql["text"]
    # item 에 owner_agent_id 미포함
    assert "owner_agent_id" not in items[0]


# ---------------------------------------------------------------------------
# run_once forward — feed_event source.owner_agent_id (GPT-5 사전 verdict 권고)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_forwards_owner_agent_id_to_feed_event_source():
    """run_once → insert_feed_event 호출 시 source.owner_agent_id forward 확인."""
    from src.agent_framework.workers import schedule_alert as mod

    owner_aid = uuid4()
    schedule_id = "sch-123"
    when_ts = datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc)
    items = [
        {
            "id": schedule_id,
            "title": "회의",
            "when": when_ts,
            "owner_agent_id": str(owner_aid),
        }
    ]
    accounts = [
        {
            "account_id": uuid4(),
            "tenant_id": uuid4(),
            "preferences": {},
            "tenant_prefs": {},
        }
    ]

    with patch.object(mod, "_get_engine", return_value=MagicMock()):
        with patch.object(
            mod,
            "_detect_schedule_columns",
            new_callable=AsyncMock,
            return_value={
                "when": "starts_at",
                "title": "title",
                "scope_col": "account_id",
                "owner_agent_col": "owner_agent_id",
            },
        ):
            with patch.object(mod, "list_active_accounts", new_callable=AsyncMock, return_value=accounts):
                with patch.object(mod, "_list_upcoming_for_account", new_callable=AsyncMock, return_value=items):
                    with patch.object(mod, "_already_alerted", new_callable=AsyncMock, return_value=False):
                        with patch.object(mod, "insert_feed_event", new_callable=AsyncMock) as insert_mock:
                            await mod.run_once(now=datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc))
                            assert insert_mock.await_count == 1
                            kw = insert_mock.await_args.kwargs
                            assert "source" in kw
                            assert kw["source"]["owner_agent_id"] == str(owner_aid)
                            assert kw["source"]["schedule_id"] == schedule_id


@pytest.mark.asyncio
async def test_run_once_no_owner_key_when_col_absent():
    """legacy schema → source 에 owner_agent_id key 미포함 (회귀 0)."""
    from src.agent_framework.workers import schedule_alert as mod

    schedule_id = "sch-456"
    when_ts = datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc)
    # legacy item — owner_agent_id key 자체 없음
    items = [{"id": schedule_id, "title": "리마인더", "when": when_ts}]
    accounts = [
        {
            "account_id": uuid4(),
            "tenant_id": uuid4(),
            "preferences": {},
            "tenant_prefs": {},
        }
    ]

    with patch.object(mod, "_get_engine", return_value=MagicMock()):
        with patch.object(
            mod,
            "_detect_schedule_columns",
            new_callable=AsyncMock,
            return_value={
                "when": "starts_at",
                "title": "title",
                "scope_col": "account_id",
            },
        ):
            with patch.object(mod, "list_active_accounts", new_callable=AsyncMock, return_value=accounts):
                with patch.object(mod, "_list_upcoming_for_account", new_callable=AsyncMock, return_value=items):
                    with patch.object(mod, "_already_alerted", new_callable=AsyncMock, return_value=False):
                        with patch.object(mod, "insert_feed_event", new_callable=AsyncMock) as insert_mock:
                            await mod.run_once(now=datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc))
                            assert insert_mock.await_count == 1
                            kw = insert_mock.await_args.kwargs
                            assert "owner_agent_id" not in kw["source"]


@pytest.mark.asyncio
async def test_list_upcoming_owner_agent_id_null_in_db():
    """DB row 의 owner_agent_id 가 NULL → item.owner_agent_id = None."""
    from src.agent_framework.workers.schedule_alert import _list_upcoming_for_account

    aid = uuid4()
    schedule_id = uuid4()
    when_ts = datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc)

    fake_result = MagicMock()
    fake_result.all = MagicMock(return_value=[(schedule_id, "회의", when_ts, None)])

    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock(return_value=fake_result)

    class _CM:
        async def __aenter__(self_):
            return fake_conn
        async def __aexit__(self_, *a):
            return False

    fake_eng = MagicMock()
    fake_eng.connect = MagicMock(return_value=_CM())

    cols = {
        "when": "starts_at",
        "title": "title",
        "scope_col": "account_id",
        "owner_agent_col": "owner_agent_id",
    }
    items = await _list_upcoming_for_account(
        fake_eng,
        aid,
        cols,
        datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc),
    )
    assert items[0]["owner_agent_id"] is None
