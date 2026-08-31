## timbloRecApp 로깅 설계서

### 1) 목적과 범위
- **목적**: 모든 프로세스의 로그를 메인 프로세스에서 중앙 수집·기록하여 일관성과 신뢰성을 높이고, 장애 원인 파악을 용이하게 한다.
- **범위**: Hybrid 아키텍처(메인 중앙 수집 + 폴백), 구조적(JSON Lines) 로그 스키마, 파일/회전 정책, IPC 규칙, 폴백/흡수 시나리오, 운영 가이드, 도입 체크리스트.

### 2) 아키텍처 개요(Hybrid)
- **메인 중앙 수집(기본)**
  - 모든 프로세스(메인/렌더러/네이티브 브리지)는 `ipcRenderer.invoke('log:write', payload)` 등 IPC를 통해 메인에 로그를 전달한다.
  - 메인은 전달받은 로그를 구조적(JSON Lines) 형태로 단일(또는 일 단위) 파일에 기록한다.
- **폴백(옵션)**
  - 메인 전달 실패(타임아웃/채널 없음/권한 이슈) 시, 렌더러는 자기 전용 임시 파일에 동일 포맷으로 기록한다.
  - 다음 앱 가동 시 메인이 임시 파일을 흡수(merge)하여 중앙 로그로 통합 후 임시 파일을 삭제한다.

### 3) 로깅 기본 원칙
- **레벨 정의**
  - `error`: 사용자 영향/복구 필요. 예외/크래시/데이터 손실 위험.
  - `warn`: 잠재 이슈/자동복구 가능/성능 저하.
  - `info`: 중요한 상태 전이/주요 이벤트(시작·종료·완료).
  - `debug`: 진단용 상세 흐름/파라미터/분기 결과.
- **메시지 설계**: “무엇을 시도/성공/실패했는가”를 핵심 문장으로, 상세는 구조화된 컨텍스트에 분리.
- **에러 표준**: 실패 시 `error.name`, `message`, `stack`, `cause`, `lastOkState`를 컨텍스트에 포함.
- **민감정보**: 토큰/사용자명/연락처/정확한 파일 경로는 마스킹(또는 해시). 필요한 경우 일부만 노출.
- **상관관계 유지**: `sessionId`/`recordingId`/`uploadId` 등 상관키를 메인↔렌더러↔네이티브로 전파.

### 4) 페이로드 스키마(표준 키)
- **필수**: `timestamp(ISO8601)`, `process(main|renderer|helper)`, `pid`, `level`, `message`, `version`, `platform`, `sessionId`
- **상황별**
  - 녹음: `recordingId`, `deviceId/name(마스킹)`, `sampleRate`, `channelCount`, `bufferSize`
  - 윈도우: `windowId`, `route/url`
  - IPC: `ipcChannel`, `payloadSize`, `timeoutMs`
  - 파일/업로드: `filePath(마스킹)`, `bytesWritten`, `chunkSeq`, `uploadId`, `retryCount`, `statusCode`
  - 시스템/네트워크: `networkStatus`, `battery`, `powerEvent`
- **포맷**: JSON Lines(한 줄에 하나의 JSON)
- **예시(JSON)**
```json
{
  "timestamp": "2025-10-20T10:12:33.120Z",
  "process": "main",
  "pid": 12345,
  "level": "info",
  "message": "Recording session started",
  "version": "1.0.0",
  "platform": "win32",
  "sessionId": "sess_abc",
  "recordingId": "rec_123",
  "sampleRate": 48000,
  "windowId": 2
}
```

### 5) 파일/회전/포맷 정책
- **기본 경로(BaseDir)**: `app.getPath('logs')/timbloRecApp/`
  - Windows: `C:\\Users\\<user>\\AppData\\Roaming\\timbloRecApp\\` (Electron 환경에 따라 하위 구조 상이 가능)
  - macOS: `~/Library/Logs/timbloRecApp/`
- **서브 디렉터리**: `logs/` (중앙 수집 파일을 보관)
- **파일명(중앙 수집, 일 단위 권장)**
  - 통합 로그: `logs/combined-YYYYMMDD.log` — 모든 레벨(`verbose`~`error`)
  - 에러 전용: `logs/error-YYYYMMDD.log` — `error` 레벨만 별도 집계
  - 단일 파일 운용 시: `logs/combined.log` 및 `logs/error.log` + 용량 회전(`.1`, `.2`, ...)
- **회전(권장: Hybrid)**
  - 기본은 일 단위(`YYYYMMDD`) 파일 생성
  - 파일 당 10MB 초과 시 추가 회전, 스트림별 최근 7개 보존(약 70MB 내 관리)
- **레벨**: 프로덕션 기본 `info`, 문제 재현 시 세션 단위로 `debug` 임시 상향(세션 종료 시 원복)
- **포맷**: JSON Lines(UTF-8, 개행 구분). 타임스탬프는 ISO8601.

