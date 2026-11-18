from pathlib import Path
import unittest

from audio_sync.export import (
    AlignedTrackArtifact,
    LoudnessStats,
    MixArtifact,
    build_listening_mix_plan,
)


class ListeningMixPlanTests(unittest.TestCase):
    def test_builds_ffmpeg_plan_with_all_inputs(self) -> None:
        tracks = (
            AlignedTrackArtifact(
                track_id="track-a",
                participant_id="alice",
                aligned_path=Path("artifacts/alice.wav"),
                gain_db=1.5,
                loudness=LoudnessStats(integrated_lufs=-21.0),
            ),
            AlignedTrackArtifact(
                track_id="track-b",
                participant_id="bob",
                aligned_path=Path("artifacts/bob.wav"),
                gain_db=-2.0,
                loudness=LoudnessStats(integrated_lufs=-20.0),
            ),
        )

        plan = build_listening_mix_plan(
            tracks,
            MixArtifact(output_path=Path("mix/listening_mix.wav")),
        )

        self.assertEqual(plan.command[:3], ("ffmpeg", "-y", "-i"))
        self.assertIn("artifacts/alice.wav", plan.command)
        self.assertIn("artifacts/bob.wav", plan.command)
        self.assertIn("amix=inputs=2", plan.filter_complex)
        self.assertIn("volume=1.500dB", plan.filter_complex)
        self.assertIn("volume=-2.000dB", plan.filter_complex)
        self.assertEqual(plan.output_path, Path("mix/listening_mix.wav"))


if __name__ == "__main__":
    unittest.main()

