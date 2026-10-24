"""Generate the three sync sounds (options.syncSound) for the app and for listening tests.

    python3 newDocs/assets/sync_sounds/gen_sync_sounds.py

Writes into this script's directory:

    1_beep3.wav         current spec (copy of ../sync_beep.wav)
    2_voice.wav         "음성녹음을 시작합니다" (macOS `say -v Yuna`)
    2_voice_end.wav     "녹음을 종료합니다" -- the end sync sound for voice
    3_jingle.wav        short logo melody (E-B-G#-C#-E)
    preview/1_beep3.wav, preview/3_jingle.wav
                        announcement voice followed by the sync sound,
                        i.e. what people in the room will actually hear

and the server's copies of both voices, src/recog/assets/sync_voice{,_end}_16k.wav.

All files are 48 kHz / 16-bit / mono, peak -6 dBFS like sync_beep.wav. Every
tone sits below 8 kHz -- the app records at 16 kHz, so anything above is lost --
and mostly above 2.5 kHz, out of the way of speech.

Stdlib only; the voice needs macOS `say` and ffmpeg.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
RATE = 48000
PEAK = 10 ** (-6 / 20)  # -6 dBFS, same as sync_beep.wav
VOICE = "Yuna"
VOICE_TEXT = "음성녹음을 시작합니다"
VOICE_END_TEXT = "녹음을 종료합니다"
VOICE_RATE = "180"  # words per minute for `say`; a calm announcement pace
PREVIEW_GAP = 0.5  # silence between the announcement and the sync sound

# E-major notes, all inside 2.5-6 kHz.
E7, GS7, B7, CS8, E8 = 2637.0, 3322.4, 3951.1, 4434.9, 5274.0


def silence(seconds: float) -> list[float]:
    return [0.0] * int(RATE * seconds)


def bell(freq: float, seconds: float, decay: float, partial: float = 0.25) -> list[float]:
    """A struck tone: 5 ms attack, exponential decay, a little 2nd partial if it fits."""
    out = []
    attack = int(RATE * 0.005)
    for i in range(int(RATE * seconds)):
        t = i / RATE
        env = math.exp(-t / decay) * min(1.0, i / attack)
        value = math.sin(2 * math.pi * freq * t)
        if freq * 2 < 7800:
            value += partial * math.sin(2 * math.pi * freq * 2 * t)
        out.append(env * value)
    # 5 ms fade-out so the cut is click-free
    fade = int(RATE * 0.005)
    for k in range(fade):
        out[-1 - k] *= k / fade
    return out


def sweep(f0: float, f1: float, seconds: float) -> list[float]:
    """Linear chirp with 10 ms raised-cosine edges."""
    n = int(RATE * seconds)
    edge = int(RATE * 0.010)
    out = []
    for i in range(n):
        t = i / RATE
        phase = 2 * math.pi * (f0 * t + (f1 - f0) * t * t / (2 * seconds))
        env = 1.0
        if i < edge:
            env = 0.5 - 0.5 * math.cos(math.pi * i / edge)
        elif i >= n - edge:
            env = 0.5 - 0.5 * math.cos(math.pi * (n - 1 - i) / edge)
        out.append(env * math.sin(phase))
    return out


def place(total: float, events: list[tuple[float, list[float]]]) -> list[float]:
    buf = silence(total)
    for at, sound in events:
        base = int(RATE * at)
        for i, v in enumerate(sound):
            if base + i < len(buf):
                buf[base + i] += v
    return buf


def normalize(buf: list[float]) -> list[float]:
    top = max(abs(v) for v in buf) or 1.0
    return [v * PEAK / top for v in buf]


def write(path: Path, buf: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(struct.pack("<h", int(round(max(-1.0, min(1.0, v)) * 32767))) for v in buf)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(frames)


def read(path: Path) -> list[float]:
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 1 and handle.getsampwidth() == 2
        assert handle.getframerate() == RATE, f"{path} is not {RATE} Hz"
        raw = handle.readframes(handle.getnframes())
    return [s / 32768 for (s,) in struct.iter_unpack("<h", raw)]


def make_voice(text: str = VOICE_TEXT) -> list[float]:
    with tempfile.TemporaryDirectory() as tmp:
        aiff = Path(tmp) / "voice.aiff"
        wav = Path(tmp) / "voice.wav"
        subprocess.run(["say", "-v", VOICE, "-r", VOICE_RATE, "-o", str(aiff), text], check=True)
        # Trim the silence `say` leaves at both ends so the file starts on speech.
        trim = (
            "silenceremove=start_periods=1:start_threshold=-50dB,"
            "areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse"
        )
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-af", trim,
             "-ac", "1", "-ar", str(RATE), "-sample_fmt", "s16", str(wav)],
            check=True,
        )
        buf = read(wav)
    if max(abs(v) for v in buf) < 0.01:
        raise SystemExit(f"`say -v {VOICE}` produced silence -- is the Korean voice installed?")
    return normalize(buf)


def main() -> None:
    sounds: dict[str, list[float]] = {}

    shutil.copyfile(HERE.parent / "sync_beep.wav", HERE / "1_beep3.wav")
    sounds["1_beep3"] = read(HERE / "1_beep3.wav")

    voice = make_voice()
    sounds["2_voice"] = voice
    # End-of-recording counterpart, for drift correction (options.syncSound=voice).
    sounds["2_voice_end"] = make_voice(VOICE_END_TEXT)

    # 3: short arpeggio jingle, E-B-G#-C#-E, last note held.
    sounds["3_jingle"] = normalize(place(1.6, [
        (0.00, bell(E7, 0.30, 0.10)),
        (0.15, bell(B7, 0.30, 0.10)),
        (0.30, bell(GS7, 0.30, 0.10)),
        (0.45, bell(CS8, 0.30, 0.10)),
        (0.60, bell(E8, 1.00, 0.30)),
    ]))

    for name, buf in sounds.items():
        write(HERE / f"{name}.wav", buf)
        if not name.startswith("2_"):
            write(HERE / "preview" / f"{name}.wav", voice + silence(PREVIEW_GAP) + buf)
        print(f"{name}.wav  {len(buf) / RATE:.2f}s")

    # The server matches the voice by its exact spectrogram, so it needs the
    # very same recording at the working rate (16 kHz).
    for source, name in (("2_voice.wav", "sync_voice_16k.wav"), ("2_voice_end.wav", "sync_voice_end_16k.wav")):
        template = HERE.parents[2] / "src" / "recog" / "assets" / name
        template.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(HERE / source),
             "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(template)],
            check=True,
        )
        print(f"{template.relative_to(HERE.parents[2])}  (server template)")


if __name__ == "__main__":
    main()
