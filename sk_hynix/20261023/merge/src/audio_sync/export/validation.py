from __future__ import annotations

from typing import Any


def validate_export_manifest(manifest: dict[str, Any]) -> None:
    _require_keys(
        manifest,
        "sessionId",
        "schemaVersion",
        "canonicalFormat",
        "recommendedSttInput",
        "tracks",
        "qaSummary",
    )
    if manifest["recommendedSttInput"] not in {"tracks", "mixdown"}:
        raise ValueError("recommendedSttInput must be 'tracks' or 'mixdown'")
    if not isinstance(manifest["tracks"], list) or not manifest["tracks"]:
        raise ValueError("tracks must be a non-empty list")
    for track in manifest["tracks"]:
        _require_keys(track, "trackId", "participantId", "alignedArtifact", "offsetMs", "driftPpm")


def validate_recog_manifest(manifest: dict[str, Any]) -> None:
    _require_keys(
        manifest,
        "sessionId",
        "canonical_format",
        "recommended_stt_input",
        "non_goals_excluded",
        "tracks",
        "qa_summary",
    )
    if manifest["recommended_stt_input"] not in {"tracks", "mixdown"}:
        raise ValueError("recommended_stt_input must be 'tracks' or 'mixdown'")
    if not isinstance(manifest["tracks"], list) or not manifest["tracks"]:
        raise ValueError("tracks must be a non-empty list")
    for track in manifest["tracks"]:
        _require_keys(
            track,
            "file_id",
            "participant_id",
            "aligned_path",
            "offset_seconds",
            "drift_ppm",
            "correction_factor",
            "alignment_confidence",
        )


def _require_keys(payload: dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError(f"missing required keys: {', '.join(missing)}")
