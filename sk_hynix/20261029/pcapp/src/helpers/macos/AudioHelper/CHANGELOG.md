# 변경 사항

## 25.11.18

### 세그먼트 길이 및 MAX_SEGMENTS 동적 계산 구현

#### 배경
- 테스트 시 `max_ms=30초` 설정해도 세그먼트 길이(3분) 때문에 3분 후에야 정지
- 세그먼트 길이가 고정되어 유연한 테스트 불가능
- MAX_SEGMENTS가 하드코딩되어 duration_ms 변경 시 정확한 정지 불가

#### 구현 내용

**1. duration_ms 파싱 및 반영**
- `SegmentingConfig` 구조체 추가 (JSONModels.swift)
  - `duration_ms`: 세그먼트 길이 (밀리초)
  - `max_cipher_bytes`: 최대 암호화 바이트
  - `align_to_block`: 블록 정렬 여부
- `Command` 구조체에 `segmenting` 필드 추가
- renderer에서 전달한 `segmenting.duration_ms` 파싱
- SegmentManager에 동적으로 전달
- 기본값: 180,000ms (3분)

**2. MAX_SEGMENTS 동적 계산**
- `max_ms ÷ duration_ms`로 자동 계산 (올림)
- `max_ms=0` (무제한)인 경우: 3시간 기준으로 계산
- 상세 로그 추가:
  - INFO: 정상 계산 로그
  - WARN: `max_ms < duration_ms` 경우 경고

**3. 로직 상세**
```swift
// duration_ms 파싱
let segmentDurationMs = cmd.segmenting?.duration_ms ?? 180_000

// MAX_SEGMENTS 계산
if max_ms > 0 {
    MAX_SEGMENTS = ceil(max_ms / duration_ms)
} else {
    MAX_SEGMENTS = ceil(3시간 / duration_ms)  // 무제한 모드
}
```

#### 테스트 시나리오

**시나리오 1: 30초 테스트 (완벽한 매칭)**
```javascript
const command = {
    cmd: 'start',
    max_ms: 30000,
    segmenting: { duration_ms: 30000 }
};
// → MAX_SEGMENTS = 1, 30초 후 정지 ✅
```

**시나리오 2: max_ms만 지정**
```javascript
const command = {
    cmd: 'start',
    max_ms: 10800000  // 3시간
};
// → duration_ms = 180,000ms (기본값)
// → MAX_SEGMENTS = 60, 3시간 후 정지
```

**시나리오 3: duration_ms만 지정 (1분 세그먼트)**
```javascript
const command = {
    cmd: 'start',
    segmenting: { duration_ms: 60000 }  // 1분
};
// → max_ms = 0 (무제한)
// → MAX_SEGMENTS = 180 (3시간 ÷ 1분), 3시간 후 정지
```

**시나리오 4: max_ms < duration_ms (경고 케이스)**
```javascript
const command = {
    cmd: 'start',
    max_ms: 30000,       // 30초
    segmenting: { duration_ms: 60000 }  // 1분
};
// → MAX_SEGMENTS = 1
// → WARN 로그: "will stop at first segment"
// → 실제 정지: 1분 후 (첫 세그먼트 완료 시)
```

#### 효과
- ✅ **테스트 용이성 대폭 향상**: 30초 세그먼트 + 30초 제한 = 정확히 30초 후 정지
- ✅ **유연한 세그먼트 길이**: 10초~무제한까지 자유롭게 설정 가능
- ✅ **정확한 정지 시간**: duration_ms와 max_ms 조합으로 정밀 제어
- ✅ **하위 호환성 보장**: 파라미터 미지정 시 기존 동작(3분 세그먼트) 유지
- ✅ **상세한 로깅**: 계산 과정 및 경고 명확히 기록

#### 기술적 세부사항
- **세그먼트 길이 범위**: 제한 없음 (1초~무제한)
- **MAX_SEGMENTS 계산**: `ceil(max_ms / duration_ms)`
- **무제한 모드**: `max_ms=0` 시 3시간 기준 계산
- **경고 조건**: `max_ms < duration_ms`
- **로그 카테고리**: `recording`

#### 변경 파일
- `JSONModels.swift`
- `AudioHelperController.swift`

---

## 25.11.17

### macOS Helper에 3시간 녹음 제한 로직 구현 (Windows Helper와 동일)

#### 배경
- 녹음이 21시간 동안 지속되는 심각한 버그 발견
- macOS Helper에 `max_ms` 파라미터 처리 및 워치독 타이머가 구현되지 않았음
- Windows Helper는 이미 구현되어 3시간 후 자동 정지 동작 중

#### 구현 내용

**1. JSONModels.swift**
- `Command` 구조체에 `maxMs` 필드 추가
- `max_ms` 파라미터를 JSON에서 파싱할 수 있도록 `CodingKeys` 추가

**2. AudioHelperController.swift**
- **프로퍼티 추가**:
  - `maxDurationMs`: 최대 녹음 시간 (밀리초, 0=무제한)
  - `startTimeMs`: 녹음 시작 시각
  - `stopAtBoundary`: 세그먼트 경계에서 안전 정지 플래그
  - `watchdogTimer`: 워치독 타이머

- **`start()` 함수 수정**:
  - `max_ms` 파라미터 파싱 및 저장 (빈 문자열/0은 무제한)
  - 녹음 시작 시각(`startTimeMs`) 기록
  - `startWatchdogIfNeeded()` 호출하여 워치독 시작

- **워치독 타이머 구현** (Windows Helper와 동일):
  - `startWatchdogIfNeeded()`: max_ms > 0일 때만 워치독 시작
  - 50ms마다 현재 시각 체크 (Windows Helper와 동일 주기)
  - 시간 초과 시 `stopAtBoundary` 플래그 설정 (즉시 중지 X)
  - `stopWatchdog()`: 워치독 타이머 정리

- **`tryMixAndBuffer()` 수정**:
  - 세그먼트 완료 시(`segmentCompleted=true`) `stopAtBoundary` 체크
  - 조건 충족 시 안전하게 `stop()` 호출 (데이터 무결성 보장)

- **`stop()` 함수 수정**:
  - `stopWatchdog()` 호출하여 워치독 정리

- **`requestStopAtBoundary()` 메서드 추가**:
  - SegmentManager가 MAX_SEGMENTS 도달 시 호출하는 public 메서드

