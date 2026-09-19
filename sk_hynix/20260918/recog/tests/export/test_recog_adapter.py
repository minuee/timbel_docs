from pathlib import Path
import unittest

from audio_sync.export.recog_adapter import build_exports_from_file_records
from recog.models import FileRecord


class RecogAdapterTests(unittest.TestCase):
    def test_build_exports_from_file_records_maps_pipeline_fields(self) -> None:
        file_record = FileRecord(
            file_id="file-1",
            participant_id="alice",
            filename="alice.m4a",
            uploaded_path="uploads/alice.m4a",
            aligned_path="aligned/alice.wav",
            stt_path="canonical/alice.stt.wav",
            offset_seconds=0.125,
            drift_ppm=-1.5,
            alignment_confidence=0.9,
        )

        exports = build_exports_from_file_records(
            session_id="session-789",
            files=[file_record],
            mix_output_path=Path("artifacts/listening_mix.wav"),
            qa_summary={"loudness_spread_db": 1.2},
            bundle_path=Path("artifacts/aligned_tracks.zip"),
        )

        self.assertEqual(exports.session_id, "session-789")
        self.assertEqual(exports.recommended_stt_input, "mixdown")
        self.assertAlmostEqual(exports.alignment_confidence or 0.0, 0.9)
        self.assertEqual(exports.bundle_path, Path("artifacts/aligned_tracks.zip"))
        self.assertEqual(exports.tracks[0].offset_ms, 125.0)
        self.assertEqual(exports.tracks[0].extra_metadata["sttPath"], "canonical/alice.stt.wav")


if __name__ == "__main__":
    unittest.main()
