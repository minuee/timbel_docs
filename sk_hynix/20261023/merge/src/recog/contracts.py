from __future__ import annotations

from typing import Any

from .rooms import CapturePolicyError, MetadataValidationError


RESEARCH_REQUIRED_UPLOAD_FIELDS = (
    "start_command_id",
    "server_start_issued_at",
    "start_command_received_at",
    "client_record_invoked_at",
    "local_monotonic_start_tick",
    "anchor_type",
    "anchor_expected_at",
)


def _require_fields(payload: dict[str, Any], fields: tuple[str, ...] | list[str]) -> None:
    for field in fields:
        if field not in payload:
            raise MetadataValidationError(f"missing field: {field}")




def validate_create_room_payload(payload: dict[str, Any]) -> None:
    _require_fields(payload, ["host_participant_id"])
    expected = payload.get("expected_participant_count", 5)
    minimum_ready = payload.get("minimum_ready_participants", 1)
    if not isinstance(expected, int) or expected < 1 or expected > 5:
        raise MetadataValidationError("expected_participant_count must be between 1 and 5")
    if not isinstance(minimum_ready, int) or minimum_ready < 1 or minimum_ready > expected:
        raise MetadataValidationError("minimum_ready_participants must be between 1 and expected_participant_count")
    mode = payload.get("mode", "research")
    if mode not in {"research", "pilot"}:
        raise MetadataValidationError("mode must be 'research' or 'pilot'")
    if "evidence_auto_export" in payload and not isinstance(payload["evidence_auto_export"], bool):
        raise MetadataValidationError("evidence_auto_export must be a boolean")
    if "evidence_default_run_type" in payload and payload["evidence_default_run_type"] not in {None, "synthetic", "controlled_device", "field"}:
        raise MetadataValidationError("evidence_default_run_type must be synthetic, controlled_device, field, or null")


def validate_join_room_payload(payload: dict[str, Any]) -> None:
    _require_fields(payload, ["participant_id", "device_id", "os_type", "os_version", "app_version"])
    if payload.get("os_type") not in {"ios", "android"}:
        raise MetadataValidationError("os_type must be 'ios' or 'android'")


def validate_start_room_payload(payload: dict[str, Any], *, mode: str) -> None:
    _require_fields(payload, ["participant_id", "anchor_type"])
    if payload.get("anchor_type") not in {"beep", "clap"}:
        raise MetadataValidationError("anchor_type must be 'beep' or 'clap'")
    if mode == "research" and payload.get("anchor_type") not in {"beep", "clap"}:
        raise CapturePolicyError("research_mode_requires_anchor")

def validate_ready_payload(payload: dict[str, Any], *, mode: str) -> None:
    _require_fields(payload, ["participant_id", "recorder_engine", "mic_route", "audio_processing_flags"])
    flags = payload["audio_processing_flags"]
    if not isinstance(flags, dict):
        raise MetadataValidationError("audio_processing_flags must be an object")
    _require_fields(flags, ["agc", "noise_suppression", "echo_cancellation"])
    if mode == "research":
        if payload.get("mic_route") != "built_in_mic":
            raise CapturePolicyError("research_mode_requires_built_in_mic")
        if any(bool(flags[name]) for name in ("agc", "noise_suppression", "echo_cancellation")):
            raise CapturePolicyError("research_mode_requires_processing_flags_disabled")


def validate_preflight_payload(payload: dict[str, Any], *, mode: str) -> list[str]:
    _require_fields(
        payload,
        ["participant_id", "recorder_engine", "mic_route", "audio_processing_flags", "permission_state", "time_sync"],
    )
    flags = payload["audio_processing_flags"]
    if not isinstance(flags, dict):
        raise MetadataValidationError("audio_processing_flags must be an object")
    _require_fields(flags, ["agc", "noise_suppression", "echo_cancellation"])

    permission_state = payload["permission_state"]
    if not isinstance(permission_state, dict):
        raise MetadataValidationError("permission_state must be an object")
    if permission_state.get("microphone") != "granted":
        raise CapturePolicyError("microphone_permission_required")

    time_sync = payload["time_sync"]
    if not isinstance(time_sync, dict):
        raise MetadataValidationError("time_sync must be an object")
    _require_fields(time_sync, ["server_time_offset_ms", "round_trip_ms", "sync_quality_bucket"])

    warnings: list[str] = []
    if mode == "research":
        if payload.get("mic_route") != "built_in_mic":
            raise CapturePolicyError("research_mode_requires_built_in_mic")
        if any(bool(flags[name]) for name in ("agc", "noise_suppression", "echo_cancellation")):
            raise CapturePolicyError("research_mode_requires_processing_flags_disabled")
        if time_sync.get("sync_quality_bucket") in {"degraded", "poor"}:
            warnings.append("time_sync_quality_degraded")
    return warnings


def validate_upload_metadata(payload: dict[str, Any], *, mode: str) -> None:
    required = [
        "room_id",
        "session_id",
        "participant_id",
        "device_id",
        "filename",
        "container",
        "codec",
        "sample_rate_hz",
        "channels",
        "duration_seconds",
        "mic_route",
        "audio_processing_flags",
        "recording_started_at",
        "os_type",
        "os_version",
        "app_version",
    ]
    _require_fields(payload, required)

    flags = payload["audio_processing_flags"]
    if not isinstance(flags, dict):
        raise MetadataValidationError("audio_processing_flags must be an object")
    _require_fields(flags, ["agc", "noise_suppression", "echo_cancellation"])

    if mode == "research":
        _require_fields(payload, RESEARCH_REQUIRED_UPLOAD_FIELDS)
        if payload.get("container") != "wav":
            raise CapturePolicyError("research_mode_requires_wav")
        if payload.get("sample_rate_hz") != 48000:
            raise CapturePolicyError("research_mode_requires_48khz")
        if payload.get("channels") != 1:
            raise CapturePolicyError("research_mode_requires_mono")
        if payload.get("mic_route") != "built_in_mic":
            raise CapturePolicyError("research_mode_requires_built_in_mic")
        if payload.get("pause_resume_events"):
            raise CapturePolicyError("pause_resume_not_allowed")
