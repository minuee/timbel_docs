from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


RoomState = str
ParticipantState = str
MetadataStatus = str
BinaryStatus = str
ValidationStatus = str


@dataclass(slots=True)
class ParticipantRecord:
    participant_id: str
    display_name: str | None = None
    device_id: str = ""
    os_type: str = "unknown"
    os_version: str = ""
    app_version: str = ""
    recorder_engine: str = ""
    mic_route: str = "unknown"
    audio_processing_flags: dict[str, bool] = field(default_factory=dict)
    state: ParticipantState = "joined"
    joined_at: str = field(default_factory=utc_now)
    preflight_passed_at: str | None = None
    preflight_snapshot: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RoomEventRecord:
    event_id: str
    room_id: str
    event_type: str
    participant_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RoomRecord:
    room_id: str
    host_participant_id: str
    protocol_version: str = "recording-protocol/v1"
    start_strategy: str = "server_authoritative_beep"
    anchor_policy: str = "beep_required"
    mode: str = "research"
    state: RoomState = "created"
    expected_participant_count: int = 5
    minimum_ready_participants: int = 1
    session_id: str | None = None
    join_code: str = ""
    evidence_auto_export: bool = False
    evidence_default_run_type: str | None = None
    start_command_id: str | None = None
    server_start_issued_at: str | None = None
    anchor_type: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    participants: list[ParticipantRecord] = field(default_factory=list)
    events: list[RoomEventRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["participants"] = [entry.to_dict() for entry in self.participants]
        payload["events"] = [entry.to_dict() for entry in self.events]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RoomRecord":
        return cls(
            room_id=payload["room_id"],
            host_participant_id=payload["host_participant_id"],
            protocol_version=payload.get("protocol_version", "recording-protocol/v1"),
            start_strategy=payload.get("start_strategy", "server_authoritative_beep"),
            anchor_policy=payload.get("anchor_policy", "beep_required"),
            mode=payload.get("mode", "research"),
            state=payload.get("state", "created"),
            expected_participant_count=payload.get("expected_participant_count", 5),
            minimum_ready_participants=payload.get("minimum_ready_participants", 1),
            session_id=payload.get("session_id"),
            join_code=payload.get("join_code", ""),
            evidence_auto_export=payload.get("evidence_auto_export", False),
            evidence_default_run_type=payload.get("evidence_default_run_type"),
            start_command_id=payload.get("start_command_id"),
            server_start_issued_at=payload.get("server_start_issued_at"),
            anchor_type=payload.get("anchor_type"),
            created_at=payload.get("created_at", utc_now()),
            updated_at=payload.get("updated_at", utc_now()),
            participants=[ParticipantRecord(**entry) for entry in payload.get("participants", [])],
            events=[RoomEventRecord(**entry) for entry in payload.get("events", [])],
        )


@dataclass(slots=True)
class RecordingRecord:
    recording_id: str
    session_id: str
    participant_id: str
    metadata_status: MetadataStatus = "missing"
    binary_status: BinaryStatus = "missing"
    validation_status: ValidationStatus = "pending"
    control_metadata: dict[str, Any] = field(default_factory=dict)
    audio_file: dict[str, Any] = field(default_factory=dict)
    uploaded_path: str | None = None
    rejection_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FileRecord:
    file_id: str
    participant_id: str
    filename: str
    uploaded_path: str
    recording_id: str | None = None
    format_name: str = "unknown"
    sha256: str = ""
    filesize_bytes: int = 0
    room_id: str | None = None
    session_id: str | None = None
    device_id: str = ""
    classification: str = "baseline_valid"
    baseline_valid: bool = True
    violations: list[str] = field(default_factory=list)
    container: str = "unknown"
    codec: str = "unknown"
    sample_rate_hz: int | None = None
    channels: int | None = None
    duration_seconds: float | None = None
    status: str = "uploaded"
    rejection_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    recording_metadata: dict[str, Any] | None = None
    mic_route: str = "unknown"
    audio_processing_flags: dict[str, bool] = field(default_factory=dict)
    start_command_id: str | None = None
    server_start_issued_at: str | None = None
    start_command_received_at: str | None = None
    client_record_invoked_at: str | None = None
    recording_started_at: str | None = None
    local_monotonic_start_tick: int | None = None
    anchor_type: str | None = None
    anchor_expected_at: str | None = None
    anchor_detected_at: str | None = None
    pause_resume_events: list[dict[str, Any]] = field(default_factory=list)
    canonical_path: str | None = None
    stt_path: str | None = None
    aligned_path: str | None = None
    offset_seconds: float = 0.0
    drift_ppm: float = 0.0
    correction_factor: float = 1.0
    alignment_confidence: float = 0.0
    loudness_dbfs: float | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArtifactRecord:
    artifact_id: str
    kind: str
    name: str
    path: str
    mime_type: str
    sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    status: str = "queued"
    stage: str = "queued"
    state: str = "open"
    room_id: str | None = None
    host_id: str | None = None
    mode: str = "research"
    protocol_version: str = "recording-protocol/v1"
    start_strategy: str = "legacy_unknown"
    anchor_policy: str = "none"
    join_code: str | None = None
    evidence_auto_export: bool = False
    evidence_default_run_type: str | None = None
    start_command_id: str | None = None
    server_start_issued_at: str | None = None
    anchor_type: str | None = None
    closed_at: str | None = None
    archive_dir: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    participant_ids: list[str] = field(default_factory=list)
    files: list[FileRecord] = field(default_factory=list)
    recordings: list[RecordingRecord] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    classification: str = "baseline"
    classification_reason: str = ""
    failed_rules: list[str] = field(default_factory=list)
    degraded_rules: list[str] = field(default_factory=list)
    evidence_ready: bool = False
    recommended_run_type: str | None = None
    evidence_export_hint: str | None = None
    evidence_bundle_path: str | None = None
    evidence_exported_at: str | None = None
    evidence_run_type: str | None = None
    artifacts_index_path: str | None = None
    qa_summary: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    limits: dict[str, Any] = field(
        default_factory=lambda: {"max_participants": 5, "max_duration_seconds": 3600}
    )
    scope_audit: dict[str, Any] = field(
        default_factory=lambda: {
            "real_time": False,
            "speaker_diarization": False,
            "speaker_identification": False,
            "manual_editing_ui": False,
            "video_sync": False,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["files"] = [entry.to_dict() for entry in self.files]
        payload["recordings"] = [entry.to_dict() for entry in self.recordings]
        payload["artifacts"] = [entry.to_dict() for entry in self.artifacts]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionRecord":
        return cls(
            session_id=payload["session_id"],
            status=payload.get("status", "queued"),
            stage=payload.get("stage", "queued"),
            state=payload.get("state", "open"),
            room_id=payload.get("room_id"),
            host_id=payload.get("host_id"),
            mode=payload.get("mode", "research"),
            protocol_version=payload.get("protocol_version", "recording-protocol/v1"),
            start_strategy=payload.get("start_strategy", "legacy_unknown"),
            anchor_policy=payload.get("anchor_policy", "none"),
            join_code=payload.get("join_code"),
            evidence_auto_export=payload.get("evidence_auto_export", False),
            evidence_default_run_type=payload.get("evidence_default_run_type"),
            start_command_id=payload.get("start_command_id"),
            server_start_issued_at=payload.get("server_start_issued_at"),
            anchor_type=payload.get("anchor_type"),
            closed_at=payload.get("closed_at"),
            archive_dir=payload.get("archive_dir"),
            created_at=payload.get("created_at", utc_now()),
            updated_at=payload.get("updated_at", utc_now()),
            participant_ids=payload.get("participant_ids", []),
            files=[FileRecord(**entry) for entry in payload.get("files", [])],
            recordings=[RecordingRecord(**entry) for entry in payload.get("recordings", [])],
            artifacts=[ArtifactRecord(**entry) for entry in payload.get("artifacts", [])],
            events=payload.get("events", []),
            classification=payload.get("classification", "baseline"),
            classification_reason=payload.get("classification_reason", ""),
            failed_rules=payload.get("failed_rules", []),
            degraded_rules=payload.get("degraded_rules", []),
            evidence_ready=payload.get("evidence_ready", False),
            recommended_run_type=payload.get("recommended_run_type"),
            evidence_export_hint=payload.get("evidence_export_hint"),
            evidence_bundle_path=payload.get("evidence_bundle_path"),
            evidence_exported_at=payload.get("evidence_exported_at"),
            evidence_run_type=payload.get("evidence_run_type"),
            artifacts_index_path=payload.get("artifacts_index_path"),
            qa_summary=payload.get("qa_summary", {}),
            errors=payload.get("errors", []),
            limits=payload.get(
                "limits", {"max_participants": 5, "max_duration_seconds": 3600}
            ),
            scope_audit=payload.get("scope_audit", {}),
        )
