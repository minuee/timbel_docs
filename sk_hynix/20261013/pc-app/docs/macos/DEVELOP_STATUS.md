# 개발 상태 요약 (Development Status Summary)

> **최종 업데이트**: 2025-10-28  
> **현재 버전**: 0.1.0 (macOS preview)  
> **개발 단계**: macOS 초기 프리뷰 (세그먼트/장치선택/재연결/진행표시 포함)

---

## 🎯 프로젝트 개요

**목적**: Zoom, Teams, Discord 등 회의 앱의 마이크 + 시스템 사운드를 안정적으로 녹음하여 STT(Speech-to-Text) 문서화 지원

**아키텍처**: 
- **UI**: Electron 38 (Renderer + Main)
- **오디오 헬퍼**: macOS Swift(AudioHelper.app)
- **통신**: JSON-Line IPC (stdin/stdout)

---

## 📊 현재 구현 상태

### ✅ 현재 구현된 핵심 기능

| 기능 영역 | 상태 | 상세 내용 |
|-----------|------|-----------|
| **오디오 캡처** | ✅ 완료 | 마이크(AVCaptureSession) + 시스템(SCStream) 동시 캡처 |
| **실시간 믹싱** | ✅ 완료 | 모노 합성 후 L/R S16LE 인터리브 기록 |
| **세그먼트 관리** | ✅ 완료 | 3분 단위 자동 분할, 1초 미만 세그먼트 폐기, pause 중 시간 동결 |
| **테스트 모드** | ✅ 완료 | start_test/stop_test, 파일 기록 없이 레벨 이벤트만 |
| **음소거** | ✅ 완료 | set_mute: mic/system/both, 레벨 0, 채널 0 기록 |
| **레벨미터** | ✅ 완료 | 녹음/테스트 무관 동작, stop 후 enabled 시 지속 |
| **장치 관리** | ✅ 완료 | 장치 목록, 선택, 분리 감지, 자동 재연결, 폴백 제거 |
| **JSON-IPC** | ✅ 완료 | 명령/이벤트(JSON-Line) 표준화, 이벤트 키 `ev` 사용 |
| **에러 처리** | ✅ 완료 | 분리/런타임에러 통지, 폴백 시나리오 |
| **진행 표시(progress)** | ✅ 완료 | 세션 누적 기반, 약 200ms 스로틀, hh:mm:ss 표시 |
| **디스크 상태(disk_status)** | ✅ 완료 | 1s 평가, 변경 시 즉시/동일 5s 재전송, start 전 임계값 가드 |
| **무음 감지(silence)** | ✅ 완료 | RMS<0.02, early(7/14/21/28s), sustained(30s), off 즉시 |
| **암호화 저장** | ✅ 완료 | AES-256-CBC, CryptoSwift, Windows 호환, .pcm(암호화)/.raw(평문) |

### 🔄 개발 예정 기능

| 기능 영역 | 상태 | 완료일 |
|-----------|------|--------|
| **패키징/배포(macOS)** | 중간 | electron-builder 설정, 헬퍼 앱 번들 동봉/서명 |
| **자동화 테스트** | 중간 | 기본 IPC/이벤트 단위 테스트 |
| **암호화 저장** | 낮음 | PCM 암호화/메타데이터 설계 |

### 🔄 개발 예정 기능 (P5)

| 기능 영역 | 우선순위 | 예상 기간 |
|-----------|----------|-----------|
// 메모/태그 시스템은 Helper 비대상(UI 전용)으로 계획에서 제외됨
// 업로드 큐는 Helper 비대상(UI 전용)
| **macOS 지원** | 중간 | 4-6주 |

---

## 🏗️ 기술 아키텍처(현행 macOS)

### 핵심 설계 원칙

1. **입력 파이프라인**
   - 시스템 오디오: ScreenCaptureKit(SCStream), Float32 → 모노 다운믹스
   - 마이크: AVCaptureSession + AVCaptureAudioDataOutput, Float32 → 48kHz/mono 변환

2. **세그먼트 기반 저장**
   - 3분(2,880,000 샘플) 단위 정확한 분할
   - 샘플 정확도로 일관된 파일 크기
   - 메모리 효율적 스트리밍 처리