**3. SegmentManager.swift**
- `maxSegments` 프로퍼티 추가 (0 = unlimited)
- `setMaxSegments()` 메서드 추가
- `addSamples()` 함수 수정:
  - 세그먼트 완료 시 최대 세그먼트 수(`maxSegments`) 체크
  - `segmentIndex >= maxSegments`일 때 `controller.requestStopAtBoundary()` 호출
  - FileLogger에 최대 세그먼트 도달 로그 기록

#### 특징
- **기존 동작 보존**: `max_ms`가 없거나 0이면 무제한 녹음 (하위 호환성)
- **독립적 구현**: 워치독 타이머는 별도 큐에서 실행되어 오디오 처리와 완전 격리
- **안전 정지**: 즉시 중지가 아닌 세그먼트 경계에서 안전하게 정지 (데이터 무결성 보장)
- **이중 안전장치**:
  1. `max_ms` 워치독 (시간 기반, 기본값 3시간 = 10800000ms)
  2. `MAX_SEGMENTS=60` 체크 (세그먼트 개수 기반, 3분×60 = 3시간)

#### 효과
- ✅ **21시간 녹음 버그 수정**: 3시간 후 자동 정지
- ✅ **Windows Helper와 동작 일치**: 플랫폼 간 일관성 확보
- ✅ **데이터 무결성**: 세그먼트 경계에서 안전하게 정지
- ✅ **유연성**: `max_ms` 파라미터로 시간 제한 커스터마이즈 가능
- ✅ **시스템 자원 보호**: 장시간 녹음으로 인한 메모리/디스크 낭비 방지

#### 기술적 세부사항
- **워치독 주기**: 50ms (Windows Helper와 동일)
- **타이머 큐**: `DispatchQueue.global(qos: .utility)` (백그라운드)
- **시간 측정**: `uptimeMs()` 함수 사용 (monotonic clock)
- **로깅**:
  - 워치독 시작: "Watchdog started: max_ms=10800000, start_ms=..., deadline_ms=..."
  - 시간 초과: "Watchdog timeout reached, will stop at next segment boundary"
  - 최대 세그먼트: "Max segments reached: index=60, max=60"
  - 정지 실행: "Stopping at segment boundary (watchdog/max_segments)"

#### 테스트 체크리스트
- [ ] 3시간 녹음 후 자동 정지 확인
- [ ] `max_ms` 파라미터 변경 테스트 (예: 10분 = 600000ms)
- [ ] `max_ms=0` 또는 미설정 시 무제한 녹음 동작 확인
- [ ] 세그먼트 경계에서 정지되는지 확인 (마지막 세그먼트 완전성)
- [ ] 워치독 타이머가 stop 후 정리되는지 확인 (메모리 누수 방지)

#### 변경 파일
- `JSONModels.swift`
- `AudioHelperController.swift`
- `SegmentManager.swift`

---

## 25.11.10

### 장치 변경 시 불필요한 에러 이벤트 전송 방지

#### 문제
- 마이크 장치 제거/추가 시 `AVCaptureSession`이 런타임 에러 발생
- `sessionErrorObserver`가 모든 런타임 에러를 `COMMAND_ERROR`로 전송
- 사용자에게 "Recording Stopped" 에러 메시지가 표시됨
- 장치 목록 요청(`list_devices`)과 타이밍이 겹쳐 혼란 발생

#### 해결 방법
- 녹음 중이 아닐 때 AVCaptureSession 런타임 에러 무시
- 디버그 로그만 기록하고 에러 이벤트 전송 안 함
- 녹음 중일 때만 실제 에러로 처리

#### 변경 내용
**AudioHelper/AudioHelperController.swift** (line 636-639):
```swift
sessionErrorObserver = nc.addObserver(...) {
    guard let self else { return }
    
    // 녹음 중이 아니라면 에러 무시 (장치 변경은 정상 동작)
    guard self.isRecording else {
        FileLogger.shared.log(.debug, category: "device", 
                            message: "AVCaptureSession runtime error ignored (not recording)")
        return
    }
    
    self.postEvent(.errorCode(code: "COMMAND_ERROR", message: ...))
}
```

#### 효과
- ✅ 장치 변경 시 불필요한 에러 메시지 제거
- ✅ 녹음 중 실제 에러는 여전히 감지
- ✅ 장치 추가/제거 이벤트는 `deviceConnectObserver`/`deviceDisconnectObserver`에서 정상 처리
- ✅ UI 사용자 경험 개선

---

## 25.10.31

### macOS Helper 샘플레이트 16kHz로 변경 및 자동 리샘플링 구현

#### 변경 사항
- **샘플레이트 기본값 변경**: 48kHz → 16kHz
  - `runtimeSampleRate` 기본값 변경 (AudioHelperController.swift:40)
  - `start` 명령 기본값 변경 (AudioHelperController.swift:213)
- **자동 리샘플링 구현**:
  - SCStream (시스템 오디오): 실제 샘플레이트 감지 후 16kHz로 자동 변환
  - AVCaptureSession (마이크): 실제 샘플레이트 감지 후 16kHz로 자동 변환
  - 선형 보간 방식 사용 (Windows Helper와 동일)
- **리샘플링 유틸리티 함수 추가**:
  - `resampleLinear(_:from:to:)`: 선형 보간 리샘플링
  - `extractSampleRate(from:)`: AudioStreamBasicDescription에서 실제 샘플레이트 추출

#### 기술적 세부사항
- **리샘플링 위치**:
  - `stream(_:didOutputSampleBuffer:of:)`: SCStream 콜백 (line 700-715)
  - `captureOutput(_:didOutput:from:)`: AVCaptureSession 콜백 (line 813-828)
- **실제 동작**:
  - macOS는 대부분 48kHz로 오디오를 캡처 (시스템 기본값)
  - Helper 내부에서 자동으로 16kHz로 다운샘플링
  - 사용자에게는 투명하게 처리
- **디버그 로그**:
  - `debugRawEnabled=true` 시 리샘플링 정보 로그 출력
  - 입력/출력 샘플레이트 및 샘플 수 기록

#### 효과
- ✅ **파일 크기 감소**: 3분 세그먼트 5.76MB
- ✅ **네트워크 트래픽 67% 절감**: 서버 업로드 부담 감소
- ✅ **STT 최적화**: Google/AWS/Azure STT 엔진 권장 샘플레이트
- ✅ **Windows Helper와 동일**: 플랫폼 간 일관성 확보
- ✅ **CPU/메모리 효율 향상**: 처리할 데이터 양 감소

#### 음질 영향
- **주파수 범위**: 24kHz → 8kHz (나이퀴스트 정리)
- **음성 인식**: 충분 (인간 음성 주요 대역 300Hz-3.5kHz)
- **음악/고음질**: 열화 있음 (하지만 STT 용도로는 문제없음)

