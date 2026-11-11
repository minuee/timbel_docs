"""Mixed-format ingestion and failure-path scenario scaffolding."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestionCase:
    case_id: str
    file_name: str
    media_type: str
    expected_outcome: str
    acceptance_criteria: tuple[str, ...]
    notes: str


def build_ingestion_matrix() -> tuple[IngestionCase, ...]:
    return (
        IngestionCase(
            case_id="wav-happy-path",
            file_name="participant-1.wav",
            media_type="audio/wav",
            expected_outcome="canonicalize",
            acceptance_criteria=("AC2", "AC3"),
            notes="Reference PCM path used by the synthetic generator.",
        ),
        IngestionCase(
            case_id="m4a-happy-path",
            file_name="participant-2.m4a",
            media_type="audio/mp4",
            expected_outcome="canonicalize",
            acceptance_criteria=("AC2",),
            notes="iOS-style recording container expected to normalize into the canonical master.",
        ),
        IngestionCase(
            case_id="flac-happy-path",
            file_name="participant-3.flac",
            media_type="audio/flac",
            expected_outcome="canonicalize",
            acceptance_criteria=("AC2",),
            notes="Lossless Android/desktop ingestion path for mixed-format sessions.",
        ),
        IngestionCase(
            case_id="corrupt-wav",
            file_name="corrupt-track.wav",
            media_type="audio/wav",
            expected_outcome="reject_corrupt",
            acceptance_criteria=("AC9",),
            notes="Should fail before DSP with a file-level corruption reason.",
        ),
        IngestionCase(
            case_id="unsupported-text",
            file_name="unsupported-track.txt",
            media_type="text/plain",
            expected_outcome="reject_unsupported",
            acceptance_criteria=("AC9",),
            notes="Non-audio payload must be rejected with unsupported-format classification.",
        ),
    )

