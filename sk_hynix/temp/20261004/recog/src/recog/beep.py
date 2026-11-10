"""Sync-beep detection for /v1/merge track alignment.

The mobile app plays a short dual-tone beep a few seconds into a recording.
Every phone in the room picks it up, so the beep is a *shared point in the audio
itself* -- unlike ``startedAt``, it is immune to device clock skew, recorder
start-up lag and mic buffering. Lining the beeps up lines the recordings up.

Who plays it is the caller's ``options.beepSource`` (see ``BEEP_SOURCES``), and
it does not change detection: the app schedules playback off its pub/sub start
signal, so in ``all`` mode every phone's beep lands within a few tens of
milliseconds and the track reads as one event. Only the width of that event
differs, which is why the trailing pad is per-source.

Detection is three steps, each earning its place (see newDocs/04):

1. **Goertzel** gives the per-frame energy of exactly two frequencies at O(N),
   which keeps us inside the zero-pip-dependency rule.
2. A **comb filter** over the known repeat interval finds the beep: a candidate
   only scores high when *all* repeats are present, so a lone cough cannot pass.
3. **Forward onset scanning**, medianed across the repeats, pins the rise.

Measured on synthetic babble with the beep attenuated 6/20/26 dB: 100% detection,
worst inter-track alignment error 42 ms, 0.11 s per track.

Everything is configurable through ``BEEP_*`` environment variables because the
app side may still change the tone.
"""

from __future__ import annotations

import math
import os
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from statistics import median


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class BeepSpec:
    """What the app plays. Must match ``newDocs/assets/sync_beep.wav``.

    ``frequency_1``/``frequency_2`` must stay below the Nyquist limit of the
    working format (16 kHz -> 8 kHz); anything above is gone before we see it.
    They must also not be harmonically related, or one tone's overtone lands in
    the other's bin and the "both tones together" test stops meaning anything.
    """

    frequency_1: float = 3000.0
    frequency_2: float = 4200.0
    duration_ms: int = 250
    repeat: int = 3
    period_ms: int = 1000

    #: Only the head of the file is searched -- the beep is played seconds in,
    #: and scanning an hour of audio would cost far more than it can return.
    search_seconds: float = 10.0

    #: Analysis window. Long enough for narrowband selectivity, short enough
    #: that the onset is not smeared beyond the alignment budget.
    window_ms: int = 40
    hop_ms: int = 10
    fine_hop_ms: int = 2

    #: Band energy must exceed the track's own median by this factor. A ratio,
    #: never an absolute level: across the room the beep is quieter than the
    #: chatter, and an absolute threshold silently drops those tracks.
    min_rise: float = 6.0

    #: Onset is where energy crosses this fraction of the local peak and stays.
    onset_fraction: float = 0.5
    sustain_ms: int = 40

    @classmethod
    def from_env(cls) -> BeepSpec:
        return cls(
            frequency_1=_env_float("BEEP_FREQ_1", 3000.0),
            frequency_2=_env_float("BEEP_FREQ_2", 4200.0),
            duration_ms=_env_int("BEEP_DURATION_MS", 250),
            repeat=_env_int("BEEP_REPEAT", 3),
            period_ms=_env_int("BEEP_PERIOD_MS", 1000),
            search_seconds=_env_float("BEEP_SEARCH_SEC", 10.0),
            window_ms=_env_int("BEEP_WINDOW_MS", 40),
            hop_ms=_env_int("BEEP_HOP_MS", 10),
            fine_hop_ms=_env_int("BEEP_FINE_HOP_MS", 2),
            min_rise=_env_float("BEEP_MIN_RISE", 6.0),
            onset_fraction=_env_float("BEEP_ONSET_FRACTION", 0.5),
            sustain_ms=_env_int("BEEP_SUSTAIN_MS", 40),
        )


#: Master switch. Turning this off drops straight to the ``align`` modes.
BEEP_ENABLED = _env_bool("BEEP_ENABLED", True)
#: Cut everything up to and including the last beep, so the merged file starts
#: where the meeting does. This also removes the beeps themselves, which is why
#: it supersedes BEEP_MUTE rather than adding to it. The amount removed comes
#: back as ``alignment.trimmedMs`` so callers can map timestamps back.
BEEP_TRIM = _env_bool("BEEP_TRIM", True)
#: Silence the beep in place instead. Only used when trimming is off or refused.
BEEP_MUTE = _env_bool("BEEP_MUTE", True)
#: Never trim a merge down to less than this. A guard against a beep found near
#: the end of a very short recording taking the whole thing with it.
BEEP_TRIM_MIN_REMAINDER_SEC = _env_float("BEEP_TRIM_MIN_REMAINDER_SEC", 5.0)
#: Extra silence around each beep. The leading pad is the larger of the two:
#: the reported onset trails the true one by roughly a window (the analysis
#: window has to fill with beep before the energy crosses), so muting from the
#: reported onset alone would leave the beep's attack audible. The trailing pad
#: covers the room's reverb tail. Both sit inside the pre-meeting preamble, so
#: being generous costs nothing.
BEEP_MUTE_LEAD_MS = _env_int("BEEP_MUTE_LEAD_MS", 150)
BEEP_MUTE_TAIL_MS = _env_int("BEEP_MUTE_TAIL_MS", 100)
#: At least this many tracks must carry a beep, or there is nothing to line up.
BEEP_MIN_TRACKS = _env_int("BEEP_MIN_TRACKS", 2)

#: Which phones played the beep, as reported in ``options.beepSource``.
#:
#: ``leader``  only the host phone plays; every track holds that one sound.
#: ``all``     every phone plays; each track holds its own loud beep (speaker
#:             centimetres from the mic) plus the others', quieter.
#:
#: Both are aligned by the same code. In ``all`` mode the comb filter picks the
#: loudest train, which is the phone's own -- and that is the *right* pick only
#: because playback is synchronized by the pub/sub start signal. If the app ever
#: schedules the beep off its own recorder-start callback instead, each phone's
#: beep becomes a device-local event carrying that phone's 0-2.2 s start-up lag,
#: and aligning on it would preserve exactly the skew we are trying to remove.
#: **The 5 s offset must be measured from the pub/sub signal, not from the
#: recorder starting.** See newDocs/05.
BEEP_SOURCE_LEADER = "leader"
BEEP_SOURCE_ALL = "all"
BEEP_SOURCES = (BEEP_SOURCE_LEADER, BEEP_SOURCE_ALL)

#: Trailing pad for ``all``. The other phones' beeps arrive a little after the
#: track's own -- sound travels roughly 3 ms per metre, and pub/sub delivery is
#: not perfectly simultaneous -- so the beep block is wider than one beep. Too
#: small a pad and the last phone's beep survives the trim and is audible at the
#: head of the merged file. The pad sits inside the pre-meeting preamble, so
#: being generous costs nothing.
BEEP_ALL_TAIL_MS = _env_int("BEEP_ALL_TAIL_MS", 400)


def tail_ms_for(source: str) -> int:
    """Trailing pad for the beep block, given who played it."""
    return BEEP_ALL_TAIL_MS if source == BEEP_SOURCE_ALL else BEEP_MUTE_TAIL_MS


@dataclass(frozen=True)
class BeepDetection:
    """Where the beep sits in one track."""

    detected: bool
    onset_seconds: float | None
    #: Comb score over the track's own median band energy. Not a probability --
    #: it is a signal-to-background ratio, and runs from ~10 to ~10^5.
    confidence: float
    repeats_found: int

    @property
    def onset_ms(self) -> int | None:
        if self.onset_seconds is None:
            return None
        return int(round(self.onset_seconds * 1000))


class BeepError(RuntimeError):
    pass


def _load_mono16(path: str | Path) -> tuple[int, array]:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise BeepError("expected mono 16-bit wav input")
        samples = array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
        return handle.getframerate(), samples


def _goertzel(buf: array, start: int, length: int, sample_rate: int, frequency: float) -> float:
    """Energy of a single frequency over ``buf[start:start+length]``.

    One multiply-add per sample, no buffers -- which is why this is affordable
    in pure Python where an FFT would not be.
    """
    bin_index = int(0.5 + length * frequency / sample_rate)
    omega = 2.0 * math.pi * bin_index / length
    coeff = 2.0 * math.cos(omega)
    s1 = s2 = 0.0
    for index in range(start, start + length):
        s0 = buf[index] + coeff * s1 - s2
        s2, s1 = s1, s0
    return (s1 * s1 + s2 * s2 - coeff * s1 * s2) / (length * length / 4.0)


def _pair_energy(
    buf: array, sample_rate: int, start: int, length: int, spec: BeepSpec
) -> float:
    """Energy of the *weaker* tone.

    Taking the minimum is the whole trick: speech is broadband and lights up one
    bin at a time, so requiring both tones at once rejects it. A single loud tone
    scores zero here.
    """
    return min(
        _goertzel(buf, start, length, sample_rate, spec.frequency_1),
        _goertzel(buf, start, length, sample_rate, spec.frequency_2),
    )


