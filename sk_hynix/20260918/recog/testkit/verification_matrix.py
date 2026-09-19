"""Scenario matrix for the MVP acceptance checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationScenario:
    scenario_id: str
    participant_count: int
    fixture_session_id: str
    acceptance_criteria: tuple[str, ...]
    verification_types: tuple[str, ...]
    notes: str


def build_verification_matrix() -> tuple[VerificationScenario, ...]:
    return (
        VerificationScenario(
            scenario_id="happy-path-p2",
            participant_count=2,
            fixture_session_id="synthetic-session-p2",
            acceptance_criteria=("AC1", "AC2", "AC3", "AC5"),
            verification_types=("integration", "artifact"),
            notes="Minimal aligned-track success path with mixed sample rates.",
        ),
        VerificationScenario(
            scenario_id="happy-path-p3",
            participant_count=3,
            fixture_session_id="synthetic-session-p3",
            acceptance_criteria=("AC1", "AC2", "AC3", "AC5", "AC6"),
            verification_types=("integration", "benchmark"),
            notes="Adds drift benchmark coverage on a medium session.",
        ),
        VerificationScenario(
            scenario_id="load-path-p5",
            participant_count=5,
            fixture_session_id="synthetic-session-p5",
            acceptance_criteria=("AC1", "AC2", "AC3", "AC5", "AC6", "AC7"),
            verification_types=("load", "benchmark", "manual"),
            notes="Stress session for 5 participants / 1-hour-equivalent orchestration paths.",
        ),
        VerificationScenario(
            scenario_id="corrupt-input",
            participant_count=3,
            fixture_session_id="synthetic-session-p3",
            acceptance_criteria=("AC9",),
            verification_types=("failure-path",),
            notes="Uses corrupt-track.wav to verify early rejection and file-level error reporting.",
        ),
        VerificationScenario(
            scenario_id="unsupported-input",
            participant_count=3,
            fixture_session_id="synthetic-session-p3",
            acceptance_criteria=("AC9",),
            verification_types=("failure-path",),
            notes="Uses unsupported-track.txt to verify unsupported-format handling.",
        ),
    )

