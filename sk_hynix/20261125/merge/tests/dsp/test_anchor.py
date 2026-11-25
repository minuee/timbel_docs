from __future__ import annotations

from array import array
import tempfile
import unittest
import wave
from pathlib import Path

from audio_sync.dsp import (
    DEFAULT_SYNC_BEEP_SPEC,
    build_sync_beep_samples,
    detect_beep_offset_from_arrays,
    detect_beep_offset_seconds_from_arrays,
    write_sync_beep_wav,
)


class SyncBeepTests(unittest.TestCase):
    def test_build_sync_beep_samples_uses_expected_length(self) -> None:
        spec = DEFAULT_SYNC_BEEP_SPEC
        samples = build_sync_beep_samples(spec)
        expected = round(spec.sample_rate_hz * (spec.duration_ms / 1000.0))
        self.assertEqual(len(samples), expected)
        self.assertGreater(max(abs(sample) for sample in samples), 0)

    def test_write_sync_beep_wav_persists_wave_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = write_sync_beep_wav(Path(tmpdir) / "beep.wav")
            with wave.open(str(output), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getframerate(), DEFAULT_SYNC_BEEP_SPEC.sample_rate_hz)
                self.assertGreater(handle.getnframes(), 0)

    def test_detect_beep_offset_from_arrays_uses_expected_window(self) -> None:
        template = build_sync_beep_samples()
        prefix = array("h", [0] * 240)
        suffix = array("h", [0] * 200)
        samples = array("h")
        samples.extend(prefix)
        samples.extend(template)
        samples.extend(suffix)
        result = detect_beep_offset_from_arrays(
            samples,
            sample_rate=DEFAULT_SYNC_BEEP_SPEC.sample_rate_hz,
            expected_offset_seconds=len(prefix) / DEFAULT_SYNC_BEEP_SPEC.sample_rate_hz,
            expected_window_seconds=0.05,
        )
        self.assertTrue(result.detected)
        self.assertEqual(result.search_mode, "expected")
        self.assertAlmostEqual(result.offset_seconds or 0.0, len(prefix) / DEFAULT_SYNC_BEEP_SPEC.sample_rate_hz, places=4)

    def test_detect_beep_offset_from_arrays_falls_back_when_expected_window_is_wrong(self) -> None:
        template = build_sync_beep_samples()
        prefix = array("h", [0] * (len(template) + 480))
        samples = array("h")
        samples.extend(prefix)
        samples.extend(template)
        samples.extend(array("h", [0] * 100))
        result = detect_beep_offset_from_arrays(
            samples,
            sample_rate=DEFAULT_SYNC_BEEP_SPEC.sample_rate_hz,
            expected_offset_seconds=0.0,
            expected_window_seconds=0.001,
            fallback_window_seconds=0.2,
        )
        self.assertTrue(result.detected)
        self.assertEqual(result.search_mode, "fallback")

    def test_detect_beep_offset_seconds_from_arrays_returns_none_for_silence(self) -> None:
        samples = array("h", [0] * 1000)
        offset_seconds, confidence, search_mode = detect_beep_offset_seconds_from_arrays(
            samples,
            sample_rate=DEFAULT_SYNC_BEEP_SPEC.sample_rate_hz,
            expected_offset_seconds=0.0,
            expected_window_seconds=0.01,
            fallback_window_seconds=0.02,
            minimum_confidence=0.95,
        )
        self.assertIsNone(offset_seconds)
        self.assertGreaterEqual(confidence, 0.0)
        self.assertIn(search_mode, {"expected", "fallback"})


if __name__ == "__main__":
    unittest.main()