def _onset_near(
    samples: array,
    sample_rate: int,
    center: int,
    window: int,
    spec: BeepSpec,
) -> float | None:
    """Find the rising edge of a beep near ``center`` (a sample index).

    Scans *forward* for the first sustained crossing rather than walking back
    from the peak: a 250 ms beep's energy plateau is ragged at low SNR, and a
    backward walk stops at the first dip, reporting the onset up to 140 ms late.
    """
    fine_hop = max(1, int(sample_rate * spec.fine_hop_ms / 1000))
    low = max(0, center - window * 2)
    high = min(len(samples) - window, center + window * 2)
    if high <= low:
        return None
    starts = list(range(low, high, fine_hop))
    if len(starts) < 4:
        return None
    energies = [_pair_energy(samples, sample_rate, start, window, spec) for start in starts]

    threshold = max(energies) * spec.onset_fraction
    needed = max(1, int(spec.sustain_ms / spec.fine_hop_ms))
    for index in range(len(energies) - needed):
        if energies[index] < threshold:
            continue
        if all(value >= threshold * 0.6 for value in energies[index : index + needed]):
            # The window reaches half energy when it is half full of beep, so
            # the rise sits half a window after the window's start.
            return (starts[index] + window / 2) / sample_rate
    return None


def detect_beep(path: str | Path, spec: BeepSpec | None = None) -> BeepDetection:
    """Locate the sync beep in one normalized track."""
    spec = spec or BeepSpec()
    sample_rate, samples = _load_mono16(path)
    if sample_rate <= 0 or not samples:
        return BeepDetection(False, None, 0.0, 0)

    window = int(sample_rate * spec.window_ms / 1000)
    hop = max(1, int(sample_rate * spec.hop_ms / 1000))
    limit = min(int(spec.search_seconds * sample_rate), len(samples) - window)
    if limit <= 0 or window <= 0:
        return BeepDetection(False, None, 0.0, 0)

    starts = list(range(0, limit, hop))
    energies = [_pair_energy(samples, sample_rate, start, window, spec) for start in starts]
    if not energies:
        return BeepDetection(False, None, 0.0, 0)

    background = max(median(energies), 1e-12)

    # Comb filter: score a position by its weakest repeat, so a candidate only
    # wins when every repeat is present at the exact spacing the app plays.
    step = max(1, spec.period_ms // spec.hop_ms)
    span = step * (spec.repeat - 1)
    best_index: int | None = None
    best_score = 0.0
    for index in range(max(1, len(energies) - span)):
        score = min(
            energies[index + step * repeat]
            for repeat in range(spec.repeat)
            if index + step * repeat < len(energies)
        )
        if score > best_score:
            best_index, best_score = index, score

    rise = best_score / background
    if best_index is None or rise < spec.min_rise:
        return BeepDetection(False, None, rise, 0)

    # The comb scores highest somewhere *inside* the beep, not at its edge, and
    # a 250 ms beep's plateau is flat enough that the winner lands anywhere
    # along it. Walk back to where the band energy first lifted, or the fine
    # scan below starts mid-beep and reports the onset up to 140 ms late.
    threshold = background * spec.min_rise
    max_back = max(1, spec.duration_ms // spec.hop_ms)
    anchor = best_index
    while anchor > 0 and best_index - anchor < max_back and energies[anchor - 1] > threshold:
        anchor -= 1

    # Refine each repeat, then median the implied first-beep positions. One
    # repeat alone is 2-3x noisier; this is what the repeats buy us.
    period_samples = int(sample_rate * spec.period_ms / 1000)
    candidates: list[float] = []
    for repeat in range(spec.repeat):
        center = starts[anchor] + repeat * period_samples
        onset = _onset_near(samples, sample_rate, center, window, spec)
        if onset is not None:
            candidates.append(onset - repeat * spec.period_ms / 1000.0)
    if not candidates:
        return BeepDetection(False, None, rise, 0)

    return BeepDetection(True, median(candidates), rise, len(candidates))


def compute_beep_offsets_ms(
    files: list[dict],
    detections: list[BeepDetection],
    *,
    max_offset_ms: int,
) -> tuple[str, list[dict], float]:
    """Turn per-track beep positions into ``adelay`` values.

    The track whose beep sits latest becomes the reference: every other track is
    pushed forward until its beep lands in the same place. Returns the reference
    participant, the per-track records, and the beep's position on the merged
    timeline (which is where every aligned beep ends up, so it is also where the
    output gets muted).

    A track without a beep is placed by ``startedAt`` when that is possible --
    one participant whose phone was in a bag should not cost everyone else their
    alignment. Failing that it falls back to 0 and is flagged.
    """
    anchored = [
        (entry, detection)
        for entry, detection in zip(files, detections, strict=True)
        if detection.detected and detection.onset_seconds is not None
    ]
    if len(anchored) < BEEP_MIN_TRACKS:
        raise BeepError("not enough tracks carry a beep")

    latest_onset = max(detection.onset_seconds for _, detection in anchored)

    # Wall-clock instant of the beep, if any anchored track also reported a
    # startedAt. This lets undetected-but-timestamped tracks join the same
    # timeline instead of dropping to zero.
    beep_wallclock = None
    for entry, detection in anchored:
        if entry.get("startedAt") is not None:
            beep_wallclock = entry["startedAt"].timestamp() + detection.onset_seconds
            break

    reference = max(anchored, key=lambda item: item[1].onset_seconds)[0]["participantId"]

    tracks: list[dict] = []
    for entry, detection in zip(files, detections, strict=True):
        record = {
            "participantId": entry["participantId"],
            "beepAtMs": detection.onset_ms,
            "confidence": round(detection.confidence, 1),
            "fallback": None,
        }
        if detection.detected and detection.onset_seconds is not None:
            delta_ms = int(round((latest_onset - detection.onset_seconds) * 1000))
        elif beep_wallclock is not None and entry.get("startedAt") is not None:
            # Where the beep would sit in this track, derived from its clock.
            implied = beep_wallclock - entry["startedAt"].timestamp()
            delta_ms = int(round((latest_onset - implied) * 1000))
            record["fallback"] = "timestamp"
        else:
            delta_ms = 0
            record["fallback"] = "none"

        if not 0 <= delta_ms <= max_offset_ms:
            # Same guard as the timestamp path: one wrong track must not shove
            # everyone else off the timeline.
            delta_ms = 0
            record["fallback"] = record["fallback"] or "outlier"
        record["offsetMs"] = delta_ms
        tracks.append(record)

    return reference, tracks, latest_onset


def mute_ranges(
    beep_at_seconds: float,
    spec: BeepSpec,
    *,
    lead_ms: int = BEEP_MUTE_LEAD_MS,
    tail_ms: int = BEEP_MUTE_TAIL_MS,
) -> list[tuple[float, float]]:
    """Where the beeps land on the merged timeline.

    Alignment puts every track's beep at the same instant, so one set of ranges
    covers all of them. In ``all`` mode the other phones' beeps trail the
    track's own by propagation delay and delivery jitter; ``tail_ms`` is what
    has to cover them, so pass ``tail_ms_for(source)``.
    """
    lead = lead_ms / 1000.0
    tail = tail_ms / 1000.0
    ranges: list[tuple[float, float]] = []
    for repeat in range(spec.repeat):
        centre = beep_at_seconds + repeat * spec.period_ms / 1000.0
        ranges.append((max(0.0, centre - lead), centre + spec.duration_ms / 1000.0 + tail))
    return ranges


def wav_duration_seconds(path: str | Path) -> float:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        return handle.getnframes() / rate if rate else 0.0


def trim_point(
    beep_at_seconds: float,
    spec: BeepSpec,
    merged_duration_seconds: float,
    *,
    tail_ms: int = BEEP_MUTE_TAIL_MS,
    min_remainder_seconds: float = BEEP_TRIM_MIN_REMAINDER_SEC,
) -> float | None:
    """Where to cut the merged file so it starts at the end of the last beep.

    ``tail_ms`` sets how far past the last beep the cut goes, and in ``all``
    mode it is also what removes the *other* phones' beeps -- pass
    ``tail_ms_for(source)`` or they survive at the head of the output.

    Returns ``None`` when cutting there would leave too little audio -- a beep
    found late in a short recording must not swallow the meeting. The caller
    then falls back to muting the beeps in place.
    """
    end_of_last = (
        beep_at_seconds
        + (spec.repeat - 1) * spec.period_ms / 1000.0
        + spec.duration_ms / 1000.0
        + tail_ms / 1000.0
    )
    if end_of_last <= 0:
        return None
    if merged_duration_seconds - end_of_last < min_remainder_seconds:
        return None
    return end_of_last
