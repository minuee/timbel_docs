# Electron 과 Swift AudioHelper 개발

## 개요
Electron UI 와 연동하여 동작할 MacOS용 Swift로 작성된 Helper프로그램 

### 버전 정보
Electron: 38.0.0
Swift: 5 (MacOS 15~)
Node: 22~

---

## 주요기능

[v] Mic + Sys 사운드 믹싱(스테레오)
[v] 파일 생성 포맷: wav, pcm (raw는 향후)
[v] 오디오 컴포넌트(시작, 종료(취소), 일시정지, 재시작)
[v] 장치(Mic) 목록 반환 및 장치 선택
[v] 장치 분리/재연결(자동 재바인딩/폴백)
[v] 3분 단위 세그먼트 저장
[v] 녹음 시간 반환(Progress)
[v] 이벤트 스펙 통일(ev 키 사용)
[v] 세션 폴더/파일명 정책(`/tmp/recordings/{session}/{session}_{n}.{ext}`)
[] AES_256 암호화
[] 오디오 파형 데이터 반환
[] 저장공간 상태 처리
[] 무음 감지 기능
[] 예외처리(정교화)

### Mic + Sys 사운드 믹싱
pcm, wav 지원(배포 시 pcm 기본, 개발 단계에서 wav 헤더 검증 용도)

- 시스템 오디오(System): ScreenCaptureKit `SCStream`
  - 입력: Float32, 최대 스테레오
  - 처리: 모든 채널을 평균해 모노 버퍼로 다운믹스
  - 큐: `audio.stream.queue (userInteractive)`에서 샘플 핸들링

- 마이크(Mic): `AVCaptureSession + AVCaptureAudioDataOutput`
  - 입력: Float32, 하드웨어 포맷
  - 처리: 필요 시 `AVAudioConverter`로 48kHz/mono 변환(지터/레이트 변동 대비)
  - 큐: `mic.capture.queue (userInteractive)`에서 샘플 콜백 수신

- 믹싱/기록(Output)
  - 내부 처리 단위: `framesPerChunk = 2048`(≈42.7ms@48k)
  - L/R 인터리브: L=System 모노, R=Mic 모노 → S16LE로 클램프/스케일링 후 파일에 스트리밍 기록
  - 진행(progress): 실제로 기록된 누적 프레임 기반, 약 200ms 스로틀로 전송

- 포맷/헤더
  - WAV: 시작 시 RIFF 헤더(placeholder), 종료 시 data/RIFF 크기 패치
  - PCM: RAW S16LE 스트림(헤더 없음)


### 3분단위 세그먼트 저장
3분 단위로 세그먼트를 파일로 분할 저장합니다. 최소 길이 1초 미만은 저장하지 않습니다.

- 경로/규칙
  - 세션 폴더: `/tmp/recordings/{session_id}` (메인 프로세스에서 생성/전달)
  - 파일명: `{session_id}_{segment_idx}.{ext}` (0부터 시작, 확장자 wav/pcm)

- 롤오버 조건/흐름
  - 세그먼트 누적 시간이 `SEGMENT_DURATION_MS=180000`(3분) 도달 시 롤오버
  - 현재 세그먼트 finalize → 길이 < 1초면 삭제, 그 외 `segment_ready` 이벤트 전송
  - 인덱스 +1 후 새 파일 open, 카운터 리셋
  - 최대 세그먼트 `MAX_SEGMENTS=60` 도달 시 자동 stop

- 안정화 처리
  - zero-pad: 시스템/마이크 프레임 불일치 시 부족 채널 0 채움(클릭/시간 점프 방지)
  - 페이드 인: 장치 재바인딩 직후 200ms 선형 페이드로 트랜지언트 억제(선택 적용)
  - 큐 우선순위: 오디오 처리 큐는 `.userInteractive`로 UI 체감 지연 최소화




## 세부 구현 아키텍처

### 프로세스/IPC
- 통신: JSON-Line (stdin/stdout), 모든 이벤트 키는 `ev` 사용
- 주요 명령/이벤트
  - cmd: `start`, `pause`, `resume`, `stop`, `list_devices`
  - ev: `started`, `devices`, `device_reconnected`, `segment_ready`, `progress`, `paused`, `resumed`, `stopped`, `error`

### 캡처 파이프라인
- 시스템 오디오: ScreenCaptureKit(SCStream), Float32 입력을 모노로 다운믹스
- 마이크: AVCaptureSession + AVCaptureAudioDataOutput, Float32 → 48kHz/mono 변환
- 믹싱/출력: 모노 모노를 L/R S16LE로 인터리브, 파일에 스트리밍 기록

### 세그먼트 관리
- 상수: `SEGMENT_DURATION_MS=180000`, `MIN_SEGMENT_MS=1000`, `MAX_SEGMENTS=60`
- 파일 규칙: `/tmp/recordings/{session}/{session}_{n}.{ext}` (n=0부터)
- 롤오버: 경과가 3분 도달 시 현재 세그먼트 finalize → `segment_ready` 이벤트 → 다음 파일 open
- 1초 미만 세그먼트는 저장하지 않음(폐기)

### 장치 선택/재연결
- `list_devices`: `AVCaptureDevice.DiscoverySession([.microphone,.external])` 열거
- 시작 시 `micDeviceId` 지정 가능
- 분리 감지: `AVCaptureDevice.wasDisconnectedNotification`
- 복귀 감지: `AVCaptureDevice.wasConnectedNotification`
- 재연결: 선택 장치 발견 시 세션 입력 재바인딩, 5회 실패 시 기본 장치 폴백(성공 시 이벤트 통지)

### 진행(progress) 이벤트
- 기준: 세션 전체에서 파일에 실제 기록된 누적 프레임(`totalFramesWritten`)
- 전송: 약 200ms 스로틀, `seconds/samples/mic_seconds/mic_samples` 포함
- UI: hh:mm:ss 포맷 표기(필요 시 보간로직으로 체감 지연 최소화)

### 타이밍/안정화 보완
- 프라임: 초기 지연 보장(마이크/시스템 충분 프레임 확보 후 방출) — 필요시 활성화
- zero-pad: 채널 불균형 시 부족분 0 채움, 인터리브 길이 일치
- 페이드 인: 장치 재바인딩 직후 200ms 선형 페이드로 클릭 억제
- 큐 QoS: 오디오 처리 큐는 `.userInteractive` 우선순위

### 저장/포맷
- 포맷 결정: 렌더러에서 wav/pcm 선택 → 메인에서 세션/경로 생성 → Swift에 전달
- WAV: 헤더 사후 패치(finalize 시 RIFF/data 사이즈)
- PCM: RAW S16LE 스트림

### 로그 위치(FileLogger)
- 기본 경로: `~/Library/Application Support/<bundleId>/Logs/AudioHelper.log`
- 롤링 정책: 파일당 5MB, 최대 5개 보관(`AudioHelper.log.1..5`)
- 레벨: `set_debug_files { enabled }`에 따라 info/debug 동적 전환
- 경로 변경: 현재 명령 미제공(내부 API `FileLogger.setDirectory`는 존재)

### 오류/예외 처리(요약)
- 디바이스 분리/런타임 에러 이벤트 전송
- 세그먼트 파일 open 실패 시 `error` 전송 후 녹음 중단
- 폴백 실패 시 안전 종료