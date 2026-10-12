# Electron과 AudioHelper 간의 JSON-IPC 인터페이스 명세서

> **목적**  
> Electron UI와 Windows AudioHelper 간의 통신 프로토콜을 정의하고, 명령어와 이벤트의 상세한 구조를 문서화합니다.  
> 이 문서는 개발자가 UI와 백엔드 간의 통신을 이해하고 구현하는 데 필요한 모든 정보를 제공합니다.

---

## 1) 통신 아키텍처

### 전체 구조
```
┌─────────────────┐    JSON-IPC    ┌───────────────────┐
│  Electron Main  │ ←────────────→ │    AudioHelper    │
│    (Process)    │   stdin/stdout │(C++ EXE/Swift APP)│
└─────────────────┘                └───────────────────┘
         ↑                                   ↓
         │                              Windows WASAPI/
         │                             AVCaptureSession(mac) 
         │                              (오디오 캡처)
┌─────────────────┐
│   Electron UI   │
│   (Renderer)    │
└─────────────────┘
```

### 통신 방식
- **프로토콜**: JSON-Line (각 명령/이벤트가 한 줄의 JSON)
- **방향**: 양방향 (명령: UI→Helper, 이벤트: Helper→UI)
- **전송**: `stdin` (명령), `stdout` (이벤트)
- **인코딩**: UTF-8

---

## 2) 명령어 (UI → Helper)

### 2.1 기본 명령어

#### `version` 또는 `get_version`
Helper의 버전 정보와 기능 상태를 요청합니다.

**요청:**
```json
{
  "cmd": "version",
  "sessionId": "uuid-string"
}
```

**응답 이벤트:**
```json
{
  "ev": "version_info",
  "version": "2.0.0",
  "version_full": "2.0.0.1",
  "product_name": "Meeting Recorder Audio Helper",
  "description": "Audio capture helper with WebRTC AEC support",
  "webrtc_aec": true,
  "noise_suppression": false,
  "gain_control": false,
  "build_date": "Sep 23 2025",
  "build_time": "15:25:25",
  "copyright": "Copyright (C) 2025",
  "webrtc_available": true,
  "webrtc_initialized": false
}
```

**추가 이벤트:**
Helper 초기화 시 `helper_info` 이벤트도 전송됩니다 (UI에서 버전 표시용).

**필드 설명:**
- `version`: 짧은 버전 (Major.Minor.Patch)
- `version_full`: 전체 버전 (Major.Minor.Patch.Build)
- `webrtc_aec`: WebRTC AEC 기능 포함 여부
- `noise_suppression`: 노이즈 억제 활성화 상태
- `gain_control`: 게인 컨트롤 활성화 상태
- `webrtc_available`: 런타임에 WebRTC 사용 가능 여부
- `webrtc_initialized`: WebRTC AudioProcessor 초기화 상태

#### `list_devices`
오디오 장치 목록을 요청합니다.

**요청:**
```json
{
  "cmd": "list_devices",
  "sessionId": "uuid-string"
}
```

**응답 이벤트:**
```json
{
  "ev": "devices",
  "devices": [
    {
      "id": "device-id-1",
      "name": "마이크 이름",
      "name_b64_utf16le": "base64-encoded-name",
      "isDefault": true
    }
  ],
  "renderDevices": [
    {
      "id": "render-device-id-1",
      "name": "스피커 이름",
      "name_b64_utf16le": "base64-encoded-name",
      "isDefault": false
    }
  ]
}
```

**필드 설명:**
- `devices`: 캡처(마이크) 장치 목록
- `renderDevices`: 렌더(스피커) 장치 목록
- `name_b64_utf16le`: UTF-16LE로 인코딩된 Base64 장치명 (한글 지원)
- `isDefault`: 기본 장치 여부

#### `set_output_dir`
출력 디렉토리를 설정합니다. 실제 녹음 파일은 `{directory}/{sessionId}/` 구조로 저장됩니다.

**요청:**
```json
{
  "cmd": "set_output_dir",
  "directory": "C:/recordings",
  "sessionId": "uuid-string"
}
```

**응답 이벤트:**
```json
{
  "ev": "output_dir_set",
  "directory": "C:/recordings"
}
```

**파일 저장 구조:**
```
{output_directory}/
└── {sessionId}/
    ├── {sessionId}_0.pcm
    ├── {sessionId}_1.pcm
    ├── {sessionId}_2.pcm
    ├── {sessionId}(1)_0.pcm    ← 중복 시 (동일 폴더)
    ├── {sessionId}(1)_1.pcm
    ├── {sessionId}(2)_0.pcm    ← 세 번째 녹음
    └── {sessionId}(2)_1.pcm
```

