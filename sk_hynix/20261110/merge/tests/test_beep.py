"""Sync-beep detection and the three-tier alignment fallback.

Fixtures are synthesised here rather than checked in: the beep is defined by its
spec, so generating it from that spec keeps the tests honest about what the app
is being asked to play. Everything runs on pure-Python WAV writing -- no ffmpeg,
so these stay fast and work anywhere.
"""

from __future__ import annotations

import math
import random
import sys
import tempfile
import unittest
import wave
from array import array
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recog import beep as beep_mod
from recog.audio import _mute_expression
from recog.beep import (
    BeepDetection,
    BeepError,
    BeepSpec,
    compute_beep_offsets_ms,
    detect_beep,
    mute_ranges,
    tail_ms_for,
    trim_point,
    wav_duration_seconds,
)

SAMPLE_RATE = 16_000


def _write_wav(path: Path, samples: array, sample_rate: int = SAMPLE_RATE) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())
    return path


def _babble(length: int, rng: random.Random, level: float = 900.0) -> array:
    """Stand-in for a room: broadband noise plus a few wandering voiced tones.

    The tones matter -- flat noise is an unrealistically easy background, and an
    earlier frequency choice (1600/2500 Hz) only failed once speech-like
    formants were present.
    """
    out = array("h", [0]) * length
    for index in range(length):
        t = index / SAMPLE_RATE
        voiced = (
            math.sin(2 * math.pi * 220 * t) * (0.6 + 0.4 * math.sin(2 * math.pi * 4 * t))
            + 0.7 * math.sin(2 * math.pi * 700 * t) * (0.6 + 0.4 * math.sin(2 * math.pi * 3 * t))
            + 0.5 * math.sin(2 * math.pi * 1900 * t) * (0.6 + 0.4 * math.sin(2 * math.pi * 5 * t))
        )
        value = level * voiced + rng.uniform(-level, level)
        out[index] = max(-32768, min(32767, int(value)))
    return out


def _add_beep(
    buffer: array,
    onset_ms: int,
    spec: BeepSpec,
    *,
    peak: float = 12000.0,
) -> None:
    """Mix the beep into ``buffer`` at ``onset_ms``, in place."""
    beep_samples = int(SAMPLE_RATE * spec.duration_ms / 1000)
    fade = max(1, int(SAMPLE_RATE * 0.005))
    amplitude = peak / 2.0
    for repeat in range(spec.repeat):
        base = int(SAMPLE_RATE * (onset_ms + repeat * spec.period_ms) / 1000)
        for index in range(beep_samples):
            position = base + index
            if not 0 <= position < len(buffer):
                continue
            envelope = 1.0
            if index < fade:
                envelope = index / fade
            elif index >= beep_samples - fade:
                envelope = (beep_samples - index - 1) / fade
            t = index / SAMPLE_RATE
            value = amplitude * envelope * (
                math.sin(2 * math.pi * spec.frequency_1 * t)
                + math.sin(2 * math.pi * spec.frequency_2 * t)
            )
            buffer[position] = max(-32768, min(32767, int(buffer[position] + value)))


class _Fixtures:
    """Builds throwaway tracks in a temp dir."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="beep-test-"))
        self.rng = random.Random(20260922)

    def track(self, name: str, onset_ms: int | None, *, peak: float = 12000.0,
              seconds: float = 12.0, spec: BeepSpec | None = None) -> Path:
        length = int(SAMPLE_RATE * seconds)
        buffer = _babble(length, self.rng)
        if onset_ms is not None:
            _add_beep(buffer, onset_ms, spec or BeepSpec(), peak=peak)
        return _write_wav(self.dir / f"{name}.wav", buffer)


class DetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fx = _Fixtures()
        cls.spec = BeepSpec()

    def test_finds_the_beep_and_all_repeats(self) -> None:
        path = self.fx.track("clean", 5000)
        result = detect_beep(path, self.spec)
        self.assertTrue(result.detected)
        self.assertEqual(result.repeats_found, self.spec.repeat)
        self.assertAlmostEqual(result.onset_ms, 5000, delta=120)

    def test_own_beep_is_found_when_another_phone_beeps_first(self) -> None:
        """``all`` mode: playback jitter puts a neighbour's quieter beep ahead of
        the track's own. The anchor walk follows it back, and the onset scan
        used to end before the loud rise -- every phone but the earliest one
        reported no beep and merges fell to align=none."""
        length = int(SAMPLE_RATE * 12.0)
        buffer = _babble(length, self.fx.rng)
        _add_beep(buffer, 5000, self.spec, peak=12000.0)  # own phone, 10 cm
        _add_beep(buffer, 4940, self.spec, peak=1500.0)  # neighbour, 60 ms early
        path = _write_wav(self.fx.dir / "neighbour-first.wav", buffer)
        result = detect_beep(path, self.spec)
        self.assertTrue(result.detected)
        self.assertEqual(result.repeats_found, self.spec.repeat)
        self.assertAlmostEqual(result.onset_ms, 5000, delta=40)

    def test_finds_a_beep_heard_from_across_the_room(self) -> None:
        """The far phone hears the beep *below* the chatter. An absolute
        threshold drops this track; a relative one must not."""
        path = self.fx.track("far", 3070, peak=600.0)
        result = detect_beep(path, self.spec)
        self.assertTrue(result.detected)
        self.assertAlmostEqual(result.onset_ms, 3070, delta=120)

    def test_no_beep_means_no_detection(self) -> None:
        path = self.fx.track("silent", None)
        self.assertFalse(detect_beep(path, self.spec).detected)

    def test_a_single_tone_burst_is_not_a_beep(self) -> None:
        """One tone is not two, and one burst is not three."""
        spec = self.spec
        length = int(SAMPLE_RATE * 12)
        buffer = _babble(length, random.Random(7))
        base = int(SAMPLE_RATE * 4)
        for index in range(int(SAMPLE_RATE * spec.duration_ms / 1000)):
            t = index / SAMPLE_RATE
            value = 12000.0 * math.sin(2 * math.pi * spec.frequency_1 * t)
            buffer[base + index] = max(-32768, min(32767, int(buffer[base + index] + value)))
        path = _write_wav(self.fx.dir / "one_tone.wav", buffer)
        self.assertFalse(detect_beep(path, spec).detected)

    def test_relative_positions_survive_the_group_delay(self) -> None:
        """Absolute onsets trail the truth by roughly a window, but the lag is
        the same on every track -- so the differences, which is all alignment
        uses, stay accurate."""
        truth = {"a": 5000, "b": 4260, "c": 3070}
        onsets = {}
        for name, value in truth.items():
            result = detect_beep(self.fx.track(f"rel_{name}", value), self.spec)
            self.assertTrue(result.detected, name)
            onsets[name] = result.onset_ms
        for name in ("b", "c"):
            measured = onsets["a"] - onsets[name]
            expected = truth["a"] - truth[name]
            self.assertAlmostEqual(measured, expected, delta=60, msg=name)

    def test_search_window_bounds_the_cost(self) -> None:
        """A beep past the search window is not found -- by design, since
        scanning an hour of audio would cost more than it returns."""
        spec = BeepSpec(search_seconds=4.0)
        path = self.fx.track("late", 8000)
        self.assertFalse(detect_beep(path, spec).detected)


class OffsetTests(unittest.TestCase):
    @staticmethod
    def _files(*ids: str, started: dict[str, int] | None = None) -> list[dict]:
        base = datetime(2026, 9, 22, 14, 30, 0, tzinfo=timezone.utc)
        out = []
        for name in ids:
            entry = {"participantId": name, "startedAt": None}
            if started and name in started:
                entry["startedAt"] = base + timedelta(milliseconds=started[name])
            out.append(entry)
        return out

    @staticmethod
    def _found(onset_seconds: float) -> BeepDetection:
        return BeepDetection(True, onset_seconds, 1000.0, 3)

    _MISSING = BeepDetection(False, None, 0.0, 0)

    def test_latest_beep_becomes_the_reference(self) -> None:
        files = self._files("p1", "p2", "p3")
        detections = [self._found(5.0), self._found(4.26), self._found(3.07)]
        reference, tracks, beep_at = compute_beep_offsets_ms(
            files, detections, max_offset_ms=60_000
        )
        self.assertEqual(reference, "p1")
        self.assertAlmostEqual(beep_at, 5.0)
        by_id = {track["participantId"]: track for track in tracks}
        self.assertEqual(by_id["p1"]["offsetMs"], 0)
        self.assertEqual(by_id["p2"]["offsetMs"], 740)
        self.assertEqual(by_id["p3"]["offsetMs"], 1930)
        self.assertTrue(all(track["fallback"] is None for track in tracks))

    def test_aligned_beeps_all_land_together(self) -> None:
        """Which is why one set of mute ranges covers every track."""
        files = self._files("p1", "p2", "p3")
        onsets = [5.0, 4.26, 3.07]
        _, tracks, beep_at = compute_beep_offsets_ms(
            files, [self._found(value) for value in onsets], max_offset_ms=60_000
        )
        for onset, track in zip(onsets, tracks, strict=True):
            self.assertAlmostEqual(onset + track["offsetMs"] / 1000.0, beep_at, places=3)

    def test_a_missing_beep_is_placed_by_its_timestamp(self) -> None:
        """One phone in a bag must not cost everyone else their alignment."""
        files = self._files("p1", "p2", started={"p1": 0, "p2": 740})
        reference, tracks, _ = compute_beep_offsets_ms(
            files + self._files("p3", started={"p3": 1930}),
            [self._found(5.0), self._found(4.26), self._MISSING],
            max_offset_ms=60_000,
        )
        by_id = {track["participantId"]: track for track in tracks}
        self.assertEqual(by_id["p3"]["fallback"], "timestamp")
        self.assertAlmostEqual(by_id["p3"]["offsetMs"], 1930, delta=2)

    def test_a_missing_beep_without_a_timestamp_falls_back_to_zero(self) -> None:
        files = self._files("p1", "p2", "p3")
        _, tracks, _ = compute_beep_offsets_ms(
            files, [self._found(5.0), self._found(4.26), self._MISSING], max_offset_ms=60_000
        )
        by_id = {track["participantId"]: track for track in tracks}
        self.assertEqual(by_id["p3"]["offsetMs"], 0)
        self.assertEqual(by_id["p3"]["fallback"], "none")

    def test_one_beep_is_enough_to_place_its_own_track(self) -> None:
        """Cutting each file at its own beep is the alignment; one beep still
        places its track, and the other falls back as before."""
        files = self._files("p1", "p2")
        _, tracks, beep_at = compute_beep_offsets_ms(
            files, [self._found(5.0), self._MISSING], max_offset_ms=60_000
        )
        self.assertAlmostEqual(beep_at, 5.0)
        self.assertIsNone(tracks[0]["fallback"])
        self.assertEqual(tracks[1]["fallback"], "none")

    def test_no_beep_at_all_is_not_enough(self) -> None:
        files = self._files("p1", "p2")
        with self.assertRaises(BeepError):
            compute_beep_offsets_ms(
                files, [self._MISSING, self._MISSING], max_offset_ms=60_000
            )

    def test_absurd_offset_is_guarded_like_the_timestamp_path(self) -> None:
        files = self._files("p1", "p2")
        _, tracks, _ = compute_beep_offsets_ms(
            files, [self._found(120.0), self._found(0.5)], max_offset_ms=60_000
        )
        by_id = {track["participantId"]: track for track in tracks}
        self.assertEqual(by_id["p2"]["offsetMs"], 0)
        self.assertEqual(by_id["p2"]["fallback"], "outlier")


class MuteTests(unittest.TestCase):
    def test_one_range_per_repeat_at_the_right_spacing(self) -> None:
        spec = BeepSpec()
        ranges = mute_ranges(5.0, spec, lead_ms=150, tail_ms=100)
        self.assertEqual(len(ranges), spec.repeat)
        starts = [start for start, _ in ranges]
        self.assertAlmostEqual(starts[1] - starts[0], spec.period_ms / 1000.0)
        self.assertAlmostEqual(ranges[0][0], 4.85)
        self.assertAlmostEqual(ranges[0][1], 5.35)

    def test_lead_pad_covers_the_detection_lag(self) -> None:
        """The reported onset trails the real one, so muting must start earlier
        than the reported position or the beep's attack survives."""
        ranges = mute_ranges(5.0, BeepSpec())
        self.assertLess(ranges[0][0], 5.0 - 0.1)

    def test_ranges_never_go_negative(self) -> None:
        self.assertEqual(mute_ranges(0.02, BeepSpec())[0][0], 0.0)

    def test_duration_is_read_from_the_wav_header(self) -> None:
        """The trim guard needs each track's length; reading the header avoids
        an ffprobe call per track."""
        path = _Fixtures().track("dur", None, seconds=7.5)
        self.assertAlmostEqual(wav_duration_seconds(path), 7.5, places=3)

    def test_trim_lands_after_the_last_beep(self) -> None:
        spec = BeepSpec()
        point = trim_point(5.016, spec, merged_duration_seconds=13.93, tail_ms=100)
        # 5.016 + 2 periods + one beep + tail
        self.assertAlmostEqual(point, 7.366, places=3)

    def test_trim_is_refused_when_too_little_would_remain(self) -> None:
        """A beep late in a short recording must not swallow the meeting."""
        spec = BeepSpec()
        self.assertIsNone(
            trim_point(5.0, spec, merged_duration_seconds=8.0, min_remainder_seconds=5.0)
        )

    def test_trim_is_allowed_when_enough_remains(self) -> None:
        spec = BeepSpec()
        self.assertIsNotNone(
            trim_point(5.0, spec, merged_duration_seconds=60.0, min_remainder_seconds=5.0)
        )

    def test_commas_are_escaped_for_the_filtergraph(self) -> None:
        """An unescaped comma would end the filter instead of separating
        arguments, and ffmpeg would reject the whole graph."""
        expression = _mute_expression([(1.0, 1.25), (2.0, 2.25)])
        self.assertNotIn("between(t,", expression)
        self.assertIn("between(t\\,1.000\\,1.250)", expression)
        self.assertIn("+", expression)


