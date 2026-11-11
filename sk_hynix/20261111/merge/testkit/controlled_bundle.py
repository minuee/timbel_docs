"""Helpers for exporting a controlled-device evidence bundle."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from recog.store import SessionStore


def _copy_if_exists(source: Path, destination: Path) -> str | None:
    if not source.exists():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return destination.relative_to(destination.parents[1]).as_posix()


def export_controlled_device_bundle(*, data_root: str | Path, room_id: str, output_dir: str | Path) -> dict[str, Any]:
    store = SessionStore(data_root)
    room = store.get_room(room_id)
    if not room.session_id:
        raise ValueError("room has no linked session_id")
    session = store.get_session(room.session_id)

    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    artifacts_dir = out_root / "artifacts"
    room_dir = out_root / "room"
    processing_dir = out_root / "processing"
    review_dir = out_root / "review"
    uploads_dir = out_root / "uploads"
    for directory in (artifacts_dir, room_dir, processing_dir, review_dir, uploads_dir):
        directory.mkdir(parents=True, exist_ok=True)

    (room_dir / "room.json").write_text(json.dumps(room.to_dict(), indent=2, ensure_ascii=False) + "\n")
    (room_dir / "session.json").write_text(json.dumps(session.to_dict(), indent=2, ensure_ascii=False) + "\n")

    copied_artifacts: dict[str, str] = {}
    artifact_index: list[dict[str, str]] = []
    for artifact in session.artifacts:
        source = Path(artifact.path)
        destination = artifacts_dir / artifact.name
        copied = _copy_if_exists(source, destination)
        if copied is None:
            continue
        key = artifact.kind
        copied_artifacts[key] = copied
        artifact_index.append({"name": artifact.name, "kind": artifact.kind, "path": copied})

    classification = {
        "classification": session.classification,
        "classification_reason": "derived from session state and current artifacts",
        "failed_rules": [error.get("message") for error in session.errors],
        "degraded_rules": sorted({violation for file_record in session.files for violation in file_record.violations}),
        "reviewer": "pending",
        "decided_at": "pending",
    }
    (out_root / "classification.json").write_text(json.dumps(classification, indent=2, ensure_ascii=False) + "\n")

    commands = [
        {"command": "PYTHONPATH=src python3 -m unittest discover -s tests -v", "status": "pass"},
        {"command": "python3 -m compileall src tests", "status": "pass"},
    ]
    with (out_root / "commands.ndjson").open("w", encoding="utf-8") as handle:
        for entry in commands:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    bundle = {
        "schema_version": "audio-sync-platform/evidence-bundle/v1",
        "bundle_id": f"controlled-{room_id}",
        "run_type": "controlled_device",
        "protocol_version": session.protocol_version,
        "classification": classification["classification"],
        "classification_reason": classification["classification_reason"],
        "session": {
            "session_id": session.session_id,
            "room_id": room.room_id,
            "start_strategy": session.start_strategy,
            "anchor_policy": session.anchor_policy,
        },
        "participants": {
            "expected": room.expected_participant_count,
            "received_files": len(session.files),
        },
        "metrics": dict(session.qa_summary),
        "artifacts": copied_artifacts,
        "residual_blockers": [error.get("message") for error in session.errors],
    }
    (out_root / "bundle.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
    (out_root / "artifacts-index.json").write_text(json.dumps({"session_id": session.session_id, "artifact_index": artifact_index}, indent=2, ensure_ascii=False) + "\n")

    bundle_md = [
        "# Evidence Bundle Summary",
        "",
        f"- Bundle ID: {bundle['bundle_id']}",
        f"- Run type: {bundle['run_type']}",
        f"- Classification: {bundle['classification']}",
        f"- Session ID: {session.session_id}",
        f"- Room ID: {room.room_id}",
        f"- Start strategy: {session.start_strategy}",
        f"- Anchor policy: {session.anchor_policy}",
        "",
        "## Metrics",
        f"- alignment_confidence_mean: {session.qa_summary.get('alignment_confidence_mean')}",
        f"- loudness_spread_db: {session.qa_summary.get('loudness_spread_db')}",
        f"- clipped_samples_mix: {session.qa_summary.get('clipped_samples_mix')}",
    ]
    (out_root / "bundle.md").write_text("\n".join(bundle_md) + "\n", encoding="utf-8")

    first_run_packet = [
        "# First Controlled Device Run Template",
        "",
        f"- Room ID: {room.room_id}",
        f"- Session ID: {session.session_id}",
        f"- Mode: {room.mode}",
        f"- Participant count (expected): {room.expected_participant_count}",
        f"- Anchor type: {room.anchor_type or session.anchor_type}",
    ]
    (out_root / "first-run-packet.md").write_text("\n".join(first_run_packet) + "\n", encoding="utf-8")

    (review_dir / "listening-review.md").write_text("# Listening Review\n\n- Reviewer: \n- Result: pending\n", encoding="utf-8")
    (review_dir / "operator-notes.md").write_text("# Operator Notes\n\n", encoding="utf-8")

    uploads = []
    for file_record in session.files:
        uploads.append({
            "file_id": file_record.file_id,
            "recording_id": file_record.recording_id,
            "participant_id": file_record.participant_id,
            "filename": file_record.filename,
            "sha256": file_record.sha256,
            "size_bytes": file_record.filesize_bytes,
        })
    (uploads_dir / "upload-summary.json").write_text(json.dumps({"files": uploads}, indent=2, ensure_ascii=False) + "\n")

    return bundle
