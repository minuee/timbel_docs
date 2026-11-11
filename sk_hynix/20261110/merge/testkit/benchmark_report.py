"""Example benchmark verdict report scaffold for AC6 evidence capture."""

from __future__ import annotations

from testkit.benchmark import AlignmentBenchmarkResult


def build_benchmark_report_examples() -> dict:
    examples = [
        AlignmentBenchmarkResult(
            sample_count=3,
            offset_p50_ms=4.0,
            offset_p95_ms=4.0,
            offset_max_ms=4.0,
            drift_max_abs_ppm=1.0,
            verdict="pass",
        ),
        AlignmentBenchmarkResult(
            sample_count=3,
            offset_p50_ms=15.0,
            offset_p95_ms=15.0,
            offset_max_ms=15.0,
            drift_max_abs_ppm=1.0,
            verdict="degraded",
        ),
        AlignmentBenchmarkResult(
            sample_count=3,
            offset_p50_ms=35.0,
            offset_p95_ms=35.0,
            offset_max_ms=35.0,
            drift_max_abs_ppm=1.0,
            verdict="fail",
        ),
    ]
    return {
        "target_p95_ms": 10.0,
        "degraded_p95_ms": 20.0,
        "examples": [example.__dict__ for example in examples],
    }

