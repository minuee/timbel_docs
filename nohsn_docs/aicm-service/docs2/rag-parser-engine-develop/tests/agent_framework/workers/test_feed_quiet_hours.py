"""quiet_hours / cadence helper unit tests — 외부 의존 없음."""
from __future__ import annotations

from datetime import datetime, timezone

from src.agent_framework.scheduler.feed_quiet_hours import (
    cadence_enabled,
    cadence_param,
    in_quiet_hours,
)


def test_in_quiet_hours_no_config_returns_false():
    assert in_quiet_hours({}, datetime.now(timezone.utc)) is False
    assert in_quiet_hours(None, datetime.now(timezone.utc)) is False


def test_in_quiet_hours_simple_range_inside():
    prefs = {"quiet_hours": {"start": "13:00", "end": "14:00"}}
    # 13:30 KST = 04:30 UTC
    now = datetime(2026, 4, 28, 4, 30, tzinfo=timezone.utc)
    assert in_quiet_hours(prefs, now, "Asia/Seoul") is True


def test_in_quiet_hours_simple_range_outside():
    prefs = {"quiet_hours": {"start": "13:00", "end": "14:00"}}
    # 12:30 KST = 03:30 UTC
    now = datetime(2026, 4, 28, 3, 30, tzinfo=timezone.utc)
    assert in_quiet_hours(prefs, now, "Asia/Seoul") is False


def test_in_quiet_hours_overnight_range():
    prefs = {"quiet_hours": {"start": "22:00", "end": "07:00"}}
    # 23:00 KST = 14:00 UTC
    night = datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(prefs, night, "Asia/Seoul") is True
    # 06:00 KST = 21:00 UTC (전날)
    early = datetime(2026, 4, 28, 21, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(prefs, early, "Asia/Seoul") is True
    # 09:00 KST = 00:00 UTC
    morning = datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(prefs, morning, "Asia/Seoul") is False


def test_cadence_enabled_default_true():
    assert cadence_enabled({}, "daily_briefing", default=True) is True
    assert cadence_enabled(None, "daily_briefing", default=True) is True


def test_cadence_enabled_false_explicit():
    prefs = {"feed_cadence": {"daily_briefing": {"enabled": False}}}
    assert cadence_enabled(prefs, "daily_briefing") is False


def test_cadence_enabled_other_kind_default():
    prefs = {"feed_cadence": {"daily_briefing": {"enabled": False}}}
    # 다른 kind 는 default 적용.
    assert cadence_enabled(prefs, "schedule_alert", default=True) is True


def test_cadence_param_lookup():
    prefs = {
        "feed_cadence": {"stock_monitor": {"enabled": True, "min_change_pct": 1.5}}
    }
    assert cadence_param(prefs, "stock_monitor", "min_change_pct") == 1.5
    assert cadence_param(prefs, "stock_monitor", "missing", default=42) == 42
    assert cadence_param(prefs, "missing_kind", "x", default="z") == "z"
