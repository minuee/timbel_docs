"""Benchmark helpers for synthetic alignment validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class TrackPrediction:
    participant_id: str
    predicted_offset_ms: float
    predicted_drift_ppm: float


@dataclass(frozen=True)
class AlignmentBenchmarkResult:
    sample_count: int
    offset_p50_ms: float
    offset_p95_ms: float
    offset_max_ms: float
    drift_max_abs_ppm: float
    verdict: str


def load_ground_truth(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_alignment(
    ground_truth: dict,
    predictions: list[TrackPrediction],
    *,
    target_p95_ms: float = 10.0,
    degraded_p95_ms: float = 20.0,
) -> AlignmentBenchmarkResult:
    by_participant = {track["participant_id"]: track for track in ground_truth["tracks"]}
    offset_errors_ms: list[float] = []
    drift_errors_ppm: list[float] = []

    for prediction in predictions:
        track = by_participant[prediction.participant_id]
        offset_errors_ms.append(abs(prediction.predicted_offset_ms - track["start_offset_ms"]))
        drift_errors_ppm.append(abs(prediction.predicted_drift_ppm - track["drift_ppm"]))

    if not offset_errors_ms:
        raise ValueError("predictions must not be empty")

    offset_errors_ms.sort()
    offset_p50_ms = _percentile(offset_errors_ms, 0.50)
    offset_p95_ms = _percentile(offset_errors_ms, 0.95)
    offset_max_ms = offset_errors_ms[-1]
    drift_max_abs_ppm = max(drift_errors_ppm)

    if offset_p95_ms <= target_p95_ms:
        verdict = "pass"
    elif offset_p95_ms <= degraded_p95_ms:
        verdict = "degraded"
    else:
        verdict = "fail"

    return AlignmentBenchmarkResult(
        sample_count=len(offset_errors_ms),
        offset_p50_ms=offset_p50_ms,
        offset_p95_ms=offset_p95_ms,
        offset_max_ms=offset_max_ms,
        drift_max_abs_ppm=drift_max_abs_ppm,
        verdict=verdict,
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if percentile <= 0:
        return values[0]
    if percentile >= 1:
        return values[-1]

    position = (len(values) - 1) * percentile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return values[lower_index]
    lower = values[lower_index]
    upper = values[upper_index]
    return lower + ((upper - lower) * (position - lower_index))

