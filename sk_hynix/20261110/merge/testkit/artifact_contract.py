"""Expected artifact contract for aligned tracks, mixdown, and manifest outputs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactExpectation:
    artifact_type: str
    required_fields: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    notes: str


def build_artifact_contract() -> tuple[ArtifactExpectation, ...]:
    return (
        ArtifactExpectation(
            artifact_type="aligned_tracks_bundle",
            required_fields=("sessionId", "trackCount", "canonicalFormat", "tracks"),
            acceptance_criteria=("AC3", "AC5"),
            notes="Primary STT-first artifact containing aligned per-track files and metadata.",
        ),
        ArtifactExpectation(
            artifact_type="mixdown",
            required_fields=("sessionId", "durationMs", "loudnessLufs", "path"),
            acceptance_criteria=("AC4", "AC7"),
            notes="Listening artifact with normalized loudness metadata.",
        ),
        ArtifactExpectation(
            artifact_type="manifest",
            required_fields=(
                "sessionId",
                "canonicalFormat",
                "recommendedSttInput",
                "alignmentConfidence",
                "trackCorrections",
                "qaSummary",
            ),
            acceptance_criteria=("AC5", "AC6"),
            notes="Downstream handoff document referencing tracks bundle and mixdown.",
        ),
    )

