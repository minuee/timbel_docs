#!/usr/bin/env python3
"""Generate the canonical sync beep WAV asset."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audio_sync.dsp import DEFAULT_SYNC_BEEP_SPEC, SyncBeepSpec, write_sync_beep_wav


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the canonical audio sync beep WAV asset.")
    parser.add_argument(
        "output_path",
        nargs="?",
        default="artifacts/sync-beep.wav",
        help="Path where the generated WAV file should be written.",
    )
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SYNC_BEEP_SPEC.sample_rate_hz)
    parser.add_argument("--duration-ms", type=int, default=DEFAULT_SYNC_BEEP_SPEC.duration_ms)
    parser.add_argument("--frequency-hz", type=int, default=DEFAULT_SYNC_BEEP_SPEC.frequency_hz)
    parser.add_argument("--fade-ms", type=int, default=DEFAULT_SYNC_BEEP_SPEC.fade_ms)
    parser.add_argument("--peak-dbfs", type=float, default=DEFAULT_SYNC_BEEP_SPEC.peak_dbfs)
    args = parser.parse_args()

    spec = SyncBeepSpec(
        sample_rate_hz=args.sample_rate,
        duration_ms=args.duration_ms,
        frequency_hz=args.frequency_hz,
        fade_ms=args.fade_ms,
        peak_dbfs=args.peak_dbfs,
    )
    output = write_sync_beep_wav(args.output_path, spec)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
