"""Option beta stage 6 — append_time vLLM prefix cache 회복 검증."""
from __future__ import annotations

import datetime
import re

import pytest

from src.agent_framework.runtime.time_context import (
    _weekday_kr,
    append_time,
    prepend_time,
)


def test_append_time_keeps_prefix_stable():
    """append_time 은 base 문자열을 변경하지 않고 *끝* 에만 시간 추가."""
    base = "## 역할\n친절한 보조"
    out = append_time(base)
    # base 그대로 시작 — vLLM prefix cache 가 base 를 재사용 가능
    assert out.startswith(base)
    # 시간 컨텍스트 마커가 base 이후에 위치
    assert "시간 컨텍스트" in out
    assert out.index("시간 컨텍스트") > len(base)


def test_append_time_contains_datetime_string():
    """append_time 결과에 날짜 + 시간 + KST 포함."""
    out = append_time("base")
    assert re.search(r"\d{4}-\d{2}-\d{2}", out)
    assert "KST" in out


def test_append_time_locale_en():
    """locale='en' 이면 영문 헤더 + ISO 시각."""
    out = append_time("base", locale="en")
    assert out.startswith("base")
    assert "time context" in out
    # ISO 형태 날짜 포함
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", out)


def test_append_time_locale_ko_default():
    """locale 파라미터 없을 때 한국어 헤더 기본."""
    out = append_time("x")
    assert "시간 컨텍스트" in out


def test_append_time_empty_base():
    """빈 문자열에도 동작 — suffix 만 반환."""
    out = append_time("")
    assert "시간 컨텍스트" in out
    assert out.startswith("\n\n")


def test_prepend_time_deprecation_warning():
    """prepend_time 호출 시 DeprecationWarning + 'prefix cache' 메시지 포함."""
    base = "## 역할"
    with pytest.warns(DeprecationWarning, match="prefix cache"):
        out = prepend_time(base)
    # prepend 이므로 끝에 base 가 있어야 함
    assert out.endswith(base)
    assert "현재 시각:" in out


def test_prepend_time_deprecation_warning_preserves_original():
    """DeprecationWarning 이 발생해도 반환값 호환성 유지."""
    orig = "너는 친절한 AI 다."
    with pytest.warns(DeprecationWarning):
        combined = prepend_time(orig)
    assert combined.endswith(orig)
    assert len(combined) > len(orig)


def test_weekday_kr_wednesday():
    """2026-05-06 = 수 (수요일 단일 글자)."""
    dt = datetime.datetime(2026, 5, 6)
    assert _weekday_kr(dt) == "수"


def test_weekday_kr_all_days():
    """월~일 7일 모두 올바른 한글 요일 단일 글자 반환."""
    # 2026-05-04 월요일 기준
    expected = ["월", "화", "수", "목", "금", "토", "일"]
    base_monday = datetime.datetime(2026, 5, 4)
    for i, label in enumerate(expected):
        dt = base_monday + datetime.timedelta(days=i)
        assert _weekday_kr(dt) == label, f"day {i} expected {label}"


def test_append_time_does_not_prepend():
    """append_time 이 prefix 를 변경하지 않음 — vLLM stable prefix 핵심 요구사항."""
    stable_prefix = "STABLE_PREFIX_MARKER"
    out = append_time(stable_prefix + " body")
    # 첫 글자가 stable_prefix 로 시작
    assert out[: len(stable_prefix)] == stable_prefix
    # 시간 정보는 suffix (stable_prefix 가 등장하는 위치보다 뒤)
    time_idx = out.index("현재 시각:")
    assert time_idx > len(stable_prefix)
