from __future__ import annotations

import importlib
import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "recog"

PACKAGE_NAME = "src_recog"
if PACKAGE_NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        SRC_ROOT / "__init__.py",
        submodule_search_locations=[str(SRC_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to build import spec for src_recog")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)

events = importlib.import_module(f"{PACKAGE_NAME}.events")
models = importlib.import_module(f"{PACKAGE_NAME}.models")

append_protocol_event = events.append_protocol_event
classify_session = events.classify_session
summarize_room_readiness = events.summarize_room_readiness
FileRecord = models.FileRecord
ParticipantRecord = models.ParticipantRecord
RoomRecord = models.RoomRecord
SessionRecord = models.SessionRecord


class ProtocolModelTests(unittest.TestCase):
    def test_append_protocol_event_appends_event_and_updates_room(self) -> None:
        room = RoomRecord(room_id="room_1", host_participant_id="host_1")
        event = append_protocol_event(
            room,
            event_type="participant_ready",
            participant_id="host_1",
            payload={"ready": True},
        )
        self.assertEqual(event.event_type, "participant_ready")
        self.assertEqual(len(room.events), 1)
        self.assertEqual(room.events[0].payload["ready"], True)

    def test_classify_session_returns_baseline_for_clean_research_files(self) -> None:
        session = SessionRecord(session_id="session_1", mode="research")
        session.files.append(
            FileRecord(
                file_id="file_1",
                participant_id="p1",
                filename="a.wav",
                uploaded_path="/tmp/a.wav",
                baseline_valid=True,
            )
        )
        self.assertEqual(classify_session(session), "baseline")

    def test_classify_session_returns_degraded_when_any_file_is_not_baseline_valid(self) -> None:
        session = SessionRecord(session_id="session_1", mode="research")
        session.files.append(
            FileRecord(
                file_id="file_1",
                participant_id="p1",
                filename="a.wav",
                uploaded_path="/tmp/a.wav",
                baseline_valid=False,
                classification="degraded",
                violations=["mic_route_bluetooth_not_allowed"],
            )
        )
        self.assertEqual(classify_session(session), "degraded")

    def test_classify_session_returns_field_for_non_research_mode(self) -> None:
        session = SessionRecord(session_id="session_1", mode="field")
        self.assertEqual(classify_session(session), "field")

    def test_summarize_room_readiness_lists_ready_and_blocked_participants(self) -> None:
        room = RoomRecord(room_id="room_1", host_participant_id="host_1", state="ready_to_start")
        room.participants.extend(
            [
                ParticipantRecord(participant_id="host_1", state="ready"),
                ParticipantRecord(participant_id="p2", state="preflight_passed"),
            ]
        )
        summary = summarize_room_readiness(room)
        self.assertEqual(summary["ready_count"], 1)
        self.assertEqual(summary["ready_participants"], ["host_1"])
        self.assertEqual(summary["blocked_participants"][0]["participant_id"], "p2")


if __name__ == "__main__":
    unittest.main()
