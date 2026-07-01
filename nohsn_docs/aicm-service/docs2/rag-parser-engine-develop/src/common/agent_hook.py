"""Phase 1 T1.3 — Agent classification hook interface.

KMS layer (documents/blocks/sections) 가 agent layer (activation/classification)
에 *알림* 을 보내는 표준 인터페이스. Lucas-KMS 단독 배포 시 hook 미등록
상태 → 모든 호출이 silent no-op.

설계 원칙:
- KMS → Agent 방향의 *push* 만 허용 (역방향 import 금지)
- hook 등록은 agent framework 의 startup 시점에 명시적으로 수행
- 미등록 환경 (KMS-only) 에서 호출자는 None 체크 후 graceful pass

사용 예:
    from src.common.agent_hook import get_classification_hook

    hook = get_classification_hook()
    if hook is not None:
        hook.apply_classification(doc_id, user_id=user_id, action="add")
    # else: KMS-only mode — no-op
"""
from __future__ import annotations

from typing import Protocol


class AgentClassificationHook(Protocol):
    """Agent 분류 활성화/거부 hook 의 표준 인터페이스.

    실제 구현은 lucas-agent 패키지 (현재는 src/agent_framework/activation/)
    에 위치. KMS 패키지는 본 Protocol 만 import.
    """

    def apply_classification(
        self,
        artifact_type: str,
        artifact_id: str,
        *,
        user_id: str,
        action: str = "add",
    ) -> None:
        """분류 결과 활성화 (KMS doc → agent 가 인지)."""
        ...

    def reject_classification(
        self,
        artifact_type: str,
        artifact_id: str,
        *,
        user_id: str,
        reason: str = "",
    ) -> None:
        """분류 결과 거부."""
        ...


_hook: AgentClassificationHook | None = None


def register_classification_hook(hook: AgentClassificationHook) -> None:
    """Agent framework startup 시 호출. KMS-only 배포에서는 호출 안 됨."""
    global _hook
    _hook = hook


def get_classification_hook() -> AgentClassificationHook | None:
    """현재 등록된 hook 반환. 미등록 시 None — caller 가 graceful pass.

    Lucas-KMS 단독 배포 → 항상 None.
    Locus 통합 배포 → agent framework 가 startup 시 register 후 사용 가능.
    """
    return _hook