#### 호환성
- ✅ WebRTC AEC: 16kHz 완벽 지원 (Windows Helper에서 검증됨)
- ✅ 기존 파일: 독립적이므로 호환성 문제 없음
- ✅ 메타데이터: 샘플레이트 정보 포함

#### 문서 업데이트
- `DEVELOP_STATUS.md`: 입력 파이프라인 섹션 업데이트 (line 64-68)
- `CHANGELOG.md`: 이 항목 추가

#### 테스트 체크리스트
- [ ] 녹음 후 파일 재생 (속도/피치 정상 확인)
- [x] 파일 크기 확인 (3분 ≈ 5.76MB)
- [ ] 디버그 로그 확인 (리샘플링 48kHz→16kHz)
- [ ] STT 엔진 테스트 (정상 인식 확인)

---

## 25.10.30

### start_test 명령에 reuse 필드 추가 (C++ Helper 동기화)
- **macOS Helper: 캡처 재사용 로직 완전 구현**
  - **배경**:
    - C++ Helper는 `isRunning && !isRecording` 조건에서 캡처를 재사용
    - Swift Helper는 Event 모델에만 `reuse` 파라미터가 있고 로직은 불완전
  - **문제점**:
    - 녹음 중에도 재사용 시도 가능 (데이터 손실 위험)
    - `currentTestMode`만 추적 (녹음→테스트 전환 시 모드 불일치)
    - 마이크 ID 관리 단일 변수 (UI 의도와 런타임 분리 불가)
  - **구현 내용**:
    1. 상태 변수 추가:
       - `currentMode`: 전역 모드 추적 (MicPlusSystem/MicOnly/SystemOnly)
       - `selectedMicId`: UI가 선택한 영구 마이크 ID
       - `sessionMicId`: 현재 세션에서 사용 중인 마이크 ID
       - `isRunning`: 캡처 실행 여부 (computed property)
    2. `startTest` 재사용 로직:
       - 조건: `isRunning && !isRecording && sameMic && sameMode`
       - 재사용 성공: `isPaused=false`, `reuse:true` 전송
       - 재사용 실패: 기존 캡처 정리 후 재초기화, `reuse:false` 전송
    3. `start` 함수 모드 추적:
       - `currentMode` 설정 (현재 MicPlusSystem 고정)
       - `sessionMicId` 설정
    4. 레벨미터 연계:
       - `ensureCaptureForLevelMeter(mode:)` 파라미터 추가
       - `currentMode` 사용하여 레벨미터→테스트 재사용 가능
  - **효과**:
    - ✅ 녹음 중 재사용 시도 방지 (TEST_BUSY 거부)
    - ✅ 레벨미터→테스트 전환 시 재사용 (초기화 생략)
    - ✅ 모드/마이크 변경 시 재초기화 (명시적 로직)
    - ✅ UI 최적화: `reuse=true` 수신 시 타이머/파형 초기화 생략
  - **테스트 시나리오**:
    - 시나리오 1: 레벨미터 ON → 테스트 시작 → `reuse:true` ✅
    - 시나리오 2: 테스트(MicOnly) → 테스트(MicPlusSystem) → `reuse:false` (모드 변경) ✅
    - 시나리오 3: 녹음 중 → 테스트 시도 → `TEST_BUSY` 거부 ✅
  - **변경 파일**:
    - `AudioHelperController.swift`:
      - 상태 변수 추가 (라인 25-27, 83-85)
      - `startTest` 재사용 로직 개선 (라인 815-919)
      - `start` 모드 추적 (라인 401-404)
      - `set_level_meter` currentMode 사용 (라인 298-299)
      - `ensureCaptureForLevelMeter` mode 파라미터 (라인 1219-1222)
      - `stop`, `stopTest` currentMode 전달 (라인 578, 942)
  - **문서 참조**:
    - `electron_helper_interface.md` 217-270줄: reuse 파라미터 명세
    - C++ Helper `AudioHelper.cpp` 1283-1296줄: 재사용 로직 원본

### 장치 Observer를 Helper 시작 시 등록 (테스트/대기 중에도 감지)
- **macOS Helper: 장치 변경 감지를 프로세스 시작 시 활성화**
  - **문제**: 
    - 테스트 모드에서 장치 변경 감지 안됨 (observer 미등록)
    - `audio_device_change` 이벤트가 녹음 중에만 발생
  - **수정 내용**:
    - `AudioHelper.swift` (main)에서 Helper 시작 시 `startDeviceObservers()` 호출
    - 중복 등록 방지 로직 추가
    - `start()` 함수에서 중복 호출 제거
    - `stop()` 함수에서 observer 해제 제거 (프로세스 종료까지 유지)
  - **효과**:
    - ✅ 테스트 중: 장치 변경 감지
    - ✅ 대기 중: 장치 변경 감지
    - ✅ 녹음 중: 장치 변경 감지 (기존 동작 유지)
    - ✅ Helper 프로세스가 살아있는 동안 항상 감지
  - **변경 파일**:
    - `AudioHelper.swift`: Helper 시작 시 observer 등록 (라인 30-32)
    - `AudioHelperController.swift`: 
      - `startDeviceObservers()` 중복 방지 추가 (라인 991-995)
      - `start()` 중복 호출 제거 (라인 481)
      - `stop()` observer 해제 제거 (라인 541)

### 장치 변경 알림 기능 추가 (audio_device_change)
- **macOS Helper: 장치 추가/제거 시 이벤트 전송**
  - **추가 기능**:
    1. 새로운 `audio_device_change` 이벤트 타입 추가
    2. 장치 제거 시 `MIC_DEVICE_LOST` 녹음 여부 무관하게 전송
    3. 장치 추가 시 `audio_device_change(added)` 전송
  - **필요성**:
    - Main Process가 장치 변경 사실을 인지해야 함
    - UI가 장치 목록을 자동으로 갱신할 수 있어야 함
    - 테스트/대기 중 장치 제거도 감지 필요
  - **이벤트 형식**:
    ```json
    {
      "ev": "audio_device_change",
      "change_type": "added|removed",
      "device_type": "audio"
    }
    ```
  - **동작 시나리오**:
    - **장치 제거**: MIC_DEVICE_LOST → audio_device_change(removed) → (녹음중이면) stop()
    - **장치 추가**: audio_device_change(added)
  - **UI 처리 권장**:
    - `audio_device_change` 이벤트 수신 시 `list_devices` 명령으로 장치 목록 갱신
  - **변경 파일**:
    - `JSONModels.swift`: Event enum에 audioDeviceChange 케이스 추가
    - `AudioHelperController.swift`: 장치 observer 수정 (라인 990-1024)
    - `electron_helper_interface.md`: audio_device_change 이벤트 명세 추가
  - **호환성**:
    - 하위 호환: UI가 새 이벤트를 무시하면 기존 동작 유지
    - 상위 호환: UI가 새 이벤트를 처리하면 장치 목록 자동 갱신