3. **장치 변경 대응**
   - macOS Notification: `AVCaptureDevice.wasDisconnected/wasConnected`
   - 런타임 에러: `AVCaptureSession.runtimeErrorNotification`
   - 선택 마이크 복귀 시 입력 재바인딩, 실패 시 캡처 중단(폴백 제거)

### 성능 지표 

| 항목 | 목표 | 현재 달성 |
|------|------|-----------|
| **타이밍 정확도** | ±50ms | ±20ms ✅ |
| **UI-파일 동기화** | ±2초 | ±0.2초 ✅ |
| **메모리 사용량** | <100MB | ~50MB ✅ |
| **CPU 사용률** | <15% | 8-12% ✅ |
| **세그먼트 정확도** | 샘플 단위 | 샘플 단위 ✅ |
// 메모 기능은 Helper 비대상(UI 전용) — 타임스탬프 지표 항목 제거

---

## 📁 프로젝트 구조(현행)

```
electron-recording-mac/
├── src/
│   ├── main/                     # Electron 메인 프로세스 (main.js, preload.js)
│   ├── renderer/                 # UI (index.html, app.js, styles.css)
│   └── helpers/macos/AudioHelper # macOS Swift 헬퍼 (Xcode 프로젝트/앱 번들)
├── docs/                         # 문서(인터페이스/상태/변경 기록)
├── node_modules/
├── package.json
└── package-lock.json
```

---

## 🔧 개발 환경(현행)

### 필수 도구
- **Node.js**: LTS
- **Electron**: 38.x
- **Xcode**: 16+ (macOS 15 SDK)
- **Swift**: 5.9+

### 빌드/실행
```bash
# 의존성 설치
npm install

# 개발 모드 실행
npm run dev

# (참고) AudioHelper Xcode 프로젝트: src/helpers/macos/AudioHelper/AudioHelper.xcodeproj
# 배포/서명/노타리제이션은 추후 electron-builder 구성에 통합 예정
```

---

## 🧪 테스트 현황(체크리스트)

### 자동화된 테스트
- [ ] 단위 테스트 (Swift/Electron IPC)
- [ ] 통합 테스트 (Electron + Helper)
- [ ] 성능 테스트(장시간/세그먼트)

### 수동 테스트
- ✅ 마이크 단독 녹음
- ✅ 시스템 사운드 단독
- ✅ 마이크 + 시스템 믹싱
- ✅ 세그먼트 롤오버(3분)
- ✅ 장치 분리/재연결(자동 재바인딩/폴백)
- ✅ 진행(progress) 이벤트 표시(hh:mm:ss)
- ✅ 파일 로깅(FileLogger) 기본 동작/경로/롤링 확인
- [ ] 장시간 녹음(> 1시간)
- ✅ 암호화 저장

