# 다음 구현 우선순위 5개 (현재 저장소 기준)

## 목적
Flutter SDK가 있는 환경에서 실제 작업을 이어받는 사람이, 지금 무엇부터 손대야 하는지 우선순위를 빠르게 파악할 수 있도록 정리한 문서다.

---

## 1. Flutter shell 실제 컴파일 가능 상태 만들기
### 목표
`mobile_app/`가 실제 Flutter 프로젝트로 로드되고, fake mode 기준으로 분석/테스트가 돌아가게 만든다.

### 작업
- `cd mobile_app`
- `flutter pub get`
- `flutter analyze`
- `flutter test`
- import/path/package name 문제 수정

### 이유
현재 가장 큰 blocker는 외부 Flutter 환경 부재다. 이 단계를 통과해야 모바일 쪽 실제 실행이 시작된다.

---

## 2. fake host/member baseline flow를 실제 화면에서 확인하기
### 목표
Home → Room → Preflight → Recording → Upload → Result 흐름이 fake mode에서 실제로 이어지는지 본다.

### 작업
- fake bridge 유지 (`AppBootstrap.runtimeMode = AppRuntimeMode.fake`)
- 화면 진입 / 버튼 흐름 / 상태 표시 확인
- 필요 시 controller / reducer / fake API wiring 보정

### 이유
문서와 scaffold는 충분히 쌓였지만, 실제 UI 렌더 기준으로 baseline path가 맞게 이어지는지 확인이 필요하다.

---

## 3. Flutter recorder PoC 실행 및 전략 결정
### 목표
Flutter recorder 전략이 연구 baseline(WAV/PCM/48kHz/mono)을 실제로 만들 수 있는지 판단한다.

### 작업
- `./run_flutter_poc_first_step.sh`
- iOS 샘플 1개
- Android 샘플 1개
- `scripts/run_recorder_poc_check.sh <ios-file.wav> <android-file.wav>`
- 결과 기록: `docs/mobile/flutter-recorder-poc-template.md`, `docs/mobile/flutter-recorder-plugin-comparison.md`

### 이유
이 결과가 나와야 “Flutter recorder 유지 / Flutter+native bridge 강화 / 전략 재검토”를 결정할 수 있다.

---

## 4. Method-channel smoke registration
### 목표
real native bridge mode로 넘어가기 전에 iOS/Android에서 최소 smoke call만 성공시킨다.

### 작업
- `getRecorderState`
- `measureTimeSync`
- `inspectCurrentRoute`
- `scheduleSyncBeep`
- 결과 기록: `docs/mobile/native-smoke-evidence-template.md`

### 이유
한 번에 녹음까지 붙이지 말고, registration과 payload shape부터 검증해야 이후 디버깅 비용이 낮다.

---

## 5. 첫 controlled-device baseline run 준비
### 목표
앱 + backend + protocol이 실제로 맞물리는 최소 controlled run을 수행할 준비를 마친다.

### 작업
- room create/join/ready/start 흐름 점검
- metadata 업로드 shape 확인
- sync beep / anchor timing 확인
- evidence bundle 구조 확인
- 다음 controlled run에 필요한 operator checklist 준비

### 이유
이 단계부터 비로소 “연구용 앱 + 서버 + 처리 엔진”이 하나의 시스템으로 검증되기 시작한다.

---

## 한 줄 우선순위 요약
1. Flutter shell compile
2. fake flow 확인
3. recorder PoC
4. method-channel smoke
5. 첫 controlled-device baseline run 준비

## Additional Reference
- `docs/next-steps-one-page-ko.md`