class TierTests(unittest.TestCase):
    """The three-tier chain: beep beats timestamp beats zero."""

    class _Manager:
        max_offset_ms = 60_000
        _resolve_alignment = beep_mod and None  # replaced below

    def setUp(self) -> None:
        from recog.merge_job import MergeJobManager

        self.resolve = MergeJobManager._resolve_alignment
        self.manager = type("M", (), {"max_offset_ms": 60_000})()

    @staticmethod
    def _files(started: list[int] | None) -> list[dict]:
        base = datetime(2026, 9, 22, 14, 30, 0, tzinfo=timezone.utc)
        return [
            {
                "participantId": f"p{index + 1}",
                "startedAt": None if started is None else base + timedelta(milliseconds=value),
            }
            for index, value in enumerate(started or [0, 0])
        ]

    def test_beep_wins_even_when_align_is_none(self) -> None:
        """The beep is evidence inside the audio; a caller asking for 'none'
        has not seen it. Detection runs regardless of the align option."""
        fx = _Fixtures()
        tracks = [fx.track("t1", 5000), fx.track("t2", 4260)]
        alignment, delays, mutes, trim = self.resolve(
            self.manager, self._files([0, 0]), tracks, "none"
        )
        self.assertEqual(alignment["mode"], "beep")
        self.assertGreater(delays[1], 600)
        # 12s tracks leave plenty after the beep, so trimming wins and muting
        # is not needed -- the cut removes the beeps outright.
        self.assertIsNotNone(trim)
        self.assertIsNone(mutes)
        self.assertEqual(alignment["trimmedMs"], int(round(trim * 1000)))

    def test_no_beep_falls_through_to_timestamp(self) -> None:
        fx = _Fixtures()
        tracks = [fx.track("q1", None), fx.track("q2", None)]
        alignment, delays, mutes, trim = self.resolve(
            self.manager, self._files([0, 267]), tracks, "timestamp"
        )
        self.assertEqual(alignment["mode"], "timestamp")
        self.assertEqual(delays, [0, 267])
        self.assertIsNone(mutes)
        self.assertIsNone(trim)

    def test_no_beep_and_align_none_overlays_from_zero(self) -> None:
        fx = _Fixtures()
        tracks = [fx.track("z1", None), fx.track("z2", None)]
        alignment, delays, mutes, trim = self.resolve(
            self.manager, self._files([0, 267]), tracks, "none"
        )
        self.assertEqual(alignment, {"mode": "none"})
        self.assertIsNone(delays)
        self.assertIsNone(mutes)
        self.assertIsNone(trim)

    def test_short_recording_falls_back_to_muting(self) -> None:
        """Trimming is refused rather than cutting the meeting away, and the
        beeps get silenced in place instead."""
        fx = _Fixtures()
        tracks = [fx.track("s1", 3000, seconds=8.0), fx.track("s2", 2500, seconds=8.0)]
        alignment, _, mutes, trim = self.resolve(
            self.manager, self._files([0, 0]), tracks, "none"
        )
        self.assertEqual(alignment["mode"], "beep")
        self.assertIsNone(trim)
        self.assertEqual(alignment["trimmedMs"], 0)
        self.assertIsNotNone(mutes)

    def test_detection_failure_never_fails_the_merge(self) -> None:
        """A corrupt track drops a tier instead of killing the job."""
        fx = _Fixtures()
        broken = fx.dir / "broken.wav"
        broken.write_bytes(b"not a wav file at all")
        alignment, delays, _, _ = self.resolve(
            self.manager, self._files([0, 267]), [broken, fx.track("ok", None)], "timestamp"
        )
        self.assertEqual(alignment["mode"], "timestamp")
        self.assertEqual(delays, [0, 267])