### 6) IPC 로깅 규칙(렌더러 → 메인)
- **채널 명**: `log:write` (invoke 기반 권장)
- **전송 규칙**
  - 중요 이벤트는 즉시 전송, 일반 디버그는 버퍼링 후 배치 전송 가능(노이즈/성능 균형)
  - 타임아웃 기본 500ms. 실패 시 폴백으로 전환(아래 참조)
  - 메인은 비동기 큐 기반으로 파일 기록, 백프레셔 적용(과도한 로그 방지)
- **민감정보**: 전송 전 마스킹/해시 적용을 원칙으로 함

### 7) 폴백 및 흡수 정책
- **폴백 트리거**: `log:write` invoke 실패(Timeout/Channel missing/IPC 오류)
- **폴백 경로**: `app.getPath('logs')/timbloRecApp/pending/`
- **폴백 파일명**: `renderer-fallback-YYYYMMDD-{pid}.log`
- **포맷**: 중앙과 동일(JSON Lines)
- **흡수 타이밍**: 앱 시작 시 메인이 `pending/`를 스캔 → 시간순으로 중앙 로그에 merge → 성공적으로 반영된 파일은 삭제
- **주의**: 흡수 시 원본 파일명/라인 수를 메타로 기록하여 중복 병합/유실 방지

### 8) 전역 에러/크래시 핸들링
- 메인: `uncaughtException`, `unhandledRejection`를 `error`로 기록
- 렌더러: `window.onerror`, `unhandledrejection` + 현재 페이지/최근 UI 액션을 컨텍스트로 첨부(IPC 실패 시 폴백)
- 크래시 리포트 ID가 있을 경우 컨텍스트에 포함

### 9) 메인/렌더러 로깅 포인트 맵(요약)
- 파일 기준: `src/main/main.js`, `src/main/windows/*.js`, `src/main/db/*`, `src/main/services/*`, `src/renderer/**/*.js`
- **앱 라이프사이클**: 시작/종료, 윈도우 생성/표시/숨김/닫힘, 크래시/비정상 종료
- **IPC**: 채널 등록, 중요 요청/응답, 타임아웃/재시도, 핸들러 예외
- **레코딩**: 세션 시작/중지, 파일 예약/쓰기, 디스크 부족, AEC/NS/AGC 옵션
- **업데이트/전원/시스템**: `autoUpdater`, `powerMonitor`, 오디오 디바이스 변경
- **DB/파일 I/O**: 트랜잭션 성공/롤백/락 경합
- **업로드/네트워크**: 큐 등록/시작/재시도/완료, 네트워크 오류/백오프

 

### 10) 운영 가이드
- **레벨 전략**: 기본 `info`, 이슈 재현 시 특정 세션만 `debug` 임시 상향(원격 플래그/IPC 토글)
- **노이즈 관리**: 동일 메시지 과다 시 샘플링/집계(예: “버퍼 드롭 x N in 10s”)
- **성능**: 렌더러 측 버퍼링/배치 전송, 메인 측 비동기 큐 + 백프레셔 적용
- **보안/개인정보**: 민감필드 마스킹/해시

### 11) 도입 체크리스트(파일별)
- `src/main/main.js`
  - `ipcMain.handle('log:write', ...)` 구현(검증/마스킹/큐잉/파일 기록)
  - 파일 경로/회전/포맷(JSON Lines) 정책 적용, 시작 시 `pending/` 흡수 로직
- `src/renderer/*`
  - `ipcRenderer.invoke('log:write', payload)` 헬퍼 구현(타임아웃/재시도/폴백 전환)
  - 폴백 기록기(임시 파일) 및 재시작 시 자동 삭제를 위한 메타 부여

### 12) 메시지 템플릿(권장)
- 성공: `[도메인] 동작/상태 전이 성공` + 핵심 파라미터
- 실패: `[도메인] 동작 실패` + 오류 요약 + 복구 시도 여부
- 경고: `[도메인] 비정상 상태 감지` + 영향/완화 조치
- 예시
```json
{ "level": "info", "message": "Upload started", "uploadId": "up_001", "sessionId": "sess_abc" }
```

### 13) 부록: 네이밍 규칙 요약
- 중앙 로그(통합): `logs/combined-YYYYMMDD.log` 또는 `logs/combined.log(.1, .2, ...)`
- 중앙 로그(에러): `logs/error-YYYYMMDD.log` 또는 `logs/error.log(.1, .2, ...)`
- 폴백 로그: `pending/renderer-fallback-YYYYMMDD-{pid}.log`
- 키: `sessionId`, `recordingId`, `uploadId`, `windowId`, `ipcChannel`, `chunkSeq`
 