**경로 규칙:**
- `directory`가 비어있으면 기본값 `"recordings"` 사용
- `directory`에 값이 있으면 해당 경로를 직접 사용 (추가 `recordings/` 하위 폴더 생성 안 함)

#### `set_debug_files`
디버그 파일 저장을 활성화/비활성화합니다.

**요청:**
```json
{
  "cmd": "set_debug_files",
  "enabled": "true",
  "sessionId": "uuid-string"
}
```

**응답 이벤트:**
```json
{
  "ev": "debug_files_set",
  "enabled": "true"
}
```

**필드 설명:**
- `enabled`: 문자열 `"true"`|`"false"` (불리언 아님)

#### `set_segment_config`
세그먼트 설정을 구성합니다.

**요청:**
```json
{
  "cmd": "set_segment_config",
  "encryption_enabled": "true",
  "segment_seconds": "180",
  "sessionId": "uuid-string"
}
```

**응답 이벤트:**
```json
{
  "ev": "segment_config_set",
  "encryption_enabled": "true",
  "segment_seconds": "180",
  "disk_status": "ok|low|critical|unknown",
  "free_bytes": 123456789
}
```

**필드 설명:**
- `encryption_enabled`: 문자열 `"true"`|`"false"` (불리언 아님)
- `segment_seconds`: 문자열로 전달되는 세그먼트 길이(초)

> 참고: `set_output_dir` 설정 직후에도 디스크 상태 이벤트(`disk_status`)가 1회 전송됩니다.

**암호화 설정:**
- `"true"`: AES256-CBC 암호화 적용, `.pcm` 파일 생성
- `"false"`: 암호화 없음, `.raw` 파일 생성

### 2.2 녹음 제어 명령어

##### `start_test` 응답의 `reuse`
기존 캡처를 재사용했는지 여부를 나타내는 정보 플래그입니다.

UI 권장 처리:
- `reuse=true`: 캡처가 이미 동작 중이므로 타이머/파형 초기화, 장치 재조회, 레벨미터 재전송을 생략하고 버튼 상태만 갱신(시작 비활성/중지 활성).
- `reuse=false`: 신규 시작으로 간주하여 정상 초기화 후 버튼 상태 갱신.

#### `start_test`
오디오 캡처 테스트를 시작합니다.

**요청:**
```json
{
  "cmd": "start_test",
  "mode": "MicPlusSystem",
  "mic": "device-id-string",
  "sessionId": "uuid-string"
}
```

**주의사항:**
- `mic` 필드에 `"default"` 사용 금지 (구체적인 device ID 필수)
- 선택된 마이크가 ACTIVE 상태가 아니면 `NO_MIC_DEVICE` 에러 발생

**응답 이벤트:**
```json
{
  "ev": "test_started",
  "mode": "MicPlusSystem",
  "reuse": true
}
```

**필드 설명:**
- `mode`: 캡처 모드 (MicPlusSystem, MicOnly, SystemOnly)
- `reuse`: 기존 캡처 재사용 여부 (재사용 시에만 포함)
- `mic` 필드는 포함되지 않음

**재사용 정책:**
- 캡처 중(`isRunning=true`)이며 녹음 중이 아니라면, 요청 장치(`mic`/`render`)가 현재 장치와 동일할 때만 재사용
- 장치가 다르면 기존 캡처를 완전히 종료한 뒤 요청 장치로 재초기화(내부 경로) 진행

##### `test_stopped` 전송 조건 변경
- 테스트 모드일 때만 전송됩니다. 레벨미터 전용 중지는 이벤트를 발생시키지 않습니다.

##### 레벨미터 자동 재시작 단일 경로
- 즉시 재시작은 테스트 정지 경로(`HandleStopTest`) 한 곳에서만 수행됩니다. 디바운스/백오프(1s→2s→4s) 정책 적용.
- 선택 마이크가 없거나 ACTIVE가 아닐 때는 레벨미터/테스트/녹음을 시작하지 않으며, `mic_state: "unavailable"`을 전송합니다. 다른 마이크로의 폴백은 허용되지 않습니다.

##### 마이크 선택 정책
- `selectedMicId`: UI가 선택해 둔 영구 상태
- `sessionMicId`: 이번 세션에만 사용하는 마이크 ID
- UI에서 `start_test`를 직접 호출할 때 `mic`가 포함되면 `selectedMicId`에도 반영됩니다. 녹음 경로/자동 재시작으로 들어오는 내부 호출에서는 `selectedMicId`를 변경하지 않습니다.
 - 선택 마이크가 ACTIVE가 아닐 때는 다른 마이크로 자동 전환하지 않습니다(폴백 금지). 녹음/테스트/레벨미터 시작 요청은 `NO_MIC_DEVICE` 에러로 거부됩니다.

