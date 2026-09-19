from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CanonicalFormat:
    sample_rate_hz: int = 48_000
    channels: int = 1
    sample_format: str = "float32"


@dataclass(frozen=True)
class LoudnessStats:
    integrated_lufs: float | None = None
    range_lu: float | None = None
    true_peak_dbfs: float | None = None

    def as_dict(self) -> dict[str, float]:
        values = {
            "integratedLufs": self.integrated_lufs,
            "rangeLu": self.range_lu,
            "truePeakDbfs": self.true_peak_dbfs,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True)
class AlignedTrackArtifact:
    track_id: str
    participant_id: str
    aligned_path: Path
    original_path: Path | None = None
    offset_ms: float = 0.0
    drift_ppm: float = 0.0
    duration_ms: int | None = None
    gain_db: float = 0.0
    weight: float = 1.0
    loudness: LoudnessStats = field(default_factory=LoudnessStats)
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def manifest_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "trackId": self.track_id,
            "participantId": self.participant_id,
            "alignedArtifact": self.aligned_path.as_posix(),
            "offsetMs": round(self.offset_ms, 3),
            "driftPpm": round(self.drift_ppm, 3),
            "gainDb": round(self.gain_db, 3),
            "weight": round(self.weight, 4),
        }
        if self.original_path is not None:
            entry["originalArtifact"] = self.original_path.as_posix()
        if self.duration_ms is not None:
            entry["durationMs"] = self.duration_ms
        loudness_payload = self.loudness.as_dict()
        if loudness_payload:
            entry["loudness"] = loudness_payload
        if self.extra_metadata:
            entry["metadata"] = dict(sorted(self.extra_metadata.items()))
        return entry


@dataclass(frozen=True)
class MixArtifact:
    output_path: Path
    format_name: str = "wav"
    codec: str = "pcm_f32le"
    target_lufs: float = -16.0
    notes: tuple[str, ...] = ()

    def manifest_entry(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.output_path.as_posix(),
            "format": self.format_name,
            "codec": self.codec,
            "targetLufs": self.target_lufs,
        }
        if self.notes:
            payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True)
class ExportArtifacts:
    session_id: str
    tracks: tuple[AlignedTrackArtifact, ...]
    mix_artifact: MixArtifact | None
    recommended_stt_input: str = "tracks"
    alignment_confidence: float | None = None
    qa_summary: dict[str, Any] = field(default_factory=dict)
    canonical_format: CanonicalFormat = field(default_factory=CanonicalFormat)
    bundle_path: Path | None = None

