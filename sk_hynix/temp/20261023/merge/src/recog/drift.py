"""Clock-drift correction from a start and an end sync sound.

Phones record with their own crystal, off by tens to hundreds of ppm, so over
an hour two recordings of the same meeting differ by 0.1-0.4 s -- aligned at
the start, they slide apart and the tail echoes. File length cannot measure it
(each phone starts and stops with its own lag); the distance between two shared
events can. The app plays the sync sound again when recording stops (and stops
5 s later), so every track holds a start sound and an end sound, and

    ratio_i = (end_i - start_i) / (end_ref - start_ref)

is how much faster track i's clock ran. Resampling track i by that ratio puts
it on the reference's clock. A pure rate change: the pitch moves by the same
few hundred ppm, far below hearing.

The end sound is **the same kind as the start** (``options.syncSound``), and
for beep / jingle the app follows it with the announcement "녹음을 종료합니다"
(as the app team was told on 2026-10-22, and kept so on 2026-10-23). It is
searched for in the last END_SEARCH_SEC, each file on its own, like the start:
strict, then relaxed, then -- if the sound itself cannot be found -- placed
back from the announcement that follows it. Cutting from the sound's start
removes the announcement too. For ``voice`` the announcement *is* the sound.

Tracks without an end sound are left as they are -- recordings from before the
app change merge exactly as they did.
"""

from __future__ import annotations

import os
import wave
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median

from . import audio, beep, sync_sound
from .beep import BeepDetection

DRIFT_ENABLED = beep._env_bool("DRIFT_CORRECT", True)
#: The end sound is looked for in the last this-many seconds. The app stops 5 s
#: after playing it; the rest is stop latency and margin.
END_SEARCH_SEC = beep._env_float("DRIFT_END_SEARCH_SEC", 15.0)
#: Ratios further from 1 than this are not drift but a wrong detection; the
#: track is left alone. Real phones sit within a few hundred ppm.
DRIFT_MAX_PPM = beep._env_float("DRIFT_MAX_PPM", 1000.0)
#: Below this the correction is not worth a resample (~7 ms over an hour).
DRIFT_MIN_PPM = beep._env_float("DRIFT_MIN_PPM", 2.0)
#: Cut the merged file where the end sound starts, so it (and whatever the app
#: plays after it) does not reach STT.
END_TRIM = beep._env_bool("DRIFT_END_TRIM", True)
END_TRIM_LEAD_MS = beep._env_int("DRIFT_END_TRIM_LEAD_MS", 150)
#: An "end" sound this close after the start sound is the start sound itself,
#: seen again because the file is shorter than the two search windows.
END_MIN_GAP_SEC = 10.0

_ASSETS = Path(__file__).resolve().parent / "assets"
VOICE_END_TEMPLATE_PATH = Path(
    os.environ.get("SYNC_VOICE_END_TEMPLATE") or _ASSETS / "sync_voice_end_16k.wav"
)
#: asetrate takes whole hertz. At 96 kHz one hertz is ~10 ppm, so the residual
#: after correction is within +-5 ppm (~18 ms an hour). At 16 kHz it would be 62.
_RATE_STEP_HZ = 96_000


@dataclass(frozen=True)
class DriftPlan:
    #: Index of the track whose clock the others are moved onto.
    reference: int | None
    #: Per track: end-sound onset in the track's own (uncorrected) time.
    ends: list[BeepDetection]
    #: Per track: start-sound onset, own time.
    starts: list[BeepDetection]
    #: Per track: ratio to apply, None where there is nothing to correct.
    ratios: list[float | None]
    #: Per track: ppm, for the report. None where not measured.
    ppm: list[float | None]


def _tail(path: Path, seconds: float, out: Path) -> float:
    """Write the last ``seconds`` of ``path`` to ``out``; return where it began."""
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        total = handle.getnframes()
        start = max(0, total - int(seconds * rate))
        handle.setpos(start)
        frames = handle.readframes(total - start)
        params = handle.getparams()
    with wave.open(str(out), "wb") as handle:
        handle.setparams(params)
        handle.writeframes(frames)
    return start / rate if rate else 0.0


#: Pause between the end sync sound finishing and the announcement starting
#: (the player loading the second file), when no file lets us measure it.
END_VOICE_GAP_SEC = beep._env_float("DRIFT_END_VOICE_GAP_SEC", 0.3)


def _announcement(tail: Path) -> BeepDetection:
    spec = replace(sync_sound.VoiceSpec.from_env(), search_seconds=END_SEARCH_SEC)
    return sync_sound.detect_voice(tail, spec, template_path=VOICE_END_TEMPLATE_PATH)


def _sound_seconds(sound: str) -> float:
    spec = sync_sound.block_spec(sound)
    return ((spec.repeat - 1) * spec.period_ms + spec.duration_ms) / 1000.0


def _detect_end(sound: str, tail: Path) -> tuple[BeepDetection, str | None]:
    """The end sync sound in one tail, and how it was found (None = strict)."""
    if sound == sync_sound.SYNC_SOUND_VOICE:
        return _announcement(tail), None
    if sound == sync_sound.SYNC_SOUND_JINGLE:
        spec = replace(sync_sound.JingleSpec.from_env(), search_seconds=END_SEARCH_SEC)
        return sync_sound.detect_jingle(tail, spec), None
    spec = replace(beep.BeepSpec.from_env(), search_seconds=END_SEARCH_SEC)
    found = beep.detect_beep(tail, spec)
    if found.detected and found.onset_seconds is not None:
        # Same purity check as the start (sync_sound.detect): the announcement
        # right after must not pass for the beep.
        check = sync_sound.detect_beep_guided(
            tail, max(0.0, found.onset_seconds - 0.06), found.onset_seconds + 0.06, spec,
            min_rise=beep.BEEP_VERIFY_MIN_PURITY,
        )
        if check.detected:
            return found, None
    if beep.BEEP_GUIDED:
        relaxed = sync_sound.detect_beep_guided(tail, 0.0, max(0.0, END_SEARCH_SEC - _sound_seconds(sound)), spec)
        if relaxed.detected:
            return relaxed, sync_sound.FOUND_RELAXED
    return BeepDetection(False, None, found.confidence, 0), None


def _shift(detection: BeepDetection, seconds: float) -> BeepDetection:
    if detection.onset_seconds is None:
        return detection
    return replace(detection, onset_seconds=detection.onset_seconds + seconds)


def plan(sound: str, tracks: list[Path], work_dir: Path) -> DriftPlan:
    """Find start and end sounds in every track and work out the ratios."""
    starts = [sync_sound.detect(sound, path) for path in tracks]
    starts, _ = sync_sound.guided_pass(sound, tracks, starts)

    tails, offsets, ends = [], [], []
    for index, path in enumerate(tracks):
        tail = work_dir / f"drift_tail_{index}.wav"
        offsets.append(_tail(path, END_SEARCH_SEC, tail))
        tails.append(tail)
        ends.append(_detect_end(sound, tail)[0])

    # Files whose end sound could not be found: place it back from the
    # announcement that follows it. The pause between them is one acoustic
    # event heard by every phone, so measure it where both were found.
    if sound != sync_sound.SYNC_SOUND_VOICE and beep.BEEP_GUIDED and not all(e.detected for e in ends):
        notes = [_announcement(tail) for tail in tails]
        length = _sound_seconds(sound)
        gaps = [
            note.onset_seconds - (end.onset_seconds + length)
            for end, note in zip(ends, notes, strict=True)
            if end.detected and note.detected
        ]
        gaps = [gap for gap in gaps if 0.0 <= gap <= 2.0]
        gap = median(gaps) if gaps else END_VOICE_GAP_SEC
        ends = [
            BeepDetection(True, note.onset_seconds - gap - length, note.confidence, note.repeats_found)
            if not end.detected and note.detected and note.onset_seconds - gap - length > 0
            else end
            for end, note in zip(ends, notes, strict=True)
        ]
    ends = [_shift(end, offset) for end, offset in zip(ends, offsets, strict=True)]
    ends = [
        BeepDetection(False, None, end.confidence, 0)
        if end.detected and start.detected and end.onset_seconds < start.onset_seconds + END_MIN_GAP_SEC
        else end
        for start, end in zip(starts, ends, strict=True)
    ]

    intervals: list[float | None] = []
    for start, end in zip(starts, ends, strict=True):
        if start.detected and end.detected and end.onset_seconds > start.onset_seconds:
            intervals.append(end.onset_seconds - start.onset_seconds)
        else:
            intervals.append(None)

    measured = [index for index, value in enumerate(intervals) if value is not None]
    ratios: list[float | None] = [None] * len(tracks)
    ppm: list[float | None] = [None] * len(tracks)
    if len(measured) < 2:
        reference = measured[0] if measured else None
        return DriftPlan(reference, ends, starts, ratios, ppm)

    # The median interval is the reference: one phone with a wild clock (or a
    # bad detection) must not drag everyone else onto its time.
    ordered = sorted(measured, key=lambda index: intervals[index])
    reference = ordered[len(ordered) // 2]
    for index in measured:
        ratio = intervals[index] / intervals[reference]
        value = (ratio - 1.0) * 1e6
        ppm[index] = round(value, 1)
        if abs(value) <= DRIFT_MAX_PPM and abs(value) >= DRIFT_MIN_PPM and index != reference:
            ratios[index] = ratio
    return DriftPlan(reference, ends, starts, ratios, ppm)


def apply(path: Path, ratio: float, out: Path, sample_rate: int, *, timeout: float | None = None) -> None:
    """Move a track onto the reference clock: read it as if recorded at
    ``sample_rate * ratio`` and resample back to ``sample_rate``."""
    declared = round(_RATE_STEP_HZ * ratio)
    audio.run_command(
        [
            "ffmpeg", "-y", "-i", str(path),
            "-af", f"aresample={_RATE_STEP_HZ},asetrate={declared},aresample={sample_rate}",
            "-ac", "1", "-ar", str(sample_rate), "-sample_fmt", "s16", str(out),
        ],
        timeout=timeout,
    )


def end_cut_seconds(drift: DriftPlan, reference_index: int, delay_ms: int) -> float | None:
    """Where the end sound starts on the merged timeline (before the head trim),
    minus the lead -- or None when the reference track has no end sound.

    After correction every track's end sound lands with the reference's, so the
    reference alone places it. ``reference_index`` is the *alignment*
    reference; its end onset is rescaled if that track was itself corrected.
    """
    end = drift.ends[reference_index]
    if not end.detected or end.onset_seconds is None:
        return None
    ratio = drift.ratios[reference_index] or 1.0
    return end.onset_seconds / ratio + delay_ms / 1000.0 - END_TRIM_LEAD_MS / 1000.0