#### `stop_test`
오디오 캡처 테스트를 중지합니다.

**요청:**
```json
{
  "cmd": "stop_test",
  "sessionId": "uuid-string"
}
```

**응답 이벤트:**
```json
{
  "ev": "test_stopped"
}
```

#### `start`
실제 녹음을 시작합니다.

**요청:**
```json
{
  "cmd": "start",
  "mode": "MicPlusSystem",
  "out": {
    "sr": 16000,
    "ch": 1,
    "blockMs": 20
  },
  "mic": "device-id-string",
  "gains": {
    "mic": 1.0,
    "sys": 0.7
  },
  "max_ms": "10800000",
  "segmenting": {
    "duration_ms": 180000,
    "align_to_block": true
  },
  "encryption": {
    "enabled": false
  },
  "file_extension": ".pcm",
  "sessionId": "uuid-string"
}
```

**파라미터 설명:**
- `mic`: 구체적인 device ID 필수 (`"default"` 사용 금지)
- `max_ms` (선택): 최대 녹음 시간 (밀리초). 설정된 시간 후 자동으로 녹음이 중지됩니다. 기본값: `"10800000"` (3시간). `"0"` 또는 미설정 시 무제한 녹음
- `file_extension` (선택): 암호화 파일의 확장자 (기본값: `.pcm`). 암호화 안 된 파일은 항상 `.raw` 사용. `.` 포함 여부 무관

**주의사항:**
- `mic` 필드에 `"default"` 사용 금지 (구체적인 device ID 필수)
- 선택된 마이크가 ACTIVE 상태가 아니면 `NO_MIC_DEVICE` 에러 발생

**응답 이벤트:**
```json
{
  "ev": "recording_started"
}
```

**필드 설명:**
- 이벤트는 `ev` 필드만 포함 (mode, startTimeMs 등 추가 필드 없음)

**사전 조건 (디스크 용량 체크):**
- 시작 직전 디스크 여유 공간이 50MB 미만(`critical`)이면 시작을 거부합니다.
- 에러 이벤트 예시:
```json
{
  "ev": "error",
  "code": "DISK_SPACE_CRITICAL",
  "message": "디스크 여유 공간이 50MB 미만이어서 녹음을 시작할 수 없습니다."
}
```

**초기화 동작:**
녹음 시작 시 다음 상태들이 자동으로 초기화됩니다:
- 세그먼트 인덱스: 0부터 시작 (`{sessionId}_0.{ext}`)
- 음소거 상태: 마이크/시스템 모두 음소거 해제
- 무음 감지 상태: 초기화 및 활성화
- 진행 시간: 0초부터 시작
- 최대 녹음 시간: `max_ms` 파라미터로 워치독 타이머 설정

**최대 녹음 시간 처리:**
- `max_ms`가 설정되면 별도 스레드에서 워치독 타이머가 시작됩니다
- 설정된 시간 도달 시 다음 세그먼트 경계에서 안전하게 녹음을 중지합니다
- 중지 시 미완성 세그먼트는 폐기하고 완성된 세그먼트만 저장합니다

#### `pause`
녹음을 일시정지합니다.

**요청:**
```json
{
  "cmd": "pause",
  "sessionId": "uuid-string"
}
```

**응답 이벤트:**
```json
{
  "ev": "paused"
}
```

**동작 상세:**
- 일시정지 즉시 FIFO 큐와 리샘플러 상태를 초기화하여 정확한 경계 보장
- 레벨미터가 활성화되어 있으면 캡처 스레드는 계속 동작하지만 녹음 데이터는 FIFO에 쌓이지 않음
- Resume/Stop 시 시간 점프 없이 일시정지 시점부터 연속됨
- Stop 시 플래그 순서 보장 (`isRecording=false` 먼저 설정)으로 드레인 중 추가 기록 방지

#### `resume`
녹음을 재개합니다.

**요청:**
```json
{
  "cmd": "resume",
  "sessionId": "uuid-string"
}
```

**응답 이벤트:**
```json
{
  "ev": "resumed"
}
```

#### `stop`
녹음을 중지합니다.

**요청:**
```json
{
  "cmd": "stop",
  "sessionId": "uuid-string"
}
```

**응답 이벤트:**
```json
{
  "ev": "recording_stopped",
  "totalSamples": 2880000,
  "micSamplesWritten": 1440000,
  "sysSamplesWritten": 1440000
}
```

#### `set_mute`
마이크/시스템 음소거 상태를 설정합니다. 녹음 데이터는 캡쳐하되 저장 시 0으로 처리됩니다. 테스트 모드에서는 호출 가능하나, 무음 감지 중에는 거부됩니다.

요청:
```json
{
  "cmd": "set_mute",
  "target": "mic|system|both",
  "value": "true",
  "sessionId": "uuid-string"
}
```

응답 이벤트:
```json
{
  "ev": "mute_state",
  "mic": true,
  "system": false
}
```

**필드 설명:**
- `value`: 문자열 `"true"`|`"false"` 또는 `"on"`|`"off"` 허용
- 응답의 `mic`/`system`은 불리언 값

제약/동작:
- 대상: `mic`, `system`, `both` 지원. `value`는 `true|false` 또는 `"on"|"off"` 허용.
- 음소거 중에는 저장되는 오디오 샘플을 0으로 기록하며, `level` 이벤트의 `rms`는 0으로 전송됩니다.
- 무음 감지 기능 자체는 녹음 중에만 동작합니다.

#### `set_level_meter`
레벨미터 동작을 전역 토글합니다. on이면 테스트/녹음 여부와 무관하게 레벨 이벤트가 전송되지만, 선택 마이크가 ACTIVE가 아닐 경우 캡쳐는 시작/유지되지 않습니다(`mic_state: "unavailable"`). off이면 레벨 이벤트가 0 RMS로 전송됩니다.

요청:
```json
{
  "cmd": "set_level_meter",
  "enabled": "true",
  "sessionId": "uuid-string"
}
```

응답 이벤트:
```json
{
  "ev": "level_meter_state",
  "enabled": true
}
```

**필드 설명:**
- 요청의 `enabled`: 문자열 `"true"`|`"false"` (불리언 아님)
- 응답의 `enabled`: 불리언 값

### 레벨미터 동작 정책 (요약)
- `set_level_meter.enabled=true`이면 테스트/녹음 여부와 무관하게 캡쳐가 시작/유지되어 `level` 이벤트가 전송됩니다.
- 일시정지(pause) 상태에서도 레벨미터가 활성화되어 있으면 마이크/시스템 모두 레벨 이벤트가 계속 전송됩니다. (파일 기록 없음)
- `enabled=false`이면 레벨 이벤트는 0 RMS로 전송됩니다.

#### 모드 반영 및 재사용 정책
- 레벨미터 자동/수동 시작 시 캡쳐 모드는 하드코딩(MicPlusSystem)이 아닌 현재 설정된 `currentMode`를 따릅니다.
- `start_test` 재사용 조건은 장치 동일성뿐 아니라 모드 동일성까지 만족해야 하며, 모드가 다르면 내부 재초기화가 수행됩니다.

**자동 재시작(장치 변경/분리) 정책:**
- 즉시 재시작은 단일 경로에서만 수행되고, 디바운스 스케줄링이 설정된 경우 즉시 재시작은 생략됩니다.
- 스케줄러는 1s → 2s → 4s 지수 백오프로 최대 3회 재시도합니다.
- 활성 캡처 장치가 없으면 시작하지 않으며, `mic_state: "unavailable"` 이벤트를 전송합니다.

### 진행(progress) 이벤트 정책
- 진행 이벤트는 "녹음 중(isRecording=true)"에만 전송됩니다.
- 일시정지(pause) 중에는 진행 이벤트를 전송하지 않습니다.
- 테스트 모드/레벨미터 전용 캡쳐 상태에서도 진행 이벤트는 전송하지 않습니다.
- 진행 이벤트의 `mic_seconds/mic_samples`는 파일 진행(`seconds/samples`)과 동기화되어 pause 구간이 합산되지 않습니다.

### 2.3 메타데이터 명령어

> **참고**: 메모/태그 기능은 Helper에서 제공하지 않습니다. UI에서만 관리합니다.

---

## 3) 이벤트 (Helper → UI)

### 3.1 상태 이벤트

#### `level`
오디오 레벨 정보를 전송합니다.

```json
{
  "ev": "level",
  "source": "mic",
  "rms": 0.18,
  "t": 12345
}
```

**필드 설명:**
- `source`: `"mic"` | `"system"` | `"mixed"`
- `rms`: RMS 값 (0.0 ~ 1.0)
- `t`: 타임스탬프 (밀리초)

#### `waveform`
웨이브폼 데이터를 전송합니다.

```json
{
  "ev": "waveform",
  "t": 12500,
  "amplitudes": "[0.1,0.2,0.15,0.3,...]"
}
```

**필드 설명:**
- `amplitudes`: JSON 문자열로 인코딩된 진폭 배열
- `t`: 타임스탬프 (밀리초)

#### `progress`
녹음 진행 상황을 전송합니다.

