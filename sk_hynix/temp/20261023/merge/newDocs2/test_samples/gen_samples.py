"""Generate 3 simulated phone recordings of one meeting with a sync beep.

Room timeline (seconds from the pub/sub start signal):
  - leader phone (A) plays sync_beep.wav at BEEP_AT
  - meeting speech starts at SPEECH_AT
Each phone's recorder starts LAG seconds late, so its file is the room
timeline with the first LAG seconds missing.
"""

import random
import subprocess
import sys
import wave
from array import array
from pathlib import Path

SR = 16000
BEEP_AT = 3.0
SPEECH_AT = 6.0
GAP = 0.6
END_PAD = 2.0

REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
WORK = Path(sys.argv[3])
# "--no-beep": same meeting with no beep, to hear what an unaligned merge sounds like
WITH_BEEP = "--no-beep" not in sys.argv[4:]
WORK.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

# phone -> (recorder start lag s, owner speaker)
PHONES = {
    "A": (0.30, "kim"),
    "B": (0.85, "park"),
    "C": (1.60, "lee"),
}
# Yuna is the only natural-sounding Korean voice; the male Korean voices
# (Eddy/Rocko) sound foreign. So every line is read by Yuna at ~5 syllables/s
# and the two men are made by lowering formants (asetrate, tempo restored) and
# then pitch (rubberband): f0 ~267 Hz -> ~126 Hz (park) / ~107 Hz (lee).
VOICE = "Yuna"
RATE = "150"
VOICE_FX = {
    "kim": None,
    "park": "asetrate=16000*0.88,aresample=16000,atempo=1.13636,rubberband=pitch=0.53:formant=preserved",
    "lee": "asetrate=16000*0.84,aresample=16000,atempo=1.19048,rubberband=pitch=0.47:formant=preserved",
}

SCRIPT = [
    ("kim", "네, 그럼 시작하겠습니다. 오늘은 이번 주 에이치비엠 라인 수율 현황하고 다음 분기 공정 전환 일정을 같이 보겠습니다."),
    ("park", "먼저 수율부터 말씀드리겠습니다. 지난주 대비 티에스브이 공정 수율이 이 퍼센트 정도 올라서 지금 구십일 퍼센트 수준입니다."),
    ("kim", "좋네요. 올라간 원인은 파악이 됐나요?"),
    ("park", "네, 식각 장비 챔버 세정 주기를 짧게 바꾼 효과로 보고 있습니다. 파티클 불량이 눈에 띄게 줄었습니다."),
    ("lee", "그런데 세정 주기를 줄이면 장비 가동률이 떨어지지 않나요? 생산량 쪽 영향도 같이 봐야 할 것 같습니다."),
    ("park", "맞습니다. 가동률은 일 점 오 퍼센트 정도 빠졌는데, 수율 개선 폭이 더 커서 전체 양품 수는 오히려 늘었습니다."),
    ("kim", "그 수치는 다음 보고 때 표로 정리해서 같이 주세요."),
    ("lee", "알겠습니다. 다음은 하이브리드 본딩 쪽인데요, 시험 웨이퍼에서 접합 불량이 아직 목표치보다 높습니다."),
    ("kim", "어느 정도인가요?"),
    ("lee", "목표가 백만 개당 오십 개인데 지금 백이십 개 수준입니다. 주로 웨이퍼 가장자리에서 보이드가 생기고 있습니다."),
    ("park", "가장자리라면 평탄화 공정 쪽 문제일 가능성이 있겠네요. 씨엠피 이후 휨 데이터는 확인해 보셨나요?"),
    ("lee", "아직 못 봤습니다. 이번 주 안에 계측팀에 요청해서 데이터 받아보겠습니다."),
    ("kim", "좋습니다. 그 결과에 따라 다음 분기 양산 전환 일정이 바뀔 수 있으니까 우선순위 높게 봐주세요."),
    ("park", "공정 전환 일정 관련해서 하나 더 말씀드리면, 신규 노광 장비 반입이 이 주 정도 늦어진다고 연락이 왔습니다."),
    ("kim", "이 주면 전체 일정에 영향이 있겠네요. 대안은 있나요?"),
    ("park", "기존 장비로 일부 레이어를 먼저 진행하고, 신규 장비는 들어오는 대로 나머지 레이어에 투입하는 방안을 검토 중입니다."),
    ("lee", "그 경우 장비 간 오버레이 편차 관리가 중요할 것 같습니다. 제가 보정 기준을 정리해 보겠습니다."),
    ("kim", "네, 그렇게 해 주세요. 그럼 오늘 정리하면, 첫째 식각 세정 주기 효과를 표로 정리하고, 둘째 본딩 불량은 휨 데이터 확인, 셋째 노광 장비 지연 대응안 마련입니다."),
    ("park", "네, 수율 표는 제가 목요일까지 공유드리겠습니다."),
    ("lee", "휨 데이터하고 오버레이 기준은 다음 주 월요일까지 정리하겠습니다."),
    ("kim", "좋습니다. 수고하셨습니다. 다음 회의는 다음 주 같은 시간에 하겠습니다."),
]


