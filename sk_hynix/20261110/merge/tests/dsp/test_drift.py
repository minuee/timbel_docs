from __future__ import annotations

import unittest

from audio_sync.dsp import DriftLandmark, fit_piecewise_drift


class DriftModelTests(unittest.TestCase):
    def test_fit_piecewise_drift_builds_segments(self) -> None:
        segments = fit_piecewise_drift(
            (
                DriftLandmark(position_seconds=0.0, offset_seconds=0.0),
                DriftLandmark(position_seconds=10.0, offset_seconds=0.001),
                DriftLandmark(position_seconds=20.0, offset_seconds=0.003),
            )
        )
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].start_seconds, 0.0)
        self.assertEqual(segments[1].end_seconds, 20.0)
        self.assertLess(abs(segments[0].drift_ppm), 500.0)

    def test_fit_piecewise_drift_clamps_unreasonable_corrections(self) -> None:
        segments = fit_piecewise_drift(
            (
                DriftLandmark(position_seconds=0.0, offset_seconds=0.0),
                DriftLandmark(position_seconds=1.0, offset_seconds=0.25),
            )
        )
        self.assertEqual(segments[0].correction_factor, 1.0)
        self.assertEqual(segments[0].drift_ppm, 0.0)

    def test_fit_piecewise_drift_requires_two_landmarks(self) -> None:
        with self.assertRaises(ValueError):
            fit_piecewise_drift((DriftLandmark(position_seconds=0.0, offset_seconds=0.0),))


if __name__ == '__main__':
    unittest.main()