### MIC_DEVICE_LOST 오류 발생 시 녹음 즉시 중지
- **macOS Helper: 마이크 장치 분리 시 재연결 시도 없이 즉시 녹음 중지**
  - **문제**: 
    - MIC_DEVICE_LOST 오류 발생 시 재연결 시도 (최대 10초)
    - 재연결 시도 중에도 녹음이 계속되어 무음 또는 시스템 사운드만 녹음됨
    - Windows Helper와 동작이 달라 일관성 부족
  - **원인**:
    - `wasDisconnectedNotification` 핸들러에서 `beginReconnect()` 호출
    - 재연결 5회 실패 후에야 녹음 중지
    - 사용자가 물리적으로 장치를 제거한 경우 재연결이 불가능
  - **수정 내용**:
    - `wasDisconnectedNotification` 핸들러에서 녹음 중(`isRecording=true`)이면 즉시 `stop()` 호출
    - `beginReconnect()`, `tryReconnectNow()` 함수 제거
    - `wasConnectedNotification` 핸들러는 로그만 남김
  - **효과**:
    - ✅ MIC_DEVICE_LOST 오류 전송 즉시 녹음 중지
    - ✅ 무음/부분 녹음 파일 생성 방지
    - ✅ Windows Helper와 동작 일관성 확보
    - ✅ 사용자에게 명확한 오류 상태 전달
  - **변경 파일**:
    - `AudioHelperController.swift`: `startDeviceObservers()` 함수 수정 (라인 990-1027)
  - **참고**:
    - 시스템 오디오는 재연결 가능하므로 `SCStreamDelegate`의 재연결 로직은 유지
    - 마이크는 사용자가 물리적으로 제거하는 경우가 많아 재연결 불필요

## 25.10.29

### Xcode 프로젝트 설정 수정 - 마이크 권한 Info.plist 키 추가
- **macOS Helper: Xcode 빌드 설정에 마이크 권한 키 추가**
  - **문제**: 빌드된 앱 실행 시 마이크 권한 팝업이 표시되지 않고 `MIC_PERMISSION_DENIED` 오류 발생
  - **원인**:
    - Xcode 프로젝트가 `GENERATE_INFOPLIST_FILE = YES` 설정으로 Info.plist를 자동 생성
    - 별도 `AudioHelper/Info.plist` 파일은 Resources 폴더로만 복사됨
    - 빌드된 앱의 메인 `Info.plist`에 `NSMicrophoneUsageDescription` 키가 없음
    - macOS는 이 키가 없으면 권한 팝업을 표시하지 않고 즉시 거부함
  - **수정 내용**:
    - `project.pbxproj`의 Debug/Release 빌드 설정에 다음 키 추가:
      - `INFOPLIST_KEY_NSMicrophoneUsageDescription` = "마이크 소리를 녹음하기 위해 권한이 필요합니다."
      - `INFOPLIST_KEY_LSBackgroundOnly` = YES
      - `INFOPLIST_KEY_LSUIElement` = YES
    - 빌드 후 DerivedData에서 새 앱을 실행 위치로 복사
    - `tccutil reset Microphone timbel.AudioHelper`로 권한 상태 초기화
  - **효과**:
    - ✅ 앱 실행 시 macOS가 마이크 권한 팝업 자동 표시
    - ✅ 사용자가 권한 허용 시 마이크 캡처 정상 동작
    - ✅ 레벨 미터가 정상적으로 표시됨
    - ✅ 화면 녹음과 마이크 권한이 모두 제대로 요청됨
  - **변경 파일**:
    - `AudioHelper.xcodeproj/project.pbxproj`: 빌드 설정 수정 (라인 273-278, 308-313)
  - **참고**:
    - ScreenCaptureKit은 시스템이 자동으로 권한 팝업 표시
    - 마이크는 반드시 Info.plist에 Usage Description이 있어야 팝업 표시됨

## 25.10.29

### test_start 시 마이크/시스템 level meter 독립 타이머 적용
- **macOS Helper: 마이크와 시스템 오디오 level 이벤트 타이머 분리**
  - **문제**: 마이크와 시스템 오디오가 하나의 타이머(`lastLevelEmitMs`)를 공유하여 한쪽만 전송됨
  - **원인**: 
    - 시스템 오디오 콜백이 먼저 타이머를 업데이트하면 (예: 0ms)
    - 마이크 콜백이 5ms 후 호출되어도 `5ms < 100ms` 조건으로 차단됨
    - 결과적으로 시스템 오디오만 100ms마다 전송되고 마이크는 거의 전송 안됨
  - **수정 내용**:
    - `lastLevelEmitMs` → `lastMicLevelEmitMs` + `lastSysLevelEmitMs`로 분리
    - `emitLevelIfDue` 함수에서 소스별로 독립적인 타이머 사용
    - 음소거 처리 부분도 각각의 타이머 사용
  - **효과**:
    - ✅ 마이크: 100ms마다 독립적으로 전송
    - ✅ 시스템: 100ms마다 독립적으로 전송
    - ✅ 두 소스가 서로 간섭하지 않음
    - ✅ test 모드에서 마이크 레벨바가 정상적으로 움직임
  - **변경 파일**:
    - `AudioHelperController.swift`: 타이머 변수 분리 (라인 25-26)
    - `emitLevelIfDue` 함수 수정 (라인 1164-1194)
    - 음소거 처리 수정 (라인 630, 726)

