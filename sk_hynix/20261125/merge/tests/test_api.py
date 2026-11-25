from __future__ import annotations

import base64
import importlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PARENT = PROJECT_ROOT / "src"
if str(SRC_PARENT) not in sys.path:
    sys.path.insert(0, str(SRC_PARENT))
SRC_ROOT = SRC_PARENT / "recog"
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

def _reload_src_recog() -> None:
    for name in list(sys.modules):
        if name == PACKAGE_NAME or name.startswith(f"{PACKAGE_NAME}."):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        SRC_ROOT / "__init__.py",
        submodule_search_locations=[str(SRC_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to rebuild import spec for src_recog")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)


def _create_app(*args, **kwargs):
    _reload_src_recog()
    return importlib.import_module(f"{PACKAGE_NAME}.api").create_app(*args, **kwargs)


def _generate_fixture_session(*args, **kwargs):
    return importlib.import_module(f"{PACKAGE_NAME}.synthetic").generate_fixture_session(*args, **kwargs)


def request(app, method: str, path: str, body: bytes = b"", query: str = "", content_type: str = ""):
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    environ["QUERY_STRING"] = query
    environ["CONTENT_LENGTH"] = str(len(body))
    environ["wsgi.input"] = io.BytesIO(body)
    if content_type:
        environ["CONTENT_TYPE"] = content_type
    captured = {}

    def start_response(status, headers):  # noqa: ANN001
        captured["status"] = status
        captured["headers"] = headers

    body_bytes = b"".join(app(environ, start_response))
    captured["body"] = json.loads(body_bytes.decode("utf-8"))
    return captured


class ResolveBindTests(unittest.TestCase):
    def test_resolve_bind_uses_provided_host_and_port(self) -> None:
        from src_recog.api import _resolve_bind

        host, port = _resolve_bind("192.168.1.1", 9000)
        self.assertEqual(host, "192.168.1.1")
        self.assertEqual(port, 9000)

    def test_resolve_bind_defaults_to_127_0_0_1_when_host_is_none(self) -> None:
        from src_recog.api import _resolve_bind

        host, port = _resolve_bind(None, 8080)
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 8080)

    def test_resolve_bind_defaults_to_8080_when_port_is_none(self) -> None:
        from src_recog.api import _resolve_bind

        host, port = _resolve_bind("0.0.0.0", None)
        self.assertEqual(host, "0.0.0.0")
        self.assertEqual(port, 8080)

    def test_resolve_bind_uses_env_recog_host_when_host_is_none(self) -> None:
        from src_recog.api import _resolve_bind

        old = os.environ.get("RECOG_HOST")
        os.environ["RECOG_HOST"] = "192.168.0.146"
        try:
            host, port = _resolve_bind(None, 8080)
            self.assertEqual(host, "192.168.0.146")
        finally:
            if old is None:
                os.environ.pop("RECOG_HOST", None)
            else:
                os.environ["RECOG_HOST"] = old

    def test_resolve_bind_uses_env_recog_port_when_port_is_none(self) -> None:
        from src_recog.api import _resolve_bind

        old = os.environ.get("RECOG_PORT")
        os.environ["RECOG_PORT"] = "9999"
        try:
            host, port = _resolve_bind("127.0.0.1", None)
            self.assertEqual(port, 9999)
        finally:
            if old is None:
                os.environ.pop("RECOG_PORT", None)
            else:
                os.environ["RECOG_PORT"] = old

    def test_resolve_bind_ignores_env_when_args_provided(self) -> None:
        from src_recog.api import _resolve_bind

        old_host = os.environ.get("RECOG_HOST")
        old_port = os.environ.get("RECOG_PORT")
        os.environ["RECOG_HOST"] = "ignored.host"
        os.environ["RECOG_PORT"] = "7777"
        try:
            host, port = _resolve_bind("explicit.host", 5555)
            self.assertEqual(host, "explicit.host")
            self.assertEqual(port, 5555)
        finally:
            if old_host is None:
                os.environ.pop("RECOG_HOST", None)
            else:
                os.environ["RECOG_HOST"] = old_host
            if old_port is None:
                os.environ.pop("RECOG_PORT", None)
            else:
                os.environ["RECOG_PORT"] = old_port


class HealthEndpointTests(unittest.TestCase):
    def test_health_endpoint_returns_ok_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            health = request(app, "GET", "/health")
            self.assertTrue(health["status"].startswith("200"))
            self.assertEqual(health["body"]["status"], "ok")
            self.assertEqual(health["body"]["service"], "recog")

    def test_health_endpoint_is_responsive_and_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            for _ in range(5):
                health = request(app, "GET", "/health")
                self.assertTrue(health["status"].startswith("200"))


class ApiTests(unittest.TestCase):
    def test_create_room_returns_room_and_session_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            app = _create_app(root)
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps(
                    {
                        "host_participant_id": "part_host_01",
                        "mode": "research",
                        "protocol_version": "v1",
                        "start_strategy": "server_authoritative_beep",
                        "anchor_policy": "beep_required",
                        "required_participant_count": 5,
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(created["status"].startswith("201"))
            self.assertIn("room_id", created["body"])
            self.assertIn("session_id", created["body"])
            self.assertIn("join_code", created["body"])
            self.assertEqual(created["body"]["state"], "created")
            self.assertEqual(created["body"]["protocol_version"], "v1")
            self.assertEqual(created["body"]["start_strategy"], "server_authoritative_beep")
            self.assertEqual(created["body"]["anchor_policy"], "beep_required")
            self.assertTrue((root / "rooms" / created["body"]["room_id"] / "room.json").exists())
            self.assertTrue((root / "sessions" / created["body"]["session_id"] / "session.json").exists())

    def test_create_room_returns_evidence_policy_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            app = _create_app(root)
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps(
                    {
                        "host_participant_id": "host_001",
                        "mode": "research",
                        "evidence_auto_export": True,
                        "evidence_default_run_type": "controlled_device",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(created["status"].startswith("201"))
            self.assertTrue(created["body"]["evidence_auto_export"])
            self.assertEqual(created["body"]["evidence_default_run_type"], "controlled_device")

    def test_create_room_rejects_missing_required_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps({"mode": "research"}).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(created["status"].startswith("422"))
            self.assertIn("host_participant_id", created["body"]["error"])

    def test_register_recording_metadata_creates_recording_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            app = _create_app(root)
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps({"host_participant_id": "part_host_01", "mode": "research"}).encode("utf-8"),
                content_type="application/json",
            )
            session_id = created["body"]["session_id"]
            payload = {
                "participant": {"participant_id": "part_01", "device_id": "dev_hash_abc123"},
                "time_sync": {
                    "server_time_offset_ms": -23.4,
                    "round_trip_ms": 81.0,
                    "sync_quality_bucket": "good",
                },
                "recording_event": {
                    "recording_id": "rec_01abcxyz",
                    "start_command_received_at": "2026-04-09T00:01:00.124Z",
                    "recording_started_at": "2026-04-09T00:01:00.412Z",
                    "recording_stopped_at": "2026-04-09T00:05:00.000Z",
                    "anchor_type": "beep",
                    "mic_route": "built_in_mic",
                    "audio_processing_flags": {
                        "agc": False,
                        "noise_suppression": False,
                        "echo_cancellation": False,
                    },
                },
                "audio_file": {
                    "filename": "part_01.wav",
                    "container": "wav",
                    "codec": "pcm_s16le",
                    "sample_rate_hz": 48000,
                    "channels": 1,
                    "duration_seconds": 240.0,
                },
            }
            registered = request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings",
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(registered["status"].startswith("201"))
            self.assertEqual(registered["body"]["recording_id"], "rec_01abcxyz")
            self.assertEqual(registered["body"]["metadata_status"], "registered")
            self.assertEqual(registered["body"]["binary_status"], "missing")
            session_path = root / "sessions" / session_id / "session.json"
            stored = json.loads(session_path.read_text())
            self.assertEqual(stored["recordings"][0]["recording_id"], "rec_01abcxyz")
            self.assertEqual(stored["events"][0]["event_type"], "recording_metadata_registered")

    def test_register_recording_metadata_rejects_missing_recording_started_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps({"host_participant_id": "part_host_01", "mode": "research"}).encode("utf-8"),
                content_type="application/json",
            )
            session_id = created["body"]["session_id"]
            payload = {
                "participant": {"participant_id": "part_01"},
                "recording_event": {
                    "recording_stopped_at": "2026-04-09T00:05:00.000Z",
                    "anchor_type": "beep",
                    "mic_route": "built_in_mic",
                    "audio_processing_flags": {
                        "agc": False,
                        "noise_suppression": False,
                        "echo_cancellation": False,
                    },
                },
                "audio_file": {
                    "filename": "part_01.wav",
                    "container": "wav",
                    "codec": "pcm_s16le",
                    "sample_rate_hz": 48000,
                    "channels": 1,
                    "duration_seconds": 240.0,
                },
            }
            registered = request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings",
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(registered["status"].startswith("400"))
            self.assertIn("recording_started_at", registered["body"]["error"])

    def test_get_room_returns_participants_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps({"host_participant_id": "host_001", "mode": "research"}).encode("utf-8"),
                content_type="application/json",
            )
            room_id = created["body"]["room_id"]
            request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "device_id": "dev_host",
                        "os_type": "ios",
                        "os_version": "18.0",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            room = request(app, "GET", f"/rooms/{room_id}")
            self.assertTrue(room["status"].startswith("200"))
            self.assertEqual(room["body"]["room_id"], room_id)
            self.assertEqual(room["body"]["host_participant_id"], "host_001")
            self.assertEqual(len(room["body"]["participants"]), 1)
            self.assertGreaterEqual(len(room["body"]["events"]), 1)
            self.assertIn("readiness", room["body"])
            self.assertEqual(room["body"]["readiness"]["ready_count"], 0)

    def test_preflight_returns_passed_state_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps({"host_participant_id": "host_001", "mode": "research"}).encode("utf-8"),
                content_type="application/json",
            )
            room_id = created["body"]["room_id"]
            request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "device_id": "dev_host",
                        "os_type": "ios",
                        "os_version": "18.0",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            preflight = request(
                app,
                "POST",
                f"/rooms/{room_id}/preflight",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                        "permission_state": {"microphone": "granted"},
                        "time_sync": {
                            "server_time_offset_ms": 1.5,
                            "round_trip_ms": 20.0,
                            "sync_quality_bucket": "good",
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(preflight["status"].startswith("200"))
            self.assertEqual(preflight["body"]["participant_state"], "preflight_passed")
            self.assertEqual(preflight["body"]["research_mode_blockers"], [])
            self.assertEqual(preflight["body"]["research_mode_warnings"], [])

    def test_get_room_reports_blocked_participant_before_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps({"host_participant_id": "host_001", "mode": "research"}).encode("utf-8"),
                content_type="application/json",
            )
            room_id = created["body"]["room_id"]
            request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "device_id": "dev_host",
                        "os_type": "ios",
                        "os_version": "18.0",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            room = request(app, "GET", f"/rooms/{room_id}")
            self.assertEqual(room["body"]["readiness"]["ready_count"], 0)
            blocked = room["body"]["readiness"]["blocked_participants"]
            self.assertEqual(blocked[0]["participant_id"], "host_001")
            self.assertEqual(blocked[0]["state"], "joined")

    def test_attach_recording_binary_links_recording_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            app = _create_app(root)
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps({"host_participant_id": "part_host_01", "mode": "research"}).encode("utf-8"),
                content_type="application/json",
            )
            session_id = created["body"]["session_id"]
            metadata_payload = {
                "participant": {"participant_id": "part_01", "device_id": "dev_hash_abc123"},
                "recording_event": {
                    "recording_id": "rec_upload_01",
                    "recording_started_at": "2026-04-09T00:01:00.412Z",
                    "recording_stopped_at": "2026-04-09T00:05:00.000Z",
                    "mic_route": "built_in_mic",
                    "audio_processing_flags": {
                        "agc": False,
                        "noise_suppression": False,
                        "echo_cancellation": False,
                    },
                    "anchor_type": "beep",
                },
                "audio_file": {
                    "filename": "part_01.wav",
                    "container": "wav",
                    "codec": "pcm_s16le",
                    "sample_rate_hz": 48000,
                    "channels": 1,
                    "duration_seconds": 240.0,
                },
            }
            request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings",
                body=json.dumps(metadata_payload).encode("utf-8"),
                content_type="application/json",
            )
            uploaded = request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings/rec_upload_01/file",
                body=b"RIFFfakewavpayload",
                content_type="audio/wav",
            )
            self.assertTrue(uploaded["status"].startswith("201"))
            self.assertEqual(uploaded["body"]["recording_id"], "rec_upload_01")
            self.assertEqual(uploaded["body"]["binary_status"], "uploaded")
            session = json.loads((root / "sessions" / session_id / "session.json").read_text())
            self.assertEqual(session["recordings"][0]["binary_status"], "uploaded")
            self.assertEqual(session["files"][0]["recording_id"], "rec_upload_01")
            event_types = [event["event_type"] for event in session["events"]]
            self.assertIn("recording_metadata_registered", event_types)
            self.assertIn("recording_binary_uploaded", event_types)

    def test_append_session_event_persists_timeline_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            app = _create_app(root)
            created = request(app, "POST", "/sessions")
            session_id = created["body"]["session_id"]
            event = request(
                app,
                "POST",
                f"/sessions/{session_id}/events",
                body=json.dumps(
                    {
                        "event": "start_received",
                        "participant_id": "participant_03",
                        "payload": {"received_at": "2026-04-09T10:05:00.071Z"},
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(event["status"].startswith("201"))
            self.assertEqual(event["body"]["event_type"], "start_received")
            session = json.loads((root / "sessions" / session_id / "session.json").read_text())
            self.assertEqual(len(session["events"]), 1)
            self.assertEqual(session["events"][0]["participant_id"], "participant_03")

    def test_process_accepts_api_requested_evidence_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            evidence_root = Path(tmpdir) / "api-evidence"
            app = _create_app(root)
            fixture = _generate_fixture_session(Path(tmpdir) / "fixture_api_evidence", track_count=2)
            created = request(app, "POST", "/sessions")
            session_id = created["body"]["session_id"]
            for track in fixture["tracks"]:
                uploaded = request(
                    app,
                    "POST",
                    f"/sessions/{session_id}/files",
                    body=Path(track["path"]).read_bytes(),
                    query=f"participant_id={track['participant_id']}&filename={track['filename']}",
                )
                self.assertTrue(uploaded["status"].startswith("201"))
            processed = request(
                app,
                "POST",
                f"/sessions/{session_id}/process",
                body=json.dumps(
                    {
                        "evidence_export_root": str(evidence_root),
                        "evidence_run_type": "synthetic",
                        "evidence_reviewer": "api_test",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(processed["status"].startswith("202"), processed)
            expected_bundle_root = str(evidence_root / session_id)
            self.assertIn("evidence", processed["body"])
            self.assertEqual(processed["body"]["evidence"]["evidence_bundle_path"], expected_bundle_root)
            self.assertEqual(processed["body"]["evidence"]["evidence_run_type"], "synthetic")
            self.assertTrue((evidence_root / session_id / "bundle.json").exists())
            self.assertTrue((evidence_root / session_id / "classification.json").exists())

    def test_process_uses_session_evidence_defaults_when_body_omits_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            auto_root = root / "evidence-auto"
            app = _create_app(root)
            fixture = _generate_fixture_session(Path(tmpdir) / "fixture_evidence_defaults", track_count=2)
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps(
                    {
                        "host_participant_id": "host_001",
                        "expected_participant_count": 1,
                        "minimum_ready_participants": 1,
                        "mode": "research",
                        "evidence_auto_export": True,
                        "evidence_default_run_type": "controlled_device",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            room_id = created["body"]["room_id"]
            session_id = created["body"]["session_id"]
            request(app, "POST", f"/rooms/{room_id}/join", body=json.dumps({"participant_id": "host_001", "device_id": "dev_host", "os_type": "ios", "os_version": "18.0", "app_version": "0.1.0"}).encode("utf-8"), content_type="application/json")
            request(app, "POST", f"/rooms/{room_id}/preflight", body=json.dumps({"participant_id": "host_001", "recorder_engine": "native_bridge_v1", "mic_route": "built_in_mic", "audio_processing_flags": {"agc": False, "noise_suppression": False, "echo_cancellation": False}, "permission_state": {"microphone": "granted"}, "time_sync": {"server_time_offset_ms": 0.0, "round_trip_ms": 12.0, "sync_quality_bucket": "good"}}).encode("utf-8"), content_type="application/json")
            request(app, "POST", f"/rooms/{room_id}/ready", body=json.dumps({"participant_id": "host_001", "recorder_engine": "native_bridge_v1", "mic_route": "built_in_mic", "audio_processing_flags": {"agc": False, "noise_suppression": False, "echo_cancellation": False}}).encode("utf-8"), content_type="application/json")
            request(app, "POST", f"/rooms/{room_id}/start", body=json.dumps({"participant_id": "host_001", "anchor_type": "beep"}).encode("utf-8"), content_type="application/json")
            request(app, "POST", f"/rooms/{room_id}/stop", body=json.dumps({"participant_id": "host_001"}).encode("utf-8"), content_type="application/json")
            request(app, "POST", f"/sessions/{session_id}/recordings", body=json.dumps({"participant": {"participant_id": "host_001", "device_id": "dev_host"}, "recording_event": {"recording_id": "rec_defaults_01", "recording_started_at": "2026-04-09T00:01:00.412Z", "recording_stopped_at": "2026-04-09T00:05:00.000Z", "mic_route": "built_in_mic", "audio_processing_flags": {"agc": False, "noise_suppression": False, "echo_cancellation": False}, "anchor_type": "beep"}, "audio_file": {"filename": "part_01.wav", "container": "wav", "codec": "pcm_s16le", "sample_rate_hz": 48000, "channels": 1, "duration_seconds": 240.0}}).encode("utf-8"), content_type="application/json")
            request(app, "POST", f"/sessions/{session_id}/recordings/rec_defaults_01/file", body=Path(fixture["tracks"][0]["path"]).read_bytes(), content_type="audio/wav")
            processed = request(app, "POST", f"/sessions/{session_id}/process", body=json.dumps({}).encode("utf-8"), content_type="application/json")
            self.assertTrue(processed["status"].startswith("202"), processed)
            expected_bundle_root = str(auto_root / session_id)
            self.assertIn("evidence", processed["body"])
            self.assertEqual(processed["body"]["evidence"]["evidence_bundle_path"], expected_bundle_root)
            self.assertEqual(processed["body"]["evidence"]["evidence_run_type"], "controlled_device")
            self.assertTrue((auto_root / session_id / "bundle.json").exists())

    def test_stop_room_transitions_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps(
                    {
                        "host_participant_id": "host_001",
                        "expected_participant_count": 1,
                        "minimum_ready_participants": 1,
                        "mode": "research",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            room_id = created["body"]["room_id"]
            request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "device_id": "dev_host",
                        "os_type": "ios",
                        "os_version": "18.0",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/preflight",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                        "permission_state": {"microphone": "granted"},
                        "time_sync": {
                            "server_time_offset_ms": 0.0,
                            "round_trip_ms": 12.0,
                            "sync_quality_bucket": "good",
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/ready",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/start",
                body=json.dumps({"participant_id": "host_001", "anchor_type": "beep"}).encode("utf-8"),
                content_type="application/json",
            )
            stopped = request(
                app,
                "POST",
                f"/rooms/{room_id}/stop",
                body=json.dumps({"participant_id": "host_001"}).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(stopped["status"].startswith("200"))
            self.assertEqual(stopped["body"]["room_state"], "stopped")

    def test_room_closes_after_registered_recording_binary_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps(
                    {
                        "host_participant_id": "host_001",
                        "expected_participant_count": 1,
                        "minimum_ready_participants": 1,
                        "mode": "research",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            room_id = created["body"]["room_id"]
            session_id = created["body"]["session_id"]
            request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "device_id": "dev_host",
                        "os_type": "ios",
                        "os_version": "18.0",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/preflight",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                        "permission_state": {"microphone": "granted"},
                        "time_sync": {
                            "server_time_offset_ms": 0.0,
                            "round_trip_ms": 12.0,
                            "sync_quality_bucket": "good",
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/ready",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/start",
                body=json.dumps({"participant_id": "host_001", "anchor_type": "beep"}).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/stop",
                body=json.dumps({"participant_id": "host_001"}).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings",
                body=json.dumps(
                    {
                        "participant": {"participant_id": "host_001", "device_id": "dev_host"},
                        "recording_event": {
                            "recording_id": "rec_stop_01",
                            "recording_started_at": "2026-04-09T00:01:00.412Z",
                            "recording_stopped_at": "2026-04-09T00:05:00.000Z",
                            "mic_route": "built_in_mic",
                            "audio_processing_flags": {
                                "agc": False,
                                "noise_suppression": False,
                                "echo_cancellation": False,
                            },
                            "anchor_type": "beep",
                        },
                        "audio_file": {
                            "filename": "part_01.wav",
                            "container": "wav",
                            "codec": "pcm_s16le",
                            "sample_rate_hz": 48000,
                            "channels": 1,
                            "duration_seconds": 240.0,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings/rec_stop_01/file",
                body=b"RIFFfakewavpayload",
                content_type="audio/wav",
            )
            room = request(app, "GET", f"/rooms/{room_id}")
            self.assertEqual(room["body"]["state"], "closed")

    def test_process_rejects_controlled_session_before_binary_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps(
                    {
                        "host_participant_id": "host_001",
                        "expected_participant_count": 1,
                        "minimum_ready_participants": 1,
                        "mode": "research",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            room_id = created["body"]["room_id"]
            session_id = created["body"]["session_id"]
            request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "device_id": "dev_host",
                        "os_type": "ios",
                        "os_version": "18.0",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/preflight",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                        "permission_state": {"microphone": "granted"},
                        "time_sync": {
                            "server_time_offset_ms": 0.0,
                            "round_trip_ms": 12.0,
                            "sync_quality_bucket": "good",
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/ready",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/start",
                body=json.dumps({"participant_id": "host_001", "anchor_type": "beep"}).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/stop",
                body=json.dumps({"participant_id": "host_001"}).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings",
                body=json.dumps(
                    {
                        "participant": {"participant_id": "host_001", "device_id": "dev_host"},
                        "recording_event": {
                            "recording_id": "rec_guard_01",
                            "recording_started_at": "2026-04-09T00:01:00.412Z",
                            "recording_stopped_at": "2026-04-09T00:05:00.000Z",
                            "mic_route": "built_in_mic",
                            "audio_processing_flags": {
                                "agc": False,
                                "noise_suppression": False,
                                "echo_cancellation": False,
                            },
                            "anchor_type": "beep",
                        },
                        "audio_file": {
                            "filename": "part_01.wav",
                            "container": "wav",
                            "codec": "pcm_s16le",
                            "sample_rate_hz": 48000,
                            "channels": 1,
                            "duration_seconds": 240.0,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            processed = request(app, "POST", f"/sessions/{session_id}/process")
            self.assertTrue(processed["status"].startswith("409"))
            self.assertEqual(processed["body"]["error"], "session_not_ready_for_processing")

    def test_process_accepts_controlled_session_after_upload_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            fixture = _generate_fixture_session(Path(tmpdir) / "fixture_controlled", track_count=1)
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps(
                    {
                        "host_participant_id": "host_001",
                        "expected_participant_count": 1,
                        "minimum_ready_participants": 1,
                        "mode": "research",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            room_id = created["body"]["room_id"]
            session_id = created["body"]["session_id"]
            request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "device_id": "dev_host",
                        "os_type": "ios",
                        "os_version": "18.0",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/preflight",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                        "permission_state": {"microphone": "granted"},
                        "time_sync": {
                            "server_time_offset_ms": 0.0,
                            "round_trip_ms": 12.0,
                            "sync_quality_bucket": "good",
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/ready",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/start",
                body=json.dumps({"participant_id": "host_001", "anchor_type": "beep"}).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/stop",
                body=json.dumps({"participant_id": "host_001"}).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings",
                body=json.dumps(
                    {
                        "participant": {"participant_id": "host_001", "device_id": "dev_host"},
                        "recording_event": {
                            "recording_id": "rec_guard_02",
                            "recording_started_at": "2026-04-09T00:01:00.412Z",
                            "recording_stopped_at": "2026-04-09T00:05:00.000Z",
                            "mic_route": "built_in_mic",
                            "audio_processing_flags": {
                                "agc": False,
                                "noise_suppression": False,
                                "echo_cancellation": False,
                            },
                            "anchor_type": "beep",
                        },
                        "audio_file": {
                            "filename": "part_01.wav",
                            "container": "wav",
                            "codec": "pcm_s16le",
                            "sample_rate_hz": 48000,
                            "channels": 1,
                            "duration_seconds": 240.0,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings/rec_guard_02/file",
                body=Path(fixture["tracks"][0]["path"]).read_bytes(),
                content_type="audio/wav",
            )
            processed = request(app, "POST", f"/sessions/{session_id}/process")
            self.assertTrue(processed["status"].startswith("202"))

    def test_room_lifecycle_and_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            created = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps(
                    {
                        "host_participant_id": "host_001",
                        "expected_participant_count": 3,
                        "minimum_ready_participants": 2,
                        "mode": "research",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(created["status"].startswith("201"))
            room_id = created["body"]["room_id"]

            joined_host = request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "device_id": "dev_host",
                        "os_type": "ios",
                        "os_version": "18.0",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertEqual(joined_host["body"]["room_state"], "open")

            joined_peer = request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "p_002",
                        "device_id": "dev_2",
                        "os_type": "android",
                        "os_version": "15",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertEqual(joined_peer["body"]["room_state"], "open")

            preflight_host = request(
                app,
                "POST",
                f"/rooms/{room_id}/preflight",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                        "permission_state": {"microphone": "granted"},
                        "time_sync": {
                            "server_time_offset_ms": 0.0,
                            "round_trip_ms": 12.0,
                            "sync_quality_bucket": "good",
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertEqual(preflight_host["body"]["participant_state"], "preflight_passed")

            preflight_peer = request(
                app,
                "POST",
                f"/rooms/{room_id}/preflight",
                body=json.dumps(
                    {
                        "participant_id": "p_002",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                        "permission_state": {"microphone": "granted"},
                        "time_sync": {
                            "server_time_offset_ms": 0.0,
                            "round_trip_ms": 12.0,
                            "sync_quality_bucket": "good",
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertEqual(preflight_peer["body"]["participant_state"], "preflight_passed")

            ready_host = request(
                app,
                "POST",
                f"/rooms/{room_id}/ready",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertEqual(ready_host["body"]["room_state"], "open")

            ready_peer = request(
                app,
                "POST",
                f"/rooms/{room_id}/ready",
                body=json.dumps(
                    {
                        "participant_id": "p_002",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertEqual(ready_peer["body"]["room_state"], "ready_to_start")

            started = request(
                app,
                "POST",
                f"/rooms/{room_id}/start",
                body=json.dumps({"participant_id": "host_001", "anchor_type": "beep"}).encode("utf-8"),
                content_type="application/json",
            )
            self.assertEqual(started["body"]["room_state"], "recording")
            self.assertTrue(started["body"]["session_id"])
            self.assertTrue(started["body"]["start_command_id"])
            self.assertEqual(started["body"]["protocol_version"], "recording-protocol/v1")
            self.assertEqual(started["body"]["start_strategy"], "server_authoritative_beep")
            self.assertEqual(started["body"]["anchor_policy"], "beep_required")

    def test_metadata_upload_validates_research_mode_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            room = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps(
                    {
                        "host_participant_id": "host_001",
                        "expected_participant_count": 1,
                        "minimum_ready_participants": 1,
                        "mode": "research",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            room_id = room["body"]["room_id"]
            request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "device_id": "dev_host",
                        "os_type": "ios",
                        "os_version": "18.0",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/preflight",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                        "permission_state": {"microphone": "granted"},
                        "time_sync": {
                            "server_time_offset_ms": 0.0,
                            "round_trip_ms": 12.0,
                            "sync_quality_bucket": "good",
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            request(
                app,
                "POST",
                f"/rooms/{room_id}/ready",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "built_in_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            started = request(
                app,
                "POST",
                f"/rooms/{room_id}/start",
                body=json.dumps({"participant_id": "host_001", "anchor_type": "beep"}).encode("utf-8"),
                content_type="application/json",
            )
            session_id = started["body"]["session_id"]

            metadata = {
                "room_id": room_id,
                "session_id": session_id,
                "participant_id": "host_001",
                "device_id": "dev_host",
                "filename": "host.wav",
                "container": "wav",
                "codec": "pcm_s16le",
                "sample_rate_hz": 48000,
                "channels": 1,
                "duration_seconds": 1.2,
                "mic_route": "built_in_mic",
                "audio_processing_flags": {
                    "agc": False,
                    "noise_suppression": False,
                    "echo_cancellation": False,
                },
                "start_command_id": started["body"]["start_command_id"],
                "server_start_issued_at": started["body"]["server_start_issued_at"],
                "start_command_received_at": "2026-04-09T01:00:00.132Z",
                "client_record_invoked_at": "2026-04-09T01:00:00.158Z",
                "recording_started_at": "2026-04-09T01:00:00.214Z",
                "local_monotonic_start_tick": 123456789,
                "anchor_type": "beep",
                "anchor_expected_at": "2026-04-09T01:00:00.500Z",
                "pause_resume_events": [],
                "os_type": "ios",
                "os_version": "18.0",
                "app_version": "0.1.0",
            }
            uploaded = request(
                app,
                "POST",
                f"/sessions/{session_id}/files",
                body=json.dumps(
                    {
                        "metadata": metadata,
                        "contentBase64": base64.b64encode(b"RIFFfakewavpayload").decode("ascii"),
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(uploaded["status"].startswith("201"))
            self.assertEqual(uploaded["body"]["room_id"], room_id)
            self.assertEqual(uploaded["body"]["start_command_id"], metadata["start_command_id"])
            self.assertFalse(uploaded["body"]["baseline_valid"])
            self.assertEqual(uploaded["body"]["classification"], "degraded")
            self.assertIn("control_metadata_missing", uploaded["body"]["violations"])
            session = request(app, "GET", f"/sessions/{session_id}")
            self.assertEqual(session["body"]["classification"], "degraded")
            self.assertIn(
                "legacy_file_uploaded",
                {event["event_type"] for event in session["body"]["events"]},
            )

    def test_ready_rejects_bluetooth_route_in_research_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            room = request(
                app,
                "POST",
                "/rooms",
                body=json.dumps(
                    {
                        "host_participant_id": "host_001",
                        "expected_participant_count": 1,
                        "minimum_ready_participants": 1,
                        "mode": "research",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            room_id = room["body"]["room_id"]
            request(
                app,
                "POST",
                f"/rooms/{room_id}/join",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "device_id": "dev_host",
                        "os_type": "ios",
                        "os_version": "18.0",
                        "app_version": "0.1.0",
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            ready = request(
                app,
                "POST",
                f"/rooms/{room_id}/ready",
                body=json.dumps(
                    {
                        "participant_id": "host_001",
                        "recorder_engine": "native_bridge_v1",
                        "mic_route": "bluetooth_mic",
                        "audio_processing_flags": {
                            "agc": False,
                            "noise_suppression": False,
                            "echo_cancellation": False,
                        },
                    }
                ).encode("utf-8"),
                content_type="application/json",
            )
            self.assertTrue(ready["status"].startswith("422"))
            self.assertIn("built_in_mic", ready["body"]["error"])

    def test_session_file_upload_process_and_artifact_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            fixture = _generate_fixture_session(Path(tmpdir) / "fixture", track_count=2)
            created = request(app, "POST", "/sessions")
            self.assertTrue(created["status"].startswith("201"))
            session_id = created["body"]["session_id"]
            for track in fixture["tracks"]:
                uploaded = request(
                    app,
                    "POST",
                    f"/sessions/{session_id}/files",
                    body=Path(track["path"]).read_bytes(),
                    query=f"participant_id={track['participant_id']}&filename={track['filename']}",
                )
                self.assertTrue(uploaded["status"].startswith("201"))
            processed = request(app, "POST", f"/sessions/{session_id}/process")
            if not processed["status"].startswith("202"):
                app = _create_app(Path(tmpdir) / "data")
                processed = request(app, "POST", f"/sessions/{session_id}/process")
            self.assertTrue(processed["status"].startswith("202"), processed)
            fetched = request(app, "GET", f"/sessions/{session_id}")
            self.assertEqual(fetched["body"]["status"], "done")
            self.assertIn("evidence", fetched["body"])
            self.assertEqual(fetched["body"]["evidence"]["classification"], fetched["body"]["classification"])
            self.assertTrue(fetched["body"]["evidence"]["evidence_ready"])
            self.assertEqual(fetched["body"]["evidence"]["recommended_run_type"], "synthetic")
            self.assertIn("export_session_to_evidence_bundle.py", fetched["body"]["evidence"]["evidence_export_hint"])
            artifacts = request(app, "GET", f"/sessions/{session_id}/artifacts")
            names = {artifact["name"] for artifact in artifacts["body"]["artifacts"]}
            self.assertEqual(len(names), 4)
            self.assertIn("manifest.export.json", names)
            self.assertIn("evidence", artifacts["body"])
            self.assertEqual(artifacts["body"]["evidence"]["classification"], fetched["body"]["classification"])
            self.assertEqual(artifacts["body"]["evidence"]["recommended_run_type"], "synthetic")

    def test_session_process_auto_exports_evidence_when_env_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            evidence_root = Path(tmpdir) / "evidence-auto"
            app = _create_app(root)
            fixture = _generate_fixture_session(Path(tmpdir) / "fixture", track_count=2)
            created = request(app, "POST", "/sessions")
            session_id = created["body"]["session_id"]
            for track in fixture["tracks"]:
                uploaded = request(
                    app,
                    "POST",
                    f"/sessions/{session_id}/files",
                    body=Path(track["path"]).read_bytes(),
                    query=f"participant_id={track['participant_id']}&filename={track['filename']}",
                )
                self.assertTrue(uploaded["status"].startswith("201"))

            old = os.environ.get("RECOG_EVIDENCE_EXPORT_ROOT")
            os.environ["RECOG_EVIDENCE_EXPORT_ROOT"] = str(evidence_root)
            try:
                processed = request(app, "POST", f"/sessions/{session_id}/process")
            finally:
                if old is None:
                    os.environ.pop("RECOG_EVIDENCE_EXPORT_ROOT", None)
                else:
                    os.environ["RECOG_EVIDENCE_EXPORT_ROOT"] = old

            self.assertTrue(processed["status"].startswith("202"), processed)
            expected_bundle_root = str(evidence_root / session_id)
            self.assertIn("evidence", processed["body"])
            self.assertEqual(processed["body"]["evidence"]["evidence_bundle_path"], expected_bundle_root)
            self.assertEqual(processed["body"]["evidence"]["evidence_run_type"], "synthetic")
            self.assertTrue((evidence_root / session_id / "bundle.json").exists())
            self.assertTrue((evidence_root / session_id / "artifacts-index.json").exists())

            artifacts = request(app, "GET", f"/sessions/{session_id}/artifacts")
            self.assertEqual(artifacts["body"]["evidence"]["evidence_bundle_path"], expected_bundle_root)
            names = {artifact["name"] for artifact in artifacts["body"]["artifacts"]}
            self.assertIn("bundle.json", names)
            self.assertIn("classification.json", names)
            self.assertIn("artifacts-index.json", names)
