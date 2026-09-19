from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import wave

from testkit.benchmark import TrackPrediction, evaluate_alignment, load_ground_truth
from testkit.synthetic_corpus import (
    build_default_session_plan,
    build_integration_matrix,
    generate_integration_matrix,
    generate_session_fixture,
)
from testkit.verification_matrix import build_verification_matrix


class SyntheticCorpusTests(unittest.TestCase):
    def test_default_plan_spans_offsets_drift_and_sample_rates(self) -> None:
        plan = build_default_session_plan(participants=5, duration_s=10.0, max_offset_ms=3_000)

        self.assertEqual(len(plan.tracks), 5)
        self.assertEqual(plan.tracks[0].start_offset_ms, 0)
        self.assertEqual(plan.tracks[-1].start_offset_ms, 3_000)
        self.assertEqual({track.sample_rate_hz for track in plan.tracks}, {16_000, 44_100, 48_000})
        self.assertTrue(any(track.drift_ppm < 0 for track in plan.tracks))
        self.assertTrue(any(track.drift_ppm > 0 for track in plan.tracks))

    def test_generate_session_fixture_writes_ground_truth_and_failure_inputs(self) -> None:
        plan = build_default_session_plan(participants=3, duration_s=6.0, max_offset_ms=1_000)

        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = generate_session_fixture(temp_dir, plan)

            metadata = json.loads((session_dir / "ground_truth.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["session_id"], plan.session_id)
            self.assertEqual(len(metadata["generated_files"]), 3)
            self.assertEqual(
                {item["reason"] for item in metadata["failure_inputs"]},
                {"corrupt_audio_payload", "unsupported_format"},
            )

            for generated_file in metadata["generated_files"]:
                wav_path = Path(generated_file["path"])
                self.assertTrue(wav_path.exists())
                with wave.open(str(wav_path), "rb") as wav_file:
                    self.assertEqual(wav_file.getnchannels(), 1)
                    self.assertEqual(wav_file.getsampwidth(), 2)
                    self.assertEqual(wav_file.getframerate(), generated_file["sample_rate_hz"])
                    duration = wav_file.getnframes() / wav_file.getframerate()
                    self.assertAlmostEqual(duration, metadata["fixture_duration_s"], delta=0.02)

    def test_integration_matrix_covers_two_three_and_five_participant_sessions(self) -> None:
        matrix = build_integration_matrix()

        self.assertEqual([len(plan.tracks) for plan in matrix], [2, 3, 5])
        self.assertEqual([plan.session_id for plan in matrix], [
            "synthetic-session-p2",
            "synthetic-session-p3",
            "synthetic-session-p5",
        ])

        with tempfile.TemporaryDirectory() as temp_dir:
            generated = generate_integration_matrix(temp_dir)
            self.assertEqual(len(generated), 3)
            for session_dir in generated:
                metadata_path = session_dir / "ground_truth.json"
                self.assertTrue(metadata_path.exists())
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                self.assertIn("AC6 sync-error benchmark ground truth", metadata["expected_acceptance_coverage"])

    def test_verification_matrix_covers_failure_paths_and_load_case(self) -> None:
        scenarios = build_verification_matrix()

        by_id = {scenario.scenario_id: scenario for scenario in scenarios}
        self.assertEqual(by_id["load-path-p5"].participant_count, 5)
        self.assertIn("AC7", by_id["load-path-p5"].acceptance_criteria)
        self.assertEqual(by_id["corrupt-input"].verification_types, ("failure-path",))
        self.assertEqual(by_id["unsupported-input"].acceptance_criteria, ("AC9",))

    def test_benchmark_evaluator_reports_pass_for_small_errors(self) -> None:
        plan = build_default_session_plan(participants=3, duration_s=6.0, max_offset_ms=1_000)

        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = generate_session_fixture(temp_dir, plan)
            ground_truth = load_ground_truth(session_dir / "ground_truth.json")
            predictions = [
                TrackPrediction(
                    participant_id=track["participant_id"],
                    predicted_offset_ms=track["start_offset_ms"] + 3.0,
                    predicted_drift_ppm=track["drift_ppm"] + 1.25,
                )
                for track in ground_truth["tracks"]
            ]

            result = evaluate_alignment(ground_truth, predictions)

        self.assertEqual(result.sample_count, 3)
        self.assertLessEqual(result.offset_p95_ms, 10.0)
        self.assertEqual(result.verdict, "pass")

    def test_benchmark_evaluator_reports_fail_for_large_errors(self) -> None:
        plan = build_default_session_plan(participants=2, duration_s=5.0, max_offset_ms=750)

        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = generate_session_fixture(temp_dir, plan)
            ground_truth = load_ground_truth(session_dir / "ground_truth.json")
            predictions = [
                TrackPrediction(
                    participant_id=track["participant_id"],
                    predicted_offset_ms=track["start_offset_ms"] + 35.0,
                    predicted_drift_ppm=track["drift_ppm"] + 5.0,
                )
                for track in ground_truth["tracks"]
            ]

            result = evaluate_alignment(ground_truth, predictions)

        self.assertGreater(result.offset_p95_ms, 20.0)
        self.assertEqual(result.verdict, "fail")


if __name__ == "__main__":
    unittest.main()
