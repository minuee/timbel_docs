# 03. Windows 검증 체크리스트

빌드 성공 후 **아래 순서대로** 검증하세요.
아래에서 위로 올라가는 방식(앱부터 켜보기)은 문제 원인 분리가 안 됩니다.

---

## 레벨 1 — 헬퍼 단독 (Electron 없이)

> 이 단계를 통과하면 "오디오 엔진은 정상" 이 확정됩니다.

### 1-1. 기동 확인

```bat
cd src\helpers\windows
AudioHelper.exe
```

- [ ] 즉시 `{"ev":"helper_info","utf8":true,"version":"...","webrtc_aec":false,...}` 출력
  - `webrtc_aec:false` → NLMS 모드로 정상 빌드된 것 (WebRTC 없이 빌드 시 정상)
- [ ] 프로세스가 즉시 종료되지 않고 stdin 대기 상태 유지

### 1-2. 장치 열거

stdin 에 입력:
```json
{"cmd":"list_devices"}
```
- [ ] `{"ev":"devices","devices":[...]}` 수신
- [ ] 실제 연결된 마이크가 목록에 나옴
- [ ] 한글 장치명이 깨지지 않음
  - 헬퍼는 `name_b64_utf16le` 필드로 base64/UTF-16LE 인코딩해서 보냅니다
  - `audioHelperManager.js` 가 이걸 디코딩합니다

### 1-3. 마이크 캡처

```bat
AudioHelper.exe < test_mic.json
```
- [ ] `level` 이벤트의 `rms` 값이 말할 때 올라감
- [ ] `progress` 이벤트가 흐름

### 1-4. 시스템 사운드 캡처 ★핵심

**먼저 YouTube 등으로 소리를 재생시킨 상태에서** 실행하세요.

```bat
AudioHelper.exe < cmds.json
```
(SystemOnly 모드 10초)

- [ ] `source":"system"` 인 `level` 이벤트의 rms 가 0 이 아님
- [ ] 지정 폴더(`test_recordings`)에 파일 생성됨

### 1-5. 디버그 WAV 검증 ★★가장 강력한 진단

`cmds.json` 에 `set_debug_files: true` 가 이미 들어 있습니다.
출력 폴더에 mic / system / mix WAV 가 각각 생성됩니다.

- [ ] **mic WAV** 재생 → 내 목소리가 들림
- [ ] **system WAV** 재생 → 재생 중이던 음악/영상 소리가 들림
- [ ] **mix WAV** 재생 → 둘 다 섞여서 들림
- [ ] mic 와 mix 의 **길이 차이가 20ms 이내** (설계 목표치)

> 🔍 **진단 매트릭스**
> | mic | system | mix | 원인 |
> |---|---|---|---|
> | ✅ | ❌ 무음 | 마이크만 | WASAPI 루프백 문제 / 재생 중인 소리가 없었음 |
> | ❌ 무음 | ✅ | 시스템만 | 마이크 권한 or 장치 선택 문제 |
> | ✅ | ✅ | ❌ 이상 | 믹싱/타이밍 문제 |
> | ✅ | ✅ | ✅ | **정상 — 레벨 2로** |

### 1-6. 세그먼트 / 암호화

```bat
AudioHelper.exe < test_segment.json
```
- [ ] `{"ev":"segment_ready", ...}` 수신
- [ ] `{sessionId}\{sessionId}_0.pcm` 형태로 파일 생성
- [ ] 3분 세그먼트라면 약 5.76MB (16kHz × 2byte × 180초)
- [ ] `encryption_enabled:false` 로 하면 `.raw` 로 떨어지고, 재생 시 정상 오디오

---

## 레벨 2 — Electron 앱 연동

```bat
npm run dev
```

### 2-1. 헬퍼 프로세스 연결

- [ ] 앱 시작 시 `helper_status` / `stage:"spawned"` 로그
- [ ] 로그에 `helper_start` 의 `helperExists: true`
- [ ] DevTools 콘솔에 `helper_info` 수신

