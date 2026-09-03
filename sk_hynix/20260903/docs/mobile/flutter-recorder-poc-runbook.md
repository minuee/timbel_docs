# Flutter Recorder PoC Runbook

## 목적
이 문서는 Flutter recorder PoC를 실제로 수행하는 사람이 순서대로 따라 할 수 있는 운영 절차를 제공한다.

## 준비물
- iOS 테스트 기기 1대
- Android 테스트 기기 1대
- Flutter PoC 앱 또는 recorder spike 프로젝트
- 후보 recorder plugin 1개 이상
- baseline 검사 도구:
  - `tools/check_recorder_baseline.py`
  - `scripts/run_recorder_poc_check.sh`

## 관련 문서
- 작업 지시: `docs/implementation/flutter-recorder-poc-task.md`
- 결과 기록: `docs/mobile/flutter-recorder-poc-template.md`
- 후보 비교: `docs/mobile/flutter-recorder-plugin-comparison.md`
- baseline 정책: `docs/policy/recording-policy.md`

## 실행 순서
### 1. 후보 plugin 선택
- 후보 plugin 이름과 버전을 기록한다.
- 비교표의 해당 행을 준비한다.

### 2. 최소 녹음 기능 구현
PoC 범위는 아래만 포함한다.
- 녹음 시작
- 녹음 정지
- 파일 저장 경로 확인

제외 범위:
- room/session 흐름
- upload
- BLE
- anchor UX

### 3. iOS 샘플 파일 생성
- 파일 1개를 녹음한다.
- 파일 경로를 확보한다.

### 4. Android 샘플 파일 생성
- 파일 1개를 녹음한다.
- 파일 경로를 확보한다.

### 5. baseline 검사 실행
한 파일씩 검사하거나 두 파일을 한 번에 실행한다.

```bash
scripts/run_recorder_poc_check.sh <ios-file.wav> <android-file.wav>
```

이 명령은 결과를 아래 경로에 저장한다.
- `verification/evidence/<timestamp>/recorder-poc/`

### 6. 결과 기록
다음을 `docs/mobile/flutter-recorder-poc-template.md`에 기록한다.
- plugin 이름 / 버전
- iOS 결과
- Android 결과
- route 감지 가능 여부
- recording_started_at 기록 가능 여부
- baseline checker JSON 결과
- 최종 판정

### 7. 후보 비교표 업데이트
`docs/mobile/flutter-recorder-plugin-comparison.md`에 아래를 반영한다.
- iOS WAV
- Android WAV
- PCM control
- 48kHz control
- Mono control
- Route detection
- Timestamp capture
- Verdict

## 판정 기준
### PASS
- iOS / Android 모두 WAV 생성 가능
- codec = `pcm_s16le`
- sample rate = `48000`
- channels = `1`
- timestamp 기록 가능

### PARTIAL
- baseline 녹음은 되지만 route 감지 또는 일부 포맷 제어가 부족함

### FAIL
- baseline 포맷을 양 플랫폼에서 안정적으로 만들지 못함

## 최종 의사결정
### Flutter 유지
- 두 플랫폼 모두 baseline 충족

### Flutter + native bridge
- baseline은 되지만 route/timing 일부 보강이 필요

### 전략 재검토
- baseline 자체가 성립하지 않음

## 산출물
최소 산출물은 아래 네 가지다.
1. iOS 샘플 파일
2. Android 샘플 파일
3. `verification/evidence/<timestamp>/recorder-poc/*.json`
4. 업데이트된 PoC 결과 템플릿

## 한 줄 요약
Flutter recorder PoC의 성공 기준은 “녹음이 되느냐”가 아니라 “연구 baseline 파일이 실제로 나오느냐”이다.
