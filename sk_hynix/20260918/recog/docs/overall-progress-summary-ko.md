# 전체 진행 상태 요약 (한국어)

## 1. 이 프로젝트가 지금 무엇이 되었는가
처음 요구는 다음과 같았다.
- iOS / Android 스마트폰으로 같은 공간의 회의를 각자 녹음한다.
- 중앙 마이크 방식보다 STT 누락을 줄이기 위해, 각자 녹음한 파일을 정렬/보정/믹스한다.
- 장시간(예: 5명 / 1시간)에서도 sync/drift를 관리하고, 사람이 다시 들었을 때도 자연스러운 결과를 만든다.

현재 프로젝트는 이 요구를 기준으로 다음 3계층으로 정리되었다.
1. **모바일 녹음 앱 계층** — room/join/ready/start, sync beep, metadata capture, upload
2. **세션/제어 서버 계층** — room/session lifecycle, protocol events, metadata ingest
3. **오디오 처리 엔진 계층** — canonicalize, anchor-aware alignment, drift correction, mix/export/STT handoff

즉, 더 이상 단순한 “업로드 후 처리 서버”만이 아니라, **녹음 규칙을 통제하는 앱 + 세션 제어 + 처리 엔진**까지 포함한 전체 시스템으로 재정의되었다.

---

## 2. 문서/설계 상태
현재 저장소에는 다음과 같은 핵심 계획 문서가 있다.

### 핵심 시스템 계획
- `.omx/plans/prd-audio-sync-platform.md`
- `.omx/plans/test-spec-audio-sync-platform.md`
- `.omx/plans/roadmap-audio-sync-platform.md`
- `.omx/plans/implementation-backlog-audio-sync-platform-v1.md`
- `.omx/plans/p0-execution-ticket-spec-audio-sync-platform-v1.md`

### 계약 / 프로토콜 / 스키마
- `.omx/plans/metadata-schema-audio-sync-platform-v1.md`
- `.omx/plans/room-session-protocol-audio-sync-v1.md`
- `.omx/plans/backend-api-contract-audio-sync-platform-v1.md`
- `.omx/plans/backend-data-model-audio-sync-platform-v1.md`
- `.omx/plans/sync-beep-spec-audio-sync-v1.md`

### 실험 / 검증 문서
- `.omx/plans/protocol-calibration-test-plan-audio-sync-v1.md`
- `.omx/plans/controlled-spoken-script-audio-sync-v1.md`
- `.omx/plans/evidence-bundle-template-audio-sync-v1.md`

### 모바일 앱 설계 문서
- `.omx/plans/mobile-app-mvp-spec-audio-sync-platform-v1.md`
- `.omx/plans/flutter-dto-contract-audio-sync-v1.md`
- `.omx/plans/flutter-method-channel-contract-audio-sync-v1.md`
- `.omx/plans/flutter-app-directory-skeleton-audio-sync-v1.md`
- `.omx/plans/flutter-controller-reducer-spec-audio-sync-v1.md`

### Flutter 실행/인계 문서
- `docs/mobile/flutter-run-ready-checklist.md`
- `docs/mobile/flutter-implementation-handoff-packet.md`
- `docs/mobile/first-real-app-commit-guide.md`
- `docs/mobile/flutter-first-week-execution-plan.md`
- `docs/mobile/method-channel-registration-guide.md`
- `docs/mobile/method-channel-registration-checklist.md`
- `docs/mobile/native-smoke-evidence-template.md`

---

## 3. 코드 구현 상태 (Backend / DSP / Tooling)
다음은 실제 코드로 구현되어 있다.

### Backend / protocol
- metadata schema types
- room/session/event persistence
- multipart metadata + file upload
- baseline_valid / degraded 분류
- session timeline events
- processing lifecycle events

### DSP / anchor tooling
- sync beep generator
- anchor detector skeleton
- detector benchmark tool
- evidence bundle scaffold
- controlled session scaffold

### 대표 구현 파일
- `src/recog/protocol_models.py`
- `src/recog/events.py`
- `src/recog/api.py`
- `src/recog/store.py`
- `src/recog/pipeline.py`
- `src/audio_sync/dsp/anchor.py`
- `tools/generate_sync_beep.py`
- `tools/benchmark_anchor_detector.py`
- `tools/init_evidence_bundle.py`
- `tools/run_controlled_session_scaffold.py`