```json
{
  "ev": "progress",
  "seconds": 12.5,
  "samples": 200000,
  "mic_samples": 200000,
  "mic_seconds": 12.5
}
```

**필드 설명:**
- `seconds`: 실제 파일에 기록된 누적 시간 (초, t_file)
- `samples`: 실제 파일에 기록된 누적 샘플 수
- `mic_samples`: 마이크에서 캡쳐된 누적 샘플 수 (t_capture)
- `mic_seconds`: 마이크에서 캡쳐된 누적 시간 (초, t_capture)

#### `disk_status`
디스크 여유 공간 상태를 녹음 중일 때 1초 주기로 평가합니다. 상태가 변화하면 즉시 전송하며, 상태가 동일하더라도 5초마다 1회 재전송합니다.

```json
{
  "ev": "disk_status",
  "status": "ok",
  "free_bytes": 123456789
}
```

- `status`: `"ok"`(≥500MB), `"low"`(≥50MB), `"critical"`(<50MB)
- `free_bytes`: 현재 사용 가능 바이트 수

#### `mute_state`
현재 음소거 상태를 전송합니다. `set_mute` 호출 직후 1회 전송됩니다.

```json
{
  "ev": "mute_state",
  "mic": false,
  "system": true
}
```

#### `level_meter_state`
현재 레벨미터 토글 상태를 알립니다. `set_level_meter` 호출 직후 1회 전송됩니다.

```json
{
  "ev": "level_meter_state",
  "enabled": false
}
```

### 3.2 세그먼트 이벤트

#### `segment_ready`
세그먼트 파일이 완성되어 저장될 때 전송됩니다.

```json
{
  "ev": "segment_ready",
  "index": 3,
  "path": "C:/output/uuid-string/uuid-string_0.pcm",
  "samples": 2880000,
  "duration_ms": 180000,
  "size_bytes": 5760000,
  "encrypted": true
}
```

**파일명 규칙:**
- 저장 위치: `{outputDirectory}/{sessionId}/` 폴더 내 (동일 폴더)
- 형식: `{sessionId}_{n}.{ext}` (n은 0부터 시작하는 세그먼트 인덱스)
- 중복 처리: 동일 파일이 이미 존재하면 파일명에 `(m)` 추가 (m은 1부터 시작)
- 확장자: 
  - 암호화 파일: `start` 명령의 `file_extension` 파라미터 (기본값: `.pcm`)
  - 암호화 안 된 파일: 항상 `.raw`
- 예시: 
  - 첫 번째 녹음: `{outputDirectory}/session-abc/session-abc_0.pcm`, `session-abc_1.pcm`, ...
  - 두 번째 녹음: `{outputDirectory}/session-abc/session-abc(1)_0.pcm`, `session-abc(1)_1.pcm`, ... (동일 폴더)
  - 세 번째 녹음: `{outputDirectory}/session-abc/session-abc(2)_0.pcm`, `session-abc(2)_1.pcm`, ... (동일 폴더)
- 최대 3시간 녹음 시 최대 60개 파일 생성 (3분씩)
- 최소 저장 길이: 1초 미만 세그먼트는 저장되지 않음

### 3.3 장치 이벤트

#### `device_reconnected`
시스템 오디오 장치가 재연결되었을 때 전송됩니다.

```json
{
  "ev": "device_reconnected",
  "type": "system",
  "aec_reset": true
}
```

**필드 설명:**
- `type`: 장치 타입 (Windows는 "system"만 지원)
- `aec_reset`: AEC(에코 제거) 리셋 여부 (Windows에서 사용)

#### `audio_device_change`
오디오 장치가 추가되거나 제거되었을 때 전송됩니다.

```json
{
  "ev": "audio_device_change",
  "change_type": "added",
  "device_type": "audio"
}
```

**필드 설명:**
- `change_type`: 변경 타입 ("added" | "removed")
- `device_type`: 장치 타입 ("audio")

**사용 시나리오:**
- **장치 추가 (added)**: 새로운 마이크/오디오 장치가 시스템에 연결됨
- **장치 제거 (removed)**: 마이크/오디오 장치가 시스템에서 분리됨

**UI 처리 권장 사항:**
1. 이 이벤트 수신 시 `list_devices` 명령으로 장치 목록 갱신
2. 사용자에게 장치 변경 사실 알림 (선택적)
3. 장치 선택 UI 자동 업데이트

**참고:**
- 장치 제거 시에는 `MIC_DEVICE_LOST` 에러도 함께 전송될 수 있음
- 녹음 중 장치 제거 시 자동으로 녹음 중지됨
- 테스트 모드나 대기 중에도 장치 변경 알림 전송됨
- 여러 엔드포인트(마이크/스피커)를 가진 장치의 경우 각 엔드포인트별로 이벤트가 발생할 수 있음

