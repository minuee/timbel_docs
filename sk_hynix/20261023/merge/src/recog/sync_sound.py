"""Which sync sound the app played, and how to find the non-beep ones.

``options.syncSound`` picks one of three sounds. All of them are played on the
same schedule (pub/sub start signal + a fixed delay) and do the same job as the
original beep -- a shared point in the audio that every track lines up on. Only
detection differs:

``beep``    the original three-tap dual tone. Detected by ``beep.detect_beep``.
``voice``   the announcement "음성녹음을 시작합니다" itself. Detected by matching
            its spectrogram, in four pieces (see ``detect_voice``).
``jingle``  a five-note melody. Detected like the beep, but each note is looked
            for at its own frequency and time (see ``detect_jingle``).

Every detector returns a ``beep.BeepDetection`` so the alignment, trimming and
muting code downstream does not care which sound it was.

The sound files the app plays live in ``newDocs/assets/sync_sounds/`` and are
built by ``gen_sync_sounds.py`` there. The jingle's notes below and the voice
template in ``assets/`` must match those files.

Pure Python. Band energies come from per-block DFT coefficients computed with
``sum(map(mul, ...))`` -- C-speed dot products -- and summed across blocks for
overlapping windows, so each sample is touched once per frequency.
"""

from __future__ import annotations

import math
import os
from array import array
from dataclasses import dataclass, replace
from functools import lru_cache
from operator import mul
from pathlib import Path
from statistics import median

from . import beep
from .beep import BeepDetection

SYNC_SOUND_BEEP = "beep"
SYNC_SOUND_VOICE = "voice"
SYNC_SOUND_JINGLE = "jingle"
SYNC_SOUNDS = (SYNC_SOUND_BEEP, SYNC_SOUND_VOICE, SYNC_SOUND_JINGLE)
SYNC_SOUND_DEFAULT = SYNC_SOUND_BEEP

_ASSETS = Path(__file__).resolve().parent / "assets"
#: The announcement as the app plays it, at the working rate. Replace the file
#: (or point here) when the recording changes -- template and playback must be
#: the same audio, since detection matches its exact spectrogram.
VOICE_TEMPLATE_PATH = Path(os.environ.get("SYNC_VOICE_TEMPLATE") or _ASSETS / "sync_voice_16k.wav")

#: Jingle notes as (offset from the first note in ms, frequency in Hz).
#: Must match gen_sync_sounds.py.
JINGLE_NOTES: tuple[tuple[int, float], ...] = (
    (0, 2637.0),
    (150, 3951.1),
    (300, 3322.4),
    (450, 4434.9),
    (600, 5274.0),
)
#: From the first note's onset to where the last note has rung out.
JINGLE_LENGTH_MS = 1600


# ---------------------------------------------------------------------------
# Shared DSP
# ---------------------------------------------------------------------------


def _block_coefficients(samples: array, sample_rate: int, frequency: float, block: int, count: int) -> list[complex]:
    """DFT coefficient of ``frequency`` for each of ``count`` consecutive blocks.

    Phases are referenced to sample 0, so neighbouring blocks can simply be
    added to get the coefficient of a longer window.
    """
    omega = 2.0 * math.pi * frequency / sample_rate
    cos_table = [math.cos(omega * m) for m in range(block)]
    sin_table = [-math.sin(omega * m) for m in range(block)]
    out: list[complex] = []
    for index in range(count):
        start = index * block
        segment = samples[start : start + block]
        local = complex(sum(map(mul, segment, cos_table)), sum(map(mul, segment, sin_table)))
        out.append(local * complex(math.cos(omega * start), -math.sin(omega * start)))
    return out


def _window_energies(coefficients: list[complex], blocks: int, window_samples: int) -> list[float]:
    """Energy of windows ``blocks`` long, one per block (hop = one block)."""
    scale = window_samples * window_samples / 4.0
    out: list[float] = []
    running = sum(coefficients[:blocks], 0j)
    for index in range(len(coefficients) - blocks + 1):
        if index:
            running += coefficients[index + blocks - 1] - coefficients[index - 1]
        out.append((running.real * running.real + running.imag * running.imag) / scale)
    return out


