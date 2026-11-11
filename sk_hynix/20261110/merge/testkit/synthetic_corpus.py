"""Synthetic corpus generation for the audio sync merge MVP test plan.

This module intentionally uses only the Python standard library so workers can
generate deterministic fixtures in the greenfield workspace before the service
runtime and dependency set are finalized.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random
import wave


DEFAULT_SEED = 20260407
DEFAULT_SAMPLE_RATE = 48_000
DEFAULT_PCM_PEAK = 32_767


@dataclass(frozen=True)
class TrackPlan:
    """Ground-truth settings for one participant recording."""

    participant_id: str
    start_offset_ms: int
    drift_ppm: float
    sample_rate_hz: int
    duration_s: float
    base_frequency_hz: float
    amplitude: float = 0.55
    noise_floor: float = 0.015


@dataclass(frozen=True)
class SessionPlan:
    """Synthetic session configuration."""

    session_id: str
    duration_s: float
    tracks: tuple[TrackPlan, ...]
    include_corrupt_input: bool = True
    include_unsupported_input: bool = True
    sample_rate_matrix: tuple[int, ...] = (16_000, 44_100, 48_000)


def build_default_session_plan(
    *,
    participants: int = 5,
    duration_s: float = 12.0,
    seed: int = DEFAULT_SEED,
    max_offset_ms: int = 4_000,
) -> SessionPlan:
    """Build a deterministic synthetic plan covering offset/drift/sample-rate variety."""

    if participants < 2:
        raise ValueError("participants must be at least 2")
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    if max_offset_ms < 0:
        raise ValueError("max_offset_ms must be non-negative")

    rng = random.Random(seed)
    sample_rates = (16_000, 44_100, 48_000)
    tracks: list[TrackPlan] = []

    for index in range(participants):
        offset = int(round(index * max_offset_ms / max(participants - 1, 1)))
        drift = round(rng.uniform(-85.0, 85.0), 3)
        sample_rate = sample_rates[index % len(sample_rates)]
        base_frequency = 175.0 + (index * 41.0)
        amplitude = round(0.48 + (index * 0.07), 3)
        tracks.append(
            TrackPlan(
                participant_id=f"participant-{index + 1}",
                start_offset_ms=offset,
                drift_ppm=drift,
                sample_rate_hz=sample_rate,
                duration_s=duration_s,
                base_frequency_hz=base_frequency,
                amplitude=min(amplitude, 0.82),
                noise_floor=round(0.01 + (index * 0.002), 4),
            )
        )

    return SessionPlan(
        session_id=f"synthetic-session-p{participants}",
        duration_s=duration_s,
        tracks=tuple(tracks),
    )


def build_integration_matrix() -> list[SessionPlan]:
    """Coverage-focused matrix for 2/3/5 participant sessions."""

    return [
        build_default_session_plan(participants=2, duration_s=6.0, max_offset_ms=750),
        build_default_session_plan(participants=3, duration_s=8.0, max_offset_ms=1_500),
        build_default_session_plan(participants=5, duration_s=12.0, max_offset_ms=4_000),
    ]


def generate_session_fixture(output_root: str | Path, plan: SessionPlan) -> Path:
    """Generate WAV fixtures and ground-truth metadata for one session plan."""

    session_dir = Path(output_root) / plan.session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    max_offset_ms = max(track.start_offset_ms for track in plan.tracks)
    total_duration_s = plan.duration_s + (max_offset_ms / 1_000.0)
    generated_files: list[dict[str, object]] = []

    for track in plan.tracks:
        pcm = _render_track_pcm(track, total_duration_s)
        file_name = f"{track.participant_id}.wav"
        file_path = session_dir / file_name
        _write_wave(file_path, pcm, track.sample_rate_hz)
        generated_files.append(
            {
                "participant_id": track.participant_id,
                "file_name": file_name,
                "path": str(file_path),
                "start_offset_ms": track.start_offset_ms,
                "drift_ppm": track.drift_ppm,
                "sample_rate_hz": track.sample_rate_hz,
                "duration_s": total_duration_s,
            }
        )

    failure_inputs = _write_failure_inputs(session_dir, plan)

    ground_truth = {
        "session_id": plan.session_id,
        "duration_s": plan.duration_s,
        "fixture_duration_s": total_duration_s,
        "tracks": [asdict(track) for track in plan.tracks],
        "sample_rate_matrix": list(plan.sample_rate_matrix),
        "generated_files": generated_files,
        "failure_inputs": failure_inputs,
        "expected_acceptance_coverage": [
            "AC1 load/input-count matrix",
            "AC2 canonicalization sample-rate mismatch coverage",
            "AC3 aligned-track fixture source set",
            "AC5 manifest/drift ground truth",
            "AC6 sync-error benchmark ground truth",
            "AC9 corrupt/unsupported input rejection cases",
        ],
    }

    metadata_path = session_dir / "ground_truth.json"
    metadata_path.write_text(
        json.dumps(ground_truth, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return session_dir


def generate_integration_matrix(output_root: str | Path) -> list[Path]:
    """Generate the default 2/3/5 participant fixture matrix."""

    return [generate_session_fixture(output_root, plan) for plan in build_integration_matrix()]


def _write_failure_inputs(session_dir: Path, plan: SessionPlan) -> list[dict[str, str]]:
    failure_inputs: list[dict[str, str]] = []

    if plan.include_corrupt_input:
        corrupt_path = session_dir / "corrupt-track.wav"
        corrupt_path.write_bytes(b"NOT_A_REAL_WAV")
        failure_inputs.append(
            {
                "file_name": corrupt_path.name,
                "reason": "corrupt_audio_payload",
            }
        )

    if plan.include_unsupported_input:
        unsupported_path = session_dir / "unsupported-track.txt"
        unsupported_path.write_text("plain text is intentionally unsupported\n", encoding="utf-8")
        failure_inputs.append(
            {
                "file_name": unsupported_path.name,
                "reason": "unsupported_format",
            }
        )

    return failure_inputs


def _render_track_pcm(track: TrackPlan, total_duration_s: float) -> list[int]:
    total_frames = int(round(total_duration_s * track.sample_rate_hz))
    source_frames = int(round(track.duration_s * track.sample_rate_hz))
    offset_frames = int(round((track.start_offset_ms / 1_000.0) * track.sample_rate_hz))
    drift_factor = 1.0 + (track.drift_ppm / 1_000_000.0)
    rng = random.Random(f"{track.participant_id}:{track.drift_ppm}:{track.sample_rate_hz}")

    pcm: list[int] = []
    for frame_index in range(total_frames):
        source_index = (frame_index - offset_frames) / drift_factor
        if source_index < 0 or source_index >= source_frames:
            sample = 0.0
        else:
            sample = _voice_like_signal(
                time_s=source_index / track.sample_rate_hz,
                base_frequency_hz=track.base_frequency_hz,
                amplitude=track.amplitude,
            )
            sample += rng.uniform(-track.noise_floor, track.noise_floor)
        pcm.append(_float_to_pcm(sample))
    return pcm


def _voice_like_signal(*, time_s: float, base_frequency_hz: float, amplitude: float) -> float:
    # Alternating syllable-style envelope that is deterministic but non-uniform.
    envelope = 0.5 + 0.5 * math.sin(2.0 * math.pi * 1.7 * time_s)
    articulation = 0.75 + 0.25 * math.sin(2.0 * math.pi * 4.3 * time_s)
    harmonics = (
        math.sin(2.0 * math.pi * base_frequency_hz * time_s)
        + 0.35 * math.sin(2.0 * math.pi * base_frequency_hz * 2.0 * time_s)
        + 0.12 * math.sin(2.0 * math.pi * base_frequency_hz * 3.3 * time_s)
    )
    return amplitude * envelope * articulation * harmonics


def _float_to_pcm(value: float) -> int:
    clipped = max(-0.98, min(0.98, value))
    return int(clipped * DEFAULT_PCM_PEAK)


def _write_wave(path: Path, pcm_frames: list[int], sample_rate_hz: int) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate_hz)
        wav_file.writeframes(b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in pcm_frames))

