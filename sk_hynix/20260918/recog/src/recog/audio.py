from __future__ import annotations

import json
import math
import subprocess
import wave
from array import array
from pathlib import Path
from statistics import mean
from datetime import datetime, timezone


class AudioError(RuntimeError):
    pass


def run_command(
    command: list[str], *, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        raise AudioError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stderr}"
        )
    return completed


def ffprobe(path: str | Path) -> dict:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def audio_metadata(path: str | Path) -> dict:
    data = ffprobe(path)
    audio_stream = next((item for item in data.get("streams", []) if item.get("codec_type") == "audio"), None)
    if not audio_stream:
        raise AudioError("no audio stream found")
    return {
        "sample_rate": int(float(audio_stream.get("sample_rate", 0))),
        "channels": int(audio_stream.get("channels", 0)),
        "codec_name": audio_stream.get("codec_name", "unknown"),
        "duration_seconds": float(audio_stream.get("duration") or data["format"].get("duration") or 0.0),
        "bit_rate": int(float(audio_stream.get("bit_rate") or data["format"].get("bit_rate") or 0)),
    }


def canonicalize(input_path: str | Path, output_path: str | Path, sample_rate: int = 48_000) -> dict:
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-sample_fmt",
            "s16",
            str(output_path),
        ]
    )
    return audio_metadata(output_path)


def export_stt_track(
    input_path: str | Path,
    output_path: str | Path,
    sample_rate: int = 16_000,
    *,
    timeout: float | None = None,
) -> dict:
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-sample_fmt",
            "s16",
            str(output_path),
        ],
        timeout=timeout,
    )
    return audio_metadata(output_path)


def load_wav(path: str | Path) -> tuple[int, array]:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise AudioError("expected mono 16-bit wav input")
        sample_rate = handle.getframerate()
        samples = array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
        return sample_rate, samples


def envelope(samples: array, sample_rate: int, frame_ms: int = 20) -> list[float]:
    step = max(1, int(sample_rate * frame_ms / 1000))
    values: list[float] = []
    for start in range(0, len(samples), step):
        block = samples[start : start + step]
        if not block:
            break
        energy = math.sqrt(sum(value * value for value in block) / len(block))
        values.append(float(energy))
    return values


def activity_bounds(
    path: str | Path, *, frame_ms: int = 10, threshold_ratio: float = 0.3
) -> tuple[int, int, int]:
    sample_rate, samples = load_wav(path)
    values = envelope(samples, sample_rate, frame_ms=frame_ms)
    if not values:
        return sample_rate, 0, 0
    peak = max(values)
    threshold = max(200.0, peak * threshold_ratio)
    active_indices = [index for index, value in enumerate(values) if value >= threshold]
    if not active_indices:
        return sample_rate, 0, len(samples)
    step = max(1, int(sample_rate * frame_ms / 1000))
    start = active_indices[0] * step
    end = min(len(samples), (active_indices[-1] + 1) * step)
    while start > 0 and abs(samples[start]) < 128:
        start += 1
    while end > 0 and abs(samples[end - 1]) < 128:
        end -= 1
    return sample_rate, start, max(start + 1, end)


def _lag_slices(length_a: int, length_b: int, lag: int) -> tuple[int, int, int]:
    if lag >= 0:
        offset_a = 0
        offset_b = lag
        overlap = min(length_a, length_b - lag)
    else:
        offset_a = -lag
        offset_b = 0
        overlap = min(length_a + lag, length_b)
    return offset_a, offset_b, overlap


def normalized_correlation(reference: list[float], target: list[float], max_lag: int) -> tuple[int, float]:
    best_lag = 0
    best_score = -1.0
    for lag in range(-max_lag, max_lag + 1):
        offset_ref, offset_target, overlap = _lag_slices(len(reference), len(target), lag)
        if overlap <= 8:
            continue
        segment_ref = reference[offset_ref : offset_ref + overlap]
        segment_target = target[offset_target : offset_target + overlap]
        dot = sum(a * b for a, b in zip(segment_ref, segment_target, strict=False))
        ref_norm = math.sqrt(sum(a * a for a in segment_ref))
        target_norm = math.sqrt(sum(b * b for b in segment_target))
        if ref_norm == 0.0 or target_norm == 0.0:
            continue
        score = dot / (ref_norm * target_norm)
        if score > best_score:
            best_lag, best_score = lag, score
    return best_lag, max(best_score, 0.0)


