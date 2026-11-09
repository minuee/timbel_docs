from __future__ import annotations

from typing import Any

from .models import RoomEventRecord, RoomRecord, SessionRecord, new_id, utc_now


def append_protocol_event(
    room: RoomRecord,
    *,
    event_type: str,
    participant_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> RoomEventRecord:
    event = RoomEventRecord(
        event_id=new_id("event"),
        room_id=room.room_id,
        event_type=event_type,
        participant_id=participant_id,
        payload=payload or {},
    )
    room.events.append(event)
    room.updated_at = utc_now()
    return event


def classify_session(session: SessionRecord) -> str:
    if session.mode != "research":
        return "field"
    if any(file.rejection_reason for file in session.files):
        return "degraded"
    if any(not file.baseline_valid for file in session.files):
        return "degraded"
    return "baseline"


def summarize_room_readiness(room: RoomRecord) -> dict[str, Any]:
    ready = [participant.participant_id for participant in room.participants if participant.state == "ready"]
    blocked = [
        {
            "participant_id": participant.participant_id,
            "state": participant.state,
            "preflight_passed_at": participant.preflight_passed_at,
        }
        for participant in room.participants
        if participant.state != "ready"
    ]
    return {
        "room_id": room.room_id,
        "state": room.state,
        "ready_count": len(ready),
        "ready_participants": ready,
        "blocked_participants": blocked,
    }