### 3.4 무음 감지 이벤트

#### `silence`
무음 상태 변화를 전송합니다.

```json
{
  "ev": "silence",
  "state": "early",
  "elapsedMs": 14000
}
```

**상태 값:**
- `"early"`: 초기 무음 경고 (7초, 14초, 21초, 28초)
- `"off"`: 무음 종료 (사운드 감지됨)
- `"sustained"`: 30초 지속 무음 (1회만 전송, UI에서 이메일 발송)

**동작 방식:**
- 시스템 또는 마이크 사운드가 1회라도 감지되면 무음 감지 해제 (`off` 이벤트 전송)
- 30초 동안 완전 무음 시 `sustained` 이벤트 1회 전송
- 무음 평가는 녹음 중일 때만 수행
- UI에서 `sustained` 이벤트 수신 시 이메일 발송 처리

### 3.5 에러 이벤트

#### `error`
오류가 발생했을 때 전송됩니다.

```json
{
  "ev": "error",
  "code": "MIC_DEVICE_LOST",
  "message": "마이크 장치가 제거되거나 비활성화되어 녹음을 중단합니다."
}
```

**주요 에러 코드:**

**초기화 및 시스템 오류:**
- `"COM_INIT_FAILED"`: COM 초기화 실패
- `"ENUMERATOR_FAILED"`: 장치 열거자 초기화 실패
- `"MIC_INIT_FAILED"`: 마이크 초기화 실패
- `"SYS_INIT_FAILED"`: 시스템 오디오 초기화 실패
- `"START_TEST_ERROR"`: 테스트 시작 실패
- `"REINIT_FAILED"`: 재초기화 실패

**장치 관련 오류:**
- `"NO_SELECTED_MIC"`: 선택된 마이크가 없음
- `"NO_MIC_DEVICE"`: 선택된 마이크가 감지되지 않거나 사용 불가 상태
- `"MIC_DEVICE_LOST"`: 마이크 장치가 제거되거나 비활성화되어 녹음 중단
- `"MIC_DEVICE_CHANGED"`: 마이크 장치 변경으로 녹음 중단 (Windows 전용)
- `"CANNOT_RESUME_NO_MIC"`: 마이크가 복구되지 않아 재개 불가
- `"DEVICE_RECONNECT_FAILED"`: 장치 재연결 실패

**파일 및 디스크 오류:**
- `"SEGMENT_SAVE_FAILED"`: 세그먼트 저장 실패(암호화/쓰기 오류 포함)
- `"ENCRYPT_FAILED"`: 암호화 실패로 세그먼트 저장 불가
- `"DISK_SPACE_CRITICAL"`: 디스크 여유 공간 50MB 미만(세그먼트 경계에서 중지 예약)
- `"DISK_SPACE_LOW_STOP"`: 디스크 여유 공간 부족으로 안전 중지
- `"DISK_WRITE_OPEN_FAILED"`: 세그먼트 파일 열기 실패(쓰기 불가)

**명령 처리 오류:**
- `"JSON_PARSE_ERROR"`: JSON 파싱 오류
- `"UNKNOWN_COMMAND"`: 알 수 없는 명령
- `"COMMAND_ERROR"`: 명령 처리 오류
- `"BAD_PARAM"`: 잘못된 파라미터
- `"NOT_IMPLEMENTED"`: 미구현 기능 호출

**설정 관련 오류:**
- `"GET_VERSION_ERROR"`: 버전 정보 조회 오류
- `"SET_OUTPUT_DIR_ERROR"`: 출력 디렉터리 설정 오류
- `"SET_DEBUG_FILES_ERROR"`: 디버그 파일 설정 오류
- `"SET_SEGMENT_CONFIG_ERROR"`: 세그먼트 설정 오류
- `"SET_MUTE_ERROR"`: 음소거 설정 오류
- `"SET_LEVEL_METER_ERROR"`: 레벨미터 설정 오류

#### `mic_state`
선택 마이크의 가용성 상태를 전송합니다. (macOS와 Windows 모두 동일한 상태값 사용)

```json
{
  "ev": "mic_state",
  "state": "unavailable"
}
```

**상태 값:**
- `"available"`: 선택된 마이크가 사용 가능
- `"unavailable"`: 선택된 마이크가 없거나 사용 불가 상태

**전송 시점:**
- 장치 제거 시: `"unavailable"` 전송
- 장치 복구 시: `"available"` 전송
- 레벨미터/테스트/녹음 시작 시 마이크가 없거나 ACTIVE가 아닐 때: `"unavailable"` 전송
- 선택 마이크가 ACTIVE가 아닐 때: `"unavailable"` 전송

