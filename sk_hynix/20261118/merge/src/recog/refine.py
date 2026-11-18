"""Speech alignment on top of the sync-sound offsets (``ALIGN_REFINE``).

Phones in one room all pick up every voice -- each its own owner loudly, the
others faintly. When the sync sound places one of them wrong (a misread beep,
or beeps that were not played at the same instant), the automix hands the
meeting over between copies that are seconds apart, and a sentence comes back
whole. And since the clock-drift ratio is measured from the same start sound,
it goes wrong with it and the gap widens towards the end.

So the speech itself is used: for every pair of tracks it is compared at
``WINDOWS`` places of the meeting (after the sync sound, before the end sound):

1. coarse -- 50 ms log-energy envelopes over ``COARSE_SEC``, Pearson
   correlation over +-``MAX_MS`` (seconds, cheap at this frame size);
2. medium -- 10 ms log-energy envelopes of the same place, +-60 ms around
   the coarse lag;
3. fine   -- raw samples of its loudest 0.5 s, +-8 ms, one-sample steps.

The lags of one pair are then fitted with a straight line ``lag = a + s * t``
(the line that the most places lie within ``AGREE_MS`` of). ``a`` is the
offset, ``s`` what is left of the clock drift -- whatever the sync sound got
wrong, measured on the meeting itself. A pair counts only with ``MIN_AGREE``
places on its line. Phones in different rooms share no sound, never agree, and
keep their sync-sound position -- which is why this is safe to run always: it
moves a track exactly when the tracks hold the same sound, the only case where
the repetition can happen. Tracks are chained from the alignment reference
through the best-agreeing pairs, so two rooms each line up inside themselves.

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
#: How far a track may be moved, either way (ms). 200 until 1.0.1 -- too short
#: for a misplaced sync sound, which is off by whole seconds. Up to 10 s.
MAX_MS = max(0, min(10_000, _env_int("ALIGN_REFINE_MAX_MS", 4000)))
#: How many places of the meeting are compared.
WINDOWS = _env_int("ALIGN_REFINE_WINDOWS", 16)
#: Length of one compared place for the coarse search (s).
COARSE_SEC = _env_float("ALIGN_REFINE_COARSE_SEC", 20.0)
#: Coarse envelope correlation a place needs to count at all.
MIN_SCORE = _env_float("ALIGN_REFINE_MIN_SCORE", 0.3)
#: Places that must lie on one line for a pair to be trusted.
MIN_AGREE = _env_int("ALIGN_REFINE_MIN_AGREE", 3)
#: How close (ms) a place must be to the line. Who is talking moves the lag by
#: a few ms (the distance to each phone), so this is not the sample precision.
AGREE_MS = _env_float("ALIGN_REFINE_AGREE_MS", 10.0)
#: Clock drift beyond this is not drift but two wrong places.
MAX_PPM = _env_float("ALIGN_REFINE_MAX_PPM", 1000.0)
#: Places must span at least this long (s) before a slope is believed.
SLOPE_MIN_SPAN_SEC = _env_float("ALIGN_REFINE_SLOPE_MIN_SPAN_SEC", 300.0)

#: Envelope frames (ms): coarse and medium, and how far around the coarse lag
#: the medium one looks. Fine search reach (ms).
_COARSE_MS = 50
_MEDIUM_MS = 10
_MEDIUM_REACH_MS = 60
_FINE_REACH_MS = 8  # covers the medium step (10 ms) with room
#: Sub-window of a place used for the sample-level search (s).
_FINE_SEC = 0.5
#: Keep clear of the sync sound and of the end sound (s).
_HEAD_GUARD_SEC = 1.0
_TAIL_GUARD_SEC = 15.0
#: Coarse frames quieter than this (RMS of 16-bit samples) count as silence.
_FLOOR = 30.0


@dataclass
class PairResult:
    a: int
    b: int
    lag_ms: float | None          # b relative to a at merged time 0; > 0 means b is late
    agree: int                    # places on the line
    used: int                     # places that passed MIN_SCORE
    score: float                  # mean coarse correlation of the agreeing places
    ppm: float = 0.0              # lag growth per second of meeting, x 1e6
    lags: list[float] = field(default_factory=list)
    times: list[float] = field(default_factory=list)


@dataclass
class RefinePlan:
    corrections_ms: list[float]   # lag of each track at merged time 0
    linked: list[bool]            # track moved (or is the anchor of its group)
    pairs: list[PairResult]
    windows: int
    ppm: list[float] = field(default_factory=list)  # remaining drift per track


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
    out = []
    for i in range(0, len(samples) - frame + 1, frame):
        part = samples[i:i + frame]
        out.append(math.sqrt(sum(map(operator.mul, part, part)) / frame))
    return out


def _log(values: list[float]) -> list[float]:
    """dB of an envelope, floored: a faint copy of a voice keeps its shape."""
    return [20.0 * math.log10(max(v, _FLOOR)) for v in values]


def _centre(values: list[float]) -> tuple[list[float], float]:
    mean = sum(values) / len(values)
    centred = [v - mean for v in values]
    return centred, math.sqrt(sum(v * v for v in centred))


def _best_lag(ref: list[float], target: list[float], reach: int, lo: int | None = None,
              hi: int | None = None) -> tuple[int, float]:
    """Lag (in ``target`` steps, ``target`` holds ``reach`` extra on each side)
    where ``target`` best matches ``ref``, and that Pearson correlation. Only
    lags in ``lo..hi`` (default the whole reach) are tried."""
    ref_c, ref_norm = _centre(ref)
    if ref_norm == 0.0:
        return 0, 0.0
    n = len(ref)
    best, best_score = 0, -1.0
    for lag in range(-reach if lo is None else lo, (reach if hi is None else hi) + 1):
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


def _envelopes(path_a: Path, path_b: Path, delay_a: int, delay_b: int, at: float, rate: int,
               frame_ms: int, reach_ms: int) -> tuple[array, array, list[float], list[float], int]:
    """a's COARSE_SEC from merged time ``at`` and b's same stretch plus
    ``reach_ms`` either side: samples and ``frame_ms`` RMS envelopes."""
    frame = rate * frame_ms // 1000
    reach = reach_ms // frame_ms
    length = int(COARSE_SEC * rate) // frame * frame
    start_a = int((at - delay_a / 1000.0) * rate)
    start_b = int((at - delay_b / 1000.0) * rate) - reach * frame
    a = _read(path_a, start_a, length)
    b = _read(path_b, start_b, length + 2 * reach * frame)
    return a, b, _envelope(a, frame), _envelope(b, frame), reach


def _pair_window(
    path_a: Path, path_b: Path, delay_a: int, delay_b: int, at: float, rate: int
) -> tuple[float, float, float] | None:
    """Lag (ms) of b against a over the place starting at merged time ``at``,
    its coarse score, and the merged time (s) of the place's middle."""
    # Coarse: 50 ms log envelopes over the whole reach.
    _, _, env_a, env_b, reach = _envelopes(path_a, path_b, delay_a, delay_b, at, rate,
                                           _COARSE_MS, MAX_MS)
    if max(env_a, default=0.0) < _FLOOR or max(env_b, default=0.0) < _FLOOR:
        return None  # silence: nothing to compare
    coarse, score = _best_lag(_log(env_a), _log(env_b), reach)
    if score < MIN_SCORE:
        return None
    guess = coarse * _COARSE_MS

    # Medium: 10 ms log envelopes of the same place, around the coarse lag.
    reach_ms = abs(guess) + _MEDIUM_REACH_MS
    a, b, env_a, env_b, reach = _envelopes(path_a, path_b, delay_a, delay_b, at, rate,
                                           _MEDIUM_MS, reach_ms)
    centre = guess // _MEDIUM_MS
    span = _MEDIUM_REACH_MS // _MEDIUM_MS
    medium, _ = _best_lag(_log(env_a), _log(env_b), reach,
                          max(-reach, centre - span), min(reach, centre + span))

    # Fine: the loudest 0.5 s of a, sample by sample around the medium lag.
    frame = rate * _MEDIUM_MS // 1000
    fine_len = int(_FINE_SEC * rate)
    fine_frames = max(1, fine_len // frame)
    energy = [sum(env_a[i:i + fine_frames]) for i in range(0, max(1, len(env_a) - fine_frames + 1))]
    sub = max(range(len(energy)), key=energy.__getitem__) * frame
    fine_reach = rate * _FINE_REACH_MS // 1000
    ref = [float(v) for v in a[sub:sub + fine_len]]
    middle = reach * frame + medium * frame + sub
    target = [float(v) for v in b[max(0, middle - fine_reach):middle + fine_len + fine_reach]]
    lag_ms = float(medium * _MEDIUM_MS)
    if len(ref) == fine_len and len(target) == fine_len + 2 * fine_reach:
        fine, _ = _best_lag(ref, target, fine_reach)
        lag_ms += fine * 1000.0 / rate
    return lag_ms, score, at + COARSE_SEC / 2.0


def _window_starts(delays: list[int], paths: list[Path], head: float, rate: int) -> list[float]:
    ends = []
    for delay, path in zip(delays, paths, strict=True):
        with wave.open(str(path), "rb") as handle:
            ends.append(delay / 1000.0 + handle.getnframes() / handle.getframerate())
    reach = MAX_MS / 1000.0
    first = max(head, max(delays) / 1000.0) + _HEAD_GUARD_SEC + reach
    last = min(ends) - _TAIL_GUARD_SEC - COARSE_SEC - reach
    if last < first or WINDOWS < 1:
        return []
    # Places never overlap: two looks at the same speech are one measurement,
    # and agreeing with itself must not count.
    count = min(WINDOWS, int((last - first) // COARSE_SEC) + 1)
    if count == 1:
        return [first]
    step = (last - first) / (count - 1)
    return [first + step * index for index in range(count)]


def _fit(times: list[float], lags: list[float]) -> tuple[float, float, list[int]]:
    """The line ``lag = a + s * t`` that the most places lie within AGREE_MS of.

    Every flat line through one place and every line through two places is a
    candidate (a dozen places: a few dozen lines). The winner is refitted on
    its own places. Returns (a, s, indexes on the line)."""
    count = len(lags)
    span_ok = count > 1 and max(times) - min(times) >= SLOPE_MIN_SPAN_SEC
    limit = MAX_PPM * 1e-6 * 1000.0  # ms per s
    candidates: list[tuple[float, float]] = [(lag, 0.0) for lag in lags]
    if span_ok:
        for i in range(count):
            for j in range(i + 1, count):
                if abs(times[j] - times[i]) < 1.0:
                    continue
                slope = (lags[j] - lags[i]) / (times[j] - times[i])
                if abs(slope) <= limit:
                    candidates.append((lags[i] - slope * times[i], slope))
    best: list[int] = []
    best_err = math.inf
    for a, s in candidates:
        members = [k for k in range(count) if abs(lags[k] - (a + s * times[k])) <= AGREE_MS]
        err = sum(abs(lags[k] - (a + s * times[k])) for k in members)
        if len(members) > len(best) or (len(members) == len(best) and err < best_err):
            best, best_err = members, err
    if not best:
        return 0.0, 0.0, []
    xs = [times[k] for k in best]
    ys = [lags[k] for k in best]
    if span_ok and max(xs) - min(xs) >= SLOPE_MIN_SPAN_SEC:
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
        if abs(slope) <= limit:
            return my - slope * mx, slope, best
    return median(ys), 0.0, best


def plan(paths: list[Path], delays: list[int], reference: int, head_seconds: float, rate: int) -> RefinePlan:
    """Measure and chain the residual offsets (and drift). Nothing is moved here."""
    count = len(paths)
    starts = _window_starts(delays, paths, head_seconds, rate)
    pairs: list[PairResult] = []
    for a in range(count):
        for b in range(a + 1, count):
            measured: list[tuple[float, float, float]] = []
            for at in starts:
                found = _pair_window(paths[a], paths[b], delays[a], delays[b], at, rate)
                if found is not None:
                    measured.append(found)
            lags = [round(lag, 2) for lag, _, _ in measured]
            times = [round(t, 2) for _, _, t in measured]
            offset, slope, members = _fit(times, lags)
            if len(members) >= MIN_AGREE:
                scores = [measured[k][1] for k in members]
                pairs.append(PairResult(a, b, round(offset, 2), len(members), len(measured),
                                        sum(scores) / len(scores), round(slope * 1000.0, 1),
                                        lags, times))
            else:
                pairs.append(PairResult(a, b, None, len(members), len(measured), 0.0, 0.0,
                                        lags, times))

    # Chain: grow each group from its anchor through the best-agreeing pair.
    corrections = [0.0] * count
    ppm = [0.0] * count
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
                    ppm[pair.b] = ppm[pair.a] + pair.ppm
                    group.add(pair.b)
                else:
                    corrections[pair.a] = corrections[pair.b] - pair.lag_ms
                    ppm[pair.a] = ppm[pair.b] - pair.ppm
                    group.add(pair.a)
                grew = True
                break
        if len(group) > 1:
            for index in group:
                linked[index] = True
    return RefinePlan([round(c, 2) for c in corrections], linked, pairs, len(starts),
                      [round(p, 1) for p in ppm])


def ratio(ppm: float) -> float:
    """The ``drift.apply`` ratio that takes ``ppm`` of drift out of a track."""
    return 1.0 + ppm * 1e-6


def apply(delays: list[int], corrections_ms: list[float],
          ratios: list[float] | None = None) -> tuple[list[int], int]:
    """New delays, and the shift added to all of them to keep every delay >= 0
    (which the merged timeline -- trims, mutes -- must follow).

    ``ratios`` (``ratio(ppm)``, 1.0 = untouched) are for tracks the caller
    resamples with ``drift.apply``: content at file time u then sits at
    u / ratio, so the delay is scaled the same way."""
    ratios = ratios or [1.0] * len(delays)
    moved = [
        (delay - correction) / factor
        for delay, correction, factor in zip(delays, corrections_ms, ratios, strict=True)
    ]
    shift = max(0.0, -min(moved))
    return [int(round(value + shift)) for value in moved], int(round(shift))
