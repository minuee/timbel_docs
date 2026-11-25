"""Manual listening rubric scaffold for AC7 review."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RubricCriterion:
    name: str
    min_score: float
    notes: str


def build_listening_rubric() -> tuple[RubricCriterion, ...]:
    return (
        RubricCriterion("howling_free", 4.5, "No howling, flanging, or metallic resonance."),
        RubricCriterion("overlap_smear_free", 4.5, "Speech overlap should remain intelligible without smear."),
        RubricCriterion("loudness_consistency", 4.0, "Participant loudness should feel room-mic consistent."),
        RubricCriterion("naturalness", 4.0, "Overall listening experience should sound natural."),
        RubricCriterion("stt_clarity", 4.0, "Speech should be clear enough for downstream transcription."),
    )