**참고:**
- macOS와 Windows 모두 동일한 상태값(`"available"`/`"unavailable"`)을 사용합니다.
- 이전 버전의 Windows에서는 `"disconnected"` 상태도 사용했으나, v0.4.2부터 제거되어 macOS와 통일되었습니다.

---

## 4) Electron 구현 예시

### 4.1 Main Process (main.js)

```javascript
class AudioHelperManager {
  constructor() {
    this.helperProcess = null;
    this.sessionId = uuidv4();
  }

  async startHelper() {
    const helperPath = this.getHelperPath();
    this.helperProcess = spawn(helperPath, [], {
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true
    });

    this.helperProcess.stdout.on('data', (data) => {
      const lines = data.toString().split('\n').filter(line => line.trim());
      lines.forEach(line => {
        try {
          const event = JSON.parse(line);
          this.handleHelperEvent(event);
        } catch (e) {
          console.log('Helper output:', line);
        }
      });
    });
  }

  sendCommand(command) {
    if (!this.helperProcess) {
      throw new Error('Helper not running');
    }
    
    const commandWithSession = {
      ...command,
      sessionId: this.sessionId
    };
    
    this.helperProcess.stdin.write(JSON.stringify(commandWithSession) + '\n');
  }

  handleHelperEvent(event) {
    if (mainWindow) {
      mainWindow.webContents.send('helper-event', event);
    }
  }
}
```

### 4.2 Renderer Process (app.js)

```javascript
class MeetingRecorderApp {
  setupHelperEvents() {
    window.electronAPI.onHelperEvent((event) => {
      this.handleHelperEvent(event);
    });
  }

  handleHelperEvent(event) {
    switch (event.ev) {
      case 'devices':
        this.updateDeviceList(event.devices);
        break;
      case 'level':
        this.updateLevelMeter(event.source, event.rms);
        break;
      case 'error':
        this.logMessage(`헬퍼 오류: ${event.message}`, 'error');
        break;
      // ... 기타 이벤트 처리
    }
  }

  async startRecording() {
    const command = {
      cmd: 'start',
      mode: this.modeSelect.value,
      out: { sr: 16000, ch: 1, blockMs: 20 },
      mic: this.micSelect.value,
      gains: { mic: 1.0, sys: 0.7 },
      max_ms: "10800000",
      segmenting: { 
        duration_ms: 3 * 60 * 1000,
        align_to_block: true 
      },
      encryption: { enabled: false }
    };
    
    await window.electronAPI.sendHelperCommand(command);
  }

  // 메모는 UI에서만 관리 (Helper에서 처리하지 않음)
  addMemo() {
    const text = this.memoText.value.trim();
    if (!text) return;
    
    const currentTime = this.getCurrentRecordingTime();
    const memo = {
      t_ms: currentTime,
      type: 'memo',
      text: text
    };
    
    this.memos.push(memo);
    this.displayMemo(memo);
    this.memoText.value = '';
  }
}
```

---

## 5) 오류 처리 및 복구

### 5.1 연결 오류
- Helper 프로세스가 예기치 않게 종료된 경우 자동 재시작
- JSON 파싱 오류 시 해당 라인을 로그에 기록하고 계속 진행
- 명령 전송 실패 시 사용자에게 알림

### 5.2 장치 오류
- 마이크 장치 손실 시 녹음 중단 및 사용자 알림
- 시스템 오디오 장치 변경 시 자동 재연결 시도
- 재연결 실패 시 마이크만으로 계속 녹음

### 5.3 데이터 무결성
- 세그먼트 롤오버 시 이전 세그먼트 완전 저장 확인
- 녹음 중단 시 현재까지의 데이터 즉시 저장
- 메타데이터와 오디오 파일 동기화 보장

---

## 6) 성능 고려사항

### 6.1 이벤트 빈도
- `level` 이벤트: 20ms마다 전송 (50Hz)
- `waveform` 이벤트: 100ms마다 전송 (10Hz)
- `progress` 이벤트: 200ms마다 전송 (5Hz)
- `disk_status` 이벤트: 1000ms 평가(폴링), 상태 변화 시 즉시 전송, 상태 동일 시에도 5초마다 1회 재전송

### 6.2 메모리 관리
- 웨이브폼 데이터는 JSON 문자열로 압축 전송
- 세그먼트 완료 시 즉시 파일 저장하여 메모리 해제
- 장기 녹음 시 메모리 누수 방지

