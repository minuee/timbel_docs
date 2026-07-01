"""DEPRECATED — Phase 1 T1.1 (2026-05-19) 에서 src/common/time_utils.py 로 이동.

본 모듈은 호환 shim — 기존 import 들 (slot_filler, intent_classifier,
tool_calling_loop, utterance_classifier, response_generator, fallback_router,
plan_orchestrator) 가 계속 동작하도록 함수들을 re-export.

신규 코드는 `from src.common.time_utils import ...` 사용.
"""
from src.common.time_utils import (  # noqa: F401
    append_time,
    now_kst,
    now_prefix,
    prepend_time,
)
