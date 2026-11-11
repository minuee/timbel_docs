from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import utc_now


def _strict_fields(payload: dict[str, Any], required: tuple[str, ...], context: str) -> None:
    missing = [field for field in required if field not in payload]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"{context} missing required fields: {joined}")


def _dump(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_compact(item) for item in value]
    return value


@dataclass(slots=True)
class SessionMetadata:
    session_id: str
    room_id: str
    host_id: str
    protocol_version: str
    start_strategy: str
    anchor_policy: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionMetadata":
        _strict_fields(
            payload,
            ("session_id", "room_id", "host_id", "protocol_version", "start_strategy", "anchor_policy"),
            "session",
        )
        return cls(**payload)


@dataclass(slots=True)
class ParticipantMetadata:
    participant_id: str
    display_name: str | None = None
    role: str = "member"

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ParticipantMetadata":
        _strict_fields(payload, ("participant_id",), "participant")
        return cls(**payload)


@dataclass(slots=True)
class RecordingMetadata:
    recording_id: str
    filename: str
    container: str
    codec: str
    duration_seconds: float | None = None
    pause_resume_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RecordingMetadata":
        _strict_fields(payload, ("recording_id", "filename", "container", "codec"), "recording")
        return cls(**payload)


@dataclass(slots=True)
class DeviceMetadata:
    device_id: str
    device_model: str | None = None
    os_type: str = "unknown"
    os_version: str = "unknown"
    app_version: str = "unknown"
    mic_route: str = "unknown"
    audio_processing_flags: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeviceMetadata":
        _strict_fields(payload, ("device_id",), "device")
        return cls(**payload)


@dataclass(slots=True)
class TimingMetadata:
    start_command_issued_at: str | None = None
    start_command_received_at: str | None = None
    recording_started_at: str | None = None
    recording_stopped_at: str | None = None
    local_monotonic_started_at_ms: float | None = None
    server_time_offset_ms: float | None = None
    round_trip_ms: float | None = None
    sync_quality_bucket: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TimingMetadata":
        return cls(**payload)


@dataclass(slots=True)
class AudioMetadataEnvelope:
    sample_rate: int
    channels: int
    bit_depth: int | None = None
    format_profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AudioMetadataEnvelope":
        _strict_fields(payload, ("sample_rate", "channels"), "audio")
        return cls(**payload)


@dataclass(slots=True)
class AnchorMetadata:
    anchor_type: str
    anchor_expected_at: str | None = None
    anchor_expected_offset_ms_from_start_command: int | None = None
    anchor_repeat_policy: str = "none"
    anchor_spec_version: str | None = None
    beep_duration_ms: int | None = None
    beep_frequency_hz: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AnchorMetadata":
        _strict_fields(payload, ("anchor_type",), "anchor")
        return cls(**payload)


@dataclass(slots=True)
class UploadMetadata:
    sha256: str
    filesize_bytes: int
    upload_started_at: str | None = None
    upload_completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UploadMetadata":
        _strict_fields(payload, ("sha256", "filesize_bytes"), "upload")
        return cls(**payload)


@dataclass(slots=True)
class RecordingEnvelope:
    schema_version: str
    session: SessionMetadata
    participant: ParticipantMetadata
    recording: RecordingMetadata
    device: DeviceMetadata
    timing: TimingMetadata
    audio: AudioMetadataEnvelope
    anchor: AnchorMetadata
    upload: UploadMetadata

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session": self.session.to_dict(),
            "participant": self.participant.to_dict(),
            "recording": self.recording.to_dict(),
            "device": self.device.to_dict(),
            "timing": self.timing.to_dict(),
            "audio": self.audio.to_dict(),
            "anchor": self.anchor.to_dict(),
            "upload": self.upload.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RecordingEnvelope":
        _strict_fields(
            payload,
            ("schema_version", "session", "participant", "recording", "device", "timing", "audio", "anchor", "upload"),
            "recording envelope",
        )
        return cls(
            schema_version=payload["schema_version"],
            session=SessionMetadata.from_dict(payload["session"]),
            participant=ParticipantMetadata.from_dict(payload["participant"]),
            recording=RecordingMetadata.from_dict(payload["recording"]),
            device=DeviceMetadata.from_dict(payload["device"]),
            timing=TimingMetadata.from_dict(payload["timing"]),
            audio=AudioMetadataEnvelope.from_dict(payload["audio"]),
            anchor=AnchorMetadata.from_dict(payload["anchor"]),
            upload=UploadMetadata.from_dict(payload["upload"]),
        )


def validate_required_fields(envelope: RecordingEnvelope) -> list[str]:
    violations: list[str] = []
    if not envelope.timing.recording_started_at:
        violations.append("timing.recording_started_at_missing")
    if not envelope.session.session_id:
        violations.append("session.session_id_missing")
    if not envelope.participant.participant_id:
        violations.append("participant.participant_id_missing")
    if not envelope.recording.filename:
        violations.append("recording.filename_missing")
    return violations


def classify_baseline(envelope: RecordingEnvelope) -> tuple[bool, list[str], str]:
    violations = validate_required_fields(envelope)

    if envelope.session.start_strategy != "server_authoritative_beep":
        violations.append("start_strategy_not_server_authoritative_beep")
    if envelope.anchor.anchor_type != "beep":
        violations.append("anchor_type_not_beep")
    if envelope.device.mic_route != "built_in_mic":
        violations.append("mic_route_bluetooth_not_allowed")
    if envelope.audio.sample_rate != 48_000:
        violations.append("sample_rate_not_48000")
    if envelope.audio.channels != 1:
        violations.append("channels_not_mono")
    if envelope.recording.container != "wav":
        violations.append("container_not_wav")
    if envelope.recording.pause_resume_events:
        violations.append("pause_resume_not_allowed")

    if violations:
        return False, violations, "degraded"
    return True, [], "baseline_valid"


def degraded_envelope_from_legacy(
    *,
    session_id: str,
    participant_id: str,
    filename: str,
) -> RecordingEnvelope:
    return RecordingEnvelope(
        schema_version="audio-sync-platform/v1",
        session=SessionMetadata(
            session_id=session_id,
            room_id="legacy_unknown",
            host_id="legacy_unknown",
            protocol_version="legacy",
            start_strategy="legacy_unknown",
            anchor_policy="none",
        ),
        participant=ParticipantMetadata(participant_id=participant_id),
        recording=RecordingMetadata(
            recording_id=f"legacy_{participant_id}",
            filename=filename,
            container="unknown",
            codec="unknown",
        ),
        device=DeviceMetadata(device_id="legacy_unknown"),
        timing=TimingMetadata(),
        audio=AudioMetadataEnvelope(sample_rate=0, channels=0),
        anchor=AnchorMetadata(anchor_type="none"),
        upload=UploadMetadata(sha256="", filesize_bytes=0),
    )


def as_payload(value: Any) -> Any:
    return _dump(value)
