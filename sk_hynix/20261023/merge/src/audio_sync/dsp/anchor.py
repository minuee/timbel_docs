from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path

from .models import AnchorDetectionResult, SyncBeepSpec


DEFAULT_SYNC_BEEP_SPEC = SyncBeepSpec()


def build_sync_beep_samples(spec: SyncBeepSpec = DEFAULT_SYNC_BEEP_SPEC) -> array:
    if spec.sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    sample_count = max(1, round(spec.sample_rate_hz * (spec.duration_ms / 1000.0)))
    fade_count = min(sample_count // 2, max(0, round(spec.sample_rate_hz * (spec.fade_ms / 1000.0))))
    amplitude = int(32767 * (10 ** (spec.peak_dbfs / 20.0)))
    samples = array("h")
    for index in range(sample_count):
        envelope = 1.0
        if fade_count:
            if index < fade_count:
                envelope = index / fade_count
            elif index >= sample_count - fade_count:
                envelope = max(0.0, (sample_count - index - 1) / fade_count)
        sample = math.sin(2.0 * math.pi * spec.frequency_hz * index / spec.sample_rate_hz)
        samples.append(int(amplitude * envelope * sample))
    return samples


def write_sync_beep_wav(path: str | Path, spec: SyncBeepSpec = DEFAULT_SYNC_BEEP_SPEC) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    samples = build_sync_beep_samples(spec)
    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(spec.sample_rate_hz)
        handle.writeframes(samples.tobytes())
    return output


def _normalized_dot(reference: list[float], target: list[float]) -> float:
    dot = sum(a * b for a, b in zip(reference, target, strict=False))
    ref_norm = math.sqrt(sum(a * a for a in reference))
    target_norm = math.sqrt(sum(b * b for b in target))
    if ref_norm == 0.0 or target_norm == 0.0:
        return 0.0
    return dot / (ref_norm * target_norm)


def detect_beep_offset_from_arrays(
    samples: array,
    *,
    sample_rate: int,
    spec: SyncBeepSpec = DEFAULT_SYNC_BEEP_SPEC,
    expected_offset_seconds: float | None = None,
    expected_window_seconds: float = 0.5,
    fallback_window_seconds: float = 3.0,
    minimum_confidence: float = 0.55,
) -> AnchorDetectionResult:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    template = build_sync_beep_samples(spec)
    template_f = [float(value) for value in template]
    source = [float(value) for value in samples]
    if len(source) < len(template_f):
        return AnchorDetectionResult(False, None, None, 0.0, "expected")

    def search(start: int, end: int, mode: str) -> AnchorDetectionResult:
        best_offset = None
        best_score = -1.0
        last_possible = len(source) - len(template_f)
        start = max(0, min(start, last_possible))
        end = max(start, min(end, last_possible))
        stride = max(1, sample_rate // 4000)
        for offset in range(start, end + 1, stride):
            score = _normalized_dot(template_f, source[offset : offset + len(template_f)])
            if score > best_score:
                best_score = score
                best_offset = offset
        if best_offset is None or best_score < minimum_confidence:
            return AnchorDetectionResult(False, None, None, max(best_score, 0.0), mode)
        return AnchorDetectionResult(
            True,
            best_offset,
            best_offset / sample_rate,
            best_score,
            mode,
        )

    if expected_offset_seconds is not None:
        center = int(expected_offset_seconds * sample_rate)
        window = int(expected_window_seconds * sample_rate)
        result = search(center - window, center + window, "expected")
        if result.detected:
            return result
        fallback = int(fallback_window_seconds * sample_rate)
        return search(center - fallback, center + fallback, "fallback")

    return search(0, len(source) - len(template_f), "full")


def detect_beep_offset_seconds_from_arrays(
    samples: array,
    *,
    sample_rate: int,
    spec: SyncBeepSpec = DEFAULT_SYNC_BEEP_SPEC,
    expected_offset_seconds: float | None = None,
    expected_window_seconds: float = 0.5,
    fallback_window_seconds: float = 3.0,
    minimum_confidence: float = 0.55,
) -> tuple[float | None, float, str]:
    result = detect_beep_offset_from_arrays(
        samples,
        sample_rate=sample_rate,
        spec=spec,
        expected_offset_seconds=expected_offset_seconds,
        expected_window_seconds=expected_window_seconds,
        fallback_window_seconds=fallback_window_seconds,
        minimum_confidence=minimum_confidence,
    )
    return result.offset_seconds, result.confidence, result.search_mode
