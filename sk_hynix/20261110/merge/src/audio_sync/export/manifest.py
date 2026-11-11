from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ExportArtifacts

SCHEMA_VERSION = "1.0"


def build_export_manifest(exports: ExportArtifacts) -> dict[str, Any]:
    if exports.recommended_stt_input not in {"tracks", "mixdown"}:
        raise ValueError("recommended_stt_input must be 'tracks' or 'mixdown'")

    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": exports.session_id,
        "generatedAt": datetime.now(UTC).isoformat(),
        "canonicalFormat": {
            "sampleRateHz": exports.canonical_format.sample_rate_hz,
            "channels": exports.canonical_format.channels,
            "sampleFormat": exports.canonical_format.sample_format,
        },
        "recommendedSttInput": exports.recommended_stt_input,
        "tracks": [track.manifest_entry() for track in exports.tracks],
        "qaSummary": dict(sorted(exports.qa_summary.items())),
    }

    if exports.mix_artifact is not None:
        manifest["listeningMix"] = exports.mix_artifact.manifest_entry()
    if exports.bundle_path is not None:
        manifest["artifactsBundle"] = exports.bundle_path.as_posix()
    if exports.alignment_confidence is not None:
        manifest["alignmentConfidence"] = round(exports.alignment_confidence, 4)

    provenance_tracks = []
    for track in exports.tracks:
        metadata = dict(track.extra_metadata)
        provenance_tracks.append(
            {
                "trackId": track.track_id,
                "participantId": track.participant_id,
                "roomId": metadata.get("roomId"),
                "sessionId": metadata.get("sessionId"),
                "deviceId": metadata.get("deviceId"),
                "container": metadata.get("container"),
                "codec": metadata.get("codec"),
                "sampleRateHz": metadata.get("sampleRateHz"),
                "channels": metadata.get("channels"),
                "durationSeconds": metadata.get("durationSeconds"),
                "micRoute": metadata.get("micRoute"),
                "audioProcessingFlags": metadata.get("audioProcessingFlags"),
                "startCommandId": metadata.get("startCommandId"),
                "serverStartIssuedAt": metadata.get("serverStartIssuedAt"),
                "startCommandReceivedAt": metadata.get("startCommandReceivedAt"),
                "clientRecordInvokedAt": metadata.get("clientRecordInvokedAt"),
                "recordingStartedAt": metadata.get("recordingStartedAt"),
                "localMonotonicStartTick": metadata.get("localMonotonicStartTick"),
                "anchorType": metadata.get("anchorType"),
                "anchorExpectedAt": metadata.get("anchorExpectedAt"),
                "anchorDetectedAt": metadata.get("anchorDetectedAt"),
                "anchorDetectedSeconds": metadata.get("anchorDetectedSeconds"),
                "anchorDetectionConfidence": metadata.get("anchorDetectionConfidence"),
                "anchorDetectedOffsetSeconds": metadata.get("anchorDetectedOffsetSeconds"),
                "metadataPriorOffsetSeconds": metadata.get("metadataPriorOffsetSeconds"),
                "metadataPriorSource": metadata.get("metadataPriorSource"),
                "activityOffsetSeconds": metadata.get("activityOffsetSeconds"),
                "anchorRefined": metadata.get("anchorRefined"),
                "anchorSeconds": metadata.get("anchorSeconds"),
                "pauseResumeEvents": metadata.get("pauseResumeEvents") or [],
            }
        )
    manifest["captureProvenance"] = {"tracks": provenance_tracks}

    return manifest


def write_manifest(manifest: dict[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination
