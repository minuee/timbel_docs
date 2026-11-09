"""Waveform refinement of the sync-sound alignment (``ALIGN_REFINE``).

The sync sound places every track to within a few tens of milliseconds, but a
plain sum needs better than that: the same voice, picked up by every phone in
the room, is added once per phone, and copies a few ms to tens of ms apart are
heard as a hall-like echo (and, past ~100 ms, as doubled words in STT). The old
``skHynix`` pipeline did not have the echo because it lined tracks up on the
waveform itself; this module does the same on top of the sync-sound offsets.

For every pair of tracks it compares the *speech* at several places of the
meeting (after the sync sound, before the end sound):

1. coarse -- 2 ms energy envelopes, Pearson correlation over +-``MAX_MS``;
2. fine   -- raw samples, +-3 ms around the coarse lag, one-sample steps.

A pair counts only when enough windows agree on the same lag (within
``AGREE_MS``). Phones in different rooms share no sound, never agree, and keep
their sync-sound position -- which is why this is safe to run always: it moves
a track exactly when the tracks hold the same sound, the only case where the
echo can happen. Tracks are then chained from the alignment reference through
the best-agreeing pairs, so two rooms each line up inside themselves.

Standard library only (see the zero-dependency policy): windows are read with
``wave`` straight from disk, never whole tracks.
"""

from __future__ import annotations

import math
import operator
import os
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


#: On by default since 0.0.7. 0 = sync sound only, as before.
REFINE_ENABLED = _env_bool("ALIGN_REFINE", True)
#: How far a track may be moved, either way (ms).
MAX_MS = _env_int("ALIGN_REFINE_MAX_MS", 200)
#: How many places of the meeting are compared.
WINDOWS = _env_int("ALIGN_REFINE_WINDOWS", 8)
#: Length of one compared place (s).
WINDOW_SEC = _env_float("ALIGN_REFINE_WINDOW_SEC", 4.0)
#: Envelope correlation a window needs to count at all.
MIN_SCORE = _env_float("ALIGN_REFINE_MIN_SCORE", 0.5)
#: Windows that must agree on the lag for a pair to be trusted.
MIN_AGREE = _env_int("ALIGN_REFINE_MIN_AGREE", 3)
#: How close (ms) two windows' lags must be to "agree".
AGREE_MS = _env_float("ALIGN_REFINE_AGREE_MS", 2.0)

#: Coarse envelope frame (ms) and fine search reach around it (ms).
_FRAME_MS = 2
_FINE_REACH_MS = 3
#: Sub-window of a place used for the sample-level search (s).
_FINE_SEC = 0.5
#: Keep clear of the sync sound and of the end sound (s).
_HEAD_GUARD_SEC = 1.0
_TAIL_GUARD_SEC = 15.0


@dataclass
class PairResult:
    a: int
    b: int
    lag_ms: float | None          # b relative to a; > 0 means b is late
    agree: int                    # windows on that lag
    used: int                     # windows that passed MIN_SCORE
    score: float                  # mean envelope correlation of the agreeing windows
    lags: list[float] = field(default_factory=list)


@dataclass
class RefinePlan:
    corrections_ms: list[float]   # subtract from each track's delay
    linked: list[bool]            # track moved (or is the anchor of its group)
    pairs: list[PairResult]
    windows: int


def _read(path: Path, start: int, count: int) -> array:
    """``count`` samples from ``start`` (zero padded outside the file)."""
    out = array("h", bytes(2 * count))
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        lo = max(0, start)
        hi = min(frames, start + count)
        if hi <= lo:
            return out
        handle.setpos(lo)
        chunk = array("h")
        chunk.frombytes(handle.readframes(hi - lo))
        offset = lo - start
        out[offset:offset + len(chunk)] = chunk
    return out


def _envelope(samples: array, frame: int) -> list[float]:
    return [
        math.sqrt(sum(v * v for v in samples[i:i + frame]) / frame)
        for i in range(0, len(samples) - frame + 1, frame)
    ]


def _centre(values: list[float]) -> tuple[list[float], float]:
    mean = sum(values) / len(values)
    centred = [v - mean for v in values]
    return centred, math.sqrt(sum(v * v for v in centred))


def _best_lag(ref: list[float], target: list[float], reach: int) -> tuple[int, float]:
    """Lag (in ``target`` steps, ``target`` holds ``reach`` extra on each side)
    where ``target`` best matches ``ref``, and that Pearson correlation."""
    ref_c, ref_norm = _centre(ref)
    if ref_norm == 0.0:
        return 0, 0.0
    n = len(ref)
    best, best_score = 0, -1.0
    for lag in range(-reach, reach + 1):
        segment = target[reach + lag:reach + lag + n]
        if len(segment) < n:
            continue
        seg_c, seg_norm = _centre(segment)
        if seg_norm == 0.0:
            continue
        score = sum(map(operator.mul, ref_c, seg_c)) / (ref_norm * seg_norm)
        if score > best_score:
            best, best_score = lag, score
    return best, best_score


