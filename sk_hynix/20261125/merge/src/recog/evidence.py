from __future__ import annotations

import json
import shutil
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

REQUIRED_ARTIFACT_KINDS = {"manifest", "manifest_export", "bundle", "mixdown"}


def _session_dict(session: Any) -> dict[str, Any]:
    if isinstance(session, dict):
        return session
    if hasattr(session, "to_dict"):
        return session.to_dict()
    if is_dataclass(session):
        return asdict(session)
    raise TypeError(f"unsupported session payload type: {type(session)!r}")


def classify_session_payload(session: Any) -> tuple[str, str, list[str], list[str]]:
    payload = _session_dict(session)
    files = payload.get("files", [])
    failed_rules: list[str] = []
    degraded_rules: list[str] = []

    if payload.get("status") == "failed":
        failed_rules.append("session_failed")
    if any(file.get("rejection_reason") for file in files):
        failed_rules.append("file_rejected")
    if any(not file.get("participant_id") for file in files):
        failed_rules.append("missing_participant_id")
    if any(not file.get("session_id") for file in files):
        failed_rules.append("missing_session_id")

    if failed_rules:
        return "rejected", "; ".join(failed_rules), failed_rules, degraded_rules

    if payload.get("mode") != "research":
        degraded_rules.append("field_mode")
    if any(not file.get("baseline_valid", True) for file in files):
        degraded_rules.append("baseline_policy_violation")
    if any(file.get("mic_route") in {"unknown", "bluetooth", "wired", "bluetooth_mic"} for file in files):
        degraded_rules.append("non_baseline_route_or_unknown")
    if any(file.get("container") not in {None, "wav"} for file in files):
        degraded_rules.append("non_baseline_container")
    if any(file.get("channels") not in {None, 1} for file in files):
        degraded_rules.append("non_baseline_channels")
    if any(file.get("sample_rate_hz") not in {None, 48000} for file in files):
        degraded_rules.append("non_baseline_sample_rate")
    if any(file.get("pause_resume_events") for file in files):
        degraded_rules.append("pause_resume_present")
    if payload.get("room_id") is None:
        degraded_rules.append("missing_room_context")
    if payload.get("start_strategy") in {None, "legacy_unknown"}:
        degraded_rules.append("legacy_start_strategy")

    if degraded_rules:
        return "degraded", "; ".join(sorted(set(degraded_rules))), failed_rules, degraded_rules

    return "baseline-valid", "all baseline rules satisfied for exported session", failed_rules, degraded_rules


def recommended_run_type(session: Any) -> str:
    payload = _session_dict(session)
    if payload.get("mode") != "research":
        return "field"
    if payload.get("room_id"):
        return "controlled_device"
    return "synthetic"


def evidence_ready(session: Any) -> bool:
    payload = _session_dict(session)
    artifact_kinds = {artifact.get("kind") for artifact in payload.get("artifacts", [])}
    return payload.get("status") == "done" and REQUIRED_ARTIFACT_KINDS.issubset(artifact_kinds)


def build_evidence_summary(session: Any) -> dict[str, Any]:
    payload = _session_dict(session)
    classification, classification_reason, failed_rules, degraded_rules = classify_session_payload(payload)
    run_type = recommended_run_type(payload)
    return {
        "classification_reason": classification_reason,
        "failed_rules": failed_rules,
        "degraded_rules": degraded_rules,
        "evidence_ready": evidence_ready(payload),
        "recommended_run_type": run_type,
        "evidence_export_hint": (
            f"python3 scripts/export_session_to_evidence_bundle.py --data-root <data_root> --session-id {payload.get('session_id')} --evidence-root verification/evidence/<timestamp> --run-type {run_type}"
        ),
    }


