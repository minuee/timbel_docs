from .anchor import (
    DEFAULT_SYNC_BEEP_SPEC,
    build_sync_beep_samples,
    detect_beep_offset_from_arrays,
    detect_beep_offset_seconds_from_arrays,
    write_sync_beep_wav,
)
from .alignment import (
    bounded_correction_factor,
    envelope,
    estimate_alignment_from_activity,
    fine_offset_samples_from_arrays,
    estimate_offset_seconds,
    normalize_offsets,
    normalized_correlation,
    segment,
)
from .canonicalize import (
    DEFAULT_STT_SAMPLE_RATE,
    DEFAULT_WORKING_SAMPLE_RATE,
    build_canonicalize_command,
    build_stt_export_command,
    summarize_canonical_metadata,
)
from .drift import fit_piecewise_drift
from .ffmpeg_filters import build_alignment_filter, build_drift_correction_filter
from .models import (
    ActivityBounds,
    AlignmentEstimate,
    AnchorDetectionResult,
    DriftLandmark,
    DriftSegment,
    SyncBeepSpec,
)

__all__ = [
    "ActivityBounds",
    "AlignmentEstimate",
    "AnchorDetectionResult",
    "SyncBeepSpec",
    "DEFAULT_SYNC_BEEP_SPEC",
    "DriftLandmark",
    "DriftSegment",
    "build_sync_beep_samples",
    "DEFAULT_STT_SAMPLE_RATE",
    "DEFAULT_WORKING_SAMPLE_RATE",
    "bounded_correction_factor",
    "build_canonicalize_command",
    "build_stt_export_command",
    "detect_beep_offset_from_arrays",
    "detect_beep_offset_seconds_from_arrays",
    "envelope",
    "estimate_alignment_from_activity",
    "fine_offset_samples_from_arrays",
    "estimate_offset_seconds",
    "fit_piecewise_drift",
    "build_alignment_filter",
    "build_drift_correction_filter",
    "normalize_offsets",
    "normalized_correlation",
    "segment",
    "summarize_canonical_metadata",
    "write_sync_beep_wav",
]
