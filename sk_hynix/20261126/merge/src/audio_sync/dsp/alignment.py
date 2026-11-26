from __future__ import annotations

import math
from array import array

from .models import ActivityBounds, AlignmentEstimate


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


def normalized_correlation(reference: list[float], target: list[float], max_lag: int) -> tuple[int, float]:
    best_lag = 0
    best_score = -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            ref_start = 0
            target_start = lag
            overlap = min(len(reference), len(target) - lag)
        else:
            ref_start = -lag
            target_start = 0
            overlap = min(len(reference) + lag, len(target))
        if overlap <= 2:
            continue
        ref_segment = reference[ref_start : ref_start + overlap]
        target_segment = target[target_start : target_start + overlap]
        ref_norm = math.sqrt(sum(value * value for value in ref_segment))
        target_norm = math.sqrt(sum(value * value for value in target_segment))
        if ref_norm == 0.0 or target_norm == 0.0:
            continue
        dot = sum(a * b for a, b in zip(ref_segment, target_segment, strict=False))
        score = dot / (ref_norm * target_norm)
        if score > best_score:
            best_lag = lag
            best_score = score
    return best_lag, max(best_score, 0.0)




def segment(samples: array, start: int, length: int) -> list[float]:
    end = max(start, start + length)
    return [float(value) for value in samples[start:end]]


def fine_offset_samples_from_arrays(
    reference_samples: array,
    target_samples: array,
    *,
    sample_rate: int,
    approximate_offset_seconds: float,
    window_seconds: float = 1.5,
    search_radius_seconds: float = 0.25,
    anchor_seconds: float = 0.0,
) -> tuple[int, float]:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    approx_offset = int(approximate_offset_seconds * sample_rate)
    anchor = int(anchor_seconds * sample_rate)
    window = max(sample_rate // 2, int(window_seconds * sample_rate))
    radius = max(sample_rate // 20, int(search_radius_seconds * sample_rate))
    offset_ref = min(max(0, anchor), max(0, len(reference_samples) - window))
    segment_ref = segment(reference_samples, offset_ref, window)
    best_lag = approx_offset
    best_score = -1.0
    start_target = approx_offset + offset_ref
    step = max(1, sample_rate // 2000)
    for lag in range(start_target - radius, start_target + radius + 1, step):
        offset_target = max(0, lag)
        if offset_target + window > len(target_samples):
            continue
        segment_target = segment(target_samples, offset_target, window)
        ref_norm = math.sqrt(sum(value * value for value in segment_ref))
        target_norm = math.sqrt(sum(value * value for value in segment_target))
        if ref_norm == 0.0 or target_norm == 0.0:
            continue
        dot = sum(a * b for a, b in zip(segment_ref, segment_target, strict=False))
        score = dot / (ref_norm * target_norm)
        if score > best_score:
            best_lag = lag - offset_ref
            best_score = score
    return best_lag, max(best_score, 0.0)

def estimate_offset_seconds(
    reference_envelope: list[float],
    target_envelope: list[float],
    *,
    frame_ms: int = 20,
    max_offset_seconds: float = 30.0,
) -> tuple[float, float]:
    max_lag = int(max_offset_seconds * 1000 / frame_ms)
    lag, confidence = normalized_correlation(reference_envelope, target_envelope, max_lag)
    return lag * frame_ms / 1000.0, confidence


def bounded_correction_factor(
    reference_active_samples: int,
    target_active_samples: int,
    *,
    minimum: float = 0.995,
    maximum: float = 1.005,
) -> float:
    if reference_active_samples <= 0 or target_active_samples <= 0:
        return 1.0
    factor = reference_active_samples / target_active_samples
    if minimum <= factor <= maximum:
        return factor
    return 1.0


def estimate_alignment_from_activity(
    reference: ActivityBounds,
    target: ActivityBounds,
    *,
    sample_rate: int,
    coarse_offset_seconds: float | None = None,
    coarse_confidence: float = 0.95,
) -> AlignmentEstimate:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    offset_seconds = (
        coarse_offset_seconds
        if coarse_offset_seconds is not None
        else (target.start_sample - reference.start_sample) / sample_rate
    )
    correction_factor = bounded_correction_factor(reference.active_samples, target.active_samples)
    drift_ppm = ((target.active_samples / reference.active_samples) - 1.0) * 1_000_000.0
    return AlignmentEstimate(
        offset_seconds=offset_seconds,
        confidence=max(0.0, min(1.0, coarse_confidence)),
        drift_ppm=drift_ppm,
        correction_factor=correction_factor,
    )


def normalize_offsets(offsets_seconds: dict[str, float]) -> dict[str, float]:
    if not offsets_seconds:
        return {}
    baseline = min(offsets_seconds.values())
    return {key: value - baseline for key, value in offsets_seconds.items()}
