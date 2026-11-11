from __future__ import annotations

from array import array
import tempfile
import unittest
import wave
from pathlib import Path

from audio_sync.dsp import (
    ActivityBounds,
    bounded_correction_factor,
    envelope,
    estimate_alignment_from_activity,
    fine_offset_samples_from_arrays,
    estimate_offset_seconds,
    normalize_offsets,
    normalized_correlation,
    segment,
)
from recog.audio import detect_anchor_peak_seconds, estimate_alignment_and_drift


class AlignmentPrimitiveTests(unittest.TestCase):
    def test_envelope_reduces_signal_into_frame_energies(self) -> None:
        samples = array('h', [0, 1000, -1000, 0] * 50)
        values = envelope(samples, sample_rate=1_000, frame_ms=20)
        self.assertTrue(values)
        self.assertGreater(max(values), 0.0)

    def test_normalized_correlation_finds_best_lag(self) -> None:
        reference = [0.0, 1.0, 0.5, 0.0, 0.0]
        target = [0.0, 0.0, 1.0, 0.5, 0.0]
        lag, confidence = normalized_correlation(reference, target, max_lag=3)
        self.assertEqual(lag, 1)
        self.assertGreater(confidence, 0.9)

    def test_estimate_offset_seconds_scales_lag_by_frame_duration(self) -> None:
        reference = [0.0, 1.0, 0.5, 0.0, 0.0]
        target = [0.0, 0.0, 1.0, 0.5, 0.0]
        offset_seconds, confidence = estimate_offset_seconds(reference, target, frame_ms=10, max_offset_seconds=1.0)
        self.assertAlmostEqual(offset_seconds, 0.01)
        self.assertGreater(confidence, 0.9)

    def test_alignment_from_activity_reports_drift_and_bounded_factor(self) -> None:
        estimate = estimate_alignment_from_activity(
            ActivityBounds(start_sample=100, end_sample=2_100),
            ActivityBounds(start_sample=220, end_sample=2_224),
            sample_rate=1_000,
        )
        self.assertAlmostEqual(estimate.offset_seconds, 0.12)
        self.assertGreater(estimate.drift_ppm, 0.0)
        self.assertNotEqual(estimate.correction_factor, 1.0)

    def test_bounded_correction_factor_clamps_large_deltas(self) -> None:
        self.assertEqual(bounded_correction_factor(1_000, 500), 1.0)

    def test_normalize_offsets_rebases_against_minimum(self) -> None:
        normalized = normalize_offsets({"ref": -0.1, "guest": 0.25, "host": 0.0})
        self.assertEqual(normalized["ref"], 0.0)
        self.assertAlmostEqual(normalized["host"], 0.1)
        self.assertAlmostEqual(normalized["guest"], 0.35)


    def test_segment_returns_requested_window(self) -> None:
        samples = array('h', [1, 2, 3, 4, 5])
        self.assertEqual(segment(samples, 1, 3), [2.0, 3.0, 4.0])

    def test_fine_offset_samples_from_arrays_refines_positive_offset(self) -> None:
        reference = array('h', [0, 0, 1000, -1000, 500, 0, 0, 0])
        target = array('h', [0, 0, 0, 1000, -1000, 500, 0, 0])
        lag, confidence = fine_offset_samples_from_arrays(
            reference,
            target,
            sample_rate=4,
            approximate_offset_seconds=0.25,
            window_seconds=1.0,
            search_radius_seconds=0.5,
        )
        self.assertEqual(lag, 1)
        self.assertGreater(confidence, 0.9)

    def test_estimate_alignment_and_drift_accepts_anchor_window(self) -> None:
        def write_wav(path: Path, samples: list[int], sample_rate: int = 1000) -> None:
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(sample_rate)
                payload = array("h", samples)
                handle.writeframes(payload.tobytes())

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference = root / "reference.wav"
            target = root / "target.wav"
            reference_samples = [0] * 200
            target_samples = [0] * 240
            for idx, value in enumerate([0, 0, 22000, -22000, 12000, 0, 0]):
                reference_samples[100 + idx] = value
                target_samples[125 + idx] = value
            write_wav(reference, reference_samples)
            write_wav(target, target_samples)
            summary = estimate_alignment_and_drift(
                reference,
                target,
                coarse_offset_seconds=0.02,
                anchor_seconds=0.1,
            )
            self.assertIn("anchor_refined", summary)
            self.assertAlmostEqual(summary["offset_seconds"], 0.0225, places=3)

    def test_detect_anchor_peak_seconds_finds_peak_near_expected_time(self) -> None:
        def write_wav(path: Path, samples: list[int], sample_rate: int = 1000) -> None:
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(sample_rate)
                payload = array("h", samples)
                handle.writeframes(payload.tobytes())

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "anchor.wav"
            samples = [0] * 220
            samples[110] = 28000
            samples[111] = -28000
            write_wav(path, samples)
            detected_seconds, confidence = detect_anchor_peak_seconds(
                path,
                expected_anchor_seconds=0.1,
                search_radius_seconds=0.05,
            )
            self.assertIsNotNone(detected_seconds)
            self.assertAlmostEqual(detected_seconds or 0.0, 0.11, places=2)
            self.assertGreater(confidence, 0.9)


if __name__ == '__main__':
    unittest.main()
