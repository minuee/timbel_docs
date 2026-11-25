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


def _room(seconds: float, rate: int = RATE) -> tuple[list[float], list[float]]:
    """Two talkers taking turns every 5 s (the other one murmurs)."""
    one, two = _speech(seconds, 1), _speech(seconds, 2)
    if rate != RATE:
        step = RATE // rate
        one, two = one[::step], two[::step]
    turn = 5 * rate
    one = [v if (i // turn) % 2 == 0 else v * 0.05 for i, v in enumerate(one)]
    two = [v if (i // turn) % 2 == 1 else v * 0.05 for i, v in enumerate(two)]
    return one, two


def _phone(near: list[float], far: list[float], cross: float, seed: int) -> list[float]:
    """A phone in the room: its own talker loud, the other one ``cross`` as loud."""
    rng = random.Random(seed)
    return [n + cross * f + rng.uniform(-150, 150) for n, f in zip(near, far, strict=True)]


def _late(samples: list[float], ms: float, ppm: float, rate: int) -> list[float]:
    """The same recording ``ms`` late, its clock running ``ppm`` slow."""
    scale = 1.0 + ppm * 1e-6
    n = len(samples)
    out = []
    for u in range(n):
        src = (u - ms * rate / 1000.0) / scale
        i = math.floor(src)
        frac = src - i
        out.append(samples[i] * (1 - frac) + samples[i + 1] * frac if 0 <= i < n - 1 else 0.0)
    return out


def _write_rate(path: Path, samples: list[float], rate: int) -> Path:
    data = array("h", (max(-32767, min(32767, int(v))) for v in samples))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data.tobytes())
    return path


class RefineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.room = _speech(150, seed=1)
        self._max_ms = refine.MAX_MS

    def tearDown(self) -> None:
        refine.MAX_MS = self._max_ms
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

    def test_misplaced_sync_sound_is_found_seconds_away(self) -> None:
        # The 1.0.1 field case: each phone holds its own talker loudly and the
        # other faintly, and one phone was placed 2.3 s late.
        one, two = _room(150)
        paths = [
            _write(self.dir / "a.wav", _phone(one, two, 0.15, 5)),
            _write(self.dir / "b.wav", _shift(_phone(two, one, 0.15, 6), 2300, 1.0, 7)),
        ]
        result = refine.plan(paths, [0, 0], 0, 2.0, RATE)
        self.assertEqual(result.linked, [True, True])
        self.assertAlmostEqual(result.corrections_ms[1], 2300, delta=2.0)

    def test_reach_is_max_ms(self) -> None:
        refine.MAX_MS = 1000
        one, two = _room(150)
        paths = [
            _write(self.dir / "a.wav", _phone(one, two, 0.15, 5)),
            _write(self.dir / "b.wav", _shift(_phone(two, one, 0.15, 6), 2300, 1.0, 7)),
        ]
        result = refine.plan(paths, [0, 0], 0, 2.0, RATE)
        self.assertEqual(result.linked, [False, False])

    def test_clock_drift_is_measured(self) -> None:
        # 7 minutes at 8 kHz (cheaper): 1.5 s late and 300 ppm slow.
        rate = 8000
        one, two = _room(420, rate)
        paths = [
            _write_rate(self.dir / "a.wav", _phone(one, two, 0.15, 5), rate),
            _write_rate(self.dir / "b.wav", _late(_phone(two, one, 0.15, 6), 1500, 300, rate), rate),
        ]
        result = refine.plan(paths, [0, 0], 0, 2.0, rate)
        self.assertEqual(result.linked, [True, True])
        self.assertAlmostEqual(result.corrections_ms[1], 1500, delta=15)
        self.assertAlmostEqual(result.ppm[1], 300, delta=40)

    def test_apply_scales_resampled_tracks(self) -> None:
        delays, shift = refine.apply([0, 3000], [0.0, 1000.0], [1.0, refine.ratio(500)])
        self.assertEqual(shift, 0)
        self.assertEqual(delays, [0, round(2000 / 1.0005)])

    def test_other_place_is_left_alone(self) -> None:
        paths = [
            _write(self.dir / "a.wav", self.room),
            _write(self.dir / "b.wav", _shift(self.room, 30, 0.4, 2)),
            _write(self.dir / "x.wav", _speech(150, seed=9)),
        ]
        result = refine.plan(paths, [0, 0, 0], 0, 2.0, RATE)
        self.assertEqual(result.linked, [True, True, False])
        self.assertEqual(result.corrections_ms[2], 0.0)

    def test_two_rooms_line_up_inside_themselves(self) -> None:
        other = _speech(150, seed=9)
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


class HeadCheckTests(unittest.TestCase):
    """ALIGN_HEAD_CHECK (1.0.3): a phone whose first minute is off the line."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.room = _speech(200, seed=1)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _pair(self, head_ms: float, change_sec: float) -> list[Path]:
        cut = int(change_sec * RATE)
        late = _shift(self.room, head_ms, 0.4, 2)[:cut] + _shift(self.room, 0, 0.4, 3)[cut:]
        return [_write(self.dir / "a.wav", self.room), _write(self.dir / "b.wav", late)]

    def test_a_head_off_the_line_is_spliced_back(self) -> None:
        paths = self._pair(40, 70)
        fixes, measured = refine.head_plan(paths, [0, 0], 0, [True, True], 2.0, RATE)
        self.assertEqual(len(fixes), 1)
        fix = fixes[0]
        self.assertEqual(fix.track, 1)
        self.assertAlmostEqual(fix.shift_ms, 40, delta=1.0)
        self.assertTrue(50 < fix.splice_at < 110, fix.splice_at)
        target = self.dir / "b2.wav"
        refine.splice(paths[1], target, fix.splice_at, fix.shift_ms)
        delays, shift = refine.apply([0, 0], [0.0, fix.shift_ms])
        again, record = refine.head_plan([paths[0], target], delays, 0, [True, True], 2.0, RATE)
        self.assertEqual(again, [])
        for value in record[1]:
            if value is not None:
                self.assertLessEqual(abs(value), 2.0)

    def test_a_phone_on_the_line_is_left_alone(self) -> None:
        paths = self._pair(0, 70)
        fixes, measured = refine.head_plan(paths, [0, 0], 0, [True, True], 2.0, RATE)
        self.assertEqual(fixes, [])
        self.assertIn(1, measured)

    def test_off_all_the_way_is_not_a_head_problem(self) -> None:
        paths = self._pair(40, 199)
        fixes, _ = refine.head_plan(paths, [0, 0], 0, [True, True], 2.0, RATE)
        self.assertEqual(fixes, [])

    def test_splice_cuts_when_the_head_is_early(self) -> None:
        source = _write(self.dir / "s.wav", [float(i % 1000) for i in range(RATE * 2)])
        target = self.dir / "t.wav"
        refine.splice(source, target, 1.0, -50)
        with wave.open(str(target), "rb") as handle:
            self.assertEqual(handle.getnframes(), RATE * 2 - RATE // 20)
        refine.splice(source, target, 1.0, 50)
        with wave.open(str(target), "rb") as handle:
            self.assertEqual(handle.getnframes(), RATE * 2 + RATE // 20)
