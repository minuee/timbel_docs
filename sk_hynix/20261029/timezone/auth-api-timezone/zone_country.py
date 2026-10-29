"""X-Device-Timezone 헤더 값으로 국가 코드(ISO 3166 두 글자)를 찾는다.

표준 라이브러리만 쓴다. 대응표는 같은 폴더의 zone.tab (tzdata 2026e).

    from zone_country import country_from_timezone
    country_from_timezone("Asia/Seoul")           # "KR"
    country_from_timezone("America/Chicago")      # "US"
    country_from_timezone("UTC")                  # None -> 기본 정책 적용
"""

from __future__ import annotations

import os
import re
from pathlib import Path

HEADER_NAME = "X-Device-Timezone"

#: 대응표 위치. 환경 변수로 바꿀 수 있다.
ZONE_TAB_PATH = Path(os.environ.get("ZONE_TAB_PATH", Path(__file__).with_name("zone.tab")))

#: zone.tab 에 없는 옛 이름 -> 현재 이름. 오래된 기기·브라우저가 보내는 값들.
ALIASES = {
    "US/Eastern": "America/New_York",
    "US/Central": "America/Chicago",
    "US/Mountain": "America/Denver",
    "US/Arizona": "America/Phoenix",
    "US/Pacific": "America/Los_Angeles",
    "US/Alaska": "America/Anchorage",
    "US/Hawaii": "Pacific/Honolulu",
    "America/Indianapolis": "America/Indiana/Indianapolis",
    "America/Louisville": "America/Kentucky/Louisville",
    "ROK": "Asia/Seoul",
    "Japan": "Asia/Tokyo",
    "PRC": "Asia/Shanghai",
    "Asia/Chongqing": "Asia/Shanghai",
    "Asia/Harbin": "Asia/Shanghai",
    "Asia/Calcutta": "Asia/Kolkata",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Rangoon": "Asia/Yangon",
    "Europe/Kiev": "Europe/Kyiv",
}

#: 헤더 값으로 허용하는 형태. 그 밖의 값은 무시한다.
_VALID = re.compile(r"^[A-Za-z0-9_+\-/]{1,64}$")


def _load(path: Path) -> dict[str, str]:
    table: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) >= 3:
                table[cols[2]] = cols[0]
    return table


ZONE_COUNTRY = _load(ZONE_TAB_PATH)


def country_from_timezone(value: str | None) -> str | None:
    """시간대 이름 -> 국가 코드. 모르는 값이면 None."""
    if not value:
        return None
    tz = value.strip()
    if not _VALID.match(tz):
        return None
    return ZONE_COUNTRY.get(tz) or ZONE_COUNTRY.get(ALIASES.get(tz, ""))
