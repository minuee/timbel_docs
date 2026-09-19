# 다음 단계 한 페이지 실행 체크리스트

## 목적
이 문서는 현재 저장소를 이어받는 작업자가 **무엇을 먼저 실행해야 하는지**를 가장 짧은 형태로 보여주는 1페이지 요약본이다.

---

## 0. 현재 상태 한 줄 요약
- backend / protocol / DSP / tooling: 준비 완료 (Python test suite 110개 통과)
- mobile_app scaffold / contract / mock flow: 준비 완료
- 자동 검증: Python test suite 110개 통과
- Flutter SDK 설치 및 doctor 통과
- mobile_app: flutter analyze / flutter test 통과
- Android APK build 성공
- iOS simulator build 성공
- iOS Simulator 부팅/설치/실행 가능
- Android Emulator(AVD AudioSyncPixel36) 생성/설치/실행 가능
- 실기기 테스트용 환경 준비 완료 (기기 연결만 남음)
- 가장 큰 blocker: **실제 iOS/Android 물리 디바이스 연결 및 recorder PoC 실측 데이터 없음**

---

## 1. 가장 먼저 할 일
### Step 1 — 환경 확인
```bash
scripts/run_flutter_run_ready_checks.sh
```

### Step 2 — Flutter shell 로드
```bash
cd mobile_app
flutter pub get
flutter analyze
flutter test
```

### Step 3 — fake flow 확인
확인할 화면 흐름:
- Home
- Room Lobby
- Preflight
- Recording
- Upload
- Result

### Step 4 — Recorder PoC
```bash
./run_flutter_poc_first_step.sh
scripts/run_recorder_poc_check.sh <ios-file.wav> <android-file.wav>
```

### Step 5 — Native smoke
최소 확인 대상:
- `getRecorderState`
- `measureTimeSync`
- `inspectCurrentRoute`
- `scheduleSyncBeep`

---

## 2. 지금 절대 하면 안 되는 것
- BLE/proximity sync 먼저 시작
- real-time 기능 추가
- transcript/result viewer 확장
- fake mode를 바로 제거
- native recorder를 첫 커밋부터 깊게 구현
- room/session protocol을 임의로 바꾸기

---

## 3. 첫 실제 앱 커밋의 목표
첫 커밋은 이것만 달성하면 된다.

- `mobile_app/`가 Flutter에서 로드됨
- fake mode 유지
- analyze/test 통과
- mock baseline flow가 화면에서 깨지지 않음

즉, **첫 커밋은 bootstrap stabilization commit**이어야 한다.

---

## 4. 성공/실패 판단 기준
### 성공
- Flutter shell이 뜬다
- fake flow가 돈다
- recorder PoC 결과가 문서로 남는다
- native smoke 등록 다음 단계가 보인다

### 실패
- Flutter shell 자체가 로드되지 않음
- fake flow가 깨짐
- recorder baseline 포맷이 양 플랫폼에서 안 나옴

---

## 5. 참고 문서 5개만 보면 된다
1. `docs/overall-progress-summary-ko.md`
2. `docs/mobile/flutter-run-ready-checklist.md`
3. `docs/mobile/flutter-implementation-handoff-packet.md`
4. `docs/mobile/first-real-app-commit-guide.md`
5. `docs/mobile/method-channel-registration-checklist.md`

---

## 한 줄 결론
**지금은 더 설계할 때가 아니라, Flutter 환경에서 shell을 실제로 띄워보고 recorder PoC와 native smoke를 돌려야 할 때다.**
