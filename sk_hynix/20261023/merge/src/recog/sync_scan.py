"""``python -m recog sync-scan`` -- why did (or didn't) the sync sound align?

The site is air-gapped: recordings and response JSON cannot leave it. This
prints, per track, what each detector saw -- found or not, where, and how far
above or below its threshold -- then runs the same offset maths the merge runs.
A handful of numbers read off the screen is enough to tell "the sound is not in
the recording" (NS/AEC removed it) from "it is there but weak" (threshold) from
"found, but the playback schedule is wrong" (offsets).

Read-only. Nothing is uploaded, merged or stored.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from statistics import median

from . import audio, beep, merge_job, sync_sound
from .beep import BeepDetection, BeepError, BeepSpec

_THRESHOLDS = {
    sync_sound.SYNC_SOUND_BEEP: lambda: BeepSpec.from_env().min_rise,
    sync_sound.SYNC_SOUND_JINGLE: lambda: sync_sound.JingleSpec.from_env().min_rise,
    sync_sound.SYNC_SOUND_VOICE: lambda: sync_sound.VoiceSpec.from_env().min_score,
}
#: Below the threshold but above this, the sound is probably there and weak.
#: Under it the track looks like ordinary conversation (measured: speech alone
#: scores voice ~0.2-0.44, beep/jingle rise ~1-4 at most frames).
_NEAR = {
    sync_sound.SYNC_SOUND_BEEP: 3.0,
    sync_sound.SYNC_SOUND_JINGLE: 3.0,
    sync_sound.SYNC_SOUND_VOICE: 0.4,
}
_PARTS = {
    sync_sound.SYNC_SOUND_BEEP: lambda: BeepSpec.from_env().repeat,
    sync_sound.SYNC_SOUND_JINGLE: lambda: len(sync_sound.JINGLE_NOTES),
    sync_sound.SYNC_SOUND_VOICE: lambda: sync_sound.VoiceSpec.from_env().pieces,
}


def beep_block(path: Path, onset_seconds: float, spec: BeepSpec | None = None) -> tuple[int, int]:
    """How far the first beep's band energy reaches before and after the onset.

    In ``all`` mode the block is every phone's beep together, so ``lead`` is
    how much earlier the earliest other phone played, and ``trail`` (past the
    250 ms beep) is the latest one plus the room's reverb. Upper bounds on the
    playback jitter, in ms -- reverb and the 40 ms analysis window are in them.
    """
    spec = spec or BeepSpec.from_env()
    sample_rate, samples = beep._load_mono16(path)
    window = int(sample_rate * spec.window_ms / 1000)
    hop = int(sample_rate * spec.hop_ms / 1000)
    limit = min(int(spec.search_seconds * sample_rate), len(samples) - window)
    energies = [beep._pair_energy(samples, sample_rate, s, window, spec) for s in range(0, limit, hop)]
    threshold = max(median(energies), 1e-12) * spec.min_rise
    centre = int((onset_seconds + spec.duration_ms / 2000) * sample_rate) // hop
    if not 0 <= centre < len(energies) or energies[centre] <= threshold:
        return 0, 0
    gap = 2  # tolerate 20 ms dips (beating between phones)
    start = centre
    while start - 1 >= 0 and any(e > threshold for e in energies[max(0, start - gap) : start]):
        start -= 1
    end = centre
    while end + 1 < len(energies) and any(e > threshold for e in energies[end + 1 : end + 1 + gap]):
        end += 1
    # Frame k's window covers [k, k + window); its energy rises when the beep
    # enters the window's end and falls when the beep leaves its start.
    block_start = start * hop / sample_rate + spec.window_ms / 1000
    block_end = end * hop / sample_rate
    lead = max(0, int(round((onset_seconds - block_start) * 1000)))
    trail = max(0, int(round((block_end - onset_seconds) * 1000)) - spec.duration_ms)
    return lead, trail


def beep_tones(path: Path, onset_seconds: float | None = None, spec: BeepSpec | None = None) -> dict[str, list[float]]:
    """Each tone's rise over its own background, for each of the three repeats,
    mid-beep at the detected onset -- or, when nothing was detected, at the
    position where that tone's three taps add up highest (a sum, not a median:
    a median ties with the position one beep early).

    This is the "audible but not detected" breakdown: one tone near 1 means the
    phone barely carries it; repeats falling off (e.g. 40 / 9 / 3) means noise
    suppression learning the tone; everything low means it is simply quiet.
    """
    spec = spec or BeepSpec.from_env()
    sample_rate, samples = beep._load_mono16(path)
    window = int(sample_rate * spec.window_ms / 1000)
    hop = int(sample_rate * spec.hop_ms / 1000)
    limit = min(int(spec.search_seconds * sample_rate), len(samples) - window)
    starts = range(0, max(0, limit), hop)
    step = spec.period_ms // spec.hop_ms
    out: dict[str, list[float]] = {}
    for frequency in (spec.frequency_1, spec.frequency_2):
        values = [beep._goertzel(samples, s, window, sample_rate, frequency) for s in starts]
        if len(values) <= step * (spec.repeat - 1):
            out[f"{frequency:g}"] = []
            continue
        background = max(median(values), 1e-12)
        last = len(values) - 1 - step * (spec.repeat - 1)
        if onset_seconds is not None:
            # Window centred mid-beep: start = onset + duration/2 - window/2.
            centre_ms = onset_seconds * 1000 + spec.duration_ms / 2 - spec.window_ms / 2
            best = min(last, max(0, int(round(centre_ms / spec.hop_ms))))
        else:
            best = max(range(last + 1), key=lambda i: sum(values[i + step * r] for r in range(spec.repeat)))
        out[f"{frequency:g}"] = [round(values[best + step * r] / background, 1) for r in range(spec.repeat)]
    return out


def scan(paths: list[Path], sounds: list[str], beep_source: str) -> dict:
    """Detect every sound in every file; align the files on each sound found."""
    report: dict = {"files": [p.name for p in paths], "beepSource": beep_source, "sounds": {}}
    with tempfile.TemporaryDirectory(prefix="sync-scan-") as tmp:
        normalized = []
        for index, path in enumerate(paths):
            target = Path(tmp) / f"norm_{index}.wav"
            audio.export_stt_track(path, target, merge_job.WORKING_SAMPLE_RATE)
            normalized.append(target)

        for sound in sounds:
            entry: dict = {
                "threshold": _THRESHOLDS[sound](),
                "near": _NEAR[sound],
                "parts": _PARTS[sound](),
                "tracks": [],
            }
            strict = [sync_sound.detect(sound, norm) for norm in normalized]
            detections, guided = sync_sound.guided_pass(sound, normalized, strict)
            for index, (path, norm) in enumerate(zip(paths, normalized, strict=True)):
                detection = detections[index]
                track = {
                    "file": path.name,
                    "detected": detection.detected,
                    "atMs": detection.onset_ms,
                    "confidence": round(detection.confidence, 3),
                    "partsFound": detection.repeats_found,
                    "guided": index in guided,
                    "foundBy": guided.get(index),
                    "strictConfidence": round(strict[index].confidence, 3),
                }
                if sound == sync_sound.SYNC_SOUND_BEEP:
                    track["tones"] = beep_tones(norm, detection.onset_seconds if detection.detected else None)
                if sound == sync_sound.SYNC_SOUND_BEEP and detection.detected:
                    track["leadMs"], track["trailMs"] = beep_block(norm, detection.onset_seconds)
                entry["tracks"].append(track)

            files = [{"participantId": p.name, "startedAt": None} for p in paths]
            try:
                reference, tracks, beep_at = beep.compute_beep_offsets_ms(
                    files, detections, max_offset_ms=merge_job.MAX_OFFSET_MS
                )
            except BeepError:
                entry["alignment"] = {"mode": "none", "why": f"found in fewer than {beep.BEEP_MIN_TRACKS} files"}
            else:
                spec = sync_sound.block_spec(sound)
                cut = beep.trim_point(beep_at, spec, float("inf"), tail_ms=beep.tail_ms_for(beep_source))
                entry["alignment"] = {
                    "mode": "beep",
                    "reference": reference,
                    "offsets": {t["participantId"]: t["offsetMs"] for t in tracks},
                    "fallbacks": {t["participantId"]: t["fallback"] for t in tracks if t["fallback"]},
                    "trimmedMs": int(round(cut * 1000)) if cut is not None else None,
                }
            report["sounds"][sound] = entry
    return report


def render(report: dict) -> str:
    lines = [f"sync-scan  files={len(report['files'])}  beepSource={report['beepSource']}", ""]
    width = max(len(name) for name in report["files"]) + 2
    for sound, entry in report["sounds"].items():
        lines.append(f"== {sound}  (기준: 신뢰도 {entry['threshold']:g} 이상, 조각 {entry['parts']}개 중)")
        lines.append(f"  {'파일':<{width - 2}}검출  위치ms   신뢰도        조각   비고")
        for track in entry["tracks"]:
            mark = "O" if track["detected"] else "X"
            at = "-" if track["atMs"] is None else str(track["atMs"])
            note = ""
            if track.get("foundBy") == sync_sound.FOUND_BY_VOICE:
                note = f"비프는 못 찾고 안내 음성 위치로 대신 정함 (1차 신뢰도 {track['strictConfidence']:g})"
            elif track.get("guided"):
                note = f"느슨한 기준으로 찾음 (1차 신뢰도 {track['strictConfidence']:g})"
            elif not track["detected"]:
                near = track["confidence"] >= entry["near"]
                note = "기준 근처 — 소리는 있으나 약함" if near else "소리가 거의 없음"
            elif "leadMs" in track:
                note = f"다른 폰 소리: 최대 {track['leadMs']}ms 먼저 / {track['trailMs']}ms 늦게"
            lines.append(
                f"  {track['file']:<{width}}{mark:<6}{at:<9}{track['confidence']:<14g}"
                f"{track['partsFound']}/{entry['parts']:<5}{note}"
            )
            if track.get("tones"):
                detail = "  ".join(
                    f"{hz}Hz {' / '.join(f'{v:g}' for v in rises)}" for hz, rises in track["tones"].items()
                )
                lines.append(f"  {'':<{width}}└ 음별 1·2·3번째 크기(배경 대비 배수): {detail}")
        alignment = entry["alignment"]
        if alignment["mode"] == "none":
            lines.append(f"  -> 정렬: none ({alignment['why']})")
        else:
            offsets = ", ".join(f"{name}={ms}" for name, ms in alignment["offsets"].items())
            lines.append(f"  -> 정렬: beep  기준={alignment['reference']}  offsetMs: {offsets}")
            if alignment["fallbacks"]:
                lines.append(f"     fallback: {alignment['fallbacks']}")
            lines.append(f"     trimmedMs={alignment['trimmedMs']}")
        lines.append("")
    lines.append("참고: '먼저/늦게' 는 재생 지터의 상한(잔향 포함). 수십 ms 면 정상, 300ms 넘으면 재생 시점 기준을 확인할 것.")
    return "\n".join(lines)


def main(paths: list[str], sound: str, beep_source: str, as_json: bool) -> int:
    files = [Path(p) for p in paths]
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        print(f"없는 파일: {', '.join(missing)}")
        return 2
    sounds = list(sync_sound.SYNC_SOUNDS) if sound == "all" else [sound]
    report = scan(files, sounds, beep_source)
    print(json.dumps(report, ensure_ascii=False, indent=2) if as_json else render(report))
    return 0
