"""공통 시간 컨텍스트 유틸 — Lucas-KMS / Lucas-Agent 양쪽이 import.

이전 위치: src/agent_framework/runtime/time_context.py (agent layer 전용 위치).
Phase 1 T1.1 에서 KMS / shared 양쪽이 사용 가능하도록 src/common/ 으로 이동.

타임존: Asia/Seoul (tenant 관례).

vLLM prefix cache 정책
-----------------------
- append_time() : 시간을 system prompt *끝* 에 붙임. 안정 prefix (템플릿 +
  도구 카탈로그) 가 매 호출 동일 → vLLM prefix cache hit 가능. **권장**.
- prepend_time() : DEPRECATED — 시간을 *앞* 에 박아 prefix cache miss 100%.
  호환성 위해 보존하지만 신규 호출자는 append_time 사용.
"""
from __future__ import annotations

import warnings
from datetime import datetime
from zoneinfo import ZoneInfo


_TZ = ZoneInfo("Asia/Seoul")
_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _weekday_kr(dt: datetime) -> str:
    return _WEEKDAYS[dt.weekday()]


def now_kst() -> datetime:
    """현재 Asia/Seoul datetime 반환 (공유 헬퍼)."""
    return datetime.now(_TZ)


def now_prefix() -> str:
    """'현재 시각: 2026-04-24 (금) 14:32 KST\\n' 같은 한 줄 프리픽스.

    LLM 이 상대 시간 ('내일', '다음주 월요일', '모레') 을 파싱할 수 있게
    사용. 매 호출마다 새로 생성 -> 최신 시각 보장.
    """
    now = now_kst()
    weekday = _weekday_kr(now)
    return (
        f"현재 시각: {now.strftime('%Y-%m-%d')} ({weekday}) "
        f"{now.strftime('%H:%M')} KST\n"
    )


def append_time(system: str, *, locale: str = "ko") -> str:
    """system prompt *끝* 에 현재 시각 추가. vLLM prefix cache 보호."""
    now = now_kst()
    if locale == "ko":
        weekday = _weekday_kr(now)
        suffix = (
            f"\n\n## 시간 컨텍스트 (caching 최적화 — prompt 끝)\n"
            f"현재 시각: {now.strftime('%Y-%m-%d')} ({weekday}) "
            f"{now.strftime('%H:%M')} KST"
        )
    else:
        suffix = (
            f"\n\n## time context (cache-optimized — prompt suffix)\n"
            f"now: {now.isoformat()}"
        )
    return system + suffix


def prepend_time(system: str, *, locale: str = "ko") -> str:  # noqa: ARG001
    """DEPRECATED — append_time 사용. prefix cache miss 유발.

    기존 system prompt *앞* 에 현재 시각을 붙임. 시각이 매 호출 바뀌므로
    vLLM prefix cache 가 system prompt 전체를 재디코딩해야 함 → latency 증가.

    호환성 위해 보존. 신규 호출자는 :func:`append_time` 으로 교체.
    """
    warnings.warn(
        "prepend_time causes vLLM prefix cache miss on every call; "
        "use append_time instead",
        DeprecationWarning,
        stacklevel=2,
    )
    now = now_kst()
    if locale == "ko":
        weekday = _weekday_kr(now)
        prefix = (
            f"현재 시각: {now.strftime('%Y-%m-%d')} ({weekday}) "
            f"{now.strftime('%H:%M')} KST\n"
        )
    else:
        prefix = f"## time context\nnow: {now.isoformat()}\n\n"
    return prefix + system
