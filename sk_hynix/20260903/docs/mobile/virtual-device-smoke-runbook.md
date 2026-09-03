# Virtual Device Smoke Runbook

## 목적
실물 기기가 없을 때 iOS Simulator와 Android Emulator에서 `mobile_app`을 띄워 UI/플로우를 먼저 검증하는 절차입니다.

## 전제 조건
- `flutter doctor -v` 통과
- `mobile_app/flutter analyze` 통과
- `mobile_app/flutter test` 통과
- Android AVD `AudioSyncPixel36` 생성 완료

## 1. 가상 디바이스 실행
```bash
scripts/launch_virtual_test_devices.sh
```

이 스크립트는:
- iOS Simulator `iPhone 17` 부팅
- Android AVD `AudioSyncPixel36` 실행 시도
- `flutter devices` 출력
을 한 번에 수행합니다.

## 2. iOS Simulator 실행
```bash
cd mobile_app
flutter run -d "iPhone 17"
```

## 3. Android Emulator 실행
에뮬레이터가 `flutter devices`에 보이면:
```bash
cd mobile_app
flutter run -d emulator-5554
```

## 4. 가상 환경에서 확인할 것
- Home → Room Lobby → Preflight → Recording → Upload → Result 흐름
- room create/join/ready/start 동작
- fake/native bridge wiring 오류 유무
- metadata 화면/상태 표시
- 업로드/결과 UI 진입 가능 여부

## 5. 가상 환경에서 확인할 수 없는 것
- 실제 마이크 품질
- 실제 recorder baseline 파일(WAV/48kHz/mono) 유효성
- route detection 신뢰성
- sync beep 실제 녹음 포착 품질
- cross-device drift 실측

## 6. 다음 단계
가상 환경 통과 후에는 반드시 실기기에서 recorder PoC를 수행합니다.
