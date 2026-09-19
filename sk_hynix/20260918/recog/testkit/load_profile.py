"""Load-test scaffolding for the MVP limits described in the PRD/test spec."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageBudget:
    stage_name: str
    budget_minutes: int
    notes: str


@dataclass(frozen=True)
class LoadProfile:
    profile_id: str
    participant_count: int
    duration_minutes: int
    stages: tuple[StageBudget, ...]
    acceptance_criteria: tuple[str, ...]
    retry_cases: tuple[str, ...]


def build_default_load_profile() -> LoadProfile:
    return LoadProfile(
        profile_id="mvp-5p-60m",
        participant_count=5,
        duration_minutes=60,
        stages=(
            StageBudget("upload", 5, "Signed upload + metadata persistence for five devices."),
            StageBudget("normalize", 12, "Canonicalization queue fan-in across mixed sample rates."),
            StageBudget("align", 15, "Coarse/fine alignment plus drift estimation."),
            StageBudget("mix", 10, "Listening mixdown and loudness normalization."),
            StageBudget("qa_export", 8, "Manifest emission, checksums, and artifact publication."),
        ),
        acceptance_criteria=("AC1", "AC6", "AC7"),
        retry_cases=(
            "worker_crash_during_align",
            "storage_refetch_after_restart",
            "single_track_low_snr",
        ),
    )

