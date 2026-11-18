from pathlib import Path
import unittest

from audio_sync.export import (
    AlignedTrackArtifact,
    ExportArtifacts,
    LoudnessStats,
    MixArtifact,
    build_export_manifest,
)


class ExportManifestTests(unittest.TestCase):
    def test_manifest_contains_tracks_mix_and_qa_summary(self) -> None:
        exports = ExportArtifacts(
            session_id="session-123",
            tracks=(
                AlignedTrackArtifact(
                    track_id="track-a",
                    participant_id="alice",
                    aligned_path=Path("aligned/alice.wav"),
                    original_path=Path("raw/alice.m4a"),
                    offset_ms=42.125,
                    drift_ppm=-3.5,
                    duration_ms=1_000,
                    loudness=LoudnessStats(integrated_lufs=-18.2, true_peak_dbfs=-0.7),
                ),
            ),
            mix_artifact=MixArtifact(output_path=Path("mix/listening_mix.wav")),
            recommended_stt_input="tracks",
            alignment_confidence=0.98234,
            qa_summary={"loudnessSpreadDb": 2.1, "clippedSamples": 0},
            bundle_path=Path("bundle/session-123.zip"),
        )

        manifest = build_export_manifest(exports)

        self.assertEqual(manifest["sessionId"], "session-123")
        self.assertEqual(manifest["recommendedSttInput"], "tracks")
        self.assertEqual(manifest["tracks"][0]["offsetMs"], 42.125)
        self.assertEqual(manifest["tracks"][0]["driftPpm"], -3.5)
        self.assertEqual(manifest["tracks"][0]["loudness"]["integratedLufs"], -18.2)
        self.assertEqual(manifest["listeningMix"]["path"], "mix/listening_mix.wav")
        self.assertEqual(manifest["qaSummary"]["clippedSamples"], 0)
        self.assertEqual(manifest["artifactsBundle"], "bundle/session-123.zip")
        self.assertAlmostEqual(manifest["alignmentConfidence"], 0.9823)


if __name__ == "__main__":
    unittest.main()

