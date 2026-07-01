"""Conversation reliability modules — Phase 2 (KMS-Plus).

7 모듈 (대화 신뢰성 §C 의 10 키 일부):
 - voice_friendly_filter — TTS 친화 변환 (마크다운 strip, 숫자 한글화)
 - uncertainty_filter    — confidence < threshold 시 prepend "확실하지 않습니다..."
 - fallback_composer     — 외부 호출 실패 시 대안 합성
 - ambiguity_resolver    — 다중 의도 시 짧은 확인 질문
 - self_check            — 답변 후 자기 검증 (small LLM)
 - progress_emitter      — 처리 시간 임계 기반 progress 메시지 생성
 - ack_generator         — 즉시 ack (E2B @7020 wrapper, 300ms timeout, static fallback)

각자 독립 모듈. engine.turn() 의 hook 위치에서 호출.
"""

from src.agent_framework.conversation.ack_generator import AckGenerator
from src.agent_framework.conversation.ambiguity_resolver import AmbiguityResolver
from src.agent_framework.conversation.fallback_composer import FallbackComposer
from src.agent_framework.conversation.progress_emitter import ProgressEmitter
from src.agent_framework.conversation.self_check import SelfCheck
from src.agent_framework.conversation.uncertainty_filter import UncertaintyFilter
from src.agent_framework.conversation.voice_friendly_filter import (
    humanize_numbers,
    strip_markdown,
    to_voice_friendly,
)

__all__ = [
    "AckGenerator",
    "AmbiguityResolver",
    "FallbackComposer",
    "ProgressEmitter",
    "SelfCheck",
    "UncertaintyFilter",
    "humanize_numbers",
    "strip_markdown",
    "to_voice_friendly",
]
