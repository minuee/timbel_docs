"""Task 25-A — 시간 컨텍스트 주입 helper."""
from __future__ import annotations

import re
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

from src.agent_framework.runtime.time_context import now_prefix, prepend_time


def test_now_prefix_format():
    p = now_prefix()
    # 예: '현재 시각: 2026-04-24 (금) 14:32 KST\n'
    assert re.match(
        r"^현재 시각: \d{4}-\d{2}-\d{2} \([월화수목금토일]\) \d{2}:\d{2} KST\n$",
        p,
    )


def test_now_prefix_matches_seoul_time():
    """서울 타임존 기준 현재 날짜 포함."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    assert today in now_prefix()


def test_prepend_time_preserves_original():
    orig = "너는 친절한 AI 다."
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        combined = prepend_time(orig)
    assert combined.endswith(orig)
    assert "현재 시각:" in combined
    # 원본보다 길어짐
    assert len(combined) > len(orig)


def test_prepend_time_idempotent_behavior():
    """같은 함수 두 번 부르면 시각 두 번 박힘 (의도적 — 호출자가 한 번만 불러야)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        p = prepend_time(prepend_time("x"))
    assert p.count("현재 시각:") == 2
