# 변경 사항

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

