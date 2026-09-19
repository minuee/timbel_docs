from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from zipfile import ZipFile

from audio_sync.export import (
    AlignedTrackArtifact,
    ExportArtifacts,
    MixArtifact,
    build_file_record_session_export,
    build_session_export,
)
from recog.models import FileRecord


class ExportServiceTests(unittest.TestCase):
    def test_build_session_export_writes_manifest_bundle_and_mix_plan(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            aligned_track = root / "aligned.wav"
            aligned_track.write_bytes(b"aligned-track")
            mix_path = root / "listening_mix.wav"
            mix_path.write_bytes(b"mix")

            exports = ExportArtifacts(
                session_id="session-456",
                tracks=(
                    AlignedTrackArtifact(
                        track_id="track-1",
                        participant_id="alice",
                        aligned_path=aligned_track,
                        offset_ms=12.0,
                        drift_ppm=0.5,
                    ),
                ),
                mix_artifact=MixArtifact(output_path=mix_path),
                qa_summary={"alignmentGate": "pass"},
            )

            manifest_path = root / "manifest.json"
            compat_manifest_path = root / "manifest.recog.json"
            bundle_path = root / "bundle.zip"
            result = build_session_export(
                exports,
                manifest_path=manifest_path,
                compat_manifest_path=compat_manifest_path,
                bundle_path=bundle_path,
            )

            self.assertEqual(result.manifest_path, manifest_path)
            self.assertEqual(result.compat_manifest_path, compat_manifest_path)
            self.assertEqual(result.bundle_path, bundle_path)
            self.assertIsNotNone(result.mix_plan)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["sessionId"], "session-456")
            self.assertEqual(manifest["qaSummary"]["alignmentGate"], "pass")
            compat_manifest = json.loads(compat_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(compat_manifest["sessionId"], "session-456")
            self.assertEqual(compat_manifest["recommended_stt_input"], "tracks")

            with ZipFile(bundle_path) as archive:
                self.assertIn("manifest.json", archive.namelist())
                self.assertIn("manifest.recog.json", archive.namelist())
                self.assertIn("tracks/aligned.wav", archive.namelist())
                self.assertIn("mix/listening_mix.wav", archive.namelist())

    def test_build_file_record_session_export_writes_outputs_from_file_records(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            aligned_track = root / "aligned.wav"
            aligned_track.write_bytes(b"aligned-track")
            upload = root / "upload.m4a"
            upload.write_bytes(b"upload-track")
            stt = root / "aligned.stt.wav"
            stt.write_bytes(b"stt-track")
            mix = root / "listening_mix.wav"
            mix.write_bytes(b"mix-track")

            result = build_file_record_session_export(
                session_id="session-789",
                files=[
                    FileRecord(
                        file_id="file-1",
                        participant_id="alice",
                        filename="alice.m4a",
                        uploaded_path=str(upload),
                        aligned_path=str(aligned_track),
                        stt_path=str(stt),
                        offset_seconds=0.2,
                        drift_ppm=1.5,
                        alignment_confidence=0.88,
                    )
                ],
                manifest_path=root / "manifest.json",
                compat_manifest_path=root / "manifest.recog.json",
                bundle_path=root / "aligned_tracks.zip",
                mix_output_path=mix,
                qa_summary={"clipped_samples_mix": 0},
            )

            self.assertTrue(result.manifest_path.exists())
            self.assertTrue(result.compat_manifest_path and result.compat_manifest_path.exists())
            self.assertTrue(result.bundle_path and result.bundle_path.exists())


if __name__ == "__main__":
    unittest.main()
