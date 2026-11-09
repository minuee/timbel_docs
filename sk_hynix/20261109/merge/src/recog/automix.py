"""Gain-sharing automixer: in every instant, the phone closest to the talker wins.

Field report (2026-10-22): in a small room every phone records every voice, so
the plain sum plays each sentence N times -- once per phone, a little later and
quieter each time -- which is heard as howling and as words repeating
("5초뒤5초뒤5초뒤"). Perfect alignment would turn the repeats into a smear, not
remove them; the copies themselves have to go.

The classic conference-room answer (Dugan's gain sharing): every 10 ms, give
each track the share of the total energy it carries. The talker's own phone
holds most of it and stays near unity; the others, carrying the same voice
10-20 dB down, fall away by about as much again. Shares always sum to one, so
the overall level never pumps, and two people talking at once simply split it.

Decisions are made on *normalised* energy -- each phone divided by its own
typical speaking level -- because phones differ in mic gain and AGC by several
dB, and on raw energy the hottest phone would win every frame. The gains are
applied to the raw audio; this decides who is heard, not how loud.

Since 0.0.8 that gain sharing is only the ``share`` mode; the default is
``select`` (one phone at a time), see MODE below for why.

Python only computes 100 gain values a second per track. ffmpeg does the
per-sample work (``amultiply``), so an hour of audio stays cheap.
"""

from __future__ import annotations

import math
import os
import wave
from array import array
from operator import mul
from pathlib import Path

from . import beep

#: Master switch for requests that do not say (``options.automix``).
AUTOMIX_DEFAULT = beep._env_bool("MERGE_AUTOMIX", True)
FRAME_MS = 10
#: Energy is averaged over this before deciding, so one plosive does not flip
#: the winner.
SMOOTH_MS = beep._env_int("AUTOMIX_SMOOTH_MS", 50)
#: Least a track is ever turned down to. Not silence: a little of every phone
#: keeps the room tone continuous, and switching into dead silence is audible.
FLOOR_DB = beep._env_float("AUTOMIX_FLOOR_DB", -20.0)
#: Gain follows a new talker within ATTACK and lets go over RELEASE; the slow
#: release bridges the gaps between words so a speaker is not chopped.
ATTACK_MS = beep._env_int("AUTOMIX_ATTACK_MS", 10)
RELEASE_MS = beep._env_int("AUTOMIX_RELEASE_MS", 200)
#: A phone's "typical speaking level" is this percentile of its frame energies.
REFERENCE_PERCENTILE = 0.95

#: How the tracks are combined (``AUTOMIX_MODE``), since 0.0.8.
#:
#: ``select`` -- at every instant exactly one phone is heard, the one closest to
#: whoever is talking; the rest are fully off. Field test 2026-11-09: in one room
#: every phone holds every voice, each a few ms later and with its own room
#: echo, so *any* sum of them (even a perfectly aligned one, even gain-shared
#: down to 20-50 %) is heard as a big-hall echo. Each original on its own sounds
#: clean, so the merged file is built from originals only, one at a time. No
#: speech is lost by switching: the chosen phone also hears the other talkers.
#:
#: ``share`` -- the 0.0.4-0.0.7 gain sharing above, kept to compare against.
MODE_SELECT = "select"
MODE_SHARE = "share"
MODES = (MODE_SELECT, MODE_SHARE)
MODE = os.environ.get("AUTOMIX_MODE", MODE_SELECT).strip().lower()
if MODE not in MODES:
    MODE = MODE_SELECT
#: Once a phone is chosen it stays at least this long, so the voice does not
#: flutter between phones inside one word.
HOLD_MS = beep._env_int("AUTOMIX_HOLD_MS", 300)
#: Another phone takes over only when it is this much louder (dB, on the
#: normalised level) than the current one.
SWITCH_DB = beep._env_float("AUTOMIX_SWITCH_DB", 3.0)
#: Hand-over length (ms): the old phone fades out while the new one fades in.
FADE_MS = beep._env_int("AUTOMIX_FADE_MS", 30)
#: Below this normalised level (dB under the phone's typical speaking level)
#: nobody is talking: keep the current phone instead of chasing room noise.
SPEECH_DB = beep._env_float("AUTOMIX_SPEECH_DB", -20.0)


