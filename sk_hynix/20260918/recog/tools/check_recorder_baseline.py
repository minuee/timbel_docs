#!/usr/bin/env python3
"""Validate a recorded audio file against the research baseline.

Usage:
  python3 tools/check_recorder_baseline.py path/to/file.wav
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from recog.audio import audio_metadata, ffprobe  # noqa: E402

REQUIRED_CONTAINER = "wav"
REQUIRED_CODEC = "pcm_s16le"
REQUIRED_SAMPLE_RATE = 48_000
REQUIRED_CHANNELS = 1


def detect_container(path: Path) -> str:
    return path.suffix.lower().lstrip(".") or "unknown"


def validate_file(path: Path) -> dict:
    metadata = audio_metadata(path)
    probe = ffprobe(path)
    audio_stream = next(
        item for item in probe.get("streams", []) if item.get("codec_type") == "audio"
    )

    container = detect_container(path)
    codec = audio_stream.get("codec_name", "unknown")
    sample_rate = int(float(audio_stream.get("sample_rate", 0) or 0))
    channels = int(audio_stream.get("channels", 0) or 0)

    violations: list[str] = []
    if container != REQUIRED_CONTAINER:
        violations.append(f"container={container} expected={REQUIRED_CONTAINER}")
    if codec != REQUIRED_CODEC:
        violations.append(f"codec={codec} expected={REQUIRED_CODEC}")
    if sample_rate != REQUIRED_SAMPLE_RATE:
        violations.append(f"sample_rate={sample_rate} expected={REQUIRED_SAMPLE_RATE}")
    if channels != REQUIRED_CHANNELS:
        violations.append(f"channels={channels} expected={REQUIRED_CHANNELS}")

    return {
        "path": str(path),
        "baseline_valid": not violations,
        "container": container,
        "codec": codec,
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "duration_seconds": metadata["duration_seconds"],
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate recorder output against the research baseline")
    parser.add_argument("audio_file", help="Path to a recorded WAV file")
    args = parser.parse_args(argv)

    result = validate_file(Path(args.audio_file))
    print(json.dumps(result, indent=2))
    return 0 if result["baseline_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
