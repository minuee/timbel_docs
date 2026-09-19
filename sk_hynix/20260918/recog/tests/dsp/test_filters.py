from __future__ import annotations

import unittest

from audio_sync.dsp import build_alignment_filter, build_drift_correction_filter


class FfmpegFilterHelperTests(unittest.TestCase):
    def test_build_drift_correction_filter_uses_asetrate_and_aresample(self) -> None:
        self.assertEqual(
            build_drift_correction_filter(sample_rate=48_000, correction_factor=1.0005),
            'asetrate=48024.0,aresample=48000',
        )

    def test_build_alignment_filter_for_positive_offset_adds_delay(self) -> None:
        filter_chain = build_alignment_filter(offset_seconds=0.125, duration_seconds=3.5)
        self.assertIn('adelay=125:all=1', filter_chain)
        self.assertTrue(filter_chain.endswith('atrim=end=3.500000'))

    def test_build_alignment_filter_for_negative_offset_trims_start(self) -> None:
        filter_chain = build_alignment_filter(offset_seconds=-0.25, duration_seconds=2.0)
        self.assertIn('atrim=start=0.250000', filter_chain)
        self.assertIn('asetpts=PTS-STARTPTS', filter_chain)
