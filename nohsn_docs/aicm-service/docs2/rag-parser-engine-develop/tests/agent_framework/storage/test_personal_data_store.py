"""PersonalDataStore 테스트 — mock DB 로 4 케이스 검증."""

from __future__ import annotations

import asyncio
from datetime import date

from src.agent_framework.storage.personal_data_store import PersonalDataStore


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _MockMappings:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def all(self) -> list[dict]:
        return list(self._rows)


class _MockResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self) -> _MockMappings:
        return _MockMappings(self._rows)


class _MockSession:
    """execute(text, params) 호출 → 미리 큐된 결과 반환."""

    def __init__(self, queue: list[list[dict]]):
        self._queue = list(queue)
        self.calls: list[tuple[str, dict]] = []

    def execute(self, sql, params=None):
        # sql 은 sqlalchemy TextClause — text 비교용으로 .text 속성 사용
        sql_text = getattr(sql, "text", str(sql))
        self.calls.append((sql_text, dict(params or {})))
        if not self._queue:
            return _MockResult([])
        return _MockResult(self._queue.pop(0))


def test_get_schedules_in_period_returns_dicts():
    rows = [
        {"id": "s1", "scheduled_at": "2026-03-01 14:00", "title": "회의", "category": "회의", "metadata": {}},
        {"id": "s2", "scheduled_at": "2026-03-05 09:00", "title": "병원", "category": "병원", "metadata": {}},
    ]
    db = _MockSession([rows])
    store = PersonalDataStore(db)
    out = _run(store.get_schedules_in_period(
        "00000000-0000-0000-0000-000000000099",
        date(2026, 3, 1),
        date(2026, 3, 31),
    ))
    assert len(out) == 2
    assert out[0]["title"] == "회의"
    # SQL 에 user_schedules 포함, params 가 정확히 전달
    assert "user_schedules" in db.calls[0][0]
    assert db.calls[0][1]["s"] == date(2026, 3, 1)
    assert db.calls[0][1]["e"] == date(2026, 3, 31)


def test_get_expenses_in_period_returns_dicts():
    rows = [
        {"id": "e1", "date": date(2026, 3, 1), "category": "식비",
         "amount_krw": 15000, "description": "점심", "payment_method": "카드"},
    ]
    db = _MockSession([rows])
    store = PersonalDataStore(db)
    out = _run(store.get_expenses_in_period(
        "00000000-0000-0000-0000-000000000099",
        date(2026, 3, 1),
        date(2026, 3, 31),
    ))
    assert len(out) == 1
    assert out[0]["category"] == "식비"
    assert "expense_ledger" in db.calls[0][0]


def test_get_health_logs_in_period_returns_dicts():
    rows = [
        {"id": "h1", "date": date(2026, 3, 1), "kind": "exercise",
         "value_text": "30분 조깅", "value_numeric": 30, "metadata": {}},
        {"id": "h2", "date": date(2026, 3, 2), "kind": "sleep",
         "value_text": "7시간", "value_numeric": 7, "metadata": {}},
    ]
    db = _MockSession([rows])
    store = PersonalDataStore(db)
    out = _run(store.get_health_logs_in_period(
        "00000000-0000-0000-0000-000000000099",
        date(2026, 3, 1),
        date(2026, 3, 31),
    ))
    assert len(out) == 2
    assert out[0]["kind"] == "exercise"
    assert "health_log" in db.calls[0][0]


def test_expense_summary_by_category_aggregates():
    rows = [
        {"category": "주거", "cnt": 1, "total": 450000},
        {"category": "식비", "cnt": 3, "total": 55000},
        {"category": "교통", "cnt": 2, "total": 7000},
    ]
    db = _MockSession([rows])
    store = PersonalDataStore(db)
    out = _run(store.expense_summary_by_category(
        "00000000-0000-0000-0000-000000000099",
        date(2026, 3, 1),
        date(2026, 3, 31),
    ))
    assert out["주거"] == {"count": 1, "total_krw": 450000}
    assert out["식비"] == {"count": 3, "total_krw": 55000}
    assert out["교통"]["total_krw"] == 7000


def test_schedule_summary_by_category_count():
    rows = [
        {"category": "회의", "cnt": 5},
        {"category": "운동", "cnt": 3},
    ]
    db = _MockSession([rows])
    store = PersonalDataStore(db)
    out = _run(store.schedule_summary_by_category(
        "00000000-0000-0000-0000-000000000099",
        date(2026, 3, 1),
        date(2026, 3, 31),
    ))
    assert out == {"회의": 5, "운동": 3}


def test_health_summary_by_kind_count():
    rows = [
        {"kind": "exercise", "cnt": 4},
        {"kind": "sleep", "cnt": 7},
    ]
    db = _MockSession([rows])
    store = PersonalDataStore(db)
    out = _run(store.health_summary_by_kind(
        "00000000-0000-0000-0000-000000000099",
        date(2026, 3, 1),
        date(2026, 3, 31),
    ))
    assert out == {"exercise": 4, "sleep": 7}
