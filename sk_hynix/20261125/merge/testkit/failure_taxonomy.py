"""Failure taxonomy scaffold for file-level and pipeline-level rejection paths."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FailureReason:
    code: str
    scope: str
    retryable: bool
    acceptance_criteria: tuple[str, ...]
    notes: str


def build_failure_taxonomy() -> tuple[FailureReason, ...]:
    return (
        FailureReason(
            code="unsupported_format",
            scope="file",
            retryable=False,
            acceptance_criteria=("AC9",),
            notes="Non-audio or unsupported container rejected before DSP.",
        ),
        FailureReason(
            code="corrupt_audio_payload",
            scope="file",
            retryable=False,
            acceptance_criteria=("AC9",),
            notes="Unreadable payload rejected during format sniffing or decode probe.",
        ),
        FailureReason(
            code="low_signal_alignment_confidence",
            scope="file",
            retryable=True,
            acceptance_criteria=("AC6", "AC9"),
            notes="Track may need re-anchor or degraded-quality reporting rather than hard failure.",
        ),
        FailureReason(
            code="worker_crash_during_align",
            scope="session",
            retryable=True,
            acceptance_criteria=("AC1",),
            notes="Queue restart path should resume from stage markers.",
        ),
        FailureReason(
            code="artifact_publish_mismatch",
            scope="session",
            retryable=True,
            acceptance_criteria=("AC3", "AC4", "AC5"),
            notes="Manifest/artifact mismatch should trigger export retry and evidence logging.",
        ),
    )

