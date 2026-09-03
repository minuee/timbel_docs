# Method Channel Registration TODO Checklist — Audio Sync Platform

## Purpose
이 문서는 Flutter fake mode에서 real native bridge mode로 전환할 때,
iOS/Android에서 실제로 해야 할 작업을 체크박스 단위로 정리한 TODO 목록이다.

이 문서는 다음 가이드를 실무 체크리스트로 쪼갠 버전이다.
- `docs/mobile/method-channel-registration-guide.md`

---

## 1. Global Preconditions
- [ ] `scripts/run_flutter_run_ready_checks.sh` 통과
- [ ] `flutter pub get` 통과
- [ ] `flutter analyze` 통과
- [ ] `flutter test` 통과
- [ ] `AppBootstrap.runtimeMode = AppRuntimeMode.fake` 상태에서 앱 shell 정상 구동 확인
- [ ] native bridge 전환 전, fake host/member baseline flow가 깨지지 않는지 확인

---

## 2. iOS Registration Checklist
### 2.1 Project wiring
- [ ] Flutter iOS runner 프로젝트 열기
- [ ] `AppDelegate.swift` 또는 등록 지점을 확인
- [ ] `mobile_app/ios/Runner/AudioSyncBridges/` 파일이 실제 target에 포함되는지 확인

### 2.2 Recorder channel
- [ ] `audio_sync/recorder` 채널 생성
- [ ] `prepareRecorder` method routing 추가
- [ ] `startRecording` method routing 추가
- [ ] `stopRecording` method routing 추가
- [ ] `getRecorderState` method routing 추가
- [ ] unknown method -> `FlutterMethodNotImplemented`

### 2.3 Time sync channel
- [ ] `audio_sync/time_sync` 채널 생성
- [ ] `measureTimeSync` routing 추가

### 2.4 Route channel
- [ ] `audio_sync/route` 채널 생성
- [ ] `inspectCurrentRoute` routing 추가
- [ ] `inspectProcessingFlags` routing 추가

### 2.5 Beep channel
- [ ] `audio_sync/beep` 채널 생성
- [ ] `scheduleSyncBeep` routing 추가
- [ ] optional `playSyncBeepNow` routing 추가 여부 판단

### 2.6 Error handling
- [ ] native 예외를 `FlutterError`로 변환
- [ ] `ok: false` payload strategy와 `FlutterError` 전략 중 하나로 통일

### 2.7 iOS smoke checks
- [ ] Flutter에서 `getRecorderState` 호출 성공
- [ ] Flutter에서 `measureTimeSync` 호출 성공
- [ ] Flutter에서 `inspectCurrentRoute` 호출 성공
- [ ] Flutter에서 `scheduleSyncBeep` 호출 성공
- [ ] 앱 crash 없음

---

## 3. Android Registration Checklist
### 3.1 Project wiring
- [ ] Android runner 프로젝트 열기
- [ ] `MainActivity.kt` 또는 등록 지점 확인
- [ ] `mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/` 파일이 실제 package path와 맞는지 확인

### 3.2 Recorder channel
- [ ] `audio_sync/recorder` 채널 생성
- [ ] `prepareRecorder` method routing 추가
- [ ] `startRecording` method routing 추가
- [ ] `stopRecording` method routing 추가
- [ ] `getRecorderState` method routing 추가
- [ ] unknown method -> `result.notImplemented()`

### 3.3 Time sync channel
- [ ] `audio_sync/time_sync` 채널 생성
- [ ] `measureTimeSync` routing 추가

### 3.4 Route channel
- [ ] `audio_sync/route` 채널 생성
- [ ] `inspectCurrentRoute` routing 추가
- [ ] `inspectProcessingFlags` routing 추가

### 3.5 Beep channel
- [ ] `audio_sync/beep` 채널 생성
- [ ] `scheduleSyncBeep` routing 추가
- [ ] optional `playSyncBeepNow` routing 추가 여부 판단

### 3.6 Error handling
- [ ] exception -> `result.error(...)` 매핑
- [ ] `ok: false` payload strategy와 native exception strategy 정리

### 3.7 Android smoke checks
- [ ] Flutter에서 `getRecorderState` 호출 성공
- [ ] Flutter에서 `measureTimeSync` 호출 성공
- [ ] Flutter에서 `inspectCurrentRoute` 호출 성공
- [ ] Flutter에서 `scheduleSyncBeep` 호출 성공
- [ ] 앱 crash 없음

---

## 4. Safe Switch Strategy
### Phase A — registration only
- [ ] fake mode 유지
- [ ] 채널만 등록
- [ ] smoke call만 확인

### Phase B — one bridge at a time
- [ ] recorder bridge만 native로 교체
- [ ] route bridge만 native로 교체
- [ ] time sync bridge만 native로 교체
- [ ] beep bridge만 native로 교체

### Phase C — recording flow integration
- [ ] `startRecording` + `scheduleSyncBeep` 조합 검증
- [ ] metadata capture 값이 Flutter DTO와 일치하는지 확인

---

## 5. Must-Capture Evidence
native registration 작업 후 최소한 아래 evidence를 남긴다.
- [ ] iOS smoke log
- [ ] Android smoke log
- [ ] method name / payload 확인 스크린샷 또는 로그
- [ ] 실패 시 error payload 예시 1개
- [ ] 성공 시 return payload 예시 1개

Recommended path:
- `verification/evidence/<timestamp>/mobile-native-smoke/`

---

## 6. Exit Criteria
real native bridge mode로 넘어갈 수 있는 기준:
- [ ] iOS smoke pass
- [ ] Android smoke pass
- [ ] payload shape가 Dart DTO 기대와 일치
- [ ] fake mode fallback이 여전히 남아 있음
- [ ] registration 변경이 fake flow를 깨지 않음

---

## 7. Next Step After Checklist Complete
이 체크리스트가 끝나면 바로 다음은:
1. recorder 실제 capture smoke
2. route/processing flags 진짜 값 확인
3. beep playback timing 확인
4. recorder PoC baseline 파일 생성

## Additional Reference
- `docs/mobile/native-smoke-evidence-template.md`
