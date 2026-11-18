"""``options.syncSound``: the voice and jingle detectors, and their wiring.

The jingle is synthesised from ``JINGLE_NOTES``, as test_beep does for the
beep. The voice cannot be -- it is a recording -- so the template the server
ships (``assets/sync_voice_16k.wav``) is mixed into the babble instead, which is
exactly what a phone records when the app plays it.
"""

from __future__ import annotations

import math
import random
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_beep import SAMPLE_RATE, _add_beep, _babble, _write_wav
from test_merge_api import _payload

from recog import beep, merge_job, sync_sound
from recog.beep import BeepSpec, trim_point
from recog.merge_job import MergeValidationError, validate_merge_payload
from recog.sync_sound import (
    JINGLE_LENGTH_MS,
    JINGLE_NOTES,
    block_spec,
    detect,
    detect_jingle,
    detect_voice,
    voice_length_ms,
)


def _add_jingle(buffer: array, onset_ms: int, *, peak: float = 12000.0) -> None:
    """The five notes as gen_sync_sounds.py plays them: struck, decaying."""
    for offset_ms, frequency in JINGLE_NOTES:
        base = int(SAMPLE_RATE * (onset_ms + offset_ms) / 1000)
        attack = int(SAMPLE_RATE * 0.005)
        for index in range(int(SAMPLE_RATE * 0.3)):
            position = base + index
            if not 0 <= position < len(buffer):
                continue
            t = index / SAMPLE_RATE
            envelope = math.exp(-t / 0.1) * min(1.0, index / attack)
            value = peak * envelope * math.sin(2 * math.pi * frequency * t)
            buffer[position] = max(-32768, min(32767, int(buffer[position] + value)))


def _voice() -> array:
    _, samples = beep._load_mono16(sync_sound.VOICE_TEMPLATE_PATH)
    return samples


def _add_voice(buffer: array, onset_ms: int, *, gain: float = 1.0, keep: float = 1.0) -> None:
    voice = _voice()
    base = int(SAMPLE_RATE * onset_ms / 1000)
    for index in range(int(len(voice) * keep)):
        position = base + index
        if 0 <= position < len(buffer):
            buffer[position] = max(-32768, min(32767, int(buffer[position] + voice[index] * gain)))


class _Fixtures:
    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="sync-sound-test-"))
        self.rng = random.Random(20261022)

    def track(self, name: str, build=None, *, seconds: float = 12.0) -> Path:
        buffer = _babble(int(SAMPLE_RATE * seconds), self.rng)
        if build is not None:
            build(buffer)
        return _write_wav(self.dir / f"{name}.wav", buffer)


class JingleDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fx = _Fixtures()

    def test_finds_the_jingle_and_every_note(self) -> None:
        result = detect_jingle(self.fx.track("clean", lambda b: _add_jingle(b, 4000)))
        self.assertTrue(result.detected)
        self.assertEqual(result.repeats_found, len(JINGLE_NOTES))
        self.assertAlmostEqual(result.onset_ms, 4000, delta=30)

    def test_finds_a_jingle_heard_from_across_the_room(self) -> None:
        result = detect_jingle(self.fx.track("far", lambda b: _add_jingle(b, 3300, peak=900.0)))
        self.assertTrue(result.detected)
        self.assertAlmostEqual(result.onset_ms, 3300, delta=30)

    def test_own_jingle_is_found_when_another_phone_plays_first(self) -> None:
        def build(buffer: array) -> None:
            _add_jingle(buffer, 4000)
            _add_jingle(buffer, 3940, peak=1500.0)

        result = detect_jingle(self.fx.track("neighbour-first", build))
        self.assertTrue(result.detected)
        self.assertAlmostEqual(result.onset_ms, 4000, delta=30)

    def test_no_jingle_means_no_detection(self) -> None:
        self.assertFalse(detect_jingle(self.fx.track("none")).detected)

    def test_the_beep_is_not_a_jingle(self) -> None:
        """Wrong sound selected: must fall through, not align on garbage."""
        result = detect_jingle(self.fx.track("beep", lambda b: _add_beep(b, 4000, BeepSpec())))
        self.assertFalse(result.detected)


class VoiceDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fx = _Fixtures()

    def test_finds_the_announcement(self) -> None:
        result = detect_voice(self.fx.track("clean", lambda b: _add_voice(b, 3700)))
        self.assertTrue(result.detected)
        self.assertAlmostEqual(result.onset_ms, 3700, delta=20)

    def test_finds_a_quiet_announcement(self) -> None:
        result = detect_voice(self.fx.track("quiet", lambda b: _add_voice(b, 2500, gain=0.15)))
        self.assertTrue(result.detected)
        self.assertAlmostEqual(result.onset_ms, 2500, delta=20)

    def test_own_voice_is_found_when_another_phone_plays_first(self) -> None:
        def build(buffer: array) -> None:
            _add_voice(buffer, 4000)
            _add_voice(buffer, 3940, gain=0.1)

        result = detect_voice(self.fx.track("neighbour-first", build))
        self.assertTrue(result.detected)
        self.assertAlmostEqual(result.onset_ms, 4000, delta=20)

    def test_no_announcement_means_no_detection(self) -> None:
        self.assertFalse(detect_voice(self.fx.track("none")).detected)

    def test_the_beep_is_not_the_announcement(self) -> None:
        result = detect_voice(self.fx.track("beep", lambda b: _add_beep(b, 4000, BeepSpec())))
        self.assertFalse(result.detected)


class DispatchTests(unittest.TestCase):
    def test_each_sound_goes_to_its_detector(self) -> None:
        fx = _Fixtures()
        jingle = fx.track("jingle", lambda b: _add_jingle(b, 4000))
        self.assertTrue(detect(sync_sound.SYNC_SOUND_JINGLE, jingle).detected)
        self.assertFalse(detect(sync_sound.SYNC_SOUND_BEEP, jingle).detected)

    def test_block_spec_spans_the_whole_sound(self) -> None:
        """The trim lands past the end of the sound, whichever it was."""
        for sound, length_ms in (
            (sync_sound.SYNC_SOUND_JINGLE, JINGLE_LENGTH_MS),
            (sync_sound.SYNC_SOUND_VOICE, voice_length_ms()),
        ):
            with self.subTest(sound=sound):
                cut = trim_point(3.0, block_spec(sound), 60.0, tail_ms=0)
                self.assertAlmostEqual(cut, 3.0 + length_ms / 1000, places=3)

    def test_beep_keeps_its_three_repeats(self) -> None:
        spec = BeepSpec()
        self.assertEqual(
            trim_point(3.0, block_spec(sync_sound.SYNC_SOUND_BEEP), 60.0, tail_ms=0),
            trim_point(3.0, spec, 60.0, tail_ms=0),
        )


class OptionTests(unittest.TestCase):
    def _payload(self, options: dict | None = None) -> dict:
        return _payload(options={"align": "none", **(options or {})})

    def test_default_is_beep(self) -> None:
        self.assertEqual(validate_merge_payload(self._payload())["options"]["syncSound"], "beep")

    def test_voice_and_jingle_are_accepted(self) -> None:
        for sound in ("voice", "jingle"):
            with self.subTest(sound=sound):
                result = validate_merge_payload(self._payload({"syncSound": sound}))
                self.assertEqual(result["options"]["syncSound"], sound)

    def test_unknown_sound_is_e4001(self) -> None:
        with self.assertRaises(MergeValidationError) as ctx:
            validate_merge_payload(self._payload({"syncSound": "chime"}))
        self.assertEqual(ctx.exception.code, "E4001")

    def test_upload_path_takes_the_same_option(self) -> None:
        request = merge_job.validate_upload_request([("a.flac", b"x")], sync_sound_name="jingle")
        self.assertEqual(request["options"]["syncSound"], "jingle")
        with self.assertRaises(MergeValidationError):
            merge_job.validate_upload_request([("a.flac", b"x")], sync_sound_name="chime")


class AlignmentTests(unittest.TestCase):
    """The chosen sound drives detection and the cut, and is reported back."""

    def test_jingle_aligns_and_cuts_past_the_jingle(self) -> None:
        from recog.merge_job import MergeJobManager

        fx = _Fixtures()
        tracks = [
            fx.track("a", lambda b: _add_jingle(b, 4000)),
            fx.track("b", lambda b: _add_jingle(b, 3260)),
        ]
        files = [{"participantId": "p1", "startedAt": None}, {"participantId": "p2", "startedAt": None}]
        manager = type("M", (), {"max_offset_ms": 60_000})()
        alignment, delays, _, trim = MergeJobManager._resolve_alignment(
            manager, files, tracks, "none", "all", "jingle"
        )
        self.assertEqual(alignment["mode"], "beep")
        self.assertEqual(alignment["syncSound"], "jingle")
        self.assertAlmostEqual(delays[1] - delays[0], 740, delta=30)
        expected = alignment["beepAtMs"] + JINGLE_LENGTH_MS + beep.tail_ms_for("all")
        self.assertAlmostEqual(alignment["trimmedMs"], expected, delta=1)
        self.assertAlmostEqual(trim * 1000, expected, delta=1)


if __name__ == "__main__":
    unittest.main()


class SyncScanTests(unittest.TestCase):
    """The air-gapped diagnostic: numbers read off a screen must be right."""

    def test_beep_block_measures_the_neighbours_lead(self) -> None:
        from recog.sync_scan import beep_block

        fx = _Fixtures()

        def build(buffer: array) -> None:
            _add_beep(buffer, 5000, BeepSpec(), peak=12000.0)
            _add_beep(buffer, 4900, BeepSpec(), peak=2000.0)

        path = fx.track("block", build)
        result = beep.detect_beep(path)
        lead, _trail = beep_block(path, result.onset_seconds)
        self.assertAlmostEqual(lead, 100, delta=30)

    def test_render_explains_a_miss(self) -> None:
        from recog.sync_scan import render

        report = {
            "files": ["a.flac", "b.flac"],
            "beepSource": "all",
            "sounds": {
                "beep": {
                    "threshold": 6.0,
                    "near": 3.0,
                    "parts": 3,
                    "tracks": [
                        {"file": "a.flac", "detected": True, "atMs": 2700, "confidence": 900.0,
                         "partsFound": 3, "leadMs": 0, "trailMs": 40},
                        {"file": "b.flac", "detected": False, "atMs": None, "confidence": 4.2, "partsFound": 0},
                    ],
                    "alignment": {"mode": "none", "why": "found in fewer than 2 files"},
                }
            },
        }
        text = render(report)
        self.assertIn("기준 근처", text)
        self.assertIn("정렬: none", text)


def _add_beep_tones(buffer: array, onset_ms: int, *, tones: tuple[float, ...], gains: tuple[float, ...] = (1.0, 1.0, 1.0), peak: float = 6000.0) -> None:
    """The beep with chosen tones and per-repeat gains -- what a phone that
    barely hears one tone, or whose noise suppression fades the later
    repeats, actually records."""
    spec = BeepSpec()
    beep_samples = int(SAMPLE_RATE * spec.duration_ms / 1000)
    for repeat, gain in enumerate(gains):
        base = int(SAMPLE_RATE * (onset_ms + repeat * spec.period_ms) / 1000)
        for index in range(beep_samples):
            position = base + index
            if not 0 <= position < len(buffer):
                continue
            t = index / SAMPLE_RATE
            value = peak * gain * sum(math.sin(2 * math.pi * f * t) for f in tones)
            buffer[position] = max(-32768, min(32767, int(buffer[position] + value)))


