"""Waveform refinement of the sync-sound alignment (recog.refine)."""

from __future__ import annotations

import math
import random
import tempfile
import unittest
import wave
from array import array
from pathlib import Path

from recog import refine

RATE = 16_000


def _speech(seconds: float, seed: int) -> list[float]:
    """Noise bursts with syllable-like envelopes: enough structure to correlate."""
    rng = random.Random(seed)
    out: list[float] = []
    while len(out) < seconds * RATE:
        length = int(rng.uniform(0.08, 0.35) * RATE)
        level = rng.choice((0.0, 0.0, rng.uniform(2000, 9000)))
        for i in range(length):
            shape = math.sin(math.pi * i / length)
            out.append(level * shape * rng.uniform(-1, 1))
    return out[: int(seconds * RATE)]


def _write(path: Path, samples: list[float]) -> Path:
    data = array("h", (max(-32767, min(32767, int(v))) for v in samples))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(data.tobytes())
    return path


def _shift(samples: list[float], ms: float, gain: float, seed: int) -> list[float]:
    """The same sound heard ``ms`` later (negative: earlier), quieter, plus noise."""
    rng = random.Random(seed)
    n = int(round(ms * RATE / 1000))
    moved = [0.0] * n + samples if n >= 0 else samples[-n:] + [0.0] * (-n)
    return [gain * v + rng.uniform(-150, 150) for v in moved[: len(samples)]]


class RefineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.room = _speech(60, seed=1)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_same_room_offsets_are_found(self) -> None:
        paths = [
            _write(self.dir / "a.wav", self.room),
            _write(self.dir / "b.wav", _shift(self.room, 37, 0.4, 2)),
            _write(self.dir / "c.wav", _shift(self.room, -55, 0.3, 3)),
        ]
        result = refine.plan(paths, [0, 0, 0], 0, 2.0, RATE)
        self.assertEqual(result.linked, [True, True, True])
        self.assertAlmostEqual(result.corrections_ms[1], 37, delta=0.5)
        self.assertAlmostEqual(result.corrections_ms[2], -55, delta=0.5)
        delays, shift = refine.apply([0, 0, 0], result.corrections_ms)
        # b was 37 ms late and c 55 ms early: b moves back, so all shift by 37.
        self.assertEqual(shift, 37)
        self.assertEqual(delays, [37, 0, 92])

    def test_sync_sound_delays_are_respected(self) -> None:
        # Track b holds 1.2 s more lead-in; the sync sound already knows it
        # (a is pushed 1200 ms) but is 20 ms off.
        late = [0.0] * int(1.2 * RATE) + _shift(self.room, 20, 0.5, 4)
        paths = [_write(self.dir / "a.wav", self.room), _write(self.dir / "b.wav", late)]
        result = refine.plan(paths, [1200, 0], 0, 2.0, RATE)
        self.assertAlmostEqual(result.corrections_ms[1], 20, delta=0.5)

    def test_other_place_is_left_alone(self) -> None:
        paths = [
            _write(self.dir / "a.wav", self.room),
            _write(self.dir / "b.wav", _shift(self.room, 30, 0.4, 2)),
            _write(self.dir / "x.wav", _speech(60, seed=9)),
        ]
        result = refine.plan(paths, [0, 0, 0], 0, 2.0, RATE)
        self.assertEqual(result.linked, [True, True, False])
        self.assertEqual(result.corrections_ms[2], 0.0)

    def test_two_rooms_line_up_inside_themselves(self) -> None:
        other = _speech(60, seed=9)
        paths = [
            _write(self.dir / "a.wav", self.room),
            _write(self.dir / "b.wav", _shift(self.room, 30, 0.4, 2)),
            _write(self.dir / "x.wav", other),
            _write(self.dir / "y.wav", _shift(other, -40, 0.5, 5)),
        ]
        result = refine.plan(paths, [0, 0, 0, 0], 0, 2.0, RATE)
        self.assertEqual(result.linked, [True, True, True, True])
        self.assertAlmostEqual(result.corrections_ms[1], 30, delta=0.5)
        self.assertAlmostEqual(result.corrections_ms[3] - result.corrections_ms[2], -40, delta=0.5)

    def test_too_short_measures_nothing(self) -> None:
        short = self.room[: 10 * RATE]
        paths = [_write(self.dir / "a.wav", short), _write(self.dir / "b.wav", short)]
        result = refine.plan(paths, [0, 0], 0, 2.0, RATE)
        self.assertEqual(result.windows, 0)
        self.assertEqual(result.corrections_ms, [0.0, 0.0])
        self.assertEqual(result.linked, [False, False])


if __name__ == "__main__":
    unittest.main()