### test_start 시 마이크 권한 처리 및 level meter 문제 수정
- **macOS Helper: 마이크 권한 명시적 요청 추가**
  - **문제**: 처음 test_start 시 마이크 권한이 "Not Determined" 상태에서 콜백이 오지 않음
  - **원인**: 
    - `AVCaptureDeviceInput` 생성 시 권한 다이얼로그가 표시되지만 비동기적
    - `session.startRunning()`이 권한 허용 전에 실행되어 콜백이 발생하지 않음
    - 녹음 후 테스트에서는 이미 권한이 부여되어 정상 작동
  - **수정 내용**:
    - `startMicCaptureSession`을 `async` 함수로 변경
    - 권한 상태 명시적 확인 (`AVCaptureDevice.authorizationStatus`)
    - `notDetermined` 상태일 때 `requestAccess` 호출 후 `await`로 대기
    - 권한 허용 후에만 세션 시작하여 콜백 보장
    - 권한 거부 시 `MIC_PERMISSION_DENIED` 에러 전송
  - **효과**:
    - ✅ 처음 test_start 시에도 마이크 권한 다이얼로그 표시 후 정상 작동
    - ✅ 권한 허용 전까지 대기하여 콜백 누락 방지
    - ✅ 권한 거부 시 명확한 에러 메시지
  - **변경 파일**:
    - `AudioHelperController.swift`: `startMicCaptureSession` 함수 수정 (라인 905-987)
    - 호출부에 `await` 추가 (라인 479, 820, 1232)

### test_start 이후 level meter 이벤트 전송 문제 수정
- **macOS Helper: Windows와 동작 정렬**
  - **문제**: test_start 이후 Windows에서는 level meter 정보가 전송되지만 macOS에서는 전송되지 않음
  - **원인**: `emitLevelIfDue` 함수에서 `levelMeterEnabled` 체크로 인해 이벤트 자체가 전송되지 않음
  - **수정 내용**:
    - `emitLevelIfDue`: `levelMeterEnabled` guard 체크 제거
    - 대신 `levelMeterEnabled`에 따라 RMS 값 조절 (`effectiveRms`)
    - levelMeterEnabled=true: 실제 RMS 전송
    - levelMeterEnabled=false: 0 RMS 전송
    - 음소거 상태(mute)에서도 일관되게 level 이벤트 전송
  - **효과**:
    - ✅ test_start 시 macOS에서도 UI 레벨 미터가 정상 표시됨
    - ✅ Windows와 동작 완전 정렬
    - ✅ 사용자가 오디오 입력을 시각적으로 확인 가능
  - **변경 파일**:
    - `AudioHelperController.swift`: `emitLevelIfDue` 함수 수정 (라인 1137-1156)
    - 시스템 음소거 처리 수정 (라인 626-640)
    - 마이크 음소거 처리 수정 (라인 723-736)

## 25.10.28

### Bundle에서 버전 정보 동적 읽기
- **macOS Helper: 버전 관리 개선**
  - Xcode 프로젝트 설정으로 버전 통일
    - `MARKETING_VERSION`: `1.0` → `0.1.0`
    - `CURRENT_PROJECT_VERSION`: `1` 유지
  - Bundle.main.infoDictionary에서 버전 동적 읽기
    - `CFBundleShortVersionString`: 짧은 버전 (0.1.0)
    - `CFBundleVersion`: 빌드 번호 (1)
    - `version_full`: "0.1.0.1" 형식으로 자동 생성
  - 빌드 날짜/시간 동적 생성
    - 하드코딩된 날짜 대신 실행 시점 기준으로 생성
    - DateFormatter로 표준 형식 사용
  - 개선 효과:
    - ✅ 단일 진실 공급원 (Xcode 프로젝트 설정만 수정)
    - ✅ 코드 수정 없이 버전 업데이트 가능
    - ✅ CI/CD에서 빌드 번호 자동 증가 가능
    - ✅ 3곳에 하드코딩된 버전을 1곳으로 통합

### unreachable catch 블록 제거 및 정리
- **코드 품질 개선: 도달 불가능한 예외 처리 제거**
  - `SET_DEBUG_FILES_ERROR`: do-catch 블록 제거
    - FileLogger.setLevel()은 non-throwing 함수
    - 실제로 에러가 발생하지 않아 catch 블록 unreachable
    - 주석으로 명세 존재 명시
  - `ENUMERATOR_FAILED`: do-catch 블록 제거
    - AVCaptureDevice.DiscoverySession은 throwing initializer가 아님
    - 장치 열거 실패 시 빈 배열 반환, 에러 throw 안 함
    - 주석으로 명세 존재 및 macOS 동작 방식 명시
  - 개선 사항:
    - 컴파일러 경고 해결 (unreachable code)
    - 코드 의도 명확화
    - 명세 일관성은 주석으로 유지
    - Windows Helper와의 플랫폼 차이 문서화

### 명령 처리 오류 예외처리 추가
- **macOS Helper: 명령 처리 오류 예외처리 구현 완료**
  - `BAD_PARAM`: 잘못된 파라미터 검증 추가
    - `start` 명령: sampleRate 검증 (8000-96000Hz 범위)
    - `start` 명령: channels 검증 (1 또는 2만 지원)
    - `start_test` 명령: mode 검증 (MicPlusSystem, MicOnly, SystemOnly)
    - 잘못된 값 입력 시 명확한 에러 메시지와 허용 범위 안내
  - `NOT_IMPLEMENTED`: 미구현 기능 처리 가이드 추가
    - 향후 WebRTC AEC, Noise Suppression, Gain Control 등을 위한 주석 가이드
    - 미래 확장성을 위한 에러 코드 준비
  - `JSON_PARSE_ERROR`: 이미 구현됨 (확인)
    - AudioHelper.swift에서 stdin JSON 파싱 실패 시 전송
  - `UNKNOWN_COMMAND`: 이미 구현됨 (확인)
    - switch default case에서 알 수 없는 명령 처리
  - `COMMAND_ERROR`: 이미 구현됨 (확인)
    - AVCaptureSession 런타임 에러 처리에 사용 중
  - 구현 특징:
    - guard 문으로 파라미터 검증 및 early return
    - 각 검증 실패 시 FileLogger로 상세 로깅
    - 사용자에게 허용 범위와 함께 명확한 에러 메시지 제공

### 설정 관련 오류 예외처리 추가
- **macOS Helper: 설정 관련 오류 예외처리 구현 완료**
  - `GET_VERSION_ERROR`: 버전 정보 조회 오류 처리
    - postEvent 실패 시 에러 전송 (드묾)
  - `SET_OUTPUT_DIR_ERROR`: 출력 디렉터리 설정 오류 처리
    - 경로 누락 시 명확한 에러 메시지
    - 디렉터리 생성 권한 오류 처리
    - Bundle 내부 경로 거부 처리
    - 읽기 전용 파일시스템 등 쓰기 불가 처리
  - `SET_DEBUG_FILES_ERROR`: 디버그 파일 설정 오류 처리
    - FileLogger.setLevel() 실패 시 에러 전송
  - `SET_SEGMENT_CONFIG_ERROR`: 세그먼트 설정 오류 처리
    - currentDiskStatus() 실패 시 에러 전송
    - 파라미터 검증 및 에러 처리
  - `SET_MUTE_ERROR`: 음소거 설정 오류 처리
    - 빈 target 값 검증 및 에러 전송
    - 잘못된 target 값 세분화 처리 (기존 error → errorCode)
    - if-else에서 switch 문으로 개선
  - `SET_LEVEL_METER_ERROR`: 레벨미터 설정 오류 처리
    - ensureCaptureForLevelMeter() 실패 처리
    - stopCaptureOnly() 실패 처리
  - 구현 특징:
    - 모든 설정 명령에 do-catch 블록 추가
    - 기존 postEvent(.error(...))를 postEvent(.errorCode(...))로 통일
    - 각 명령 성공 시 FileLogger로 상세 로깅
    - 모든 에러는 electron_helper_interface.md 명세 준수