class BeepSourceTests(unittest.TestCase):
    """``options.beepSource`` widens the beep block; nothing else.

    Detection and the offset maths are shared, because the app schedules
    playback off its pub/sub start signal either way -- so in ``all`` mode every
    phone's beep lands within tens of milliseconds and reads as one event.
    """

    def test_all_gets_the_wider_trailing_pad(self) -> None:
        self.assertEqual(tail_ms_for("leader"), beep_mod.BEEP_MUTE_TAIL_MS)
        self.assertEqual(tail_ms_for("all"), beep_mod.BEEP_ALL_TAIL_MS)
        self.assertGreater(beep_mod.BEEP_ALL_TAIL_MS, beep_mod.BEEP_MUTE_TAIL_MS)

    def test_an_unknown_source_is_treated_as_leader(self) -> None:
        """A record written before the field existed replays as it was merged."""
        self.assertEqual(tail_ms_for(""), beep_mod.BEEP_MUTE_TAIL_MS)

    def test_all_cuts_past_the_other_phones_beeps(self) -> None:
        """The other phones' beeps trail the track's own, so the cut has to go
        further or the last one survives at the head of the output."""
        spec = BeepSpec()
        leader = trim_point(5.0, spec, 60.0, tail_ms=tail_ms_for("leader"))
        every = trim_point(5.0, spec, 60.0, tail_ms=tail_ms_for("all"))
        self.assertAlmostEqual(
            every - leader,
            (beep_mod.BEEP_ALL_TAIL_MS - beep_mod.BEEP_MUTE_TAIL_MS) / 1000.0,
            places=6,
        )

    def test_all_mutes_past_the_other_phones_beeps(self) -> None:
        spec = BeepSpec()
        leader = mute_ranges(5.0, spec, tail_ms=tail_ms_for("leader"))
        every = mute_ranges(5.0, spec, tail_ms=tail_ms_for("all"))
        self.assertEqual([start for start, _ in leader], [start for start, _ in every])
        for (_, leader_end), (_, all_end) in zip(leader, every, strict=True):
            self.assertGreater(all_end, leader_end)