> ❌ 실패 시: `%APPDATA%\timbloRecApp\logs\` 의 로그에서
> `helper_start` 이벤트의 `helperPath` 를 확인 → 경로가 맞는지 대조

### 2-2. 초기 화면 (index.html)

- [ ] 마이크 장치 목록이 드롭다운에 표시됨
- [ ] 장치 선택 시 레벨미터가 반응
- [ ] 녹음 시작 버튼 활성화

### 2-3. 녹음 화면

- [ ] 녹음 시작 → 타이머 동작
- [ ] mic / sys 레벨미터 둘 다 반응
- [ ] 남은 시간 바가 3시간 기준으로 감소
- [ ] 일시정지 / 재개 정상 (경계에 클릭음 없음)
- [ ] 메모 입력 → 타임스탬프와 함께 목록에 추가
- [ ] 태그 입력 (최대 10개 제한 동작)
- [ ] 상시 최상위(AOT) 토글
- [ ] 음소거 토글 (mic / sys 각각)
- [ ] 최소화 / 트레이 동작

### 2-4. 세그먼트 생성

- [ ] 3분 경과 시 `segment_ready` 수신
- [ ] `Documents\timbloRecApp\recordings\{sessionId}\` 에 파일 생성
- [ ] DB(`%APPDATA%\timbloRecApp\app.db`)의 `recordings` 테이블에 레코드 생성

> 💡 3분을 기다리기 싫으면 `recording.js` 상단의 테스트용 상수를 임시로 켜세요.
> ```js
> // const TOTAL_RECORD_MS = 30 * 1000;   // 30초(테스트 용)
> // const SEGMENT_DURATION_MS = 30 * 1000;
> ```
> (주석 처리된 채로 이미 있습니다 — 검증 후 반드시 되돌릴 것)

### 2-5. 장치 변경 시나리오 ★Windows 고유

| 시나리오 | 기대 동작 |
|---|---|
| 녹음 중 스피커 → 이어폰 전환 | 녹음 **안 끊김**, `device_reconnected` 이벤트 |
| 녹음 중 USB 마이크 제거 | 녹음 **즉시 중단**, `MIC_DEVICE_LOST` 에러, 그때까지 데이터 저장 |
| 녹음 대기 중 마이크 제거 | 초기 화면으로 이동 (최근 커밋에서 수정된 동작) |
| Bluetooth 헤드셋 연결/해제 | 시스템은 자동 추종, 마이크는 폴백 금지 |

- [ ] 위 4가지 확인

### 2-6. 디스크 잔량 가드

- [ ] `disk_status` 이벤트 수신 (`ok`)
- [ ] (선택) 가상 디스크로 50MB 미만 상황 재현 → `DISK_SPACE_CRITICAL`

---

## 레벨 3 — 업로드 (서버 접근 필요)

> ⚠️ 이 단계는 **유효한 인증 `code` 를 발급하는 웹 서비스 접근이 필요**합니다.
> `token` 과 `endpoint` 가 모두 딥링크로만 주입되므로, 서버 없이는 검증 불가입니다.

### 3-1. 딥링크 인증

```
timbloRecApp://connect?code=<code>&host=<base64-encoded-endpoint>
```

- [ ] 브라우저에서 위 URL 실행 → 앱이 뜨거나 포커스됨
- [ ] `deeplink_received` 로그
- [ ] `GET {endpoint}/api/auth/recorder/exchange/{code}` 호출됨
- [ ] `deeplink_exchange_success` 로그
- [ ] 앱이 이미 실행 중일 때도 동작 (`second-instance` 경로)
- [ ] **앱이 꺼진 상태에서 딥링크로 최초 실행** 해도 토큰 교환됨
  - 최근 커밋(`3fa3e9e`)에서 수정된 이슈 — Windows 에서 재확인 필요

### 3-2. 업로드

- [ ] 녹음 완료 → 요약 창(언어/발화자 수) → 업로드
- [ ] 진행률 팝업에 퍼센트 / 속도 / ETA 표시
- [ ] `POST {endpoint}/api/contents/upload/encryption/files` 성공
- [ ] 성공 시 로컬 녹음 폴더 삭제됨
- [ ] 메모/태그가 `manual` 필드로 함께 전송됨

### 3-3. 실패 / 재시도

- [ ] 네트워크 끊고 업로드 → 실패 팝업
- [ ] 업로드 리스트 창에 실패 항목 표시
- [ ] 재시도 성공
- [ ] 다건 재시도 (`retry-server-uploads`)
- [ ] 재시도 결과 시스템 알림 (4초 디바운스로 묶임)

### 3-4. 크래시 복구

- [ ] 녹음 중 앱 강제 종료 → 재시작
- [ ] `scanAndAutoQueue` 가 미업로드 녹음을 자동으로 큐에 넣음
- [ ] 파일이 없는 레코드는 정리됨

---

## 레벨 4 — 패키징 배포

```bat
npm run build
```

- [ ] `dist\timbloRecApp Setup 1.0.0.exe` 생성
- [ ] 설치 경로 변경 가능 (NSIS `allowToChangeInstallationDirectory: true`)
- [ ] 설치 후 실행 → **헬퍼 경로 탐색 성공** (개발 모드와 경로가 다르므로 반드시 확인)
- [ ] `timbloRecApp://` 프로토콜이 설치 시 등록됨
- [ ] 설치본에서 녹음 → 업로드 전체 흐름 재확인
- [ ] SmartScreen 경고 확인 (서명 미설정이라 뜨는 게 정상 — 04번 문서 참조)

