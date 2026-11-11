from __future__ import annotations

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

contracts = importlib.import_module(f"{PACKAGE_NAME}.contracts")
rooms = importlib.import_module(f"{PACKAGE_NAME}.rooms")
validate_upload_metadata = contracts.validate_upload_metadata
validate_ready_payload = contracts.validate_ready_payload
CapturePolicyError = rooms.CapturePolicyError
MetadataValidationError = rooms.MetadataValidationError


def valid_upload_metadata() -> dict:
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


class UploadMetadataValidationTests(unittest.TestCase):
    def test_valid_ready_payload_passes_in_research_mode(self) -> None:
        validate_ready_payload(
            {
                "participant_id": "p_001",
                "recorder_engine": "native_bridge_v1",
                "mic_route": "built_in_mic",
                "audio_processing_flags": {
                    "agc": False,
                    "noise_suppression": False,
                    "echo_cancellation": False,
                },
            },
            mode="research",
        )

    def test_research_mode_rejects_non_wav_upload(self) -> None:
        payload = valid_upload_metadata()
        payload["container"] = "m4a"
        with self.assertRaises(CapturePolicyError):
            validate_upload_metadata(payload, mode="research")

    def test_research_mode_rejects_non_48khz_upload(self) -> None:
        payload = valid_upload_metadata()
        payload["sample_rate_hz"] = 44100
        with self.assertRaises(CapturePolicyError):
            validate_upload_metadata(payload, mode="research")

    def test_research_mode_rejects_stereo_upload(self) -> None:
        payload = valid_upload_metadata()
        payload["channels"] = 2
        with self.assertRaises(CapturePolicyError):
            validate_upload_metadata(payload, mode="research")

    def test_research_mode_rejects_bluetooth_route(self) -> None:
        payload = valid_upload_metadata()
        payload["mic_route"] = "bluetooth_mic"
        with self.assertRaises(CapturePolicyError):
            validate_upload_metadata(payload, mode="research")

    def test_missing_research_field_rejected(self) -> None:
        payload = valid_upload_metadata()
        del payload["start_command_id"]
        with self.assertRaises(MetadataValidationError):
            validate_upload_metadata(payload, mode="research")

    def test_pause_resume_event_rejected(self) -> None:
        payload = valid_upload_metadata()
        payload["pause_resume_events"] = [{"at": "2026-04-09T01:05:00Z"}]
        with self.assertRaises(CapturePolicyError):
            validate_upload_metadata(payload, mode="research")
