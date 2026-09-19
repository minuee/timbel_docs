# Flutter Implementation Handoff Packet

## 1. Current Goal
Start the first executable Flutter research-mode recorder shell for the Audio Sync Platform.

This handoff packet is for the next operator/developer who has a Flutter-capable environment and needs a compact, execution-oriented summary.

---

## 2. What Already Exists
### Backend / protocol / DSP side
Implemented and regression-tested:
- metadata schema types
- room/session/event persistence
- multipart metadata+file upload
- baseline vs degraded classification
- session timeline events
- sync beep generator and anchor detector skeleton
- evidence bundle scaffold
- controlled-session scaffold

### Mobile side scaffold
Implemented as file/code scaffold:
- `mobile_app/` Flutter shell structure
- fake API clients
- fake native bridges
- method-channel wrappers
- iOS / Android native bridge stub files
- mock host/member baseline flow coordinator
- mobile scaffold / contract / mock-flow validation tools

### Current regression evidence
- backend/tooling regression: **PASS**
- mobile scaffold checks: **PASS**

---

## 3. Must-Read Docs Before Touching Code
1. `docs/mobile/flutter-run-ready-checklist.md`
2. `docs/mobile/flutter-recorder-poc-runbook.md`
3. `docs/mobile/flutter-app-requirements.md`
4. `docs/mobile/flutter-state-machine.md`
5. `.omx/plans/mobile-app-mvp-spec-audio-sync-platform-v1.md`
6. `.omx/plans/flutter-dto-contract-audio-sync-v1.md`
7. `.omx/plans/flutter-method-channel-contract-audio-sync-v1.md`
8. `.omx/plans/flutter-app-directory-skeleton-audio-sync-v1.md`
9. `.omx/plans/flutter-controller-reducer-spec-audio-sync-v1.md`

---

## 4. Run-Ready Commands
### Environment readiness
```bash
scripts/run_flutter_run_ready_checks.sh
```

### Individual checks
```bash
python3 tools/check_mobile_scaffold.py
python3 tools/check_mobile_contracts.py
python3 tools/check_mobile_mock_flow.py
./run_flutter_poc_first_step.sh
```

### Recorder baseline validation after samples exist
```bash
scripts/run_recorder_poc_check.sh <ios-file.wav> <android-file.wav>
```

---

## 5. Expected Starting Point in Repo
### Mobile app root
- `mobile_app/`

### Key app shell files
- `mobile_app/lib/app/bootstrap.dart`
- `mobile_app/lib/app/bridge_registry.dart`
- `mobile_app/lib/app/mock_host_member_flow.dart`
- `mobile_app/lib/app/router.dart`
- `mobile_app/lib/app/route_names.dart`

### Key fake/native bridge files
- fake: `mobile_app/lib/native/*/*_fake.dart`
- method-channel: `mobile_app/lib/native/*/*_method_channel.dart`
- iOS stubs: `mobile_app/ios/Runner/AudioSyncBridges/*.swift`
- Android stubs: `mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/*.kt`

---

## 6. Recommended First Execution Scope
### Step 1 — Make Flutter shell loadable
Once Flutter SDK is present:
```bash
cd mobile_app
flutter pub get
flutter analyze
flutter test
```

### Step 2 — Keep fake mode first
Do **not** switch to method-channel/native mode immediately.
- keep `AppBootstrap.runtimeMode = AppRuntimeMode.fake`
- make the shell and fake flow compile first

### Step 3 — Fix compile/import gaps
Typical expected work:
- finalize Dart imports
- normalize DTO naming
- fix package name / test package imports
- make fake flows compile under Flutter analyzer/test

### Step 4 — Run mock flow UI
Verify baseline path conceptually works:
- Home
- Room Lobby
- Preflight
- Recording
- Upload
- Result

### Step 5 — Only then start native integration
- wire iOS method-channel registration
- wire Android method-channel registration
- replace one bridge at a time from fake to method-channel

---

## 7. Decision Rules
### If Flutter shell compiles and fake flow works
- continue with Flutter shell as orchestration layer
- keep recorder/time-sync/route/beep as native bridge targets

### If Flutter shell compiles but recorder PoC is partial
- continue with Flutter + native bridge strategy
- prioritize recorder/route native bridge first

### If Flutter recorder PoC fails baseline badly on both platforms
- revisit recorder strategy/plugin choice before further app polish

---

## 8. Known Blockers / External Dependencies
The main blocker is still **external Flutter-capable environment availability**.

Specifically required:
- Flutter SDK
- Dart SDK
- iOS/Android test device access
- ffmpeg/ffprobe installed locally

Without these, only scaffold/code-structure work can continue here.

---

## 9. What Not To Do First
- do not start with BLE/proximity sync
- do not start with full transcript/result UX
- do not start with realtime streaming
- do not remove fake mode before method-channel is proven
- do not loosen research-mode recording policy too early

---

## 10. Best Next Commit Scope
Recommended first real app commit scope once Flutter SDK is ready:
1. make `mobile_app/` compile
2. keep fake bootstrap active
3. make mock host/member baseline flow render cleanly
4. add one tiny widget test or smoke test if possible

---

## 11. Handoff Summary
In one sentence:

> The repository is ready for Flutter execution work, but the next developer should first validate environment readiness, compile the Flutter shell in fake mode, and only then move one native bridge at a time into real method-channel integration.

## Additional Reference
- `docs/mobile/first-real-app-commit-guide.md`

## Additional Reference
- `docs/mobile/flutter-first-week-execution-plan.md`

## Additional Reference
- `docs/mobile/method-channel-registration-checklist.md`

## Additional Reference
- `docs/mobile/native-smoke-evidence-template.md`

## Additional Reference
- `docs/next-steps-one-page-ko.md`