class BeepSourceAlignmentTests(unittest.TestCase):
    """The option reaches the mixing decision and is reported back."""

    def setUp(self) -> None:
        from recog.merge_job import MergeJobManager

        self.resolve = MergeJobManager._resolve_alignment
        self.manager = type("M", (), {"max_offset_ms": 60_000})()
        self.files = [
            {"participantId": "p1", "startedAt": None},
            {"participantId": "p2", "startedAt": None},
        ]

    def _trim_for(self, source: str | None) -> tuple[dict, float]:
        fx = _Fixtures()
        tracks = [fx.track(f"a-{source}", 5000), fx.track(f"b-{source}", 4260)]
        args = (self.manager, self.files, tracks, "none")
        alignment, _, _, trim = self.resolve(*args) if source is None else self.resolve(*args, source)
        return alignment, trim

    def test_source_is_reported_back(self) -> None:
        alignment, _ = self._trim_for("all")
        self.assertEqual(alignment["mode"], "beep")
        self.assertEqual(alignment["beepSource"], "all")

    def test_default_is_leader(self) -> None:
        alignment, _ = self._trim_for(None)
        self.assertEqual(alignment["beepSource"], "leader")

    def test_all_trims_further_than_leader(self) -> None:
        leader, leader_trim = self._trim_for("leader")
        every, all_trim = self._trim_for("all")
        gap = beep_mod.BEEP_ALL_TAIL_MS - beep_mod.BEEP_MUTE_TAIL_MS
        self.assertEqual(every["trimmedMs"] - leader["trimmedMs"], gap)
        self.assertAlmostEqual(all_trim - leader_trim, gap / 1000.0, places=3)


if __name__ == "__main__":
    unittest.main()