class FallbackPassTests(unittest.TestCase):
    """Each file on its own (2026-10-23): strict, then relaxed, then the
    announcement. No file leans on another to be found."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fx = _Fixtures()

    def _one(self, path: Path) -> tuple[beep.BeepDetection, dict]:
        strict = [beep.detect_beep(path)]
        detections, methods = sync_sound.guided_pass("beep", [path], strict)
        return detections[0], methods

    def test_one_tone_missing_is_recovered_in_a_single_file(self) -> None:
        path = self.fx.track("one-tone", lambda b: _add_beep_tones(b, 2450, tones=(3000.0,)))
        self.assertFalse(beep.detect_beep(path).detected)  # the strict miss
        detection, methods = self._one(path)
        self.assertEqual(methods, {0: "relaxed"})
        self.assertAlmostEqual(detection.onset_ms, 2450, delta=40)

    def test_faded_third_repeat_does_not_shift_by_a_period(self) -> None:
        """Beeps 1+2 alone look like 2+3 one second early; the first anchors it."""
        path = self.fx.track(
            "faded", lambda b: _add_beep_tones(b, 2450, tones=(3000.0,), gains=(1.0, 0.8, 0.0))
        )
        detection, methods = self._one(path)
        self.assertEqual(methods, {0: "relaxed"})
        self.assertAlmostEqual(detection.onset_ms, 2450, delta=40)

    def test_no_beep_and_no_announcement_stays_missing(self) -> None:
        detection, methods = self._one(self.fx.track("none"))
        self.assertEqual(methods, {})
        self.assertFalse(detection.detected)

    def test_a_held_harmonic_is_not_a_beep(self) -> None:
        """A tone with neighbours (a voice's harmonic stack) fails purity."""
        path = self.fx.track("harmonics", lambda b: _add_beep_tones(b, 2450, tones=(2700.0, 3000.0, 3300.0)))
        _, methods = self._one(path)
        self.assertEqual(methods, {})

    def test_a_broken_beep_is_placed_by_the_announcement(self) -> None:
        """Only one beep tap survived -- too little even for the relaxed rule --
        but the announcement before it places the beep."""
        voice_ms = sync_sound.voice_length_ms()
        beep_at = 1000 + voice_ms + 300

        def build(buffer: array) -> None:
            _add_voice(buffer, 1000)
            _add_beep_tones(buffer, beep_at, tones=(3000.0, 4200.0), gains=(1.0, 0.0, 0.0))

        detection, methods = self._one(self.fx.track("broken-beep", build))
        self.assertEqual(methods, {0: "voice"})
        self.assertAlmostEqual(detection.onset_ms, beep_at, delta=60)

    def test_the_gap_is_measured_from_a_file_that_has_both(self) -> None:
        voice_ms = sync_sound.voice_length_ms()
        gap_ms = 700  # far from the 300 ms default: must come from the good file

        def good(buffer: array) -> None:
            _add_voice(buffer, 1000)
            _add_beep(buffer, 1000 + voice_ms + gap_ms, BeepSpec())

        def broken(buffer: array) -> None:
            _add_voice(buffer, 1500)
            _add_beep_tones(buffer, 1500 + voice_ms + gap_ms, tones=(3000.0, 4200.0), gains=(1.0, 0.0, 0.0))

        paths = [self.fx.track("gap-good", good), self.fx.track("gap-broken", broken)]
        strict = [beep.detect_beep(p) for p in paths]
        detections, methods = sync_sound.guided_pass("beep", paths, strict)
        self.assertEqual(methods, {1: "voice"})
        self.assertAlmostEqual(detections[1].onset_ms, 1500 + voice_ms + gap_ms, delta=60)

    def test_merge_reports_how_the_track_was_found(self) -> None:
        from recog.merge_job import MergeJobManager

        leader = self.fx.track("leader", lambda b: _add_beep(b, 3000, BeepSpec()))
        other = self.fx.track("one-tone-c", lambda b: _add_beep_tones(b, 2450, tones=(3000.0,)))
        files = [{"participantId": "p1", "startedAt": None}, {"participantId": "p2", "startedAt": None}]
        manager = type("M", (), {"max_offset_ms": 60_000})()
        alignment, delays, _, _ = MergeJobManager._resolve_alignment(
            manager, files, [leader, other], "none", "leader", "beep"
        )
        self.assertEqual(alignment["mode"], "beep")
        self.assertEqual(alignment["tracks"][1].get("foundBy"), "relaxed")
        self.assertAlmostEqual(delays[1] - delays[0], 550, delta=40)


class AutomixTests(unittest.TestCase):
    """The closest phone wins; shares sum to one; options reach the request."""

    def test_the_loudest_track_takes_the_share(self) -> None:
        from recog import automix

        loud = [100.0] * 50 + [1.0] * 50
        quiet = [10.0] * 50 + [100.0] * 50  # the same voice 10 dB down, then its own
        gains = automix.compute_gains([loud, quiet], [0, 0])
        self.assertGreater(gains[0][40], 0.8)
        self.assertLess(gains[1][40], 0.2)
        self.assertGreater(gains[1][90], 0.8)

    def test_gains_are_returned_in_each_tracks_own_time(self) -> None:
        from recog import automix

        a = [100.0] * 30 + [0.0] * 70
        b = [0.0] * 100
        gains = automix.compute_gains([a, b], [0, 200])
        self.assertEqual(len(gains[0]), len(a))
        self.assertEqual(len(gains[1]), len(b))

    def test_select_hears_one_phone_at_a_time(self) -> None:
        from recog import automix

        # Talker 1 for 2 s (phone b hears it 10 dB down), then talker 2.
        a = [100.0] * 200 + [10.0] * 200
        b = [10.0] * 200 + [100.0] * 200
        gains = automix.compute_select_gains([a, b], [0, 0])
        self.assertEqual(gains[0][100], 1.0)
        self.assertEqual(gains[1][100], 0.0)  # fully off, not -20 dB
        self.assertEqual(gains[0][350], 0.0)
        self.assertEqual(gains[1][350], 1.0)
        # Never both fully on: at most a short cross-fade overlaps.
        both = sum(1 for x, y in zip(gains[0], gains[1]) if x > 0 and y > 0)
        self.assertLessEqual(both, automix.FADE_MS // automix.FRAME_MS)

    def test_select_holds_through_short_flips(self) -> None:
        from recog import automix

        a = [100.0] * 400
        b = [10.0] * 400
        for start in range(50, 400, 60):  # b peaks for 50 ms, every 600 ms
            b[start:start + 5] = [1000.0] * 5
        gains = automix.compute_select_gains([a, b], [0, 0])
        summary = automix.selection_summary(gains, [0, 0])
        self.assertLess(summary["switches"], 4)
        self.assertGreater(summary["heardPct"][0], 80)

    def test_select_leaves_a_phone_that_has_ended(self) -> None:
        from recog import automix

        a = [100.0] * 100            # phone a stops after 1 s
        b = [10.0] * 300
        gains = automix.compute_select_gains([a, b], [0, 0])
        self.assertEqual(gains[1][200], 1.0)

    def test_speech_level_ignores_a_short_loud_beep(self) -> None:
        from recog import automix

        speech = [1000.0 ** 2] * 6000          # 60 s of speech at 1000 rms
        speech[100:200] = [30000.0 ** 2] * 100  # a 1 s beep near full scale
        level = automix.speech_level_db(speech)
        self.assertAlmostEqual(level, 20 * math.log10(1000 / 32768), delta=0.5)

    def test_track_gains_bring_speech_to_target_within_limit(self) -> None:
        import tempfile

        from recog import automix

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index, amplitude in enumerate((3277, 650, 20)):  # -20, -34, -64 dBFS rms
                path = Path(tmp) / f"t{index}.wav"
                _write_square(path, amplitude, seconds=5)
                paths.append(path)
            gains, levels = automix.track_gains_db(
                paths, [0, 0, 0], None, None, target_db=-20.0, max_db=12.0
            )
        self.assertAlmostEqual(gains[0], 0.0, delta=0.5)
        self.assertEqual(gains[1], 12.0)  # -34 dB needs +14, clamped to +12
        self.assertEqual(gains[2], 12.0)
        self.assertAlmostEqual(levels[1], -34.0, delta=0.5)

    def test_track_gains_measure_after_the_start_trim(self) -> None:
        import tempfile

        from recog import automix

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.wav"
            # 3 s near full scale (sync sound and preamble), then 5 s of speech at -20 dBFS.
            _write_square(path, 30000, seconds=3, then=(3277, 5))
            gains, levels = automix.track_gains_db([path], [0], 3.0, None, target_db=-20.0, max_db=12.0)
        self.assertAlmostEqual(levels[0], -20.0, delta=0.5)
        self.assertAlmostEqual(gains[0], 0.0, delta=0.5)

    def test_build_envelopes_follows_mode(self) -> None:
        import tempfile
        import wave as wave_module
        from array import array as arr

        from recog import automix

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index, level in enumerate((8000, 800)):
                path = Path(tmp) / f"t{index}.wav"
                with wave_module.open(str(path), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(16000)
                    handle.writeframes(arr("h", [level, -level] * 8000).tobytes())
                paths.append(path)
            _, summary = automix.build_envelopes(paths, [0, 0], Path(tmp), automix.MODE_SELECT)
            self.assertEqual(summary["mode"], "select")
            self.assertEqual(len(summary["heardPct"]), 2)
            _, summary = automix.build_envelopes(paths, [0, 0], Path(tmp), automix.MODE_SHARE)
            self.assertEqual(summary, {"mode": "share"})

    def test_option_defaults_on_and_rejects_junk(self) -> None:
        self.assertTrue(validate_merge_payload(_payload(options={"align": "none"}))["options"]["automix"])
        off = validate_merge_payload(_payload(options={"align": "none", "automix": False}))
        self.assertFalse(off["options"]["automix"])
        with self.assertRaises(MergeValidationError):
            validate_merge_payload(_payload(options={"align": "none", "automix": "yes"}))
        request = merge_job.validate_upload_request([("a.flac", b"x")], automix_raw="false")
        self.assertFalse(request["options"]["automix"])


class DriftTests(unittest.TestCase):
    """Start and end sounds measure each phone's clock; the median is the reference.

    The end is what the app plays on stop: the same beep as the start, then
    "녹음을 종료합니다" (2026-10-22 app spec, kept 2026-10-23).
    """

    GAP_MS = 250  # player pause between the end beep and the announcement

    @classmethod
    def setUpClass(cls) -> None:
        cls.fx = _Fixtures()
        cls.dir = cls.fx.dir

    def _track(self, name: str, start_ms: int, end_ms: int | None, seconds: float = 26.0,
               end_beep: bool = True, end_voice: bool = True) -> Path:
        from recog import drift

        _, announcement = beep._load_mono16(drift.VOICE_END_TEMPLATE_PATH)
        beep_ms = 2250

        def build(buffer: array) -> None:
            _add_beep(buffer, start_ms, BeepSpec())
            if end_ms is None:
                return
            if end_beep:
                _add_beep(buffer, end_ms, BeepSpec())
            if end_voice:
                base = int(SAMPLE_RATE * (end_ms + beep_ms + self.GAP_MS) / 1000)
                for index, value in enumerate(announcement):
                    if base + index < len(buffer):
                        buffer[base + index] = max(-32768, min(32767, buffer[base + index] + value))

        return self.fx.track(name, build, seconds=seconds)

    def test_ratio_is_measured_between_start_and_end(self) -> None:
        from recog import drift

        # 15 s between the beeps on the reference; 15.009 s on the fast phone = +600 ppm.
        tracks = [
            self._track("ref", 3000, 18000),
            self._track("fast", 2400, 17409),
            self._track("mid", 2700, 17703),
        ]
        plan = drift.plan("beep", tracks, self.dir)
        self.assertEqual(plan.reference, 2)  # median interval
        # Onsets are good to ~2 ms; over a 15 s test interval that is ~130 ppm.
        # (Over a real hour the same 2 ms is 0.5 ppm.)
        self.assertAlmostEqual(plan.ppm[1], 600 - 200, delta=150)
        self.assertIsNotNone(plan.ratios[1])
        self.assertIsNone(plan.ratios[2])  # the reference itself is not resampled

    def test_a_lost_end_beep_is_placed_back_from_the_announcement(self) -> None:
        """Beep gone, announcement there: the gap measured on the other files
        puts the end where the beep was."""
        from recog import drift

        tracks = [
            self._track("ann-a", 3000, 18000),
            self._track("ann-b", 2400, 17400, end_beep=False),
        ]
        plan = drift.plan("beep", tracks, self.dir)
        self.assertTrue(plan.ends[1].detected)
        self.assertAlmostEqual(plan.ends[1].onset_ms, 17400, delta=60)

    def test_no_end_sound_means_no_correction(self) -> None:
        from recog import drift

        tracks = [self._track("a-noend", 3000, None), self._track("b-noend", 2400, None)]
        plan = drift.plan("beep", tracks, self.dir)
        self.assertEqual(plan.ratios, [None, None])
        self.assertTrue(all(value is None for value in plan.ppm))

    def test_end_cut_lands_just_before_the_end_beep(self) -> None:
        """Cutting from the beep removes the announcement after it too."""
        from recog import drift

        tracks = [self._track("cut-a", 3000, 18000), self._track("cut-b", 2400, 17400)]
        plan = drift.plan("beep", tracks, self.dir)
        cut = drift.end_cut_seconds(plan, 0, 0)
        self.assertAlmostEqual(cut, 18.0 - drift.END_TRIM_LEAD_MS / 1000, delta=0.05)


class DriftShortFileTests(unittest.TestCase):
    def test_a_short_file_does_not_mistake_the_start_for_the_end(self) -> None:
        from recog import drift

        fx = _Fixtures()
        tracks = [
            fx.track(f"short-{i}", lambda b, at=at: _add_beep(b, at, BeepSpec()), seconds=12.0)
            for i, at in enumerate((3000, 2400))
        ]
        plan = drift.plan("beep", tracks, fx.dir)
        self.assertFalse(any(end.detected for end in plan.ends))
        self.assertIsNone(drift.end_cut_seconds(plan, 0, 0))




def _add_template(buffer: array, template: Path, onset_ms: int) -> None:
    _, samples = beep._load_mono16(template)
    base = int(SAMPLE_RATE * onset_ms / 1000)
    for index, value in enumerate(samples):
        position = base + index
        if 0 <= position < len(buffer):
            buffer[position] = max(-32768, min(32767, int(buffer[position] + value)))


class VoiceLangTests(unittest.TestCase):
    """``options.soundLang``: the app's announcement language picks the template."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fx = _Fixtures()
        cls.en = sync_sound.voice_template_path("en")
        cls.ko = sync_sound.voice_template_path("ko")

    def test_default_is_ko_and_en_is_accepted(self) -> None:
        payload = _payload(options={"align": "none"})
        self.assertEqual(validate_merge_payload(payload)["options"]["soundLang"], "ko")
        payload = _payload(options={"align": "none", "soundLang": "en"})
        self.assertEqual(validate_merge_payload(payload)["options"]["soundLang"], "en")

    def test_any_other_value_falls_back_to_ko(self) -> None:
        for value in ("jp", "", None, 3, "EN"):
            with self.subTest(value=value):
                payload = _payload(options={"align": "none", "soundLang": value})
                expected = "en" if value == "EN" else "ko"
                self.assertEqual(validate_merge_payload(payload)["options"]["soundLang"], expected)

    def test_upload_path_takes_the_same_option(self) -> None:
        request = merge_job.validate_upload_request([("a.flac", b"x")], sound_lang="en")
        self.assertEqual(request["options"]["soundLang"], "en")
        request = merge_job.validate_upload_request([("a.flac", b"x")], sound_lang="jp")
        self.assertEqual(request["options"]["soundLang"], "ko")

    def test_each_language_finds_only_its_own_announcement(self) -> None:
        en_track = self.fx.track("en-voice", lambda b: _add_template(b, self.en, 3200))
        ko_track = self.fx.track("ko-voice", lambda b: _add_template(b, self.ko, 3200))
        found = detect(sync_sound.SYNC_SOUND_VOICE, en_track, "en")
        self.assertTrue(found.detected)
        self.assertAlmostEqual(found.onset_ms, 3200, delta=20)
        self.assertFalse(detect(sync_sound.SYNC_SOUND_VOICE, en_track, "ko").detected)
        self.assertFalse(detect(sync_sound.SYNC_SOUND_VOICE, ko_track, "en").detected)

    def test_the_cut_spans_the_english_announcement(self) -> None:
        length_ms = voice_length_ms("en")
        self.assertNotEqual(length_ms, voice_length_ms("ko"))
        cut = trim_point(3.0, block_spec(sync_sound.SYNC_SOUND_VOICE, "en"), 60.0, tail_ms=0)
        self.assertAlmostEqual(cut, 3.0 + length_ms / 1000, places=3)

    def test_a_broken_beep_is_placed_by_the_english_announcement(self) -> None:
        beep_at = 1000 + voice_length_ms("en") + 300

        def build(buffer: array) -> None:
            _add_template(buffer, self.en, 1000)
            _add_beep_tones(buffer, beep_at, tones=(3000.0, 4200.0), gains=(1.0, 0.0, 0.0))

        path = self.fx.track("en-broken-beep", build)
        strict = [beep.detect_beep(path)]
        detections, methods = sync_sound.guided_pass("beep", [path], strict, "en")
        self.assertEqual(methods, {0: "voice"})
        self.assertAlmostEqual(detections[0].onset_ms, beep_at, delta=60)
        _, methods = sync_sound.guided_pass("beep", [path], strict, "ko")
        self.assertEqual(methods, {})

    def test_drift_uses_the_english_end_announcement(self) -> None:
        from recog import drift

        end = drift.voice_end_template_path("en")
        self.assertEqual(end.name, "sync_voice_end_en_16k.wav")
        tail = self.fx.track("en-end", lambda b: _add_template(b, end, 2000))
        self.assertTrue(drift._announcement(tail, "en").detected)
        self.assertFalse(drift._announcement(tail, "ko").detected)


def _write_square(path, amplitude: int, seconds: float, then: tuple[int, float] | None = None) -> None:
    """Mono 16 kHz wav of a square wave (rms = amplitude), optionally followed
    by a second section ``(amplitude, seconds)``."""
    import wave as wave_module
    from array import array as arr

    samples = arr("h")
    for level, length in [(amplitude, seconds)] + ([then] if then else []):
        samples.extend(level if (i // 20) % 2 == 0 else -level for i in range(int(16000 * length)))
    with wave_module.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(samples.tobytes())
