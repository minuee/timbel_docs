from __future__ import annotations

import json
import math
import random
import wave
from array import array
from pathlib import Path

from .audio import run_command


def _write_wav(path: Path, sample_rate: int, samples: array) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())


def _base_signal(sample_rate: int, duration_seconds: float, seed: int) -> array:
    total = int(sample_rate * duration_seconds)
    rng = random.Random(seed)
    samples = array("h")
    for index in range(total):
        time = index / sample_rate
        burst = 0.0
        for start in (0.35, 1.05, 1.95, 2.85, 3.65, 4.45):
            if start <= time <= start + 0.35:
                phase = time - start
                envelope = math.sin((phase / 0.35) * math.pi)
                burst += envelope * (
                    math.sin(2 * math.pi * 220 * time)
                    + 0.6 * math.sin(2 * math.pi * 330 * time)
                    + 0.3 * math.sin(2 * math.pi * 440 * time)
                )
        noise = rng.uniform(-0.03, 0.03)
        sample = max(-0.98, min(0.98, burst * 0.28 + noise))
        samples.append(int(sample * 32767))
    return samples


def _resample_linear(samples: array, factor: float) -> array:
    if abs(factor - 1.0) < 1e-6:
        return array("h", samples)
    target_length = max(1, int(len(samples) / factor))
    result = array("h")
    for index in range(target_length):
        source_position = index * factor
        lower = min(len(samples) - 1, int(source_position))
        upper = min(len(samples) - 1, lower + 1)
        fraction = source_position - lower
        interpolated = samples[lower] * (1 - fraction) + samples[upper] * fraction
        result.append(int(interpolated))
    return result


def _apply_offset_and_noise(
    sample_rate: int,
    base: array,
    *,
    offset_seconds: float,
    drift_ppm: float,
    gain: float,
    noise_seed: int,
) -> array:
    drift_factor = 1.0 + drift_ppm / 1_000_000.0
    drifted = _resample_linear(base, drift_factor)
    prefix = array("h", [0] * int(offset_seconds * sample_rate))
    rng = random.Random(noise_seed)
    result = prefix + drifted
    for index in range(len(result)):
        value = result[index] / 32767.0
        value = value * gain + rng.uniform(-0.015, 0.015)
        result[index] = int(max(-0.98, min(0.98, value)) * 32767)
    return result


def generate_fixture_session(
    root: str | Path,
    *,
    track_count: int = 3,
    duration_seconds: float = 6.0,
    sample_rate: int = 48_000,
) -> dict:
    destination = Path(root)
    destination.mkdir(parents=True, exist_ok=True)
    base = _base_signal(sample_rate, duration_seconds, seed=91)
    offsets = [0.0, 0.42, 0.83, 1.21, 1.46][:track_count]
    drifts = [0.0, 18.0, -22.0, 8.0, -9.0][:track_count]
    gains = [1.0, 0.72, 1.22, 0.88, 1.1][:track_count]
    formats = ["wav", "flac", "m4a", "wav", "flac"][:track_count]
    tracks: list[dict] = []
    for index in range(track_count):
        rendered = _apply_offset_and_noise(
            sample_rate,
            base,
            offset_seconds=offsets[index],
            drift_ppm=drifts[index],
            gain=gains[index],
            noise_seed=index + 11,
        )
        wav_path = destination / f"participant-{index+1}.wav"
        _write_wav(wav_path, sample_rate, rendered)
        final_path = wav_path
        if formats[index] != "wav":
            final_path = destination / f"participant-{index+1}.{formats[index]}"
            run_command(["ffmpeg", "-y", "-i", str(wav_path), str(final_path)])
        tracks.append(
            {
                "participant_id": f"p{index+1}",
                "path": str(final_path),
                "filename": final_path.name,
                "offset_seconds": offsets[index],
                "drift_ppm": drifts[index],
                "format": formats[index],
            }
        )
    truth = {"sample_rate": sample_rate, "duration_seconds": duration_seconds, "tracks": tracks}
    (destination / "ground_truth.json").write_text(json.dumps(truth, indent=2))
    return truth
