from __future__ import annotations

from typing import Any

from .models import ExportArtifacts


DEFAULT_NON_GOALS_EXCLUDED = {
    "real_time": True,
    "speaker_diarization": True,
    "speaker_identification": True,
    "manual_editing_ui": True,
    "video_sync": True,
}


def build_recog_manifest(
    exports: ExportArtifacts,
    *,
    non_goals_excluded: dict[str, bool] | None = None,
) -> dict[str, Any]:
    qa_summary = dict(exports.qa_summary)
    if "recommended_stt_input" not in qa_summary:
        qa_summary["recommended_stt_input"] = exports.recommended_stt_input

    payload: dict[str, Any] = {
        "sessionId": exports.session_id,
        "canonical_format": {
            "sample_rate": exports.canonical_format.sample_rate_hz,
            "channels": exports.canonical_format.channels,
            "encoding": exports.canonical_format.sample_format,
        },
        "recommended_stt_input": exports.recommended_stt_input,
        "non_goals_excluded": dict(non_goals_excluded or DEFAULT_NON_GOALS_EXCLUDED),
        "tracks": [_build_recog_track_entry(track) for track in exports.tracks],
        "qa_summary": qa_summary,
    }
    if exports.mix_artifact is not None:
        payload["listening_mix"] = exports.mix_artifact.manifest_entry()
    if exports.bundle_path is not None:
        payload["aligned_tracks_bundle"] = exports.bundle_path.as_posix()
    payload["capture_provenance"] = {
        "tracks": [
            {
                "file_id": track.track_id,
                "participant_id": track.participant_id,
                "room_id": track.extra_metadata.get("roomId"),
                "session_id": track.extra_metadata.get("sessionId"),
                "device_id": track.extra_metadata.get("deviceId"),
                "mic_route": track.extra_metadata.get("micRoute"),
                "audio_processing_flags": track.extra_metadata.get("audioProcessingFlags"),
                "start_command_id": track.extra_metadata.get("startCommandId"),
                "recording_started_at": track.extra_metadata.get("recordingStartedAt"),
                "anchor_type": track.extra_metadata.get("anchorType"),
                "anchor_expected_at": track.extra_metadata.get("anchorExpectedAt"),
                "anchor_detected_at": track.extra_metadata.get("anchorDetectedAt"),
                "anchor_detected_seconds": track.extra_metadata.get("anchorDetectedSeconds"),
                "anchor_detection_confidence": track.extra_metadata.get("anchorDetectionConfidence"),
                "anchor_detected_offset_seconds": track.extra_metadata.get("anchorDetectedOffsetSeconds"),
                "metadata_prior_offset_seconds": track.extra_metadata.get("metadataPriorOffsetSeconds"),
                "metadata_prior_source": track.extra_metadata.get("metadataPriorSource"),
                "activity_offset_seconds": track.extra_metadata.get("activityOffsetSeconds"),
                "anchor_refined": track.extra_metadata.get("anchorRefined"),
                "anchor_seconds": track.extra_metadata.get("anchorSeconds"),
                "pause_resume_events": track.extra_metadata.get("pauseResumeEvents") or [],
            }
            for track in exports.tracks
        ]
    }
    return payload


def _build_recog_track_entry(track) -> dict[str, Any]:
    metadata = dict(track.extra_metadata)
    payload: dict[str, Any] = {
        "file_id": track.track_id,
        "participant_id": track.participant_id,
        "filename": metadata.get("filename"),
        "aligned_path": track.aligned_path.as_posix(),
        "stt_path": metadata.get("sttPath"),
        "offset_seconds": round(track.offset_ms / 1000.0, 6),
        "drift_ppm": round(track.drift_ppm, 3),
        "correction_factor": round(float(metadata.get("correctionFactor", 1.0)), 8),
        "alignment_confidence": round(float(metadata.get("alignmentConfidence", 0.0)), 6),
    }
    loudness = metadata.get("loudnessDbfs")
    if loudness is not None:
        payload["loudness_dbfs"] = round(float(loudness), 3)
    return payload