def estimate_offset_seconds(
    reference_path: str | Path,
    target_path: str | Path,
    *,
    max_offset_seconds: float = 30.0,
    frame_ms: int = 20,
) -> tuple[float, float]:
    sample_rate, reference_samples = load_wav(reference_path)
    target_rate, target_samples = load_wav(target_path)
    if sample_rate != target_rate:
        raise AudioError("reference/target sample rate mismatch")
    reference_env = envelope(reference_samples, sample_rate, frame_ms=frame_ms)
    target_env = envelope(target_samples, target_rate, frame_ms=frame_ms)
    max_lag = int(max_offset_seconds * 1000 / frame_ms)
    lag, confidence = normalized_correlation(reference_env, target_env, max_lag)
    return lag * frame_ms / 1000.0, confidence


def _segment(samples: array, start: int, length: int) -> list[float]:
    end = max(start, start + length)
    return [float(value) for value in samples[start:end]]


def fine_offset_samples(
    reference_path: str | Path,
    target_path: str | Path,
    approximate_offset_seconds: float,
    *,
    window_seconds: float = 1.5,
    search_radius_seconds: float = 0.25,
    anchor_seconds: float = 0.0,
) -> tuple[int, float]:
    sample_rate, reference_samples = load_wav(reference_path)
    target_rate, target_samples = load_wav(target_path)
    if sample_rate != target_rate:
        raise AudioError("sample rate mismatch")
    approx_offset = int(approximate_offset_seconds * sample_rate)
    anchor = int(anchor_seconds * sample_rate)
    window = max(sample_rate // 2, int(window_seconds * sample_rate))
    radius = max(sample_rate // 20, int(search_radius_seconds * sample_rate))
    offset_ref = min(max(0, anchor), max(0, len(reference_samples) - window))
    segment_ref = _segment(reference_samples, offset_ref, window)
    best_lag = approx_offset
    best_score = -1.0
    start_target = approx_offset + offset_ref
    for lag in range(start_target - radius, start_target + radius + 1, max(1, sample_rate // 2000)):
        offset_target = max(0, lag)
        if offset_target + window > len(target_samples):
            continue
        segment_target = _segment(target_samples, offset_target, window)
        dot = sum(a * b for a, b in zip(segment_ref, segment_target, strict=False))
        ref_norm = math.sqrt(sum(a * a for a in segment_ref))
        target_norm = math.sqrt(sum(b * b for b in segment_target))
        if ref_norm == 0.0 or target_norm == 0.0:
            continue
        score = dot / (ref_norm * target_norm)
        if score > best_score:
            best_lag = lag - offset_ref
            best_score = score
    return best_lag, max(best_score, 0.0)


def detect_anchor_peak_seconds(
    path: str | Path,
    *,
    expected_anchor_seconds: float,
    search_radius_seconds: float = 0.35,
    min_peak_ratio: float = 0.35,
) -> tuple[float | None, float]:
    sample_rate, samples = load_wav(path)
    if not samples:
        return None, 0.0
    center = int(expected_anchor_seconds * sample_rate)
    radius = max(1, int(search_radius_seconds * sample_rate))
    start = max(0, center - radius)
    end = min(len(samples), center + radius)
    if start >= end:
        return None, 0.0
    global_peak = max(abs(sample) for sample in samples)
    if global_peak <= 0:
        return None, 0.0
    search_window = samples[start:end]
    local_peak = max(abs(sample) for sample in search_window)
    confidence = local_peak / global_peak
    if confidence < min_peak_ratio:
        return None, confidence
    for offset, sample in enumerate(search_window):
        if abs(sample) == local_peak:
            return (start + offset) / sample_rate, confidence
    return None, confidence


def estimate_alignment_and_drift(
    reference_path: str | Path,
    target_path: str | Path,
    *,
    coarse_offset_seconds: float | None = None,
    anchor_seconds: float | None = None,
) -> dict[str, float]:
    sample_rate, ref_start, ref_end = activity_bounds(reference_path)
    target_rate, target_start, target_end = activity_bounds(target_path)
    if sample_rate != target_rate:
        raise AudioError("sample rate mismatch")
    activity_offset_seconds = (target_start - ref_start) / sample_rate
    ref_active = max(1, ref_end - ref_start)
    target_active = max(1, target_end - target_start)
    correction_factor = ref_active / target_active
    if not 0.995 <= correction_factor <= 1.005:
        correction_factor = 1.0
    drift_ppm = ((target_active / ref_active) - 1.0) * 1_000_000.0 if ref_active else 0.0
    if coarse_offset_seconds is None:
        coarse_seconds = activity_offset_seconds
        coarse_confidence = 0.95
    else:
        delta = abs(activity_offset_seconds - coarse_offset_seconds)
        if delta <= 0.25:
            coarse_seconds = (activity_offset_seconds + coarse_offset_seconds) / 2.0
            coarse_confidence = 0.9
        else:
            coarse_seconds = coarse_offset_seconds
            coarse_confidence = 0.7
    if abs(coarse_seconds) <= 0.02:
        coarse_seconds, coarse_confidence = estimate_offset_seconds(
            reference_path,
            target_path,
            max_offset_seconds=1.0,
            frame_ms=5,
        )
    anchor_refined = False
    if anchor_seconds is not None and anchor_seconds >= 0.0:
        sample_rate = load_wav(reference_path)[0]
        fine_lag_samples, fine_confidence = fine_offset_samples(
            reference_path,
            target_path,
            coarse_seconds,
            anchor_seconds=anchor_seconds,
        )
        fine_seconds = fine_lag_samples / sample_rate
        if fine_confidence >= max(0.2, coarse_confidence * 0.5):
            coarse_seconds = fine_seconds
            coarse_confidence = max(coarse_confidence, fine_confidence)
            anchor_refined = True
    return {
        "offset_seconds": coarse_seconds,
        "confidence": coarse_confidence,
        "drift_ppm": drift_ppm,
        "correction_factor": correction_factor,
        "activity_offset_seconds": activity_offset_seconds,
        "anchor_refined": anchor_refined,
    }


def apply_drift_correction(
    input_path: str | Path, output_path: str | Path, correction_factor: float
) -> None:
    sample_rate = load_wav(input_path)[0]
    if abs(correction_factor - 1.0) < 1e-5:
        Path(output_path).write_bytes(Path(input_path).read_bytes())
        return
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-af",
            f"asetrate={sample_rate * correction_factor},aresample={sample_rate}",
            str(output_path),
        ]
    )


def align_track(
    input_path: str | Path,
    output_path: str | Path,
    *,
    offset_seconds: float,
    duration_seconds: float,
) -> None:
    filters: list[str] = []
    if offset_seconds < 0:
        filters.append(f"atrim=start={abs(offset_seconds):.6f}")
        filters.append("asetpts=PTS-STARTPTS")
    if offset_seconds > 0:
        delay_ms = max(0, round(offset_seconds * 1000))
        filters.append(f"adelay={delay_ms}:all=1")
    filters.append("apad")
    filters.append(f"atrim=end={duration_seconds:.6f}")
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-af",
            ",".join(filters),
            str(output_path),
        ]
    )


