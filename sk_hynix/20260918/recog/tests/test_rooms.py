from __future__ import annotations

import importlib.util
import sys
import tempfile
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

src_rooms = importlib.import_module(f"{PACKAGE_NAME}.rooms")
src_store = importlib.import_module(f"{PACKAGE_NAME}.store")
RoomStateError = src_rooms.RoomStateError
SessionStore = src_store.SessionStore


class RoomStoreTests(unittest.TestCase):
    def test_create_room_persists_created_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "data")
            room = store.create_room(
                host_participant_id="host_001",
                expected_participant_count=3,
                minimum_ready_participants=2,
                mode="research",
            )
            loaded = store.get_room(room.room_id)
            self.assertEqual(loaded.state, "created")
            self.assertEqual(loaded.host_participant_id, "host_001")
            self.assertEqual(loaded.protocol_version, "recording-protocol/v1")
            self.assertEqual(loaded.start_strategy, "server_authoritative_beep")
            self.assertEqual(loaded.anchor_policy, "beep_required")
            self.assertEqual(loaded.minimum_ready_participants, 2)
            self.assertEqual(loaded.mode, "research")

    def test_join_transitions_room_to_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "data")
            room = store.create_room(host_participant_id="host_001")
            store.join_room(
                room.room_id,
                participant_id="host_001",
                device_id="dev_host",
                os_type="ios",
                os_version="18.0",
                app_version="0.1.0",
            )
            loaded = store.get_room(room.room_id)
            self.assertEqual(loaded.state, "open")
            self.assertEqual(len(loaded.participants), 1)
            self.assertEqual(loaded.participants[0].participant_id, "host_001")

    def test_ready_threshold_promotes_ready_to_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "data")
            room = store.create_room(host_participant_id="host_001", minimum_ready_participants=2)
            store.join_room(
                room.room_id,
                participant_id="host_001",
                device_id="dev_host",
                os_type="ios",
                os_version="18.0",
                app_version="0.1.0",
            )
            store.join_room(
                room.room_id,
                participant_id="p_002",
                device_id="dev_2",
                os_type="android",
                os_version="15",
                app_version="0.1.0",
            )
            store.record_preflight(
                room.room_id,
                "host_001",
                recorder_engine="native_bridge_v1",
                mic_route="built_in_mic",
                audio_processing_flags={"agc": False, "noise_suppression": False, "echo_cancellation": False},
                permission_state={"microphone": "granted"},
                time_sync={"server_time_offset_ms": 0.0, "round_trip_ms": 15.0, "sync_quality_bucket": "good"},
            )
            store.record_preflight(
                room.room_id,
                "p_002",
                recorder_engine="native_bridge_v1",
                mic_route="built_in_mic",
                audio_processing_flags={"agc": False, "noise_suppression": False, "echo_cancellation": False},
                permission_state={"microphone": "granted"},
                time_sync={"server_time_offset_ms": 0.0, "round_trip_ms": 15.0, "sync_quality_bucket": "good"},
            )
            store.mark_ready(room.room_id, "host_001")
            store.mark_ready(room.room_id, "p_002")
            loaded = store.get_room(room.room_id)
            self.assertEqual(loaded.state, "ready_to_start")
            self.assertEqual([p.state for p in loaded.participants], ["ready", "ready"])

    def test_non_host_cannot_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "data")
            room = store.create_room(host_participant_id="host_001", minimum_ready_participants=1)
            store.join_room(
                room.room_id,
                participant_id="host_001",
                device_id="dev_host",
                os_type="ios",
                os_version="18.0",
                app_version="0.1.0",
            )
            store.join_room(
                room.room_id,
                participant_id="p_002",
                device_id="dev_2",
                os_type="android",
                os_version="15",
                app_version="0.1.0",
            )
            store.record_preflight(
                room.room_id,
                "host_001",
                recorder_engine="native_bridge_v1",
                mic_route="built_in_mic",
                audio_processing_flags={"agc": False, "noise_suppression": False, "echo_cancellation": False},
                permission_state={"microphone": "granted"},
                time_sync={"server_time_offset_ms": 0.0, "round_trip_ms": 15.0, "sync_quality_bucket": "good"},
            )
            store.mark_ready(room.room_id, "host_001")
            with self.assertRaises(RoomStateError):
                store.start_room(room.room_id, participant_id="p_002", anchor_type="beep")

    def test_host_start_mints_session_and_start_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "data")
            room = store.create_room(host_participant_id="host_001", minimum_ready_participants=1)
            store.join_room(
                room.room_id,
                participant_id="host_001",
                device_id="dev_host",
                os_type="ios",
                os_version="18.0",
                app_version="0.1.0",
            )
            store.record_preflight(
                room.room_id,
                "host_001",
                recorder_engine="native_bridge_v1",
                mic_route="built_in_mic",
                audio_processing_flags={"agc": False, "noise_suppression": False, "echo_cancellation": False},
                permission_state={"microphone": "granted"},
                time_sync={"server_time_offset_ms": 0.0, "round_trip_ms": 15.0, "sync_quality_bucket": "good"},
            )
            store.mark_ready(room.room_id, "host_001")
            started = store.start_room(room.room_id, participant_id="host_001", anchor_type="beep")
            self.assertEqual(started.state, "recording")
            self.assertTrue(started.session_id)
            self.assertTrue(started.start_command_id)
            self.assertTrue(started.server_start_issued_at)
            session = store.get_session(started.session_id)
            self.assertEqual(session.room_id, room.room_id)
            self.assertEqual(session.host_id, "host_001")
            self.assertEqual(session.protocol_version, "recording-protocol/v1")
            self.assertEqual(session.start_strategy, "server_authoritative_beep")
            self.assertEqual(session.start_command_id, started.start_command_id)
            self.assertEqual(session.anchor_type, "beep")
            self.assertEqual(session.participant_ids, ["host_001"])
            self.assertEqual(session.events[0]["event_type"], "room_recording_started")

    def test_room_events_are_appended(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "data")
            room = store.create_room(host_participant_id="host_001", minimum_ready_participants=1)
            store.join_room(
                room.room_id,
                participant_id="host_001",
                device_id="dev_host",
                os_type="ios",
                os_version="18.0",
                app_version="0.1.0",
            )
            store.record_preflight(
                room.room_id,
                "host_001",
                recorder_engine="native_bridge_v1",
                mic_route="built_in_mic",
                audio_processing_flags={"agc": False, "noise_suppression": False, "echo_cancellation": False},
                permission_state={"microphone": "granted"},
                time_sync={"server_time_offset_ms": 0.0, "round_trip_ms": 15.0, "sync_quality_bucket": "good"},
            )
            store.mark_ready(room.room_id, "host_001")
            store.start_room(room.room_id, participant_id="host_001", anchor_type="beep")
            loaded = store.get_room(room.room_id)
            event_types = [event.event_type for event in loaded.events]
            self.assertEqual(
                event_types,
                ["participant_joined", "participant_preflight_passed", "participant_ready", "recording_started"],
            )
            session = store.get_session(loaded.session_id)
            self.assertEqual(session.events[0]["event_type"], "room_recording_started")

    def test_preflight_required_before_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "data")
            room = store.create_room(host_participant_id="host_001", minimum_ready_participants=1)
            store.join_room(
                room.room_id,
                participant_id="host_001",
                device_id="dev_host",
                os_type="ios",
                os_version="18.0",
                app_version="0.1.0",
            )
            with self.assertRaises(RoomStateError):
                store.mark_ready(room.room_id, "host_001")

    def test_host_can_stop_room_and_participants_become_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "data")
            room = store.create_room(host_participant_id="host_001", minimum_ready_participants=1)
            store.join_room(
                room.room_id,
                participant_id="host_001",
                device_id="dev_host",
                os_type="ios",
                os_version="18.0",
                app_version="0.1.0",
            )
            store.record_preflight(
                room.room_id,
                "host_001",
                recorder_engine="native_bridge_v1",
                mic_route="built_in_mic",
                audio_processing_flags={"agc": False, "noise_suppression": False, "echo_cancellation": False},
                permission_state={"microphone": "granted"},
                time_sync={"server_time_offset_ms": 0.0, "round_trip_ms": 15.0, "sync_quality_bucket": "good"},
            )
            store.mark_ready(room.room_id, "host_001")
            store.start_room(room.room_id, participant_id="host_001", anchor_type="beep")
            stopped = store.stop_room(room.room_id, participant_id="host_001")
            self.assertEqual(stopped.state, "stopped")
            self.assertEqual(stopped.participants[0].state, "stopped")

    def test_room_closes_after_expected_uploads_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "data")
            room = store.create_room(host_participant_id="host_001", expected_participant_count=1, minimum_ready_participants=1)
            store.join_room(
                room.room_id,
                participant_id="host_001",
                device_id="dev_host",
                os_type="ios",
                os_version="18.0",
                app_version="0.1.0",
            )
            store.record_preflight(
                room.room_id,
                "host_001",
                recorder_engine="native_bridge_v1",
                mic_route="built_in_mic",
                audio_processing_flags={"agc": False, "noise_suppression": False, "echo_cancellation": False},
                permission_state={"microphone": "granted"},
                time_sync={"server_time_offset_ms": 0.0, "round_trip_ms": 15.0, "sync_quality_bucket": "good"},
            )
            store.mark_ready(room.room_id, "host_001")
            started = store.start_room(room.room_id, participant_id="host_001", anchor_type="beep")
            store.stop_room(room.room_id, participant_id="host_001")
            store.register_recording_metadata(
                started.session_id,
                participant_id="host_001",
                recording_id="rec_01",
                control_metadata={
                    "recording_started_at": "2026-04-09T00:01:00Z",
                    "recording_stopped_at": "2026-04-09T00:05:00Z",
                    "mic_route": "built_in_mic",
                    "audio_processing_flags": {"agc": False, "noise_suppression": False, "echo_cancellation": False},
                    "anchor_type": "beep",
                },
                audio_file_metadata={
                    "filename": "host.wav",
                    "container": "wav",
                    "codec": "pcm_s16le",
                    "sample_rate_hz": 48000,
                    "channels": 1,
                    "duration_seconds": 240.0,
                },
            )
            store.attach_recording_binary(started.session_id, "rec_01", payload=b"RIFFfake", content_type="audio/wav")
            closed = store.get_room(room.room_id)
            self.assertEqual(closed.state, "closed")


if __name__ == "__main__":
    unittest.main()
