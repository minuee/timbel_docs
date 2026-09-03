# Flutter First-Week Execution Plan — Audio Sync Platform

## Purpose
이 문서는 Flutter SDK가 준비된 환경에서 다음 작업자가 **첫 주 동안 무엇을 어떤 순서로 할지**를 day-by-day로 정리한 실행 계획이다.

이 계획은 현재 저장소의 상태를 전제로 한다.
- backend / protocol / DSP / tooling은 이미 baseline-ready
- `mobile_app/`는 fake/native dual-path scaffold 상태
- 다음 병목은 Flutter 실행 환경에서 shell을 실제로 살려보는 것

---

## Week Goal
첫 주의 목표는 다음 4가지를 달성하는 것이다.
1. `mobile_app/`를 Flutter 환경에서 실제로 컴파일 가능하게 만든다.
2. fake host/member baseline flow를 화면 상에서 끝까지 확인한다.
3. recorder PoC를 돌려 Flutter recorder 전략의 viability를 판단한다.
4. method-channel smoke registration 준비 상태를 만든다.

---

## Day 1 — Environment + Shell Bring-up
### Goals
- Flutter SDK / Dart / ffmpeg / ffprobe 준비 확인
- `mobile_app/`가 Flutter 프로젝트로 로드되게 만들기

### Tasks
1. 실행:
   ```bash
   scripts/run_flutter_run_ready_checks.sh
   ```
2. `cd mobile_app`
3. 실행:
   ```bash
   flutter pub get
   flutter analyze
   flutter test
   ```
4. import / package name / analyzer issues 수정
5. fake mode가 기본값(`AppBootstrap.runtimeMode = AppRuntimeMode.fake`)인지 확인

### Done criteria
- `flutter pub get` 통과
- `flutter analyze` 통과 또는 남은 이슈가 경미하게 정리됨
- `flutter test` 기본 실행 가능
- fake mode shell이 깨지지 않음

---

## Day 2 — Fake Baseline Flow Render
### Goals
- fake host/member baseline flow를 실제 화면으로 확인
- Home → Room → Preflight → Recording → Upload → Result 흐름 점검

### Tasks
1. 시뮬레이터/에뮬레이터에서 앱 실행
2. 확인:
   - HomeScreen 진입
   - RoomLobbyScreen 표시
   - Preflight 화면에서 warnings/blockers 표시 구조
   - Recording 화면에서 start/beep time 표시
   - Upload 화면 classification 표시
   - Result 화면 artifact/QA 표시
3. 필요 시 fake DTO / fake API / flow service 수정
4. 최소 widget test 또는 smoke test 1개 추가 가능하면 추가

### Done criteria
- fake baseline flow를 끝까지 클릭 가능
- 상태 전이와 화면 표시가 문서와 크게 어긋나지 않음

---

## Day 3 — Recorder PoC Decision Day
### Goals
- Flutter recorder 전략이 baseline 포맷을 만들 수 있는지 판단

### Tasks
1. `docs/mobile/flutter-recorder-poc-runbook.md` 따르기
2. iOS 샘플 1개 생성
3. Android 샘플 1개 생성
4. 실행:
   ```bash
   scripts/run_recorder_poc_check.sh <ios-file.wav> <android-file.wav>
   ```
5. 결과 기록:
   - `docs/mobile/flutter-recorder-poc-template.md`
   - `docs/mobile/flutter-recorder-plugin-comparison.md`

### Decision rule
- 두 플랫폼 모두 baseline PASS -> Flutter recorder path 유지
- 부분 PASS -> Flutter shell 유지 + recorder는 native bridge 강화
- FAIL -> recorder/plugin 전략 재검토

### Done criteria
- PASS / PARTIAL / FAIL이 문서로 남음
- 다음 recorder 전략 결정이 명시됨

---

## Day 4 — Method Channel Smoke Integration
### Goals
- fake mode는 유지한 채 method-channel registration smoke를 준비

### Tasks
1. `docs/mobile/method-channel-registration-guide.md` 기반으로
   - iOS registration
   - Android registration
   준비
2. 우선 smoke target만 연결:
   - `getRecorderState`
   - `measureTimeSync`
   - `inspectCurrentRoute`
   - `scheduleSyncBeep`
3. 아직 `startRecording` full integration은 하지 말고 smoke 중심으로만 확인
4. method-channel payload가 Dart wrapper와 맞는지 검토

### Done criteria
- 최소 1개 플랫폼에서 smoke registration 확인
- method-channel payload mismatch가 있으면 문서화
- fake mode fallback은 여전히 유지됨

---

## Day 5 — Week-end Integration Review
### Goals
- 첫 주 산출물을 정리하고 다음 주 우선순위를 확정

### Tasks
1. 결과 문서 업데이트:
   - `docs/mobile/flutter-implementation-handoff-packet.md`
   - `docs/mobile/first-real-app-commit-guide.md`
2. 현재 상태 분류:
   - shell readiness
   - recorder viability
   - native smoke readiness
   - next blocker
3. 다음 주 우선순위 결정:
   - fake flow polish
   - recorder native bridge
   - upload integration hardening
   - room/session UX refinement

### Done criteria
- 다음 주에 무엇을 할지 1순위가 정리됨
- recorder 전략이 유지/수정/폐기 중 하나로 확정됨

---

## Explicit Non-goals for Week 1
첫 주에는 하지 않는다:
- BLE/proximity sync 구현
- realtime capture
- transcript/result viewer 확장
- field-mode relaxed capture 지원
- full native recorder 심화 구현

---

## First-week Success Criteria
첫 주는 성공으로 본다 if:
1. Flutter shell이 fake mode에서 안정적으로 뜬다.
2. fake baseline flow가 끝까지 동작한다.
3. recorder PoC 결과가 문서로 남는다.
4. native method-channel smoke의 다음 단계가 분명해진다.

---

## Primary References
- `docs/mobile/flutter-run-ready-checklist.md`
- `docs/mobile/flutter-implementation-handoff-packet.md`
- `docs/mobile/first-real-app-commit-guide.md`
- `docs/mobile/method-channel-registration-guide.md`
- `docs/mobile/flutter-recorder-poc-runbook.md`