def copy_if_exists(src: Path, dest: Path) -> None:
    if src.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def export_session_to_evidence_bundle(
    data_root: str | Path,
    session_id: str,
    evidence_root: str | Path,
    *,
    run_type: str | None = None,
    reviewer: str = "operator",
) -> Path:
    data_root_path = Path(data_root)
    session_path = data_root_path / "sessions" / session_id / "session.json"
    if not session_path.exists():
        raise FileNotFoundError(f"missing session file: {session_path}")

    session = json.loads(session_path.read_text(encoding="utf-8"))
    evidence_root_path = Path(evidence_root)
    for name in ("room", "uploads", "processing", "artifacts", "review", "metrics"):
        (evidence_root_path / name).mkdir(parents=True, exist_ok=True)

    copy_if_exists(session_path, evidence_root_path / "room" / "session.json")
    room_id = session.get("room_id")
    if room_id:
        copy_if_exists(data_root_path / "rooms" / room_id / "room.json", evidence_root_path / "room" / "room.json")

    upload_summaries: list[dict[str, Any]] = []
    for file in session.get("files", []):
        out = {
            "file_id": file.get("file_id"),
            "participant_id": file.get("participant_id"),
            "filename": file.get("filename"),
            "device_id": file.get("device_id"),
            "recording_started_at": file.get("recording_started_at"),
            "start_command_received_at": file.get("start_command_received_at"),
            "mic_route": file.get("mic_route"),
            "audio_processing_flags": file.get("audio_processing_flags", {}),
            "container": file.get("container"),
            "codec": file.get("codec"),
            "sample_rate_hz": file.get("sample_rate_hz"),
            "channels": file.get("channels"),
            "duration_seconds": file.get("duration_seconds"),
            "baseline_valid": file.get("baseline_valid", True),
            "violations": file.get("violations", []),
            "rejection_reason": file.get("rejection_reason"),
        }
        target = evidence_root_path / "uploads" / f"{file.get('participant_id', file.get('file_id', 'unknown'))}.json"
        target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        upload_summaries.append(out)
    (evidence_root_path / "uploads" / "upload-summary.json").write_text(
        json.dumps({"count": len(upload_summaries), "files": upload_summaries}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (evidence_root_path / "processing" / "session-summary.json").write_text(
        json.dumps(
            {
                "session_id": session.get("session_id"),
                "status": session.get("status"),
                "stage": session.get("stage"),
                "qa_summary": session.get("qa_summary", {}),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    artifact_entries: list[dict[str, Any]] = []
    logical_map: dict[str, str] = {}
    for artifact in session.get("artifacts", []):
        src = Path(artifact["path"])
        dest = evidence_root_path / "artifacts" / src.name
        copy_if_exists(src, dest)
        artifact_entries.append({"path": f"artifacts/{src.name}", "kind": artifact.get("kind"), "required": True})
        if artifact.get("kind") == "manifest":
            logical_map["manifest"] = f"artifacts/{src.name}"
        elif artifact.get("kind") == "manifest_export":
            logical_map["manifest_export"] = f"artifacts/{src.name}"
        elif artifact.get("kind") == "bundle":
            logical_map["bundle"] = f"artifacts/{src.name}"
        elif artifact.get("kind") == "mixdown":
            logical_map["mixdown"] = f"artifacts/{src.name}"
    (evidence_root_path / "artifacts-index.json").write_text(
        json.dumps({"files": artifact_entries}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    classification, classification_reason, failed_rules, degraded_rules = classify_session_payload(session)
    (evidence_root_path / "classification.json").write_text(
        json.dumps(
            {
                "classification": classification,
                "classification_reason": classification_reason,
                "failed_rules": failed_rules,
                "degraded_rules": degraded_rules,
                "reviewer": reviewer,
                "decided_at": "pending" if classification == "baseline-valid" else "generated",
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    effective_run_type = run_type or recommended_run_type(session)
    bundle = {
        "schema_version": "audio-sync-platform/evidence-bundle/v1",
        "bundle_id": evidence_root_path.name,
        "run_type": effective_run_type,
        "protocol_version": session.get("protocol_version", "recording-protocol/v1"),
        "classification": classification,
        "classification_reason": classification_reason,
        "session": {
            "session_id": session.get("session_id"),
            "room_id": session.get("room_id"),
            "start_strategy": session.get("start_strategy"),
            "anchor_policy": session.get("anchor_policy"),
        },
        "participants": {
            "expected": session.get("limits", {}).get("max_participants"),
            "received_files": len(session.get("files", [])),
        },
        "metrics": session.get("qa_summary", {}),
        "artifacts": logical_map,
        "residual_blockers": [],
    }
    (evidence_root_path / "bundle.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (evidence_root_path / "bundle.md").write_text(
        "\n".join([
            "# Evidence Bundle Summary",
            "",
            f"- Bundle ID: {evidence_root_path.name}",
            f"- Run type: {effective_run_type}",
            f"- Classification: {classification}",
            f"- Classification reason: {classification_reason}",
            f"- Session ID: {session.get('session_id')}",
            f"- Room ID: {session.get('room_id')}",
            f"- Start strategy: {session.get('start_strategy')}",
            f"- Anchor policy: {session.get('anchor_policy')}",
            "",
            "## Artifacts",
            *(f"- {key}: {value}" for key, value in logical_map.items()),
        ]) + "\n",
        encoding="utf-8",
    )

    return evidence_root_path