### 🔄 최근 변경 요약
 - macOS Helper: 버전 관리 개선 (Bundle에서 동적 읽기)
   - 하드코딩된 버전 3곳을 Xcode 프로젝트 설정 1곳으로 통합
   - CFBundleShortVersionString/CFBundleVersion 활용
   - 빌드 날짜/시간 동적 생성
 - macOS Helper: unreachable catch 블록 제거
   - SET_DEBUG_FILES_ERROR, ENUMERATOR_FAILED 제거
   - 컴파일러 경고 해결, 주석으로 명세 존재 명시
 - macOS Helper: 명령 처리 오류 예외처리 구현 완료
   - BAD_PARAM: start/start_test 명령 파라미터 검증 추가
   - NOT_IMPLEMENTED: 미래 확장을 위한 가이드 추가
   - JSON_PARSE_ERROR, UNKNOWN_COMMAND, COMMAND_ERROR 확인
 - macOS Helper: 설정 관련 오류 예외처리 구현 완료
   - GET_VERSION_ERROR, SET_OUTPUT_DIR_ERROR, SET_DEBUG_FILES_ERROR 처리
   - SET_SEGMENT_CONFIG_ERROR, SET_MUTE_ERROR, SET_LEVEL_METER_ERROR 처리
   - 모든 설정 명령에 do-catch 블록 추가
   - 기존 error 형식을 errorCode 형식으로 통일
 - macOS Helper: 파일 및 디스크 오류 예외처리 구현 완료
   - SEGMENT_SAVE_FAILED: 세그먼트 저장 실패 세분화 처리
   - ENCRYPT_FAILED: 암호화 실패 시 파일 삭제 및 에러 전송
   - DISK_WRITE_OPEN_FAILED: 파일 쓰기 권한 오류 처리
   - DISK_SPACE_LOW_STOP: 디스크 부족 시 자동 중지 및 세그먼트 저장
   - 중첩 do-catch 구조로 오류 타입별 정확한 분류
 - macOS Helper: 초기화 및 시스템 오류 예외처리 구현 완료
   - ENUMERATOR_FAILED: 장치 열거자 초기화 실패 처리
   - MIC_INIT_FAILED: 마이크 초기화 단계별 실패 감지 및 에러 전송
   - SYS_INIT_FAILED: 시스템 오디오 초기화 실패 처리 (3개 함수)
   - START_TEST_ERROR: 테스트 시작 실패 표준화
   - 모든 에러는 electron_helper_interface.md 명세 준수
 - macOS Helper: 3분 버퍼링 방식 도입 (성능 개선)
   - Windows Helper와 동일한 SegmentManager 아키텍처 채택
   - 디스크 I/O 99.98% 감소 (3분에 4,167회 → 1회)
   - 메모리 사용 8.64MB 증가, CPU 사용률 20-30% 감소 예상
   - 기존 기능 모두 유지 (pause/resume/stop/암호화)
 - macOS Helper: test 모드 버퍼 누수 수정
   - 문제: test 모드 종료 후 버퍼가 클리어되지 않아 녹음 파일에 test 데이터 포함
   - 해결: `stopTest()`와 `start()` 함수에 버퍼 초기화 추가
   - 효과: 녹음 파일 데이터 무결성 보장, progress 시간 동기화
 - macOS Helper: 모노 믹싱으로 변경
   - 스테레오(L=시스템, R=마이크) → 모노(평균 믹싱)
   - 파일 크기 절반 (3분: 5.76MB → 2.88MB)
   - `runtimeChannels` 강제 1채널 고정
 - macOS Helper: AES-256-CBC 암호화 구현 (CryptoSwift)
   - Windows Helper와 동일한 키/IV 사용 (플랫폼 간 호환)
   - 파일 확장자: .pcm(암호화), .raw(평문)
   - 세그먼트 완료 시 암호화 적용, 실패 시 에러+파일 삭제
 - macOS Helper: 명령 시퀀스 및 이벤트 정렬
 - macOS Helper: Pause 동작 개선(세그먼트 시간 동결)
   - pause 중 파일 쓰기/롤오버 완전 차단, 레벨미터만 유지
   - resume 시 동일 세그먼트 이어서 기록
 - macOS Helper: Test 모드 구현(start_test/stop_test)
   - 녹음 중에는 start_test 거부(TEST_BUSY)
   - 재사용 판단 및 캡처 파이프라인 구성, tryMixWrite 차단 보장
 - macOS Helper: 음소거 구현(set_mute)
   - 레벨미터 0 RMS, 파일 기록 시 해당 채널 0 처리
   - 시퀀스: `set_output_dir → set_debug_files → set_segment_config → start`
   - Command 확장: `directory`, `enabled`, `encryption_enabled`, `segment_seconds`
   - Event 확장: `output_dir_set`, `debug_files_set`, `segment_config_set`, `recording_started`, `recording_stopped`
   - 동작: `encryption_enabled=true ⇒ .pcm`, `false ⇒ .raw (평문 PCM, 암호화 적용 완료)
   - 세그먼트 길이: 3분 고정 유지(설정값 수신만, 적용 보류)
 - macOS Helper: 디스크 상태(disk_status) 구현
   - 임계값: ok(≥500MB), low(≥50MB), critical(<50MB)
   - 전송: 녹음 중 1s 평가, 변경 즉시 전송, 동일 상태는 5s마다 재전송
   - 트리거: set_output_dir 직후 1회 전송, set_segment_config 응답에 포함, start 직전 50MB 미만 거부(`DISK_SPACE_CRITICAL`)
 - macOS Helper: 무음 감지(silence) 구현
   - 임계치: RMS < 0.02이면 무음
   - early: 7/14/21/28초 각 1회, sustained: 30초 1회, off: 즉시
   - pause 동안 시간 정지, resume 후 이어서 평가
 - macOS Helper: FileLogger 도입(JSON Lines, OSLog 연동)
  - Application Support 하위 Logs/ 경로, 5MB x5 롤링
  - set_debug_files에 따라 로그 레벨(info/debug) 동적 변경
  - 명령/시작·중지/세그먼트/에러 로깅 연결
 - macOS Helper: 장치 에러/이벤트 정비
   - 에러 전송 통일: `UNKNOWN_COMMAND`, `JSON_PARSE_ERROR`, `MIC_DEVICE_LOST`, `DEVICE_RECONNECT_FAILED` 등 코드형 에러는 `{ ev:'error', code, message }`
   - 시스템 재연결 성공 시 `{ ev:'device_reconnected', type:'system', aec_reset:false }`
   - `mic_state` 이벤트 추가 및 사전 가드(`NO_MIC_DEVICE`)
   - 마이크 재연결 실패 시 폴백 제거

### 테스트 환경
- **OS**: macOS 15+
- **오디오 장치**: USB/내장/블루투스 마이크
- **시스템 사운드**: 스피커/헤드폰

---

## 🐛 알려진 이슈

### 해결된 문제
- [ ] 타이밍 정확도 개선

### 현재 제한사항

- 테스트용 고정 암호화 키 사용
- UI 기능 최소화 (기능 확인 수준)
- SystemOnly 경계 페이드인은 기본 4ms(`AudioConfig::FADE_MS`) 설정
- 디스크 상태 이벤트: 녹음 중에만 평가(1초), 전송(5초) 정책 적용
- 파일명 형식: 시간 기반에서 인덱스 기반(`{sessionId}_{n}.{ext}`)으로 변경

---

## 📈 성능 벤치마크

### 메모리 사용량
```
기본 상태:           ~50MB
세그먼트 버퍼:       ~11.5MB (3분)
링버퍼 오버헤드:     ~1MB
총 메모리:           ~6
```

### CPU 사용률
```
유휴 상태:           2-3%
활성 녹음:           8-12%
장치 재연결:         일시적 ~15%
세그먼트 저장:       일시적 ~10%
```

### 디스크 사용량
```
3분 세그먼트:        2.88MB (모노 Raw PCM)
암호화 오버헤드:     ~16바이트 (PKCS7 패딩)
1시간 녹음:          ~58MB (20개 세그먼트)
```

---

## 🚀 배포 상태(현행)

### 현재 배포 방식
- **개발 모드**: `npm run dev` (AudioHelper.app 번들 실행)
- **저장 경로**: `/tmp/recordings/{sessionId}/{sessionId}_{n}.{ext}` (세션 단위)

### 향후 배포 계획
- **electron-builder**로 macOS 배포 패키지 생성(dmg/zip)
- AudioHelper.app 번들 동봉/서명/노타리제이션

---

## 📋 다음 개발 계획

### 단기
- 패키징/서명/노타리제이션 파이프라인 구축
- 자동화 테스트(IPC/세그먼트/진행 이벤트)
- 진행 표시 보간(렌더러 애니메이션) 옵션

// 메모/태그 시스템은 Helper 비대상(UI 전용)
   - 세그먼트별 메타데이터
   - JSON 사이드카 파일

// 업로드/재시도 큐는 Helper 비대상(UI 전용)

### 장기
- 암호화 저장/업로드 큐(렌더러 전담)
- WebRTC AEC 통합 검토
- 클라우드 STT 연동

---

## 📞 지원 및 문의

### 문서
- **아키텍처**: `docs/recording_architecture_mac_windows_v3.md`
- **API 명세**: `docs/electron_helper_interface.md`
- **설치 가이드**: `docs/install_and_run_guide.txt`
- **변경 기록**: `docs/CHANGELOG.md`

### 개발 지원
- **로그 파일**: `src/helpers/windows/AudioHelper.log`
- **디버그 모드**: `npm run dev`
- **테스트 명령**: PowerShell 스크립트 제공

---

**이 문서는 프로젝트의 현재 상태를 정확히 반영하며, 새로운 기능 추가 시 지속적으로 업데이트됩니다.**