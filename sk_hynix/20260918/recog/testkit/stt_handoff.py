"""STT handoff recommendation scaffold for manifest validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SttHandoffCase:
    case_id: str
    recommended_input: str
    conditions: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    notes: str


def build_stt_handoff_cases() -> tuple[SttHandoffCase, ...]:
    return (
        SttHandoffCase(
            case_id="tracks_preferred",
            recommended_input="tracks",
            conditions=(
                "alignment_confidence_high",
                "per_track_snr_acceptable",
                "multi_speaker_overlap_present",
            ),
            acceptance_criteria=("AC5", "AC6"),
            notes="Default STT-first path when aligned tracks preserve speaker clarity.",
        ),
        SttHandoffCase(
            case_id="mixdown_fallback",
            recommended_input="mixdown",
            conditions=(
                "track_count_low",
                "single_dominant_speaker",
                "consumer_requires_single_file",
            ),
            acceptance_criteria=("AC4", "AC5"),
            notes="Fallback path when downstream expects a single listening-friendly artifact.",
        ),
        SttHandoffCase(
            case_id="degraded_alignment_review",
            recommended_input="tracks",
            conditions=("alignment_confidence_degraded", "manual_review_required"),
            acceptance_criteria=("AC5", "AC6", "AC9"),
            notes="Manifest should keep tracks recommendation but mark degraded quality for review.",
        ),
    )