---

## 4. 코드 구현 상태 (mobile_app scaffold)
`mobile_app/` 디렉터리는 실제 Flutter SDK 환경에서 바로 이어서 작업할 수 있는 scaffold 상태로 준비되어 있다.

### 현재 구조
- Flutter shell app 구조
- feature별 폴더 구조 (`home`, `room`, `preflight`, `recording`, `upload`, `result`)
- fake API clients
- fake native bridges
- method-channel wrapper skeleton
- iOS / Android native bridge stub
- mock host/member baseline flow coordinator

### 현재 mobile_app 파일 수
- **106개**

### 대표 파일
- `mobile_app/lib/app/bootstrap.dart`
- `mobile_app/lib/app/bridge_registry.dart`
- `mobile_app/lib/app/mock_host_member_flow.dart`
- `mobile_app/lib/features/room/domain/session_controller.dart`
- `mobile_app/lib/features/preflight/domain/preflight_flow_service.dart`
- `mobile_app/lib/features/recording/domain/recording_flow_service.dart`
- `mobile_app/lib/features/upload/domain/upload_flow_service.dart`
- `mobile_app/lib/features/result/domain/result_flow_service.dart`
- `mobile_app/lib/native/*/*_fake.dart`
- `mobile_app/lib/native/*/*_method_channel.dart`
- `mobile_app/ios/Runner/AudioSyncBridges/*.swift`
- `mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/*.kt`

---

## 5. 자동 검증 상태
### Backend / tooling 회귀
다음 회귀는 현재 통과 상태다.
- **110 tests OK**
- py_compile PASS

### mobile scaffold 체크
현재 다음 3개 check가 모두 통과한다.
- `python3 tools/check_mobile_scaffold.py`
- `python3 tools/check_mobile_contracts.py`
- `python3 tools/check_mobile_mock_flow.py`

즉, Flutter SDK가 없어도 **구조 / 계약 / mock 흐름**은 자동 검사 가능한 상태다.

---

## 6. 지금 당장 남아 있는 가장 큰 blocker
가장 큰 blocker는 **외부 Flutter-capable 환경 부재**다.

즉, 현재 저장소 안에서는 설계/구조/계약/툴링은 충분히 정리되었지만,
다음 단계인 아래 작업은 Flutter SDK와 실제 iOS/Android 테스트 환경이 필요하다.
- `flutter pub get`
- `flutter analyze`
- `flutter test`
- fake flow 실제 렌더 확인
- recorder PoC
- native method-channel smoke

---

## 7. 다음 작업자가 해야 할 실제 순서
### 1단계 — 준비 확인
```bash
scripts/run_flutter_run_ready_checks.sh
```

### 2단계 — mobile_app 컴파일/정리
```bash
cd mobile_app
flutter pub get
flutter analyze
flutter test
```

### 3단계 — fake mode baseline flow 확인
- Home
- Room Lobby
- Preflight
- Recording
- Upload
- Result

### 4단계 — recorder PoC 수행
```bash
./run_flutter_poc_first_step.sh
scripts/run_recorder_poc_check.sh <ios-file.wav> <android-file.wav>
```

### 5단계 — native method-channel smoke
- `getRecorderState`
- `measureTimeSync`
- `inspectCurrentRoute`
- `scheduleSyncBeep`

---

## 8. 가장 중요한 운영 원칙
1. **fake mode를 먼저 깨지 말 것**
2. **첫 실제 앱 커밋은 compile/analyze/test 통과까지로 제한할 것**
3. **method-channel은 한 번에 다 연결하지 말고 하나씩 smoke 확인할 것**
4. **field validation 결과를 quantitative truth claim으로 섞지 말 것**
5. **타임스탬프는 prior이고, 최종 truth는 waveform anchor/onset이라는 원칙을 유지할 것**

---

## 9. 한 줄 결론
현재 저장소는:

> **“설계 문서, backend baseline, DSP anchor tooling, mobile scaffold, handoff 문서가 모두 갖춰진 상태이며, Flutter SDK 환경만 준비되면 실제 앱 실행/검증 단계로 넘어갈 수 있는 handoff-ready 상태”**

이다.

## Additional Reference
- `docs/next-steps-one-page-ko.md`
