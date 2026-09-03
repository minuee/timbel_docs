# First Real App Commit Guide — Audio Sync Platform

## Purpose
이 문서는 Flutter SDK가 준비된 이후 **첫 실제 앱 커밋**의 범위를 과도하게 넓히지 않도록 만드는 가이드다.

목표는:
1. `mobile_app/`가 실제로 컴파일되게 만들고
2. fake mode 기반 baseline 흐름을 깨지 않게 유지하며
3. native bridge 실구현이나 recorder plugin 선택 같은 큰 결정을 첫 커밋에 섞지 않는 것이다.

---

## 1. First Commit Goal
첫 커밋의 목표는 단 하나다:

> **`mobile_app/`를 Flutter 환경에서 로드/분석/테스트 가능한 상태로 만드는 것**

이 커밋은 “실제 녹음 기능 완성” 커밋이 아니다.

---

## 2. Allowed Scope
첫 커밋에서 허용되는 것:
- `flutter pub get` 통과를 위한 의존성 정리
- import path / package name 정리
- fake API / fake bridge 기반 mock flow가 컴파일되도록 수정
- `flutter analyze` 경고/에러 정리
- 최소 widget test 또는 smoke test 1개 추가
- `pubspec.yaml` / app package metadata 수정
- `mobile_app/README.md` 실행 방법 보강

---

## 3. Not Allowed in First Commit
첫 커밋에서 하지 말아야 할 것:
- 실제 recorder plugin 선정 확정
- method-channel 실구현 전환
- iOS/Android native recording 코드 심화 구현
- BLE/proximity sync 구현 시작
- real-time 기능 추가
- 업로드/processing UX 대규모 확장
- transcript/result viewer 구현
- room/session protocol 자체 변경

즉, 첫 커밋은 **bootstrap stabilization commit**이어야 한다.

---

## 4. Mandatory Checks Before Commit
반드시 통과해야 하는 것:

### A. repo-level checks
```bash
python3 tools/check_mobile_scaffold.py
python3 tools/check_mobile_contracts.py
python3 tools/check_mobile_mock_flow.py
```

### B. Flutter-level checks
```bash
cd mobile_app
flutter pub get
flutter analyze
flutter test
```

### C. optional but recommended
```bash
flutter run -d <simulator-or-device>
```
최소한 앱이 뜨고 HomeScreen 진입까지 확인

---

## 5. Recommended First Commit Steps
1. `scripts/run_flutter_run_ready_checks.sh` 실행
2. `cd mobile_app`
3. `flutter pub get`
4. 깨지는 import / package name 정리
5. `flutter analyze` 통과
6. `flutter test` 통과
7. fake mode baseline flow 화면 렌더 확인
8. commit

---

## 6. Suggested Commit Scope by File Area
### Expected touched files
- `mobile_app/pubspec.yaml`
- `mobile_app/lib/**`
- `mobile_app/test/**`
- maybe generated platform runner metadata files if Flutter tool creates them

### Avoid touching in first commit unless truly necessary
- backend Python files
- `.omx/plans/*`
- native stub logic beyond minimal registration placeholders

---

## 7. Success Criteria for First Commit
첫 커밋은 아래를 만족하면 성공이다.
1. `mobile_app/`가 Flutter 프로젝트로 로드 가능
2. fake mode가 기본값으로 유지됨
3. `flutter analyze` 통과
4. `flutter test` 통과
5. Home -> Room -> Preflight -> Recording -> Upload -> Result mock 흐름이 최소 수준으로 유지됨

---

## 8. If First Commit Fails
### Case 1 — Flutter project bootstrap 문제
- package/import/name mismatch 해결에 집중
- 기능 추가 금지

### Case 2 — fake flow compile 문제
- DTO / controller / fake bridge wiring 수정
- backend contract 변경 금지

### Case 3 — platform runner issues
- 최소 생성/설정만 반영
- native recorder implementation 착수 금지

---

## 9. What the Second Commit Should Do
첫 커밋이 성공하면 두 번째 커밋부터:
- method-channel smoke wiring
- `getRecorderState` / `measureTimeSync` / `inspectCurrentRoute` / `scheduleSyncBeep` 연결
- native registration smoke test

즉, native bridge 실연결은 **두 번째 커밋 이후**가 바람직하다.

---

## 10. One-sentence Rule
> 첫 커밋은 “앱이 뜨고 fake baseline flow가 유지되는 상태”까지만 책임진다. 실제 녹음/네이티브 bridge 심화는 다음 커밋으로 넘긴다.

## Additional Reference
- `docs/mobile/flutter-first-week-execution-plan.md`