def _pair_window(
    path_a: Path, path_b: Path, delay_a: int, delay_b: int, at: float, rate: int
) -> tuple[float, float] | None:
    """Lag (ms) of b against a at merged time ``at``, and envelope score."""
    frame = rate * _FRAME_MS // 1000
    reach_frames = MAX_MS // _FRAME_MS
    length = int(WINDOW_SEC * rate) // frame * frame
    start_a = int((at - delay_a / 1000.0) * rate)
    start_b = int((at - delay_b / 1000.0) * rate) - reach_frames * frame
    a = _read(path_a, start_a, length)
    b = _read(path_b, start_b, length + 2 * reach_frames * frame)
    env_a = _envelope(a, frame)
    env_b = _envelope(b, frame)
    if max(env_a, default=0.0) < 30.0 or max(env_b, default=0.0) < 30.0:
        return None  # silence: nothing to compare
    coarse, score = _best_lag(env_a, env_b, reach_frames)
    if score < MIN_SCORE:
        return None

    # Fine: the loudest part of a's window, sample by sample.
    fine_len = int(_FINE_SEC * rate)
    fine_frames = max(1, fine_len // frame)
    energy = [sum(env_a[i:i + fine_frames]) for i in range(0, max(1, len(env_a) - fine_frames + 1))]
    sub = max(range(len(energy)), key=energy.__getitem__) * frame
    reach = rate * _FINE_REACH_MS // 1000
    ref = [float(v) for v in a[sub:sub + fine_len]]
    centre = reach_frames * frame + coarse * frame + sub
    target = [float(v) for v in b[max(0, centre - reach):centre + fine_len + reach]]
    if len(ref) < fine_len or len(target) < fine_len + 2 * reach:
        return coarse * _FRAME_MS, score
    fine, _ = _best_lag(ref, target, reach)
    return (coarse * frame + fine) * 1000.0 / rate, score


def _window_starts(delays: list[int], paths: list[Path], head: float, rate: int) -> list[float]:
    ends = []
    for delay, path in zip(delays, paths, strict=True):
        with wave.open(str(path), "rb") as handle:
            ends.append(delay / 1000.0 + handle.getnframes() / handle.getframerate())
    first = max(head, max(delays) / 1000.0) + _HEAD_GUARD_SEC + MAX_MS / 1000.0
    last = min(ends) - _TAIL_GUARD_SEC - WINDOW_SEC - MAX_MS / 1000.0
    if last < first or WINDOWS < 1:
        return []
    if WINDOWS == 1:
        return [first]
    step = (last - first) / (WINDOWS - 1)
    return [first + step * index for index in range(WINDOWS)]


def _agree(lags: list[float]) -> list[float]:
    """The largest group of lags within AGREE_MS of each other's median."""
    best: list[float] = []
    for lag in lags:
        group = [other for other in lags if abs(other - lag) <= AGREE_MS]
        if len(group) > len(best):
            best = group
    return best


def plan(paths: list[Path], delays: list[int], reference: int, head_seconds: float, rate: int) -> RefinePlan:
    """Measure and chain the residual offsets. Nothing is moved here."""
    count = len(paths)
    starts = _window_starts(delays, paths, head_seconds, rate)
    pairs: list[PairResult] = []
    for a in range(count):
        for b in range(a + 1, count):
            measured: list[tuple[float, float]] = []
            for at in starts:
                found = _pair_window(paths[a], paths[b], delays[a], delays[b], at, rate)
                if found is not None:
                    measured.append(found)
            lags = [round(lag, 2) for lag, _ in measured]
            group = _agree(lags)
            if len(group) >= MIN_AGREE:
                scores = [score for lag, score in measured if round(lag, 2) in group]
                pairs.append(PairResult(a, b, median(group), len(group), len(measured),
                                        sum(scores) / len(scores), lags))
            else:
                pairs.append(PairResult(a, b, None, len(group), len(measured), 0.0, lags))

    # Chain: grow each group from its anchor through the best-agreeing pair.
    corrections = [0.0] * count
    linked = [False] * count
    usable = sorted((p for p in pairs if p.lag_ms is not None),
                    key=lambda p: (p.agree, p.score), reverse=True)
    order = [reference] + [index for index in range(count) if index != reference]
    for anchor in order:
        if linked[anchor]:
            continue
        group = {anchor}
        grew = True
        while grew:
            grew = False
            for pair in usable:
                if (pair.a in group) == (pair.b in group):
                    continue
                if pair.a in group:
                    corrections[pair.b] = corrections[pair.a] + pair.lag_ms
                    group.add(pair.b)
                else:
                    corrections[pair.a] = corrections[pair.b] - pair.lag_ms
                    group.add(pair.a)
                grew = True
                break
        if len(group) > 1:
            for index in group:
                linked[index] = True
    return RefinePlan([round(c, 2) for c in corrections], linked, pairs, len(starts))


def apply(delays: list[int], corrections_ms: list[float]) -> tuple[list[int], int]:
    """New delays, and the shift added to all of them to keep every delay >= 0
    (which the merged timeline -- trims, mutes -- must follow)."""
    moved = [delay - correction for delay, correction in zip(delays, corrections_ms, strict=True)]
    shift = max(0.0, -min(moved))
    return [int(round(value + shift)) for value in moved], int(round(shift))
