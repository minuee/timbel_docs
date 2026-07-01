"""Activation state machine — spec §1.4 전이 매트릭스."""
from __future__ import annotations
from enum import Enum


class ActivationState(str, Enum):
    draft = "draft"
    processing = "processing"
    pending_review = "pending_review"
    active = "active"
    archived = "archived"
    rejected = "rejected"
    failed = "failed"


_ALLOWED: set[tuple[ActivationState, ActivationState]] = {
    (ActivationState.draft, ActivationState.processing),
    (ActivationState.draft, ActivationState.failed),
    (ActivationState.processing, ActivationState.pending_review),
    (ActivationState.processing, ActivationState.active),
    (ActivationState.processing, ActivationState.failed),
    (ActivationState.pending_review, ActivationState.active),
    (ActivationState.pending_review, ActivationState.rejected),
    (ActivationState.pending_review, ActivationState.processing),
    (ActivationState.active, ActivationState.archived),
    (ActivationState.archived, ActivationState.active),
    (ActivationState.rejected, ActivationState.processing),
    (ActivationState.failed, ActivationState.processing),
}


class InvalidTransition(ValueError):
    def __init__(self, src: ActivationState, dst: ActivationState):
        super().__init__(f"invalid transition {src.value} → {dst.value}")
        self.src, self.dst = src, dst


def can_transition(src: ActivationState, dst: ActivationState) -> bool:
    if src == dst:
        return True
    return (src, dst) in _ALLOWED


def assert_transition(src: ActivationState, dst: ActivationState) -> None:
    if not can_transition(src, dst):
        raise InvalidTransition(src, dst)
