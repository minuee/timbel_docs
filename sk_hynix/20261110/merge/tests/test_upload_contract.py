from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults

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


def request(app, method: str, path: str, body: bytes = b"", content_type: str = ""):
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    environ["CONTENT_LENGTH"] = str(len(body))
    environ["wsgi.input"] = io.BytesIO(body)
    if content_type:
        environ["CONTENT_TYPE"] = content_type
    captured: dict[str, object] = {}

    def start_response(status, headers):  # noqa: ANN001
        captured["status"] = status
        captured["headers"] = headers

    body_bytes = b"".join(app(environ, start_response))
    captured["body"] = json.loads(body_bytes.decode("utf-8"))
    return captured


def valid_upload_metadata() -> dict[str, object]:
    return {
        "room_id": "room_abc123",
        "session_id": "session_xyz789",
        "participant_id": "p_001",
        "device_id": "dev_ios_01",
        "filename": "alice.wav",
        "container": "wav",
        "codec": "pcm_s16le",
        "sample_rate_hz": 48000,
        "channels": 1,
        "duration_seconds": 600.0,
        "mic_route": "built_in_mic",
        "audio_processing_flags": {
            "agc": False,
            "noise_suppression": False,
            "echo_cancellation": False,
        },
        "start_command_id": "start_cmd_001",
        "server_start_issued_at": "2026-04-09T01:00:00.000Z",
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


def nested_envelope_metadata(session_id: str) -> dict[str, object]:
    return {
        "schema_version": "audio-sync-platform/v1",
        "session": {
            "session_id": session_id,
            "room_id": "room_abc123",
            "host_id": "host_1",
            "protocol_version": "recording-protocol/v1",
            "start_strategy": "server_authoritative_beep",
            "anchor_policy": "beep_required",
            "created_at": "2026-04-09T09:00:00Z",
        },
        "participant": {
            "participant_id": "p_nested",
            "display_name": "speaker_nested",
            "role": "member",
        },
        "recording": {
            "recording_id": "rec_nested_001",
            "filename": "nested.wav",
            "container": "wav",
            "codec": "pcm_s16le",
            "duration_seconds": 12.0,
            "pause_resume_events": [],
        },
        "device": {
            "device_id": "device_nested_001",
            "device_model": "iPhone15,2",
            "os_type": "ios",
            "os_version": "19.0",
            "app_version": "0.1.0",
            "mic_route": "built_in_mic",
            "audio_processing_flags": {"agc": False, "noise_suppression": False, "echo_cancellation": False},
        },
        "timing": {
            "start_command_issued_at": "2026-04-09T09:10:00.000Z",
            "start_command_received_at": "2026-04-09T09:10:00.071Z",
            "recording_started_at": "2026-04-09T09:10:00.192Z",
            "server_time_offset_ms": -12.4,
            "round_trip_ms": 41.8,
            "sync_quality_bucket": "good",
        },
        "audio": {"sample_rate": 48000, "channels": 1, "bit_depth": 16},
        "anchor": {
            "anchor_type": "beep",
            "anchor_expected_at": "2026-04-09T09:10:00.100Z",
            "anchor_expected_offset_ms_from_start_command": 100,
            "anchor_repeat_policy": "start_only",
            "anchor_spec_version": "sync-beep/v1",
        },
        "upload": {"sha256": "nestedsha", "filesize_bytes": 12345},
    }


def multipart_body(metadata: dict[str, object], file_bytes: bytes, filename: str) -> tuple[bytes, str]:
    boundary = "----audio-sync-boundary"
    chunks = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="metadata"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        json.dumps(metadata).encode("utf-8"),
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: audio/wav\r\n\r\n",
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class UploadContractTests(unittest.TestCase):
    def test_multipart_upload_accepts_metadata_and_file_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            app = _create_app(root)
            created = request(
                app,
                "POST",
                "/sessions",
            )
            session_id = created["body"]["session_id"]
            metadata = valid_upload_metadata()
            metadata["session_id"] = session_id
            body, content_type = multipart_body(metadata, b"RIFFfake-wav-payload", "alice.wav")
            uploaded = request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings",
                body=body,
                content_type=content_type,
            )
            self.assertTrue(uploaded["status"].startswith("201"))
            self.assertEqual(uploaded["body"]["participant_id"], "p_001")
            self.assertEqual(uploaded["body"]["container"], "wav")
            self.assertEqual(uploaded["body"]["filesize_bytes"], len(b"RIFFfake-wav-payload"))
            self.assertTrue(uploaded["body"]["baseline_valid"])
            self.assertEqual(uploaded["body"]["classification"], "baseline_valid")
            session = json.loads((root / "sessions" / session_id / "session.json").read_text())
            self.assertEqual(session["classification"], "baseline")
            self.assertEqual(len(session["files"]), 1)
            self.assertEqual(session["files"][0]["recording_metadata"]["participant_id"], "p_001")
            self.assertEqual(session["events"][0]["event_type"], "recording_uploaded")

    def test_multipart_upload_accepts_nested_recording_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            app = _create_app(root)
            created = request(app, "POST", "/sessions")
            session_id = created["body"]["session_id"]
            metadata = nested_envelope_metadata(session_id)
            body, content_type = multipart_body(metadata, b"RIFFnested-wav-payload", "nested.wav")
            uploaded = request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings",
                body=body,
                content_type=content_type,
            )
            self.assertTrue(uploaded["status"].startswith("201"))
            self.assertEqual(uploaded["body"]["participant_id"], "p_nested")
            self.assertTrue(uploaded["body"]["baseline_valid"])
            self.assertEqual(uploaded["body"]["classification"], "baseline_valid")
            self.assertEqual(uploaded["body"]["recording_metadata"]["schema_version"], "audio-sync-platform/v1")
            session = json.loads((root / "sessions" / session_id / "session.json").read_text())
            self.assertEqual(session["classification"], "baseline")
            self.assertEqual(session["files"][0]["recording_metadata"]["session"]["session_id"], session_id)

    def test_multipart_upload_rejects_missing_required_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _create_app(Path(tmpdir) / "data")
            created = request(app, "POST", "/sessions")
            session_id = created["body"]["session_id"]
            metadata = valid_upload_metadata()
            metadata["session_id"] = session_id
            del metadata["recording_started_at"]
            body, content_type = multipart_body(metadata, b"RIFFfake-wav-payload", "alice.wav")
            uploaded = request(
                app,
                "POST",
                f"/sessions/{session_id}/recordings",
                body=body,
                content_type=content_type,
            )
            self.assertTrue(uploaded["status"].startswith("422"))
            self.assertIn("recording_started_at", uploaded["body"]["error"])


if __name__ == "__main__":
    unittest.main()
