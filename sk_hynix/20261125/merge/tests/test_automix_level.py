"""AUTOMIX_LEVEL_MATCH (1.0.3): the same voice keeps its level across a hand-over."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recog import audio, automix  # noqa: E402

FULL = 32768.0 ** 2


def _db(energy: float) -> float:
    return 10 * math.log10(energy / FULL)


def _speech(level_db: float, frames: int) -> list[float]:
    # Speech-like: loud and soft frames alternating, so percentiles mean something.
    loud = FULL * 10 ** (level_db / 10)
    return [loud if (i // 20) % 2 == 0 else loud * 0.01 for i in range(frames)]


class LevelMatchTests(unittest.TestCase):
    def test_one_talker_keeps_his_level_across_a_hand_over(self) -> None:
        # One talker throughout: close to A (-14 dB), far from B (-26 dB).
        a = _speech(-14.0, 1000)
        b = _speech(-26.0, 1000)
        gains = [[1.0] * 500 + [0.0] * 500, [0.0] * 500 + [1.0] * 500]
        out, summary = automix.match_levels([a, b], gains, [0, 0], target_db=-20.0, max_db=12.0)
        heard_a = automix._percentile([e * g * g for e, g in zip(a[:500], out[0][:500])], 0.9)
        heard_b = automix._percentile([e * g * g for e, g in zip(b[500:], out[1][500:])], 0.9)
        self.assertAlmostEqual(_db(heard_a), _db(heard_b), delta=1.0)
        self.assertEqual(summary["stretches"], 2)
        self.assertEqual(summary["fallback"], 0)

    def test_a_stretch_without_speech_takes_the_whole_phone_gain(self) -> None:
        a = _speech(-14.0, 3000)
        a[1000:2000] = [FULL * 1e-6] * 1000  # 40 dB under: room noise only
        b = _speech(-14.0, 3000)
        gains = [[0.0] * 1000 + [1.0] * 1000 + [0.0] * 1000,
                 [1.0] * 1000 + [0.0] * 1000 + [1.0] * 1000]
        out, summary = automix.match_levels([a, b], gains, [0, 0], target_db=-20.0, max_db=12.0,
                                             window_ms=4000)
        self.assertEqual(summary["fallback"], 1)
        # Noise is not pulled up by 12 dB: it gets A's whole-meeting gain (-6 dB).
        self.assertLess(out[0][1500], 1.0)

    def test_gains_are_clamped_and_fades_follow_their_stretch(self) -> None:
        a = _speech(-40.0, 600)
        b = _speech(-40.0, 600)
        fade = [1.0, 0.66, 0.33]
        gains = [[1.0] * 300 + fade + [0.0] * 297, [0.0] * 300 + fade[::-1] + [1.0] * 297]
        out, _ = automix.match_levels([a, b], gains, [0, 0], target_db=-20.0, max_db=12.0)
        top = 10 ** (12 / 20)
        self.assertAlmostEqual(out[0][0], top, places=3)
        self.assertAlmostEqual(out[0][301], 0.66 * top, places=3)
        self.assertAlmostEqual(out[1][300], 0.33 * top, places=3)

    def test_envelopes_are_scaled_to_fit_and_scaled_back_in_the_mix(self) -> None:
        self.assertEqual(automix.envelope_scale([[0.5, 1.0]]), 1.0)
        self.assertAlmostEqual(automix.envelope_scale([[3.0], [0.2]]), 3.0)
        with patch.object(audio, "run_command") as runner:
            audio.mix_tracks(["a.wav", "b.wav"], "out.flac", gain_envelopes=["e0.wav", "e1.wav"],
                             envelope_scale=3.0)
        command = runner.call_args.args[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("[s1][e1]amultiply,volume=3.0000[g1]", filter_complex)


class DenoiseTests(unittest.TestCase):
    def test_off_adds_nothing_and_on_cleans_each_track_first(self) -> None:
        self.assertEqual(audio.denoise_filter(0), "")
        with patch.object(audio, "run_command") as runner:
            audio.mix_tracks(["a.wav", "b.wav"], "out.flac", delays_ms=[0, 100],
                             track_gains_db=[0.0, 6.0], denoise_db=12)
        command = runner.call_args.args[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("[1:a]highpass=f=80,afftdn=nr=12:nf=-50[n1]", filter_complex)
        self.assertIn("[n1]volume=6.0dB[v1]", filter_complex)

    def test_each_phone_is_cleaned_at_its_own_floor(self) -> None:
        self.assertEqual(audio.denoise_filter(12, -46.4), "highpass=f=80,afftdn=nr=12:nf=-46")
        self.assertIn("nf=-20", audio.denoise_filter(12, -5.0))
        with patch.object(audio, "run_command") as runner:
            audio.mix_tracks(["a.wav", "b.wav"], "out.flac", denoise_db=20,
                             denoise_floors_db=[-46.0, None])
        command = runner.call_args.args[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("[0:a]highpass=f=80,afftdn=nr=20:nf=-46[n0]", filter_complex)
        self.assertIn("[1:a]highpass=f=80,afftdn=nr=20:nf=-50[n1]", filter_complex)

    def test_noise_floor_is_the_quiet_end(self) -> None:
        quiet = FULL * 10 ** (-50 / 10)
        loud = FULL * 10 ** (-15 / 10)
        energies = [quiet] * 500 + [loud] * 500
        self.assertAlmostEqual(automix.noise_floor_db(energies), -50.0, delta=0.5)
        self.assertIsNone(automix.noise_floor_db([quiet] * 50))


if __name__ == "__main__":
    unittest.main()
