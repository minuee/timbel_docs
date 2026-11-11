#!/usr/bin/env python3
"""Run a simple benchmark for the sync beep detector against synthetic cases."""

from __future__ import annotations

from array import array
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audio_sync.dsp import (
    DEFAULT_SYNC_BEEP_SPEC,
    build_sync_beep_samples,
    detect_beep_offset_from_arrays,
)


def build_case(prefix_samples: int) -> array:
    tone = build_sync_beep_samples(DEFAULT_SYNC_BEEP_SPEC)
    samples = array("h")
    samples.extend([0] * prefix_samples)
    samples.extend(tone)
    samples.extend([0] * 256)
    return samples


def main() -> int:
    sample_rate = DEFAULT_SYNC_BEEP_SPEC.sample_rate_hz
    cases = [
        ("expected_window", 240, 240 / sample_rate, 0.05, 0.2),
        ("fallback_window", len(build_sync_beep_samples()) + 480, 0.0, 0.001, 0.2),
        ("silence", None, 0.0, 0.01, 0.02),
    ]
    report: dict[str, object] = {
        "spec": {
            "sample_rate_hz": DEFAULT_SYNC_BEEP_SPEC.sample_rate_hz,
            "duration_ms": DEFAULT_SYNC_BEEP_SPEC.duration_ms,
            "frequency_hz": DEFAULT_SYNC_BEEP_SPEC.frequency_hz,
            "fade_ms": DEFAULT_SYNC_BEEP_SPEC.fade_ms,
            "peak_dbfs": DEFAULT_SYNC_BEEP_SPEC.peak_dbfs,
        },
        "cases": [],
    }

    for name, prefix_samples, expected_seconds, expected_window_seconds, fallback_window_seconds in cases:
        if prefix_samples is None:
            samples = array("h", [0] * 2_000)
        else:
            samples = build_case(prefix_samples)
        result = detect_beep_offset_from_arrays(
            samples,
            sample_rate=sample_rate,
            expected_offset_seconds=expected_seconds,
            expected_window_seconds=expected_window_seconds,
            fallback_window_seconds=fallback_window_seconds,
        )
        report["cases"].append(
            {
                "name": name,
                "detected": result.detected,
                "offset_samples": result.offset_samples,
                "offset_seconds": result.offset_seconds,
                "confidence": result.confidence,
                "search_mode": result.search_mode,
            }
        )

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
