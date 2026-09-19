from __future__ import annotations

from pathlib import Path
from typing import Mapping, Any


DEFAULT_WORKING_SAMPLE_RATE = 48_000
DEFAULT_STT_SAMPLE_RATE = 16_000
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_FORMAT = "s16"


def build_canonicalize_command(
    input_path: str | Path,
    output_path: str | Path,
    *,
    sample_rate_hz: int = DEFAULT_WORKING_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_format: str = DEFAULT_SAMPLE_FORMAT,
) -> tuple[str, ...]:
    return (
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate_hz),
        "-sample_fmt",
        sample_format,
        str(output_path),
    )


def build_stt_export_command(
    input_path: str | Path,
    output_path: str | Path,
    *,
    sample_rate_hz: int = DEFAULT_STT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_format: str = DEFAULT_SAMPLE_FORMAT,
) -> tuple[str, ...]:
    return build_canonicalize_command(
        input_path,
        output_path,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        sample_format=sample_format,
    )


def summarize_canonical_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sample_rate": int(float(metadata.get("sample_rate", 0))),
        "channels": int(metadata.get("channels", 0)),
        "codec_name": metadata.get("codec_name", "unknown"),
        "duration_seconds": float(metadata.get("duration_seconds", 0.0)),
        "bit_rate": int(float(metadata.get("bit_rate", 0))),
    }
