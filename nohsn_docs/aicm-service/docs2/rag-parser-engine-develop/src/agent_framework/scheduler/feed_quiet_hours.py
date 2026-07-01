"""Quiet hours + cadence helpers for feed cron workers.

각 사용자의 ``accounts.preferences`` JSONB 에 들어있는 ``feed_cadence`` /
``quiet_hours`` 설정을 읽어, 워커가 INSERT 직전 호출하는 단순 헬퍼.

설계 원칙
---------
- 패턴 (cadence kind 별 enable/disable + 시간대 차단) — case enumeration X.
- 키 enum 박지 않음. backend 가 cadence dict 를 그대로 받아 kind 별로 lookup.
- 시간대 비교는 사용자 timezone 기준 (Asia/Seoul fallback). zoneinfo 표준 라이브러리.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — py3.8 이하 환경
    ZoneInfo = None  # type: ignore[assignment, misc]


def _resolve_tz(tz_name: str | None) -> Any:
    """timezone 이름 → tzinfo 객체. 잘못된 이름이면 UTC fallback."""
    if not tz_name:
        return timezone.utc
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def _parse_hhmm(s: str | None) -> time | None:
    """``"22:00"`` → ``time(22, 0)``. 잘못된 형식이면 None."""
    if not s or not isinstance(s, str):
        return None
    parts = s.split(":")
    if len(parts) != 2:
        return None
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return time(h, m)


def in_quiet_hours(
    account_prefs: dict[str, Any] | None,
    now: datetime,
    account_tz: str | None = None,
) -> bool:
    """현재 시각이 사용자 quiet hours 안에 있는지.

    quiet_hours = ``{"start": "22:00", "end": "07:00"}`` 형식.
    start <= end → 같은 날 구간 [start, end].
    start  > end → 자정 너머 구간 [start, 24:00) ∪ [00:00, end].

    설정 자체가 없거나 잘못된 형식이면 ``False`` (= 차단 안 함).
    """
    if not isinstance(account_prefs, dict):
        return False
    qh = account_prefs.get("quiet_hours")
    if not isinstance(qh, dict):
        return False
    start = _parse_hhmm(qh.get("start"))
    end = _parse_hhmm(qh.get("end"))
    if start is None or end is None:
        return False
    tz = _resolve_tz(account_tz or qh.get("timezone"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(tz).time()
    if start <= end:
        return start <= local < end
    # 자정 너머
    return local >= start or local < end


def cadence_enabled(
    account_prefs: dict[str, Any] | None,
    kind: str,
    *,
    default: bool = True,
) -> bool:
    """``feed_cadence[kind].enabled`` lookup. 키가 없으면 ``default``.

    ``account_prefs.feed_cadence`` 가 없으면 default. 사용자가 처음 가입한
    상태에서도 자연스러운 first-run 경험.
    """
    if not isinstance(account_prefs, dict):
        return default
    cadence = account_prefs.get("feed_cadence")
    if not isinstance(cadence, dict):
        return default
    entry = cadence.get(kind)
    if not isinstance(entry, dict):
        return default
    val = entry.get("enabled")
    if isinstance(val, bool):
        return val
    return default


def cadence_param(
    account_prefs: dict[str, Any] | None,
    kind: str,
    key: str,
    default: Any = None,
) -> Any:
    """``feed_cadence[kind][key]`` 가져오기. 일반 cadence 파라미터 (예: min_change_pct)."""
    if not isinstance(account_prefs, dict):
        return default
    cadence = account_prefs.get("feed_cadence")
    if not isinstance(cadence, dict):
        return default
    entry = cadence.get(kind)
    if not isinstance(entry, dict):
        return default
    return entry.get(key, default)
