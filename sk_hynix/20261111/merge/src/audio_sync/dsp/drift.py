from __future__ import annotations

from .models import DriftLandmark, DriftSegment


def fit_piecewise_drift(
    landmarks: tuple[DriftLandmark, ...],
    *,
    max_correction_delta: float = 0.005,
) -> tuple[DriftSegment, ...]:
    if len(landmarks) < 2:
        raise ValueError("at least two landmarks are required")

    ordered = tuple(sorted(landmarks, key=lambda item: item.position_seconds))
    segments: list[DriftSegment] = []
    for current, nxt in zip(ordered, ordered[1:]):
        duration = max(1e-9, nxt.position_seconds - current.position_seconds)
        offset_delta = nxt.offset_seconds - current.offset_seconds
        correction_factor = 1.0 - (offset_delta / duration)
        if abs(correction_factor - 1.0) > max_correction_delta:
            correction_factor = 1.0
        drift_ppm = (1.0 - correction_factor) * 1_000_000.0
        segments.append(
            DriftSegment(
                start_seconds=current.position_seconds,
                end_seconds=nxt.position_seconds,
                offset_seconds=current.offset_seconds,
                drift_ppm=drift_ppm,
                correction_factor=correction_factor,
            )
        )
    return tuple(segments)