### 파일 및 디스크 오류 예외처리 추가
- **macOS Helper: 파일 및 디스크 오류 예외처리 구현 완료**
  - `SEGMENT_SAVE_FAILED`: 세그먼트 저장 실패 처리
    - SegmentManager의 saveSegment()에서 일반적인 파일 쓰기 오류 처리
    - 암호화/평문 파일 모두 세분화된 오류 처리
  - `ENCRYPT_FAILED`: 암호화 실패 처리
    - AES 암호화 과정 실패 시 감지
    - 생성된 파일이 있다면 즉시 삭제 (보안)
    - 키/IV 인코딩 실패, AES 객체 생성 실패 등 모든 암호화 오류 포착
  - `DISK_WRITE_OPEN_FAILED`: 파일 열기/쓰기 권한 오류
    - CocoaError.fileWriteNoPermission 감지
    - CocoaError.fileNoSuchFile 감지
    - 디렉토리 접근 권한, 읽기 전용 파일시스템 등 처리
  - `DISK_SPACE_LOW_STOP`: 디스크 부족 시 자동 중지
    - startDiskPolling() 타이머에서 critical 상태 감지
    - 디스크 여유 공간 <50MB 시 자동으로 녹음 중지
    - Main Actor 컨텍스트에서 안전하게 stop() 호출
    - 현재 세그먼트 자동 저장 (finalizeCurrentSegment)
    - CocoaError.fileWriteOutOfSpace도 별도 처리
  - 구현 특징:
    - 암호화/평문 파일 저장 경로 각각 세분화된 오류 처리
    - 중첩 do-catch로 오류 타입별 정확한 분류
    - 모든 에러는 electron_helper_interface.md 명세 준수
    - FileLogger를 통한 상세한 디버그 정보 기록

### 초기화 및 시스템 오류 예외처리 추가
- **macOS Helper: 초기화 및 시스템 오류 예외처리 구현 완료**
  - `ENUMERATOR_FAILED`: 장치 열거자 초기화 실패
    - `listAudioDevices()` 함수에서 `AVCaptureDevice.DiscoverySession` 생성 실패 시 에러 전송
    - 시스템 권한 거부 또는 오디오 서브시스템 접근 불가 상황 처리
  - `MIC_INIT_FAILED`: 마이크 초기화 실패
    - `startMicCaptureSession()` 함수에서 단계별 실패 감지 및 에러 전송
    - 장치 찾기 실패, 입력 생성 실패, 세션 추가 실패 각각 처리
    - `start()`, `startTest()`, `ensureCaptureForLevelMeter()` 호출부에서 catch 처리
  - `SYS_INIT_FAILED`: 시스템 오디오 초기화 실패
    - `SCShareableContent` 가져오기 실패 처리
    - 디스플레이 없음 상황 처리
    - `addStreamOutput()` 실패 처리
    - `startCapture()` 실패 처리
    - 3개 함수에서 구현: `start()`, `startTest()`, `ensureCaptureForLevelMeter()`
  - `START_TEST_ERROR`: 테스트 시작 실패
    - 기존 "test_start_failed" 에러를 표준 에러 코드로 교체
    - 하위 에러(MIC_INIT_FAILED, SYS_INIT_FAILED)는 각각 세분화하여 전송
  - 구현 특징:
    - 모든 에러는 `electron_helper_interface.md` 명세에 따라 구현
    - 각 에러 발생 시 한글 메시지와 함께 사용자에게 명확하게 전달
    - FileLogger를 통해 상세한 디버그 정보 기록
    - 복구 불가능한 에러는 작업 중단, 명확한 에러 이벤트 전송

## 이전 변경 사항 (25.10.28)

- **macOS Helper: 3분 버퍼링 방식 도입으로 디스크 I/O 99.98% 감소**
  - 아키텍처: Windows Helper와 동일한 세그먼트 버퍼링 방식 채택
  - 변경 전: 43ms마다 디스크 쓰기 (3분에 4,167회)
  - 변경 후: 3분치 데이터를 메모리에 버퍼링 후 1회 쓰기
  - 구현:
    - `SegmentManager` 클래스 신규 추가 (Windows Helper 로직 이식)
    - `tryMixWrite()` → `tryMixAndBuffer()`로 변경
    - 파일 핸들 직접 제어 제거, 버퍼 기반 관리로 전환
  - 성능 개선:
    - 디스크 I/O: **99.98% 감소** (3분에 4,167회 → 1회)
    - 메모리 사용: 8.64MB 증가 (48kHz mono 3분 버퍼)
    - CPU 사용률: 예상 20-30% 감소
    - 배터리 수명 및 SSD 수명 개선
  - 호환성: 기존 기능 모두 유지 (pause/resume/stop/암호화)
- **macOS Helper: test 모드 버퍼 누수 수정**
  - 문제: test 모드 종료 후 녹음 시작 시 버퍼가 클리어되지 않아, 녹음 파일 앞부분에 test 모드 데이터가 포함됨
  - 원인: `stopTest()` 함수에서 버퍼 초기화 누락
  - 결과: `seconds`와 `mic_seconds` 시간 차이 발생 (약 10초)
  - 해결:
    - `stopTest()`: test 모드 종료 시 `sysBufferF32`, `micBufferF32` 버퍼 완전 클리어
    - `start()`: 녹음 시작 전 버퍼 완전 초기화 (안전장치)
    - `audioQueue.sync` 사용으로 race condition 방지
  - 효과: 녹음 파일 데이터 무결성 보장, progress 이벤트 시간 동기화
