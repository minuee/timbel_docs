from pathlib import Path
import unittest

from audio_sync.export import build_exports_from_file_records, build_recog_manifest
from recog.models import FileRecord


class RecogManifestCompatibilityTests(unittest.TestCase):
    def test_build_recog_manifest_matches_pipeline_shape(self) -> None:
        file_record = FileRecord(
            file_id="file-1",
            participant_id="alice",
            filename="alice.m4a",
            uploaded_path="uploads/alice.m4a",
            aligned_path="aligned/alice.wav",
            stt_path="canonical/alice.stt.wav",
            offset_seconds=0.125,
            drift_ppm=-1.5,
            correction_factor=0.9999991,
            alignment_confidence=0.91,
            loudness_dbfs=-17.2,
        )
        exports = build_exports_from_file_records(
            session_id="session-789",
            files=[file_record],
            mix_output_path=Path("artifacts/listening_mix.wav"),
            qa_summary={"loudness_spread_db": 1.2, "clipped_samples_mix": 0},
            bundle_path=Path("artifacts/aligned_tracks.zip"),
        )

        manifest = build_recog_manifest(exports)

        self.assertEqual(manifest["sessionId"], "session-789")
        self.assertEqual(manifest["recommended_stt_input"], "mixdown")
        self.assertTrue(manifest["non_goals_excluded"]["video_sync"])
        self.assertEqual(manifest["qa_summary"]["clipped_samples_mix"], 0)
        self.assertEqual(manifest["tracks"][0]["file_id"], "file-1")
        self.assertEqual(manifest["tracks"][0]["stt_path"], "canonical/alice.stt.wav")
        self.assertAlmostEqual(manifest["tracks"][0]["offset_seconds"], 0.125)
        self.assertAlmostEqual(manifest["tracks"][0]["correction_factor"], 0.9999991)


if __name__ == "__main__":
    unittest.main()
