from __future__ import annotations

from pathlib import Path

from recog.models import FileRecord

from .models import AlignedTrackArtifact, ExportArtifacts, MixArtifact


def build_exports_from_file_records(
    *,
    session_id: str,
    files: list[FileRecord],
    mix_output_path: str | Path | None,
    qa_summary: dict | None = None,
    recommended_stt_input: str | None = None,
    bundle_path: str | Path | None = None,
) -> ExportArtifacts:
    tracks = tuple(_file_record_to_track(file_record) for file_record in files)
    mix_artifact = None
    if mix_output_path is not None:
        mix_artifact = MixArtifact(output_path=Path(mix_output_path))

    resolved_recommendation = recommended_stt_input or ("tracks" if len(tracks) > 1 else "mixdown")
    confidence = None
    if tracks:
        confidence_values = [
            float(file_record.alignment_confidence)
            for file_record in files
            if file_record.alignment_confidence is not None
        ]
        if confidence_values:
            confidence = sum(confidence_values) / len(confidence_values)

    return ExportArtifacts(
        session_id=session_id,
        tracks=tracks,
        mix_artifact=mix_artifact,
        recommended_stt_input=resolved_recommendation,
        alignment_confidence=confidence,
        qa_summary=qa_summary or {},
        bundle_path=Path(bundle_path) if bundle_path is not None else None,
    )


def _file_record_to_track(file_record: FileRecord) -> AlignedTrackArtifact:
    if not file_record.aligned_path:
        raise ValueError(f"file {file_record.file_id} is missing aligned_path")

    return AlignedTrackArtifact(
        track_id=file_record.file_id,
        participant_id=file_record.participant_id,
        aligned_path=Path(file_record.aligned_path),
        original_path=Path(file_record.uploaded_path) if file_record.uploaded_path else None,
        offset_ms=file_record.offset_seconds * 1000.0,
        drift_ppm=file_record.drift_ppm,
        gain_db=0.0,
        extra_metadata={
            "filename": file_record.filename,
            "sttPath": file_record.stt_path,
            "formatName": file_record.format_name,
            "correctionFactor": file_record.correction_factor,
            "alignmentConfidence": file_record.alignment_confidence,
            "loudnessDbfs": file_record.loudness_dbfs,
            "roomId": file_record.room_id,
            "sessionId": file_record.session_id,
            "deviceId": file_record.device_id,
            "container": file_record.container,
            "codec": file_record.codec,
            "sampleRateHz": file_record.sample_rate_hz,
            "channels": file_record.channels,
            "durationSeconds": file_record.duration_seconds,
            "micRoute": file_record.mic_route,
            "audioProcessingFlags": file_record.audio_processing_flags,
            "startCommandId": file_record.start_command_id,
            "serverStartIssuedAt": file_record.server_start_issued_at,
            "startCommandReceivedAt": file_record.start_command_received_at,
            "clientRecordInvokedAt": file_record.client_record_invoked_at,
            "recordingStartedAt": file_record.recording_started_at,
            "localMonotonicStartTick": file_record.local_monotonic_start_tick,
            "anchorType": file_record.anchor_type,
            "anchorExpectedAt": file_record.anchor_expected_at,
            "anchorDetectedAt": file_record.anchor_detected_at,
            "metadataPriorOffsetSeconds": (file_record.metadata or {}).get("metadata_prior_offset_seconds"),
            "metadataPriorSource": (file_record.metadata or {}).get("metadata_prior_source"),
            "activityOffsetSeconds": (file_record.metadata or {}).get("activity_offset_seconds"),
            "anchorRefined": (file_record.metadata or {}).get("anchor_refined"),
            "anchorSeconds": (file_record.metadata or {}).get("anchor_seconds"),
            "anchorDetectedSeconds": (file_record.metadata or {}).get("anchor_detected_seconds"),
            "anchorDetectionConfidence": (file_record.metadata or {}).get("anchor_detection_confidence"),
            "anchorDetectedOffsetSeconds": (file_record.metadata or {}).get("anchor_detected_offset_seconds"),
            "pauseResumeEvents": file_record.pause_resume_events,
        },
    )