- **macOS Helper: AES-256-CBC 암호화 구현 완료**
  - CryptoSwift 1.9 라이브러리 사용
  - Windows Helper와 동일한 키/IV 사용 (플랫폼 간 호환)
  - 파일 확장자 정책:
    - `encryption_enabled=true`: `.pcm` (암호화됨)
    - `encryption_enabled=false`: `.raw` (평문 PCM)
  - 세그먼트 완료 시 암호화 적용 (read → encrypt → overwrite)
  - 암호화 실패 시 `ENCRYPT_FAILED` 에러 + 파일 자동 삭제
  - `segment_ready` 이벤트에 `encrypted` 플래그 포함
- **macOS Helper: 모노 믹싱으로 변경**
  - 스테레오(L=시스템, R=마이크) → 모노(평균 믹싱)
  - 파일 크기 절반으로 감소 (3분 세그먼트: 5.76MB → 2.88MB)
  - `runtimeChannels` 강제 1채널 고정
  - Python 복호화 스크립트는 모노(channels=1) 기본값 유지
- 문서: 오류 코드 목록 업데이트 (electron_helper_interface.md, swift_helper_checklist.md)
  - Windows Helper 실제 구현 기준으로 오류 코드 정렬
  - 추가된 오류 코드 (11개):
    - `ENCRYPT_FAILED`: 암호화 실패로 세그먼트 저장 불가
    - `START_TEST_ERROR`: 테스트 시작 실패
    - `DISK_SPACE_LOW_STOP`: 디스크 여유 공간 부족으로 안전 중지
    - `BAD_PARAM`: 잘못된 파라미터
    - `NOT_IMPLEMENTED`: 미구현 기능 호출
    - `GET_VERSION_ERROR`: 버전 정보 조회 오류
    - `SET_OUTPUT_DIR_ERROR`: 출력 디렉터리 설정 오류
    - `SET_DEBUG_FILES_ERROR`: 디버그 파일 설정 오류
    - `SET_SEGMENT_CONFIG_ERROR`: 세그먼트 설정 오류
    - `SET_MUTE_ERROR`: 음소거 설정 오류
    - `SET_LEVEL_METER_ERROR`: 레벨미터 설정 오류
  - 수정된 설명: `MIC_INIT_FAILED` (장치 열거자 초기화 실패 → 마이크 초기화 실패)
  - 카테고리별 그룹화: 초기화/장치/파일·디스크/명령 처리/설정 관련 오류
  - 플랫폼별 표기 추가: `COM_INIT_FAILED`(Windows 전용), `MIC_DEVICE_LOST`(macOS 전용)
- macOS Helper: FileLogger 추가(JSON Lines) 및 OSLog 연동
  - 크기 기반 롤링(파일당 5MB, 최대 5개), Application Support 하위 경로
  - `set_debug_files`에 따라 동적 로그 레벨(debug/info)
  - 주요 명령/시작·중지/세그먼트/에러 로깅 연동
- macOS Helper: 진행(progress) 동기화 수정 — pause 중 `mic_seconds` 증가 중단으로 `seconds`와 불일치 문제 해결
 - macOS Helper: 장치 에러/이벤트 정비
   - 에러 전송 통일: 코드형 에러를 `{ ev:'error', code, message }`로 전송 (`UNKNOWN_COMMAND`, `JSON_PARSE_ERROR`, `MIC_DEVICE_LOST`, `DEVICE_RECONNECT_FAILED` 등)
   - `device_reconnected` 페이로드 변경: `{ type: 'system'|'mic', aec_reset }` (mac은 `aec_reset:false`)
   - `mic_state` 이벤트 추가: `{ ev:'mic_state', state:'available'|'unavailable' }`
   - 사전 가드: `start`, `start_test`, `set_level_meter(enabled=true)`에서 선택 마이크 미가용 시 `NO_MIC_DEVICE` 에러와 `mic_state:'unavailable'` 전송
   - 마이크 재연결 실패 시 기본장치 폴백 제거(보호 중단)
 - macOS Helper: 무음 감지 정책 C++ 정렬
   - off 전송 시 감지 비활성화(추가 off 방지), sustained 후에는 유음 감지 계속하여 off 1회 보장
   - mic/system RMS 결합(max)으로 무음 평가
 - macOS Helper: FileLogger 타임스탬프를 로컬 시스템 시간으로 변경 (UTC → 로컬 타임존)

## 25.10.27

- 진행(progress) 이벤트 추가
  - 스펙: `{ ev: 'progress', seconds, samples, mic_samples, mic_seconds }`
  - 전송 주기: 약 200ms(파일 기록 시점에서 스로틀)
  - 누적 기준: 세션 전체 기준(세그먼트 롤오버와 무관), pause 중 전송 안 함
  - 구현: 파일 쓰기 누적 프레임(`totalFramesWritten`), 마이크 누적 프레임(`totalMicFramesCaptured`) 집계
  - 렌더러: hh:mm:ss 포맷으로 표시
  - 페이로드 단순화: `emit_monotonic_ms`, `sample_rate` 제거하여 `{ ev, seconds, samples, mic_samples, mic_seconds }`로 통일

### macOS Helper: 명령 시퀀스 및 이벤트 정렬

- 녹음 시작 시퀀스 지원: `set_output_dir → set_debug_files → set_segment_config → start`
- JSON 모델 확장
  - Command: `directory`, `enabled`, `encryption_enabled`, `segment_seconds`
  - Event: `output_dir_set`, `debug_files_set`, `segment_config_set`, `recording_started`, `recording_stopped`, `version_info`, `level_meter_state`, `mute_state`, `test_started`, `test_stopped`
- 이벤트 페이로드 정렬
  - `device_reconnected`: 키를 `type`으로 통일
  - `recording_stopped`: `{ ev, totalSamples, micSamplesWritten, sysSamplesWritten }`
- start 동작 변경
  - `outputDir` 미지정 시: `set_output_dir`로 받은 base 디렉터리 하위에 `{sessionId}` 폴더 생성
  - 파일 확장자 결정: `encryption_enabled=true ⇒ .pcm`, `false ⇒ .wav` (암호화 미적용, 추후 .pcm에 암호화만 추가 예정)
- 세그먼트 길이: 3분 고정 유지 (설정값 수신은 하되 적용 보류)
 
### macOS Helper: 레벨미터(level_meter_state) 구현

- 명령: `set_level_meter { enabled: "true"|"false" }`
- 이벤트: `{ ev: 'level_meter_state', enabled }`
- 동작:
  - enabled=true: 캡쳐 파이프라인 보장(파일 기록 없이), pause 중에도 `level` 이벤트 지속 전송
  - enabled=false: 0 RMS 1회 전송 후, 레벨미터로 시작한 캡쳐는 중지