### 6.3 동기화
- 마이크를 마스터 시계로 사용하여 정확한 타임라인 보장
- 시스템 오디오 지연을 링버퍼로 보상
- 블록 경계에서 정확한 세그먼트 분할

### 6.4 타입 일관성
- **요청 명령**: 대부분의 boolean 값은 문자열 `"true"`|`"false"`로 전송
- **응답 이벤트**: boolean 값은 실제 불리언 타입으로 전송
- **숫자 값**: `max_ms`, `segment_seconds` 등은 문자열로 전송 후 내부에서 파싱
- **예외**: `mute_state` 응답의 `mic`/`system` 필드는 불리언 값

---

## 7) 테스트 및 디버깅

### 7.1 로그 확인
- Helper 프로세스의 `AudioHelper.log` 파일에서 상세 로그 확인
- Electron 콘솔에서 실시간 이벤트 모니터링
- JSON 파싱 오류 시 원본 라인 출력

### 7.2 단위 테스트
- 각 명령어별 요청/응답 테스트
- 장치 변경 시나리오 테스트
- 에러 상황 시뮬레이션 테스트

### 7.3 통합 테스트
- UI와 Helper 간의 전체 워크플로우 테스트
- 장시간 녹음 안정성 테스트
- 메모리 사용량 모니터링

---

## 8) 확장성 고려사항

### 8.1 새로운 명령어 추가
- `ProcessCommand` 함수에 새로운 케이스 추가
- UI에서 해당 명령어 호출 로직 구현
- 문서에 명령어 명세 추가

### 8.2 새로운 이벤트 추가
- `SendEvent` 함수로 새로운 이벤트 전송
- UI에서 해당 이벤트 처리 로직 구현
- 문서에 이벤트 명세 추가

### 8.3 버전 호환성
- 명령어/이벤트에 버전 필드 추가 고려
- 하위 호환성 유지를 위한 기본값 처리
- API 변경 시 마이그레이션 가이드 제공

---

## 9) 최신 구현 상태 (2025-10-14)

### ✅ 완료된 기능
- **실시간 오디오 캡처**: 마이크 + 시스템 사운드 동시 캡처 및 믹싱
- **세그먼트 관리**: 3분 단위 자동 분할 및 AES256-CBC 암호화
- **장치 관리**: 자동 감지 및 재연결 (시스템 오디오), 보호 중단 (마이크)
- **JSON-IPC**: 표준화된 명령/이벤트 통신 프로토콜
- **에러 처리**: 포괄적인 에러 코드 및 복구 메커니즘
- **무음 감지**: 7/14/21/28초 early 알림, 30초 sustained 이벤트, 테스트 모드 비활성화
- **음소거 제어**: 마이크/시스템 개별 또는 전체 음소거, 저장 데이터 0 처리
- **레벨미터 토글**: 테스트/녹음과 무관한 캡쳐 제어, pause 중 레벨 유지
- **파일명 관리**: 인덱스 기반 파일명(`{sessionId}_{n}.{ext}`), 확장자 설정 가능
- **타입 일관성**: 요청은 문자열, 응답은 적절한 타입으로 통일

### 📋 인터페이스 특징
- **장치 목록**: `devices`(캡처) + `renderDevices`(렌더) 동시 제공
- **경로 규칙**: `{outputDirectory}/{sessionId}/` 구조 (추가 recordings/ 하위 폴더 없음)
- **기본 장치**: `"default"` 사용 금지, 구체적 device ID 필수
- **이벤트 필드**: 최소한의 필드만 포함 (mode, startTimeMs 등 제거)
- **타입 정책**: 요청은 문자열, 응답은 적절한 타입으로 구분

// 메모/태그는 Helper 비대상(UI 전용)
// 업로드 큐는 Helper 비대상(UI 전용)

### 📊 성능 지표
- **타이밍 정확도**: 마이크-믹스 길이 차이 20ms 이내
- **메모리 사용량**: 기본 ~50MB, 세그먼트 버퍼 ~11.5MB
- **CPU 사용률**: 유휴 2-3%, 활성 녹음 8-12%

### 🏗️ 아키텍처 특징
- **마이크-마스터**: 마이크 콜백 기준 정확한 타이밍 제어
- **지연 보상**: 60ms 프라임 버퍼로 시스템 오디오 동기화
- **상태 유지**: 리샘플러 및 세그먼트 관리 상태 보존
- **보안**: 메모리 제로화 및 AES256-CBC 암호화

---

이 문서는 Electron과 AudioHelper 간의 통신을 완전히 이해하고 구현하는 데 필요한 모든 정보를 제공합니다. 새로운 기능 추가나 문제 해결 시 이 문서를 참조하여 일관성 있는 구현을 유지하세요.
