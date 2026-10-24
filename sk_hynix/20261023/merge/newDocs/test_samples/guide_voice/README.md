# 안내 음성 포함 샘플 (앱 실제 재생 순서)

상위 폴더 샘플과 **같은 회의·같은 녹음 지연**인데, 앱이 실제로 내는 소리를 앞뒤에 넣었다.
앱 설정 `groupSyncSound=beep`, `groupSyncGuideVoice=true` 와 같은 상황이다 (방장 폰만 재생 = `leader`).

| 구간 | 회의실 기준 시각 | 소리 |
|---|---|---|
| 시작 | 3.00초 | "음성녹음을 시작합니다" (`2_voice.wav`) |
| 시작 | 4.71초 | 3연타 비프 (`1_beep3.wav`) |
| 회의 | 8.00초 ~ 170.44초 | 3명 대화 (상위 폴더와 같은 대본) |
| 종료 | 171.94초 | 3연타 비프 |
| 종료 | 174.39초 | "녹음을 종료합니다" (`2_voice_end.wav`) |
| 녹음 끝 | 종료 비프 5초 뒤 + 폰별 지연 | A 0.10초 / B 0.45초 / C 0.80초 늦게 멈춤 |

| 파일 | 녹음 시작 지연 | 파일 속 시작 비프 | 파일 속 종료 비프 | 길이 |
|---|---|---|---|---|
| `phone_A.flac` | 0.30초 | 4.41초 | 171.64초 | 176.7초 |
| `phone_B.flac` | 0.85초 | 3.86초 | 171.09초 | 176.5초 |
| `phone_C.flac` | 1.60초 | 3.11초 | 170.34초 | 176.1초 |

## 테스트

상위 폴더 README 2·3절과 같다. 업로드 값만 아래처럼 넣는다.

- `files`: A → B → C 순서
- `beepSource`: `leader`
- `syncSound`: `beep`
- `roomNo`: `TEST-GUIDE-001` (아무 값이나 가능)

## 기대 결과 (로컬에서 실제로 돌린 값)

| 항목 | 기대값 | 실측값 |
|---|---|---|
| `alignment.mode` | `beep` | `beep` |
| `f1` / `f2` / `f3` `offsetMs` | 0 / 550 / 1300 | 0 / 544 / 1296 |
| `alignment.trimmedMs` | 약 6800 | 6776 |
| `alignment.drift.endFound` | 3 | 3 |
| `alignment.drift.endTrimmed` | `true` | `true` |
| `output.durationMs` | 약 164700 | 164728 |
| 결과 파일 앞 | 안내 음성·비프 없이 0.9초쯤 바로 회의 시작 | — |
| 결과 파일 끝 | 종료 비프·"녹음을 종료합니다" 없이 마지막 발언 뒤 1.3초쯤에서 끝남 | — |

`drift.ppm` 이 0 이 아니라 ±20 이내로 나오는 건 측정 오차라 정상이다 (샘플에는 시계 오차를 넣지 않았다).

## STT 정답지

`timeline.tsv` 의 회의실 시각에서 **7.08초**(방장 지연 0.30초 + `trimmedMs` 6.776초)를 빼면
머지 결과 파일 속 시각이다. 예: 첫 발언 8.00초 → 0:00.92, 마지막 발언 164.49초 → 2:37.41.

## 다시 만들기

```bash
python3 newDocs/test_samples/gen_samples.py "$PWD" newDocs/test_samples/guide_voice /tmp/gen_work --guide
```