def run(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2
        data = array("h")
        data.frombytes(w.readframes(w.getnframes()))
    return data


def to16k(src, dst, fx=None):
    # resample first: asetrate in fx assumes a 16 kHz input
    chain = "aresample=16000" + (f",{fx}" if fx else "")
    run("ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-af", chain,
        "-ar", str(SR), "-sample_fmt", "s16", str(dst))


# --- render speech lines and lay them on the room timeline ---------------
lines = []  # (start_s, speaker, samples)
t = SPEECH_AT
for i, (who, text) in enumerate(SCRIPT):
    aiff = WORK / f"line{i:02d}.aiff"
    wav = WORK / f"line{i:02d}.wav"
    run("say", "-v", VOICE, "-r", RATE, "-o", str(aiff), text)
    to16k(aiff, wav, VOICE_FX[who])
    samples = read_wav(wav)
    if len(samples) < SR // 2:
        sys.exit(f"voice {VOICE!r} rendered no speech for line {i}")
    lines.append((t, who, samples))
    t += len(samples) / SR + GAP
room_len = t + END_PAD

# ground truth for checking STT: when each line is spoken, in room time
NAMES = {"kim": "김 팀장", "park": "박 책임", "lee": "이 선임"}
with open(OUT / "timeline.tsv", "w", encoding="utf-8") as f:
    f.write("room_start_s\troom_end_s\tspeaker\ttext\n")
    for (at, who, samples), (_, text) in zip(lines, SCRIPT):
        f.write(f"{at:.2f}\t{at + len(samples) / SR:.2f}\t{NAMES[who]}\t{text}\n")

beep_wav = WORK / "beep16k.wav"
to16k(REPO / "newDocs/assets/sync_beep.wav", beep_wav)
beep = read_wav(beep_wav)

# --- one buffer per phone, in room time ----------------------------------
rng = random.Random(42)
total = int(room_len * SR)
expected = {}
for phone, (lag, owner) in PHONES.items():
    buf = [0.0] * total

    def add(samples, at_s, gain, delay_ms):
        base = int((at_s + delay_ms / 1000.0) * SR)
        for k, v in enumerate(samples):
            j = base + k
            if j >= total:
                break
            buf[j] += v * gain

    # beep from the leader phone: loud on A itself, quieter across the room
    if WITH_BEEP and phone == "A":
        add(beep, BEEP_AT, 0.9, 0.3)
    elif WITH_BEEP:
        add(beep, BEEP_AT, 0.22, 5.0)
    # each phone carries only its owner's lines; the merge assembles the dialogue
    for at, who, samples in lines:
        if who == owner:
            add(samples, at, 0.9, 0.5)
    # independent room noise per phone
    for j in range(total):
        buf[j] += rng.gauss(0.0, 120.0)

    # recorder started LAG seconds late: drop the head
    start = int(lag * SR)
    out = array("h", (max(-32768, min(32767, int(v))) for v in buf[start:]))
    wav_out = WORK / f"phone_{phone}.wav"
    with wave.open(str(wav_out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(out.tobytes())
    flac = OUT / f"phone_{phone}.flac"
    run("ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_out), "-c:a", "flac", str(flac))
    expected[phone] = round((BEEP_AT - lag) * 1000)
    print(f"phone_{phone}.flac  lag={lag:.2f}s  beep_in_file={BEEP_AT - lag:.2f}s  "
          f"len={len(out) / SR:.1f}s")

print("room length", round(room_len, 1))