def active_speech_dbfs(path: str | Path) -> float:
    sample_rate, samples = load_wav(path)
    block = max(1, sample_rate // 20)
    energies = [
        math.sqrt(sum(value * value for value in samples[index : index + block]) / max(1, len(samples[index : index + block])))
        for index in range(0, len(samples), block)
        if samples[index : index + block]
    ]
    if not energies:
        return -120.0
    threshold = max(200.0, max(energies) * 0.25)
    voiced = [value for value in energies if value >= threshold]
    if not voiced:
        voiced = energies
    rms = max(1e-9, math.sqrt(sum(value * value for value in voiced) / len(voiced)))
    return 20.0 * math.log10(rms / 32768.0)


def normalize_track(input_path: str | Path, output_path: str | Path, *, target_dbfs: float = -20.0) -> float:
    current = active_speech_dbfs(input_path)
    gain_db = target_dbfs - current
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-af",
            f"volume={gain_db:.3f}dB,alimiter=limit=0.98",
            str(output_path),
        ]
    )
    return active_speech_dbfs(output_path)


def mix_tracks(
    inputs: list[str | Path],
    output_path: str | Path,
    *,
    delays_ms: list[int] | None = None,
    timeout: float | None = None,
) -> None:
    """Overlay every input on one timeline and sum them (not concatenation).

    ``delays_ms`` shifts each input by that many milliseconds before summing,
    which is how ``align: "timestamp"`` lines tracks up by their recording start.
    Omit it (or pass all zeros) to overlay everything from 0s.
    """
    if delays_ms is not None and len(delays_ms) != len(inputs):
        raise AudioError("delays_ms must have one entry per input")

    command = ["ffmpeg", "-y"]
    for path in inputs:
        command.extend(["-i", str(path)])

    mix = f"amix=inputs={len(inputs)}:dropout_transition=0:normalize=0,alimiter=limit=0.95"
    if delays_ms is None:
        filter_complex = mix
    else:
        # adelay pads the head of each track; all=1 keeps mono/stereo uniform.
        stages = [f"[{index}:a]adelay={max(0, delay)}:all=1[d{index}]" for index, delay in enumerate(delays_ms)]
        labels = "".join(f"[d{index}]" for index in range(len(inputs)))
        filter_complex = ";".join(stages) + f";{labels}{mix}"

    command.extend(["-filter_complex", filter_complex, str(output_path)])
    run_command(command, timeout=timeout)


def clipped_samples(path: str | Path) -> int:
    _, samples = load_wav(path)
    return sum(1 for value in samples if abs(value) >= 32767)
