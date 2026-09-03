# Flutter Run-Ready Checklist — Audio Sync Platform

## Purpose
이 문서는 현재 저장소 기준에서 Flutter 연구용 녹음 앱 작업을 실제로 시작하기 전에 확인해야 하는 항목을 정리한다.

이 체크리스트는 두 층으로 나뉜다.
1. **SDK/도구 준비**
2. **저장소 scaffold/contract 준비**

---

## 1. SDK / Tooling Readiness
### Required commands
- `flutter`
- `dart`
- `python3`
- `ffmpeg`
- `ffprobe`

### Verify
```bash
flutter --version
flutter doctor
dart --version
ffmpeg -version
ffprobe -version
```

### Expected outcome
- Flutter SDK 설치 완료
- Dart 사용 가능
- ffmpeg / ffprobe 사용 가능

---

## 2. Repo Scaffold Readiness
### Required mobile scaffold checks
Run:
```bash
python3 tools/check_mobile_scaffold.py
python3 tools/check_mobile_contracts.py
python3 tools/check_mobile_mock_flow.py
```

### Expected outcome
- 모든 check 결과 `"ok": true`

---

## 3. Backend / Protocol Readiness
### Required regression checks
Run:
```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_api \
  tests.test_rooms \
  tests.test_upload_metadata \
  tests.test_metadata_schema \
  tests.test_protocol_models \
  tests.test_upload_contract \
  tests.test_pipeline \
  tests.test_endgame_tooling \
  tests.test_anchor_tooling \
  tests.test_evidence_bundle_tooling \
  tests.test_mobile_scaffold_tooling \
  tests.test_mobile_contracts_tooling \
  tests.test_mobile_mock_flow_tooling \
  tests.test_controlled_session_scaffold \
  tests.dsp.test_anchor \
  tests.dsp.test_alignment \
  tests.dsp.test_filters -v
```

### Expected outcome
- 전체 PASS

---

## 4. Mobile App Work Scope Readiness
### Must-exist docs
- `.omx/plans/mobile-app-mvp-spec-audio-sync-platform-v1.md`
- `.omx/plans/flutter-dto-contract-audio-sync-v1.md`
- `.omx/plans/flutter-method-channel-contract-audio-sync-v1.md`
- `.omx/plans/flutter-app-directory-skeleton-audio-sync-v1.md`
- `.omx/plans/flutter-controller-reducer-spec-audio-sync-v1.md`
- `docs/mobile/flutter-app-requirements.md`
- `docs/mobile/flutter-state-machine.md`

### Must-exist mobile scaffold paths
- `mobile_app/lib/app/`
- `mobile_app/lib/features/`
- `mobile_app/lib/native/`
- `mobile_app/ios/Runner/AudioSyncBridges/`
- `mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/`

---

## 5. First Executable Flutter Tasks
Once Flutter SDK is available, do these in order:
1. open `mobile_app/`
2. run `flutter pub get`
3. run `flutter analyze`
4. run `flutter test`
5. fix missing package/import issues from the generated scaffold
6. keep fake bridge mode as default until native bridge registration exists

---

## 6. Native Bridge Readiness
Before switching from fake mode to native bridge mode, confirm:
- iOS method-channel registration implemented
- Android method-channel registration implemented
- recorder/time-sync/route/beep methods return the contract fields defined in `.omx/plans/native-bridge-interface-audio-sync-v1.md`

---

## 7. Recorder PoC Gate
After the Flutter shell can build, run the recorder PoC gate:
- `./run_flutter_poc_first_step.sh`
- follow `docs/mobile/flutter-recorder-poc-runbook.md`
- validate samples with `scripts/run_recorder_poc_check.sh`

### Decision rule
- both platforms PASS baseline -> proceed with Flutter recorder path
- partial PASS -> keep Flutter shell, move recorder deeper into native bridge
- FAIL -> revisit recorder strategy/plugin choice

---

## 8. Stop Conditions
Do **not** start real app integration work if any of these fail:
- Flutter SDK unavailable
- mobile scaffold checks fail
- backend/protocol regressions fail
- recorder PoC blockers unresolved

---

## 9. One-command readiness sequence
Recommended sequence:
```bash
python3 tools/check_mobile_scaffold.py
python3 tools/check_mobile_contracts.py
python3 tools/check_mobile_mock_flow.py
./run_flutter_poc_first_step.sh
```

## Additional reference
- `docs/mobile/first-real-app-commit-guide.md`

## Additional Reference
- `docs/mobile/flutter-first-week-execution-plan.md`

## Additional Reference
- `docs/mobile/method-channel-registration-checklist.md`

## Additional Reference
- `docs/next-steps-one-page-ko.md`