def frame_energies(path: str | Path, frame_ms: int = FRAME_MS) -> list[float]:
    """Mean square per frame of a mono 16-bit wav."""
    sample_rate, samples = beep._load_mono16(path)
    size = max(1, int(sample_rate * frame_ms / 1000))
    out = []
    for start in range(0, len(samples) - size + 1, size):
        segment = samples[start : start + size]
        out.append(sum(map(mul, segment, segment)) / size)
    return out


def _moving_average(values: list[float], width: int) -> list[float]:
    if width <= 1:
        return list(values)
    out = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= width:
            running -= values[index - width]
        out.append(running / min(index + 1, width))
    return out


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def compute_gains(energies: list[list[float]], delays_ms: list[int]) -> list[list[float]]:
    """Per-track gain curves, one value per FRAME_MS, **in each track's own time**.

    ``energies`` are per track in its own time; ``delays_ms`` are the offsets
    the mix will apply. Shares are decided on the merged timeline, where the
    tracks line up, then handed back unshifted so they can be applied before
    the delay.
    """
    count = len(energies)
    if count <= 1:
        return [[1.0] * len(values) for values in energies]
    shifts = [max(0, delay) // FRAME_MS for delay in delays_ms]
    width = max(1, SMOOTH_MS // FRAME_MS)
    normalised = []
    for values in energies:
        smoothed = _moving_average(values, width)
        reference = _percentile(smoothed, REFERENCE_PERCENTILE) or 1.0
        normalised.append([value / reference for value in smoothed])

    length = max(shift + len(values) for shift, values in zip(shifts, normalised))
    floor = 10 ** (FLOOR_DB / 20)
    attack = 1 - math.exp(-FRAME_MS / max(1, ATTACK_MS))
    release = 1 - math.exp(-FRAME_MS / max(1, RELEASE_MS))
    current = [1.0 / count] * count
    aligned = [[0.0] * length for _ in range(count)]
    for frame in range(length):
        powers = []
        for track in range(count):
            position = frame - shifts[track]
            values = normalised[track]
            powers.append(values[position] if 0 <= position < len(values) else 0.0)
        total = sum(powers)
        for track in range(count):
            share = powers[track] / total if total > 0 else 1.0 / count
            target = max(floor, share)
            rate = attack if target > current[track] else release
            current[track] += (target - current[track]) * rate
            aligned[track][frame] = current[track]

    return [
        aligned[track][shifts[track] : shifts[track] + len(energies[track])]
        for track in range(count)
    ]


def compute_select_gains(energies: list[list[float]], delays_ms: list[int]) -> list[list[float]]:
    """``select`` mode: one phone at a time, the others fully off.

    Same inputs and output layout as :func:`compute_gains`. The decision runs
    on the merged timeline on normalised energy (each phone against its own
    typical speaking level, so a hot mic does not win every frame):

    * the loudest phone takes over only when it beats the current one by
      SWITCH_DB and the current one has been held for HOLD_MS;
    * in silence (everyone under SPEECH_DB) the current phone is kept;
    * a phone that has no audio at that instant (not started / already ended)
      is dropped at once;
    * hand-overs are a FADE_MS linear cross-fade.
    """
    count = len(energies)
    if count <= 1:
        return [[1.0] * len(values) for values in energies]
    shifts = [max(0, delay) // FRAME_MS for delay in delays_ms]
    width = max(1, SMOOTH_MS // FRAME_MS)
    normalised = []
    for values in energies:
        smoothed = _moving_average(values, width)
        reference = _percentile(smoothed, REFERENCE_PERCENTILE) or 1.0
        normalised.append([value / reference for value in smoothed])

    length = max(shift + len(values) for shift, values in zip(shifts, normalised))
    hold = max(0, HOLD_MS // FRAME_MS)
    switch_ratio = 10 ** (SWITCH_DB / 10)  # energies are power
    speech = 10 ** (SPEECH_DB / 10)
    step = 1.0 / max(1, FADE_MS // FRAME_MS)
    current: int | None = None
    held = 0
    gains_now = [0.0] * count
    aligned = [[0.0] * length for _ in range(count)]
    for frame in range(length):
        powers: list[float | None] = []
        for track in range(count):
            position = frame - shifts[track]
            values = normalised[track]
            powers.append(values[position] if 0 <= position < len(values) else None)
        present = [track for track in range(count) if powers[track] is not None]
        if present:
            best = max(present, key=lambda track: powers[track])
            if current is None or powers[current] is None:
                current, held = best, 0
            elif best != current and held >= hold and powers[best] >= speech:
                if powers[best] >= max(powers[current], 1e-12) * switch_ratio:
                    current, held = best, 0
        held += 1
        for track in range(count):
            target = 1.0 if track == current else 0.0
            if gains_now[track] < target:
                gains_now[track] = min(target, gains_now[track] + step)
            elif gains_now[track] > target:
                gains_now[track] = max(target, gains_now[track] - step)
            aligned[track][frame] = gains_now[track]

    return [
        aligned[track][shifts[track] : shifts[track] + len(energies[track])]
        for track in range(count)
    ]


def selection_summary(gains: list[list[float]], delays_ms: list[int]) -> dict:
    """Share of the merged time each track was the one heard (%) and how many
    hand-overs happened -- for the response and the log."""
    shifts = [max(0, delay) // FRAME_MS for delay in delays_ms]
    length = max((shift + len(values) for shift, values in zip(shifts, gains)), default=0)
    owner: list[int | None] = []
    for frame in range(length):
        best, best_gain = None, 0.5
        for track, (shift, values) in enumerate(zip(shifts, gains)):
            position = frame - shift
            if 0 <= position < len(values) and values[position] > best_gain:
                best, best_gain = track, values[position]
        owner.append(best)
    heard = [sum(1 for value in owner if value == track) for track in range(len(gains))]
    switches = sum(
        1 for previous, now in zip(owner, owner[1:])
        if now is not None and previous is not None and now != previous
    )
    total = max(1, length)
    return {
        "heardPct": [round(100.0 * count / total, 1) for count in heard],
        "switches": switches,
    }


def write_envelope(path: str | Path, gains: list[float]) -> Path:
    """Gains as a mono 16-bit wav at 1000 / FRAME_MS Hz, for ffmpeg to upsample."""
    # One extra frame: the track's last partial frame would otherwise fall off
    # the end, since amultiply stops with its shorter input.
    padded = list(gains) + gains[-1:]
    values = array("h", (max(0, min(32767, int(round(g * 32767)))) for g in padded))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(1000 // FRAME_MS)
        handle.writeframes(values.tobytes())
    return Path(path)


def build_envelopes(
    tracks: list[Path], delays_ms: list[int] | None, work_dir: Path, mode: str | None = None
) -> tuple[list[Path], dict]:
    """Compute and write one gain envelope per track (``mode`` defaults to
    AUTOMIX_MODE). Returns their paths and a summary for the response."""
    mode = mode or MODE
    delays = list(delays_ms) if delays_ms is not None else [0] * len(tracks)
    energies = [frame_energies(path) for path in tracks]
    if mode == MODE_SHARE:
        gains = compute_gains(energies, delays)
        summary = {"mode": MODE_SHARE}
    else:
        gains = compute_select_gains(energies, delays)
        summary = {"mode": MODE_SELECT, **selection_summary(gains, delays)}
    paths = [
        write_envelope(work_dir / f"automix_{index}.wav", values)
        for index, values in enumerate(gains)
    ]
    return paths, summary
