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

Python only computes 100 gain values a second per track. ffmpeg does the
per-sample work (``amultiply``), so an hour of audio stays cheap.
"""

from __future__ import annotations

import math
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


def build_envelopes(tracks: list[Path], delays_ms: list[int] | None, work_dir: Path) -> list[Path]:
    """Compute and write one gain envelope per track. Returns their paths."""
    delays = list(delays_ms) if delays_ms is not None else [0] * len(tracks)
    energies = [frame_energies(path) for path in tracks]
    gains = compute_gains(energies, delays)
    return [
        write_envelope(work_dir / f"automix_{index}.wav", values)
        for index, values in enumerate(gains)
    ]
