from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivityBounds:
    start_sample: int
    end_sample: int

    @property
    def active_samples(self) -> int:
        return max(1, self.end_sample - self.start_sample)


@dataclass(frozen=True)
class AlignmentEstimate:
    offset_seconds: float
    confidence: float
    drift_ppm: float
    correction_factor: float


@dataclass(frozen=True)
class DriftLandmark:
    position_seconds: float
    offset_seconds: float


@dataclass(frozen=True)
class DriftSegment:
    start_seconds: float
    end_seconds: float
    offset_seconds: float
    drift_ppm: float
    correction_factor: float


@dataclass(frozen=True)
class SyncBeepSpec:
    sample_rate_hz: int = 48_000
    duration_ms: int = 120
    frequency_hz: int = 1_750
    fade_ms: int = 5
    peak_dbfs: float = -12.0


@dataclass(frozen=True)
class AnchorDetectionResult:
    detected: bool
    offset_samples: int | None
    offset_seconds: float | None
    confidence: float
    search_mode: str
