# Flutter Recorder Spike Structure

## 목적
Flutter가 설치된 환경에서 recorder PoC를 빠르게 시작할 수 있도록, 최소 프로젝트 구조와 구현 범위를 미리 고정한다.

## Spike 목표
- iOS/Android에서 녹음 시작/정지 가능
- baseline 파일 1개 저장 가능
- 파일 경로 확인 가능
- 녹음 시작 시각 기록 가능
- 결과 파일을 `tools/check_recorder_baseline.py`로 검증 가능

## Spike 범위에 포함
- recorder plugin 연결
- start/stop 버튼 2개
- 상태 텍스트 1개
- 파일 저장 경로 출력
- timestamp capture

## Spike 범위에서 제외
- room/session API 연동
- upload
- anchor UX
- BLE
- full app navigation
- production state management

## 권장 디렉토리 구조
```text
flutter_recorder_spike/
  pubspec.yaml
  lib/
    main.dart
    recorder_service.dart
    recorder_result.dart
  test/
    recorder_service_test.dart
  README.md
```

## 파일별 역할
### `lib/main.dart`
- 단일 화면
- `Start Recording` 버튼
- `Stop Recording` 버튼
- 상태 표시
- 마지막 생성 파일 경로 표시
- recording_started_at 표시

### `lib/recorder_service.dart`
- recorder plugin wrapper
- start()
- stop()
- getCurrentRoute() (가능하면)
- returns `RecorderResult`

### `lib/recorder_result.dart`
- output file path
- recording_started_at
- recording_stopped_at
- route info
- sample rate / channels / codec (가능하면)

### `test/recorder_service_test.dart`
- 최소 smoke 수준
- service 인터페이스 존재 여부
- start/stop contract 확인

## main.dart 화면 요구사항
- 제목: Flutter Recorder PoC
- 버튼: Start / Stop
- 텍스트 영역:
  - current status
  - file path
  - recording_started_at
  - route (available if supported)

## RecorderResult 예시
```dart
class RecorderResult {
  final String filePath;
  final DateTime recordingStartedAt;
  final DateTime recordingStoppedAt;
  final String? micRoute;
  const RecorderResult({
    required this.filePath,
    required this.recordingStartedAt,
    required this.recordingStoppedAt,
    this.micRoute,
  });
}
```

## 개발 순서
1. Flutter project create
2. recorder plugin add
3. start/stop 버튼 연결
4. 파일 저장 경로 출력
5. timestamp 출력
6. iOS 샘플 1개 생성
7. Android 샘플 1개 생성
8. baseline checker 실행

## 성공 기준
- 두 플랫폼에서 파일 1개씩 생성 가능
- 생성 파일을 baseline checker로 확인 가능
- timestamp를 화면 또는 로그에 표시 가능

## 다음 단계로 넘길 조건
다음 중 하나를 명확히 판단할 수 있어야 한다.
- Flutter 유지
- Flutter + native bridge
- plugin 교체
- native recorder 전략 검토
