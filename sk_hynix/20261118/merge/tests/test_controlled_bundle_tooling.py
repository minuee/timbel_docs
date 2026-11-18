from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from recog.store import SessionStore
from recog.synthetic import generate_fixture_session
from recog.pipeline import AudioSyncPipeline


class ControlledBundleToolingTests(unittest.TestCase):
    def test_export_controlled_device_bundle_cli_emits_expected_artifacts(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = Path(tmpdir) / "data"
            fixture_dir = Path(tmpdir) / "fixture"
            truth = generate_fixture_session(fixture_dir, track_count=1, duration_seconds=4.0)
            store = SessionStore(runtime)
            room = store.create_room(host_participant_id="host_001", expected_participant_count=1, minimum_ready_participants=1, mode="research")
            store.join_room(room.room_id, participant_id="host_001", device_id="dev_host", os_type="ios", os_version="18.0", app_version="0.1.0")
            store.record_preflight(
                room.room_id,
                "host_001",
                recorder_engine="native_bridge_v1",
                mic_route="built_in_mic",
                audio_processing_flags={"agc": False, "noise_suppression": False, "echo_cancellation": False},
                permission_state={"microphone": "granted"},
                time_sync={"server_time_offset_ms": 0.0, "round_trip_ms": 12.0, "sync_quality_bucket": "good"},
            )
            store.mark_ready(room.room_id, "host_001")
            started = store.start_room(room.room_id, participant_id="host_001", anchor_type="beep")
            metadata = {
                "recording_started_at": "2026-04-09T00:01:00.100Z",
                "recording_stopped_at": "2026-04-09T00:01:04.000Z",
                "start_command_received_at": "2026-04-09T00:01:00.050Z",
                "mic_route": "built_in_mic",
                "audio_processing_flags": {"agc": False, "noise_suppression": False, "echo_cancellation": False},
                "anchor_type": "beep",
                "anchor_expected_at": "2026-04-09T00:01:00.200Z",
            }
            store.register_recording_metadata(
                started.session_id,
                participant_id="host_001",
                recording_id="rec_bundle_01",
                control_metadata=metadata,
                audio_file_metadata={
                    "filename": truth["tracks"][0]["filename"],
                    "container": "wav",
                    "codec": "pcm_s16le",
                    "sample_rate_hz": 48000,
                    "channels": 1,
                    "duration_seconds": 4.0,
                },
            )
            store.attach_recording_binary(
                started.session_id,
                "rec_bundle_01",
                payload=Path(truth["tracks"][0]["path"]).read_bytes(),
                content_type="audio/wav",
            )
            store.stop_room(room.room_id, participant_id="host_001")
            AudioSyncPipeline(store).process_session(started.session_id)

            output_dir = Path(tmpdir) / "bundle"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(project_root / "tools" / "export_controlled_device_bundle.py"),
                    room.room_id,
                    str(output_dir),
                    "--data-root",
                    str(runtime),
                ],
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": f"{project_root / 'src'}:{project_root}"},
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["run_type"], "controlled_device")
            self.assertEqual(payload["session"]["room_id"], room.room_id)
            self.assertTrue((output_dir / "bundle.json").exists())
            self.assertTrue((output_dir / "artifacts" / "manifest.json").exists())
            self.assertTrue((output_dir / "artifacts" / "manifest.export.json").exists())
            self.assertTrue((output_dir / "artifacts" / "aligned_tracks.zip").exists())
            self.assertTrue((output_dir / "artifacts" / "listening_mix.wav").exists())
            self.assertTrue((output_dir / "room" / "room.json").exists())
            self.assertTrue((output_dir / "room" / "session.json").exists())
            self.assertTrue((output_dir / "uploads" / "upload-summary.json").exists())
