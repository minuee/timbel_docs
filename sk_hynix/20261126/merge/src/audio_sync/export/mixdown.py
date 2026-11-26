from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import AlignedTrackArtifact, MixArtifact


def _volume_filter(track: AlignedTrackArtifact, index: int) -> tuple[str, str]:
    input_label = f"{index}:a"
    output_label = f"mixin{index}"
    if abs(track.gain_db) < 1e-9:
        return f"[{input_label}]anull[{output_label}]", output_label
    return f"[{input_label}]volume={track.gain_db:.3f}dB[{output_label}]", output_label


@dataclass(frozen=True)
class ListeningMixPlan:
    command: tuple[str, ...]
    filter_complex: str
    output_path: Path


def build_listening_mix_plan(
    tracks: tuple[AlignedTrackArtifact, ...],
    mix_artifact: MixArtifact,
    sample_rate_hz: int = 48_000,
    channels: int = 1,
) -> ListeningMixPlan:
    if not tracks:
        raise ValueError("at least one aligned track is required to build a mix")

    command: list[str] = ["ffmpeg", "-y"]
    filter_parts: list[str] = []
    mix_inputs: list[str] = []

    for index, track in enumerate(tracks):
        command.extend(["-i", track.aligned_path.as_posix()])
        filter_part, mix_label = _volume_filter(track, index)
        filter_parts.append(filter_part)
        mix_inputs.append(f"[{mix_label}]")

    mix_stage = (
        f"{''.join(mix_inputs)}amix=inputs={len(tracks)}:normalize=0:dropout_transition=0,"
        f"alimiter=limit=0.95[mix]"
    )
    filter_parts.append(mix_stage)
    filter_complex = ";".join(filter_parts)

    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[mix]",
            "-ar",
            str(sample_rate_hz),
            "-ac",
            str(channels),
            "-c:a",
            mix_artifact.codec,
            mix_artifact.output_path.as_posix(),
        ]
    )
    return ListeningMixPlan(
        command=tuple(command),
        filter_complex=filter_complex,
        output_path=mix_artifact.output_path,
    )

