from __future__ import annotations

from .models import RoomRecord


class RoomStateError(RuntimeError):
    pass


class CapturePolicyError(RuntimeError):
    pass


class MetadataValidationError(RuntimeError):
    pass


def ready_count(room: RoomRecord) -> int:
    return sum(1 for participant in room.participants if participant.state == "ready")


def next_room_state_after_join(room: RoomRecord) -> str:
    return "open" if room.state == "created" else room.state


def next_room_state_after_ready(room: RoomRecord) -> str:
    threshold = max(1, room.minimum_ready_participants)
    if ready_count(room) >= threshold:
        return "ready_to_start"
    return "open"


def can_start(room: RoomRecord, participant_id: str) -> tuple[bool, str | None]:
    if participant_id != room.host_participant_id:
        return False, "only_host_can_start"
    if room.state not in {"open", "ready_to_start"}:
        return False, "invalid_room_state"
    if ready_count(room) < max(1, room.minimum_ready_participants):
        return False, "not_enough_ready_participants"
    return True, None


def can_stop(room: RoomRecord, participant_id: str) -> tuple[bool, str | None]:
    if participant_id != room.host_participant_id:
        return False, "only_host_can_stop"
    if room.state != "recording":
        return False, "invalid_room_state"
    return True, None


def can_ready(participant) -> tuple[bool, str | None]:
    if participant.preflight_passed_at is None:
        return False, "preflight_required"
    return True, None


def build_start_payload(room: RoomRecord) -> dict[str, str | None]:
    return {
        "room_id": room.room_id,
        "session_id": room.session_id,
        "start_command_id": room.start_command_id,
        "server_start_issued_at": room.server_start_issued_at,
        "anchor_type": room.anchor_type,
        "mode": room.mode,
    }