---

## 부록 — 헬퍼 에러 코드 사전

문제 발생 시 `{"ev":"error","code":"..."}` 의 code 로 원인을 특정하세요.

### 초기화 / 시스템
| 코드 | 의미 |
|---|---|
| `COM_INIT_FAILED` | COM 초기화 실패 |
| `ENUMERATOR_FAILED` | 장치 열거자 초기화 실패 |
| `MIC_INIT_FAILED` | 마이크 초기화 실패 |
| `SYS_INIT_FAILED` | 시스템 오디오 초기화 실패 |
| `REINIT_FAILED` | 재초기화 실패 |

### 장치
| 코드 | 의미 |
|---|---|
| `NO_SELECTED_MIC` | 선택된 마이크 없음 |
| `NO_MIC_DEVICE` | 마이크 미감지 또는 사용 불가 |
| `MIC_DEVICE_LOST` | 마이크 제거/비활성 → 녹음 중단 |
| `MIC_DEVICE_CHANGED` | 마이크 변경 → 녹음 중단 (Windows 전용) |
| `CANNOT_RESUME_NO_MIC` | 마이크 미복구로 재개 불가 |
| `DEVICE_RECONNECT_FAILED` | 장치 재연결 실패 |

### 파일 / 디스크
| 코드 | 의미 |
|---|---|
| `SEGMENT_SAVE_FAILED` | 세그먼트 저장 실패 |
| `ENCRYPT_FAILED` | 암호화 실패 |
| `DISK_SPACE_CRITICAL` | 여유 <50MB, 세그먼트 경계에서 중지 예약 |
| `DISK_SPACE_LOW_STOP` | 공간 부족으로 안전 중지 |
| `DISK_WRITE_OPEN_FAILED` | 세그먼트 파일 열기 실패 |

### 명령 처리
| 코드 | 의미 |
|---|---|
| `JSON_PARSE_ERROR` | JSON 파싱 오류 |
| `UNKNOWN_COMMAND` | 알 수 없는 명령 |
| `COMMAND_ERROR` | 명령 처리 오류 |
| `BAD_PARAM` | 잘못된 파라미터 |
| `NOT_IMPLEMENTED` | 미구현 기능 |

### 설정
`GET_VERSION_ERROR`, `SET_OUTPUT_DIR_ERROR`, `SET_DEBUG_FILES_ERROR`,
`SET_SEGMENT_CONFIG_ERROR`, `SET_MUTE_ERROR`, `SET_LEVEL_METER_ERROR`

---

## 로그 위치

```
%APPDATA%\timbloRecApp\logs\
├─ main-{date}.log      전체 로그
└─ error-{date}.log     에러만 별도 기록
```

렌더러 콘솔 메시지도 `console-message` 훅으로 메인 로그에 수집됩니다.
