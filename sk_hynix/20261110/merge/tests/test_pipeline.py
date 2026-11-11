from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from statistics import quantiles

from recog.pipeline import AudioSyncPipeline
from recog.store import SessionStore
from recog.synthetic import generate_fixture_session
from testkit.benchmark import TrackPrediction, evaluate_alignment


class PipelineIntegrationTests(unittest.TestCase):
    def test_end_to_end_processing_generates_tracks_mix_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_dir = Path(tmpdir) / "fixture"
            truth = generate_fixture_session(fixture_dir, track_count=3)
            store = SessionStore(Path(tmpdir) / "data")
            session = store.create_session()
            for track in truth["tracks"]:
                store.add_file(
                    session.session_id,
                    participant_id=track["participant_id"],
                    filename=track["filename"],
                    payload=Path(track["path"]).read_bytes(),
                )
            result = AudioSyncPipeline(store).process_session(session.session_id)
            self.assertEqual(result["status"], "done")
            event_types = [event["event_type"] for event in result["events"]]
            self.assertIn("processing_requested", event_types)
            self.assertIn("processing_completed", event_types)
            artifact_names = {artifact["name"] for artifact in result["artifacts"]}
            self.assertIn("manifest.json", artifact_names)
            self.assertIn("manifest.export.json", artifact_names)
            self.assertIn("aligned_tracks.zip", artifact_names)
            self.assertIn("listening_mix.wav", artifact_names)

            manifest_path = Path(store.session_dir(session.session_id) / "artifacts" / "manifest.json")
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["recommended_stt_input"], "tracks")
            self.assertEqual(len(manifest["tracks"]), 3)
            self.assertTrue(manifest["non_goals_excluded"]["video_sync"])
            self.assertLessEqual(manifest["qa_summary"]["loudness_spread_db"], 3.5)
            self.assertEqual(manifest["qa_summary"]["clipped_samples_mix"], 0)

            absolute_errors = []
            for track_manifest, truth_track in zip(manifest["tracks"], truth["tracks"], strict=True):
                absolute_errors.append(abs(track_manifest["offset_seconds"] - truth_track["offset_seconds"]))
            p95 = quantiles(absolute_errors, n=20, method="inclusive")[18]
            self.assertLessEqual(p95, 0.0101)

            benchmark = evaluate_alignment(
                {
                    "tracks": [
                        {
                            "participant_id": track["participant_id"],
                            "start_offset_ms": track["offset_seconds"] * 1000,
                            "drift_ppm": track["drift_ppm"],
                        }
                        for track in truth["tracks"]
                    ]
                },
                [
                    TrackPrediction(
                        participant_id=track["participant_id"],
                        predicted_offset_ms=track["offset_seconds"] * 1000,
                        predicted_drift_ppm=track["drift_ppm"],
                    )
                    for track in manifest["tracks"]
                ],
            )
            self.assertEqual(benchmark.verdict, "pass")

    def test_rejects_corrupt_input_before_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "data")
            session = store.create_session()
            store.add_file(
                session.session_id,
                participant_id="p1",
                filename="broken.wav",
                payload=b"not-audio",
            )
            with self.assertRaises(RuntimeError):
                AudioSyncPipeline(store).process_session(session.session_id)
            failed = store.get_session(session.session_id)
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.files[0].status, "rejected")
            self.assertTrue(failed.files[0].rejection_reason)
            self.assertIn("processing_failed", [event["event_type"] for event in failed.events])

    def test_metadata_provenance_and_policy_warnings_are_exported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_dir = Path(tmpdir) / "fixture"
            truth = generate_fixture_session(fixture_dir, track_count=2)
            store = SessionStore(Path(tmpdir) / "data")
            session = store.create_session()
            for index, track in enumerate(truth["tracks"]):
                record = store.add_file(
                    session.session_id,
                    participant_id=track["participant_id"],
                    filename=track["filename"],
                    payload=Path(track["path"]).read_bytes(),
                )
                store.update_file(
                    session.session_id,
                    record.file_id,
                    room_id="room_abc123",
                    device_id=f"dev_{index}",
                    mic_route="bluetooth_mic" if index == 0 else "built_in_mic",
                    audio_processing_flags={
                        "agc": index == 0,
                        "noise_suppression": False,
                        "echo_cancellation": False,
                    },
                    start_command_id="start_cmd_001",
                    start_command_received_at="2026-04-09T01:00:00.100Z" if index == 0 else "2026-04-09T01:00:00.220Z",
                    client_record_invoked_at="2026-04-09T01:00:00.120Z" if index == 0 else "2026-04-09T01:00:00.240Z",
                    recording_started_at="2026-04-09T01:00:00.150Z" if index == 0 else "2026-04-09T01:00:00.270Z",
                    anchor_type="beep",
                    anchor_expected_at="2026-04-09T01:00:00.500Z",
                    pause_resume_events=[{"at": "2026-04-09T01:05:00Z"}] if index == 0 else [],
                )
            result = AudioSyncPipeline(store).process_session(session.session_id)
            self.assertEqual(result["status"], "done")
            manifest_path = Path(store.session_dir(session.session_id) / "artifacts" / "manifest.json")
            manifest = json.loads(manifest_path.read_text())
            self.assertIn("capture_provenance", manifest)
            self.assertEqual(manifest["capture_provenance"]["tracks"][0]["room_id"], "room_abc123")
            self.assertIn("recording_started_at", {track["metadata_prior_source"] for track in manifest["capture_provenance"]["tracks"]})
            self.assertTrue(any(track["metadata_prior_offset_seconds"] is not None for track in manifest["capture_provenance"]["tracks"]))
            self.assertTrue(any(track["anchor_refined"] for track in manifest["capture_provenance"]["tracks"]))
            self.assertTrue(any(track["anchor_detected_at"] is not None for track in manifest["capture_provenance"]["tracks"]))
            self.assertTrue(any(track["anchor_detection_confidence"] is not None for track in manifest["capture_provenance"]["tracks"]))
            export_manifest_path = Path(store.session_dir(session.session_id) / "artifacts" / "manifest.export.json")
            export_manifest = json.loads(export_manifest_path.read_text())
            self.assertIn("captureProvenance", export_manifest)
            self.assertEqual(export_manifest["captureProvenance"]["tracks"][0]["roomId"], "room_abc123")
            self.assertIn("recording_started_at", {track["metadataPriorSource"] for track in export_manifest["captureProvenance"]["tracks"]})
            self.assertTrue(any(track["metadataPriorOffsetSeconds"] is not None for track in export_manifest["captureProvenance"]["tracks"]))
            self.assertTrue(any(track["anchorRefined"] for track in export_manifest["captureProvenance"]["tracks"]))
            self.assertTrue(any(track["anchorDetectedAt"] is not None for track in export_manifest["captureProvenance"]["tracks"]))
            self.assertTrue(any(track["anchorDetectionConfidence"] is not None for track in export_manifest["captureProvenance"]["tracks"]))
            warnings = export_manifest["qaSummary"]["capture_policy_warnings"]
            warning_codes = {entry["warning"] for entry in warnings}
            self.assertIn("non_built_in_mic_route", warning_codes)
            self.assertIn("audio_processing_flags_enabled", warning_codes)
            self.assertIn("pause_resume_events_present", warning_codes)
            self.assertGreaterEqual(export_manifest["qaSummary"]["metadata_prior_tracks_used"], 1)

    def test_coarse_prior_offset_prefers_recording_started_at(self) -> None:
        reference = type("StubFile", (), {
            "recording_started_at": "2026-04-09T01:00:00.100Z",
            "start_command_received_at": "2026-04-09T01:00:00.000Z",
            "server_start_issued_at": "2026-04-09T01:00:00.000Z",
        })()
        target = type("StubFile", (), {
            "recording_started_at": "2026-04-09T01:00:00.350Z",
            "start_command_received_at": "2026-04-09T01:00:00.050Z",
            "server_start_issued_at": "2026-04-09T01:00:00.000Z",
        })()
        offset, source = AudioSyncPipeline._coarse_prior_offset_seconds(reference, target)
        self.assertEqual(source, "recording_started_at")
        self.assertAlmostEqual(offset, 0.25, places=3)