def _band_energies(samples: array, sample_rate: int, frequency: float, *, block: int, blocks: int, limit: int) -> list[float]:
    count = min(limit, len(samples)) // block
    coefficients = _block_coefficients(samples, sample_rate, frequency, block, count)
    return _window_energies(coefficients, blocks, block * blocks)


# ---------------------------------------------------------------------------
# Jingle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JingleSpec:
    search_seconds: float = 10.0
    block_ms: int = 10
    window_blocks: int = 4  # 40 ms, as for the beep
    #: Neighbours either side, as a ratio of the note. Subtracting them is what
    #: makes a note a *tone*: a cough or a hiss lifts the neighbours too.
    neighbour_ratio: float = 0.1
    min_rise: float = 6.0
    fine_step_ms: int = 2
    onset_fraction: float = 0.5
    sustain_ms: int = 20

    @classmethod
    def from_env(cls) -> JingleSpec:
        return cls(
            search_seconds=beep._env_float("BEEP_SEARCH_SEC", 10.0),
            min_rise=beep._env_float("JINGLE_MIN_RISE", 6.0),
        )


def _tonal(samples: array, sample_rate: int, frequency: float, spec: JingleSpec, limit: int) -> tuple[list[float], float]:
    """Per-hop tonal excess at ``frequency`` and the track's background for it."""
    block = int(sample_rate * spec.block_ms / 1000)
    kwargs = {"block": block, "blocks": spec.window_blocks, "limit": limit}
    centre = _band_energies(samples, sample_rate, frequency, **kwargs)
    low = _band_energies(samples, sample_rate, frequency * (1 - spec.neighbour_ratio), **kwargs)
    high = _band_energies(samples, sample_rate, frequency * (1 + spec.neighbour_ratio), **kwargs)
    excess = [max(0.0, c - (lo + hi) / 2) for c, lo, hi in zip(centre, low, high)]
    return excess, max(median(centre), 1e-12)


def _fine_onset(samples: array, sample_rate: int, frequency: float, centre: int, spec: JingleSpec) -> float | None:
    """Rising edge of one note near sample ``centre``, at ``fine_step_ms``."""
    window = int(sample_rate * spec.block_ms * spec.window_blocks / 1000)
    step = max(1, int(sample_rate * spec.fine_step_ms / 1000))
    low = max(0, centre - window * 2)
    high = min(len(samples) - window, centre + window)
    if high - low < step * 4:
        return None
    omega = 2.0 * math.pi * frequency / sample_rate
    cos_table = [math.cos(omega * m) for m in range(window)]
    sin_table = [math.sin(omega * m) for m in range(window)]
    starts = list(range(low, high, step))
    energies = []
    for start in starts:
        segment = samples[start : start + window]
        re = sum(map(mul, segment, cos_table))
        im = sum(map(mul, segment, sin_table))
        energies.append(re * re + im * im)
    threshold = max(energies) * spec.onset_fraction
    needed = max(1, spec.sustain_ms // spec.fine_step_ms)
    for index in range(len(energies) - needed):
        if energies[index] >= threshold and all(v >= threshold * 0.6 for v in energies[index : index + needed]):
            return (starts[index] + window / 2) / sample_rate
    return None


def detect_jingle(path: str | Path, spec: JingleSpec | None = None) -> BeepDetection:
    """Locate the jingle: every note at its own frequency, at its own time.

    The same comb idea as the beep -- a position only scores when *all* notes
    are present where the melody puts them -- with a different frequency per
    tap. Confidence is the weakest note's rise over its background.
    """
    spec = spec or JingleSpec()
    sample_rate, samples = beep._load_mono16(path)
    if sample_rate <= 0 or not samples:
        return BeepDetection(False, None, 0.0, 0)
    limit = int(sample_rate * (spec.search_seconds + JINGLE_LENGTH_MS / 1000))

    hop_ms = spec.block_ms
    rises: list[list[float]] = []
    for _offset, frequency in JINGLE_NOTES:
        excess, background = _tonal(samples, sample_rate, frequency, spec, limit)
        rises.append([value / background for value in excess])
    length = min(len(series) for series in rises)
    shifts = [offset // hop_ms for offset, _ in JINGLE_NOTES]
    candidates = min(int(spec.search_seconds * 1000 / hop_ms), length - shifts[-1])
    if candidates <= 0:
        return BeepDetection(False, None, 0.0, 0)

    best_index, best_score = None, 0.0
    for index in range(candidates):
        score = min(series[index + shift] for series, shift in zip(rises, shifts))
        if score > best_score:
            best_index, best_score = index, score
    if best_index is None or best_score < spec.min_rise:
        return BeepDetection(False, None, best_score, 0)

    # The comb lands somewhere inside the first note; refine each note's edge
    # and median the implied jingle starts, as the beep does with its repeats.
    window_half = spec.block_ms * spec.window_blocks / 2000
    onsets = []
    for (offset, frequency), shift in zip(JINGLE_NOTES, shifts):
        guess = (best_index + shift) * hop_ms / 1000 + window_half
        found = _fine_onset(samples, sample_rate, frequency, int(guess * sample_rate), spec)
        if found is not None:
            onsets.append(found - offset / 1000)
    if not onsets:
        return BeepDetection(False, None, best_score, 0)
    return BeepDetection(True, median(onsets), best_score, len(onsets))


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoiceSpec:
    search_seconds: float = 10.0
    block_ms: int = 5
    window_blocks: int = 4  # 20 ms frames, 5 ms hop
    #: Log-spaced analysis frequencies. The top of the range is where "시작"'s
    #: ㅅ/ㅈ live and conversation is thin, which is what keeps the match
    #: standing when someone talks over the announcement.
    low_hz: float = 250.0
    high_hz: float = 7000.0
    bands: int = 24
    #: The template is matched in this many consecutive pieces; the best
    #: ``pieces - 1`` must agree. One word drowned out by a voice in the room
    #: costs one piece, not the match.
    pieces: int = 4
    #: Exponent applied to band energy before matching (see ``_spectrogram``).
    compression: float = 0.35
    #: Correlation the agreeing pieces must average. Over 52 conversation-only
    #: clips (room + NS simulations) the worst score was 0.44 -- with the same
    #: TTS voice talking, the hardest case; the announcement from the phone's
    #: own speaker scored 0.70-0.81.
    min_score: float = 0.5

    @classmethod
    def from_env(cls) -> VoiceSpec:
        return cls(
            search_seconds=beep._env_float("BEEP_SEARCH_SEC", 10.0),
            min_score=beep._env_float("VOICE_MIN_SCORE", 0.5),
        )

    def frequencies(self) -> list[float]:
        ratio = (self.high_hz / self.low_hz) ** (1 / (self.bands - 1))
        return [self.low_hz * ratio**k for k in range(self.bands)]


def _spectrogram(samples: array, sample_rate: int, spec: VoiceSpec, limit: int) -> list[list[float]]:
    """Band energies, compressed by ``spec.compression``.

    A power law rather than a log: a log blows the quiet frames up to the
    level of the loud ones, so when the announcement plays under someone
    talking, the talker's frames dominate the correlation. Measured on room +
    NS simulations, energy**0.35 kept the weakest real match at 0.43 against
    0.30 for speech alone; log managed 0.28 against 0.21 and lost the match
    whenever the voice was quieter than the room.
    """
    block = int(sample_rate * spec.block_ms / 1000)
    rows = []
    for frequency in spec.frequencies():
        energies = _band_energies(samples, sample_rate, frequency, block=block, blocks=spec.window_blocks, limit=limit)
        rows.append([value**spec.compression for value in energies])
    return rows


@lru_cache(maxsize=4)
def _voice_template(path: str, spec: VoiceSpec) -> tuple[int, list[list[list[float]]], list[int], int]:
    """Template pieces, centred per band, plus where each piece starts (frames)."""
    sample_rate, samples = beep._load_mono16(path)
    rows = _spectrogram(samples, sample_rate, spec, len(samples))
    frames = len(rows[0])
    size = frames // spec.pieces
    pieces, starts = [], []
    for piece in range(spec.pieces):
        a = piece * size
        centred = []
        for row in rows:
            part = row[a : a + size]
            mean = sum(part) / size
            centred.append([value - mean for value in part])
        pieces.append(centred)
        starts.append(a)
    return sample_rate, pieces, starts, size


def voice_length_ms() -> int:
    """Length of the announcement, for trimming."""
    sample_rate, samples = beep._load_mono16(VOICE_TEMPLATE_PATH)
    return int(round(len(samples) * 1000 / sample_rate))


def _piece_scores(rows: list[list[float]], template: list[list[float]], start: int, size: int, candidates: int) -> list[float]:
    """Correlation of one template piece against the track at every candidate."""
    template_energy = sum(sum(map(mul, row, row)) for row in template)
    out = []
    for index in range(candidates):
        a = index + start
        numerator = 0.0
        energy = 0.0
        for row, template_row in zip(rows, template):
            part = row[a : a + size]
            numerator += sum(map(mul, part, template_row))
            total = sum(part)
            energy += sum(map(mul, part, part)) - total * total / size
        denominator = math.sqrt(energy * template_energy)
        out.append(numerator / denominator if denominator > 0 else 0.0)
    return out


def detect_voice(path: str | Path, spec: VoiceSpec | None = None, template_path: str | Path | None = None) -> BeepDetection:
    """Locate the announcement by matching its spectrogram.

    Each band is centred inside the window before correlating, so a phone
    speaker's EQ and the distance to it (a per-band gain, i.e. a per-band
    offset in log energy) do not count against the match. The four pieces are
    correlated separately, the best three averaged for the score, and their
    peaks medianed for the onset -- the voice's equivalent of the beep's
    three repeats.
    """
    spec = spec or VoiceSpec()
    template_rate, pieces, starts, size = _voice_template(str(template_path or VOICE_TEMPLATE_PATH), spec)
    sample_rate, samples = beep._load_mono16(path)
    if sample_rate != template_rate or not samples:
        return BeepDetection(False, None, 0.0, 0)

    hop_ms = spec.block_ms
    template_frames = starts[-1] + size
    limit = int(sample_rate * spec.search_seconds) + template_frames * int(sample_rate * hop_ms / 1000)
    rows = _spectrogram(samples, sample_rate, spec, limit)
    candidates = min(int(spec.search_seconds * 1000 / hop_ms), len(rows[0]) - template_frames)
    if candidates <= 0:
        return BeepDetection(False, None, 0.0, 0)

    scores = [_piece_scores(rows, piece, start, size, candidates) for piece, start in zip(pieces, starts)]
    keep = spec.pieces - 1

    def combined(index: int) -> float:
        return sum(sorted((s[index] for s in scores), reverse=True)[:keep]) / keep

    best_index = max(range(candidates), key=combined)
    best_score = combined(best_index)
    if best_score < spec.min_score:
        return BeepDetection(False, None, best_score, 0)

    # Each piece's own peak near the joint one, sub-frame by a parabola. The
    # pieces that agree are the ones that were not drowned out.
    reach = max(1, 30 // hop_ms)
    positions = []
    for series in scores:
        low, high = max(1, best_index - reach), min(candidates - 2, best_index + reach)
        if high < low:
            continue
        peak = max(range(low, high + 1), key=series.__getitem__)
        if series[peak] < spec.min_score:
            continue
        left, centre, right = series[peak - 1], series[peak], series[peak + 1]
        curvature = left - 2 * centre + right
        shift = 0.5 * (left - right) / curvature if curvature < 0 else 0.0
        positions.append(peak + shift)
    if not positions:
        positions = [float(best_index)]
    # Frame k's window starts at k blocks; the template's frame 0 is the voice's
    # first sample, so the onset is that position in time.
    onset = median(positions) * hop_ms / 1000
    return BeepDetection(True, onset, best_score, len(positions))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def detect(sound: str, path: str | Path) -> BeepDetection:
    """Find ``sound`` in one normalized track, with each detector's env spec."""
    if sound == SYNC_SOUND_VOICE:
        return detect_voice(path, VoiceSpec.from_env())
    if sound == SYNC_SOUND_JINGLE:
        return detect_jingle(path, JingleSpec.from_env())
    spec = beep.BeepSpec.from_env()
    found = beep.detect_beep(path, spec)
    if found.detected and found.onset_seconds is not None:
        # The strict test takes "both bands loud, three times, 1 s apart". The
        # start announcement now always precedes the beep, and its ㅅ/ㅈ are
        # broadband -- with the real beep damaged, "시작" twice plus the one
        # surviving tap passed it (found 1.8 s early). A real beep is a pure,
        # steady tone; check that where it was found.
        check = detect_beep_guided(
            path, max(0.0, found.onset_seconds - 0.06), found.onset_seconds + 0.06, spec,
            min_rise=beep.BEEP_VERIFY_MIN_PURITY,
        )
        if not check.detected:
            return BeepDetection(False, None, found.confidence, 0)
    return found


def block_spec(sound: str) -> beep.BeepSpec:
    """The sound's extent, in the shape ``beep.trim_point``/``mute_ranges`` read.

    Those two only look at ``repeat``, ``period_ms`` and ``duration_ms``, so a
    single sound of the voice's or the jingle's length is one long "repeat".
    """
    spec = beep.BeepSpec.from_env()
    if sound == SYNC_SOUND_VOICE:
        return replace(spec, repeat=1, duration_ms=voice_length_ms())
    if sound == SYNC_SOUND_JINGLE:
        return replace(spec, repeat=1, duration_ms=JINGLE_LENGTH_MS)
    return spec


def detect_beep_guided(
    path: str | Path,
    low_seconds: float,
    high_seconds: float,
    spec: beep.BeepSpec | None = None,
    *,
    min_rise: float | None = None,
) -> BeepDetection:
    """The beep's second pass: either tone alone, the first repeat plus one more,
    between ``low_seconds`` and ``high_seconds`` (where the beep must be, given
    another track's).

    Loosening "both tones, all repeats" lets speech in -- a vowel's harmonic
    sits on 3 kHz for a moment often enough (15 of 104 conversation clips
    passed a first cut). Two things put it back out, both true of the beep and
    rarely of speech:

    * **purity** -- energy at the tone minus its +-10 % neighbours, as for the
      jingle. A harmonic has company; the beep is alone.
    * **steadiness** -- the tone must hold at 0, 100 and 200 ms into each
      repeat. The beep is a flat 250 ms; voiced pitch wanders off a bin fast.
    """
    spec = spec or beep.BeepSpec()
    min_rise = beep.BEEP_GUIDED_MIN_RISE if min_rise is None else min_rise
    sample_rate, samples = beep._load_mono16(path)
    if sample_rate <= 0 or not samples:
        return BeepDetection(False, None, 0.0, 0)
    block = int(sample_rate * spec.hop_ms / 1000)
    blocks = max(1, spec.window_ms // spec.hop_ms)
    span_ms = (spec.repeat - 1) * spec.period_ms + spec.duration_ms
    head = int(spec.search_seconds * sample_rate)
    limit = max(head, int((high_seconds + span_ms / 1000.0) * sample_rate))
    kwargs = {"block": block, "blocks": blocks, "limit": limit}

    step = spec.period_ms // spec.hop_ms
    hold = [0, 100 // spec.hop_ms, 200 // spec.hop_ms]
    tones = (spec.frequency_1, spec.frequency_2)
    best = (-1.0, None, 0, 0.0)  # sum, index, tone, median rise
    strongest = 0.0
    for tone, frequency in enumerate(tones):
        centre = _band_energies(samples, sample_rate, frequency, **kwargs)
        low = _band_energies(samples, sample_rate, frequency * 0.9, **kwargs)
        high = _band_energies(samples, sample_rate, frequency * 1.1, **kwargs)
        background = max(median(centre[: max(1, head // block)]), 1e-12)
        pure = [max(0.0, c - (lo + hi) / 2) / background for c, lo, hi in zip(centre, low, high)]
        first = max(0, int(low_seconds * 1000) // spec.hop_ms)
        last = min(len(pure) - 1 - step * (spec.repeat - 1) - hold[-1], int(high_seconds * 1000) // spec.hop_ms)
        for index in range(first, last + 1):
            repeats = [min(pure[index + step * r + h] for h in hold) for r in range(spec.repeat)]
            # The first repeat plus any other. "Any two" is ambiguous by one
            # period -- with the third beep gone, beeps 1+2 read the same as a
            # position one beep early -- and noise suppression learns the tone,
            # so it is the *later* repeats that fade. The first is the anchor.
            rise = min(repeats[0], max(repeats[1:]))
            strongest = max(strongest, rise)
            if rise >= min_rise and sum(repeats) > best[0]:
                best = (sum(repeats), index, tone, rise)
    _total, best_index, tone, rise = best
    if best_index is None:
        return BeepDetection(False, None, strongest, 0)

    single = replace(spec, frequency_1=tones[tone], frequency_2=tones[tone])
    period_samples = int(sample_rate * spec.period_ms / 1000)
    window = block * blocks
    candidates: list[float] = []
    for repeat in range(spec.repeat):
        onset = beep._onset_near(samples, sample_rate, best_index * block + repeat * period_samples, window, single)
        if onset is not None:
            candidates.append(onset - repeat * spec.period_ms / 1000.0)
    if len(candidates) < 2:
        return BeepDetection(False, None, rise, len(candidates))
    # A repeat noise suppression ate refines to noise; the median of three
    # ignores one such outlier, which is all two-of-three can promise.
    return BeepDetection(True, median(candidates), rise, len(candidates))


#: Gap between the end of the start announcement and the beep, when no track
#: lets us measure it. The app plays the two files back to back; the pause is
#: the player loading the second file (tens to a few hundred ms, per phone).
VOICE_TO_BEEP_GAP_SEC = beep._env_float("BEEP_VOICE_GAP_SEC", 0.3)

FOUND_RELAXED = "relaxed"
FOUND_BY_VOICE = "voice"


def guided_pass(
    sound: str, paths: list[Path], detections: list[BeepDetection]
) -> tuple[list[BeepDetection], dict[int, str]]:
    """Each file on its own: if the strict test missed the beep, try harder.

    Every file is cut at its own beep -- that is all the alignment is -- so no
    file leans on another to be found (user's rule, 2026-10-23):

    1. relaxed beep: either tone alone, first repeat plus one more, anywhere in
       the head, at a bar speech does not reach (``BEEP_GUIDED_MIN_RISE``);
    2. the start announcement: the app always plays "음성녹음을 시작합니다"
       right before the beep, so its end places the beep. The gap between them
       is the same acoustic event in every file; when some file has both the
       beep and the announcement, that measured gap is used, otherwise
       ``VOICE_TO_BEEP_GAP_SEC``.

    Beep only. Returns the updated detections and, for each file it filled,
    which way it was found ("relaxed" / "voice").
    """
    if sound != SYNC_SOUND_BEEP or not beep.BEEP_GUIDED:
        return detections, {}
    spec = beep.BeepSpec.from_env()
    span = ((spec.repeat - 1) * spec.period_ms + spec.duration_ms) / 1000.0
    high = max(0.0, spec.search_seconds - span)
    updated = list(detections)
    methods: dict[int, str] = {}

    missing = [index for index, detection in enumerate(detections) if not detection.detected]
    for index in missing:
        retry = detect_beep_guided(paths[index], 0.0, high, spec)
        if retry.detected:
            updated[index] = retry
            methods[index] = FOUND_RELAXED

    still = [index for index in missing if index not in methods]
    if not still:
        return updated, methods

    voices = {index: detect_voice(path) for index, path in enumerate(paths)}
    voice_seconds = voice_length_ms() / 1000.0
    gaps = [
        updated[index].onset_seconds - (voices[index].onset_seconds + voice_seconds)
        for index in range(len(paths))
        if index not in still and updated[index].detected and voices[index].detected
    ]
    gaps = [gap for gap in gaps if 0.0 <= gap <= 2.0]  # a plausible player pause only
    gap = median(gaps) if gaps else VOICE_TO_BEEP_GAP_SEC
    for index in still:
        voice = voices[index]
        if not voice.detected:
            continue
        onset = voice.onset_seconds + voice_seconds + gap
        updated[index] = BeepDetection(True, onset, voice.confidence, voice.repeats_found)
        methods[index] = FOUND_BY_VOICE
    return updated, methods