- 레벨 이벤트: `{ ev: 'level', source: 'mic'|'system', rms, t }`를 ~100ms 주기로 전송
- 진행(progress) 및 파일 기록은 isRecording=true일 때만 수행(기존 정책 유지)

### macOS Helper: Pause 동작 개선(세그먼트 시간 동결)

- 일시정지 시 세그먼트 시간 동결 구현
  - pause에서 내부 버퍼(`sysBufferF32`, `micBufferF32`)를 비우고, 진행 이벤트를 중단
  - tryMixWrite에서 pause 중 즉시 return하여 파일 쓰기 및 세그먼트 롤오버 차단
  - 캡처 콜백(system/mic)에서 pause 시 레벨미터만 유지하고 버퍼 append 금지
  - 결과: pause 중에는 세그먼트 길이/인덱스가 증가하지 않으며, resume 시 같은 세그먼트를 이어서 기록
  - 레벨미터가 켜진 경우에도 파일 기록은 중단되므로 세그먼트 롤오버 발생하지 않음

### macOS Helper: Test 모드(start_test/stop_test)

- `start_test` / `stop_test` 구현 (파일 기록 없음)
  - 녹음 중(`isRecording=true`)에는 `start_test`를 거부하고 에러 이벤트 전송(`TEST_BUSY`)
  - 재사용 정책: 캡처 활성 + 모드/마이크 동일 시 `reuse=true`
  - 신규 테스트 시작 시 캡처 파이프라인만 구성, `isRecording=false` 유지로 `tryMixWrite()` 호출 차단
  - `stop_test`는 테스트로 시작된 캡처만 안전 종료, 항상 `test_stopped` 전송

### macOS Helper: 음소거(set_mute)

- 명령: `set_mute { target: "mic|system|both", value: "true|false|on|off" }`
- 이벤트: `{ ev: 'mute_state', mic, system }`
- 동작:
  - 레벨미터: 음소거된 소스는 0 RMS로 전송
  - 파일 기록: 음소거된 채널은 0으로 기록(L=system, R=mic)
  - 테스트/녹음 모드 모두 지원

### macOS Helper: 레벨미터 지속 동작

- 녹음 중지(`stop`) 또는 테스트 중지(`stop_test`) 이후에도 `set_level_meter.enabled=true`라면 캡처를 재보장하여 `level` 이벤트 수신이 지속되도록 변경

### macOS Helper: 기타 업데이트

- 시작 시 `helper_info` 1회 전송: `{ ev: 'helper_info', utf8, version, webrtc_aec, build_date }`
- stdin NDJSON 파서 보강: 개행 단위 버퍼링 파싱으로 연속 명령 묶음 수신 시 `invalid_json` 이슈 해결
 - Electron 렌더러 호환성
   - start: `{ sessionId?, out:{sr,ch}?, sampleRate?, channels?, mic|micDeviceId }` 지원
   - get_version: `version_info` 이벤트 추가
   - set_level_meter/mute/start_test/stop_test: 이벤트 에코 구현(후속 확장 예정)

### macOS Helper: 디스크 상태(disk_status) 구현

- 이벤트: `{ ev: 'disk_status', status: 'ok|low|critical', free_bytes }`
- 폴링 정책: 녹음 중 1s 평가, 상태 변경 즉시 전송, 동일 상태는 5s마다 1회 재전송
- 트리거:
  - `set_output_dir` 직후 1회 `disk_status` 전송
  - `set_segment_config` 응답에 `status`, `free_bytes` 포함
  - `start` 직전 여유 공간이 50MB 미만이면 시작 거부: `{ ev:'error', code:'DISK_SPACE_CRITICAL', message:'디스크 여유 공간이 50MB 미만이어서 녹음을 시작할 수 없습니다.' }`
- 임계값: ok(≥500MB), low(≥50MB), critical(<50MB)
- 구현 세부:
  - 용량 조회: `URLResourceValues.volumeAvailableCapacityForImportantUsage` 1순위, 폴백으로 `FileManager.attributesOfFileSystem(.systemFreeSize)`
  - 상태머신: `lastDiskStatus`, `lastDiskEmitMs` 유지, `DispatchSourceTimer`로 전역 큐에서 폴링

### macOS Helper: 무음 감지(silence) 구현

- 이벤트: `{ ev: 'silence', state: 'early'|'off'|'sustained', elapsedMs }`
- 임계치: RMS < 0.02이면 무음으로 간주
- 전송 정책(녹음 중에만 평가):
  - early: 7/14/21/28초 각 1회 전송
  - sustained: 30초 1회 전송
  - off: 소리(임계치 이상) 감지 즉시 전송
- 일시정지: pause 동안 시간 누적 정지, resume 후 이어서 평가

## 25.10.24
마이크+시스템 오디오 스테레오 무손실 저장 구현 및 관련 개선

1. 핵심 기능
  - mic + system 오디오 동시 캡처 및 스테레오 믹싱(L=system, R=mic)
  - 무손실 파일 출력: WAV(.wav), RAW PCM(.pcm, S16LE)
  - 스트리밍 기록: 인터리브 S16LE로 즉시 기록, WAV는 종료 시 헤더 사이즈 패치

2. 캡처 파이프라인
  - 시스템 오디오: ScreenCaptureKit(SCStream) 사용, 스테레오 소스를 모노로 다운믹스(Float32)
  - 마이크: AVCaptureSession(장치 강제 바인딩) + AVCaptureAudioDataOutput, Float32 → 48kHz/mono 변환
  - 믹싱: 두 모노 스트림을 프레임 단위로 L/R 인터리브하여 파일로 기록

3. 파일 경로/출력 안정화
  - 경로 안전화: ~ 확장, 상위 폴더 자동 생성, 번들 내부 저장 방지, 기존 파일 선삭제
  - 기본 샘플레이트 48kHz, 2ch 스테레오 고정 출력

4. 버그 수정 및 정리
  - 마이크 탭 format mismatch 크래시 수정: installTap(format:nil) + AVAudioConverter 변환
  - AVAudioConverter 반환값 처리 수정: Bool→AVAudioConverterOutputStatus 비교로 변경
  - 명칭 통일: AudioHelpr → AudioHelper (클래스/익스텐션/로그 태그 포함)
  - Electron 로그 태그 정리 및 헬퍼 실행 경로 표기 정정
  - macOS 15 API 정리: builtInMicrophone→microphone, externalUnknown→external, 연결/해제/런타임 에러 노티 리네임 반영
 
 5. 권한/주의
  - 마이크/화면 기록 권한 필요. 설정에서 허용 후 헬퍼 재시작 필요

