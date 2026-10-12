# 회의 녹음 앱 아키텍처 & 캡처 헬퍼 명세 (macOS & Windows) — v3

> **목적**  
> 줌/팀즈 등 회의의 **마이크 + 시스템 사운드**를 안정적으로 녹음하고, **STT(16 kHz/mono/PCM16)** 에 바로 투입 가능한 세그먼트를 생성한다.  
> **UI는 Electron(공통)**, **오디오 엔진은 OS별 네이티브 헬퍼(App/EXE, DLL 대안)** 로 분리한다.  
> Flutter에서도 동일한 헬퍼를 Process + JSON-IPC로 재사용한다.

---

## 1) 전체 사용자 흐름 (요약)

1. **녹음 동의** → 권한 안내  
2. **캡처 테스트** → 마이크/시스템 **레벨미터 & 미니 파형** 확인  
3. **캡처 시작**  
4. **무음 관찰(초반 30초)**  
   - 7초 간격 알림(무음 지속 시)  
   - 30초 연속 무음 → **메일 전송**(UI에서 수행)  
5. **녹음 진행**  
   - 레벨/파형 표시, **RAM 보관**  
   - (UI 전용) 타임싱크 메모 입력  
6. **세그먼트 생성(롤오버)**  
   - 시간(예: 30분) 또는 **암호문 크기**(예: 60MB) 도달 시  
   - **AES-256-CBC** 즉시 암호화(**ON/OFF 토글** 지원)  
7. **종료** (업로드는 UI 전용)

---

## 2) 역할 분담

### Electron / Flutter (UI)
- 동의/권한 안내, 캡처 테스트 UI(레벨/파형)
- **모드 선택**: `MicOnly` / `MicPlusSystem` / `SystemOnly(MicTimed)`
- 세그먼트 정책(시간·크기), 게인, 무음 파라미터, 암호화 ON/OFF 설정
- **초반 30초 무음**: 7초 간격 알림 / **30초 지속**: 메일 전송
// 메모/태그는 Helper가 처리하지 않음 (UI 전용)
- (UI 전용) 업로드/재시도 큐, 헬퍼 프로세스 생명주기/복구, 오류 표시

### 네이티브 헬퍼(App/EXE 권장, DLL 대안)
- **장치 열거/선택/테스트**
- **오디오 캡처 & 동기화 & 믹싱** 캡슐화
- **레벨(RMS)/파형/무음 감지** 이벤트 송신
 - **세그먼트 롤오버(시간·암호문 크기 동시 조건)** & **AES-CBC**(ON/OFF)
// 메모/태그 타임라인(사이드카 메타)은 UI/별도 모듈에서 처리
- 일시정지/재개/정지, 오류/통계 이벤트, 장치 변경 복구

---

## 3) 캡처 모드 & 타이밍 모델

### 공통 원칙
- **Shared 모드(Windows)** / **비독점 캡처(macOS)**  
- **마이크 = 마스터 시계**: 마이크 이벤트마다 **고정 블록(예: 20 ms)** 생성  
- 시스템 오디오는 별도 스레드에서 **링버퍼**로 수집 → 마이크 블록 시점에 필요한 만큼 Pop  
- **지터/드리프트 보정**: 링버퍼 목표수위 기반 **게이팅 ASRC(±50~100 ppm)**  
- **경계 클릭 방지**: 언더런/복구·무↔유음 전환 시 **3~5 ms 램프**

### 모드 정의
1) **MicOnly**  
   - 열기: Mic  
   - 믹싱: `out = mic * g_mic` (g_sys=0)

2) **MicPlusSystem**  
   - 열기: Mic + System  
   - 믹싱: `out = mic * g_mic + sys * g_sys`  
   - 시스템 부족분은 램프 후 0으로 스무딩

3) **SystemOnly (MicTimed)**  
   - **핵심**: **System만 저장**하더라도 **Mic을 함께 캡처**해 **타임라인(시계)** 을 공급, **g_mic=0**  
   - 무재생/뮤트/지터에도 **연속 타임라인** 보장 → 무음 주입 분기 단순화 & 클릭/갭 방지

---

## 4) 오디오 파이프라인 & 포맷

- **입력(캡처)**: 장치 **믹스 포맷(Shared)** 로 수신  
  - (Windows: 대개 48 kHz/float/stereo)  
  - (macOS: SCStream/AVAudioEngine가 제공하는 포맷)  
- **내부 정규화**: **48 kHz / float / mono**  
- **출력(저장/전송)**: **16 kHz / mono / PCM16** (STT 최적)

**블록/버퍼 권장값**
```
BLOCK_MS              = 20
RINGBUF_TARGET_MS     = 150      # 기본 120–150ms, 상황에 따라 최대 300ms
RINGBUF_MIN_MS        = 60
RINGBUF_MAX_MS        = 300
FADE_MS               = 4        # 3–5ms 권장
ASRC_ENABLE_THRESH    = 40       # |level-target| ≥ 40ms → ASRC ON
ASRC_DISABLE_THRESH   = 20       # |level-target| ≤ 20ms → ASRC OFF
ASRC_MAX_PPM          = 100
GAIN_MIC              = 1.0
GAIN_SYS              = 0.7
```

---

## 5) 세그먼트 & 암호화

- **조건 동시 지원(먼저 도달 시 롤오버)**  
  - `duration_ms` (예: 30분)  
  - `max_cipher_bytes` (예: 60MB, **암호문 기준**)  
- **블록 경계 절단**: 반드시 **BLOCK_MS** 경계(예: 20ms)에서 자름
- **암호화**: **AES-256-CBC** 스트리밍 / **ON/OFF 토글**(개발 중 OFF)  
  - ON: `...seg0001.pcm` (+ 메타 JSON)  
  - OFF: `...seg0001.raw` (+ 메타 JSON)
- **메타(JSON) 공통 필드(예)**  
  ```json
  {
    "v":1,
    "codec":"PCM_S16LE","sr":16000,"ch":1,"blockMs":20,
    "segmentIdx":1,"startUnixMs":169..., "durationMs":1800000,
    "totalSamples":28800000,
    "encryption":{"enabled":true,"mode":"CBC","iv":"...","tag":"..."}
  }
  ```

**용량 산정 참고**  
- 평문 16 kHz/mono/PCM16 ⇒ **32,000 B/s**  
- 블록 20ms ⇒ **640 B/블록**  
 - CBC 패딩 오버헤드: 세그먼트당 평균 < 16B 가정

---

## 6) IPC (JSON-line) — **MVP** vs **Full**

### MVP (Phase 1–2)
**요청 (UI→헬퍼)**
```json
{ "cmd":"list_devices" }
{ "cmd":"start",
  "mode":"MicOnly|MicPlusSystem|SystemOnly",
  "out":{"sr":16000,"ch":1,"blockMs":20},
  "mic":{"deviceId":"default"} }
{ "cmd":"pause" }
{ "cmd":"resume" }
{ "cmd":"stop" }
```

**이벤트 (헬퍼→UI)**
```json
{ "ev":"level","source":"mic|system|mixed","rms":0.18,"t":12345 }
{ "ev":"progress","seconds":12.5,"samples":200000 }
{ "ev":"error","code":"DEVICE_LOST","message":"..." }
```

### Full (Phase 3–4)
**요청 확장**
```json
{
  "cmd":"start",
  "mode":"MicPlusSystem",
  "out":{"sr":16000,"ch":1,"blockMs":20},
  "gains":{"mic":1.0,"sys":0.7},
  "silence":{"threshold":0.02,"hangoverMs":500,
             "earlyWindowMs":30000,"nudgeIntervalMs":7000,"mailAfterMs":30000},
  "segmenting":{"duration_ms":1800000,"max_cipher_bytes":60000000,"align_to_block":true},
  "encryption":{"enabled":true,"mode":"AES-256-CBC","keyRef":"env:REC_AES_KEY","rotatePerSegment":true},
  "mic":{"deviceId":"default"},
  "files":{"dir":"C:/rec/","base":"meeting_2025-09-04"},
  "waveform":{"windowMs":5000,"downsample":64}
}
```

**이벤트 확장**
```json
{ "ev":"waveform","t":12500,"amplitudes":[...]}
{ "ev":"silence","state":"early|on|off|sustained","elapsedMs":14000 }
{ "ev":"rollover","segmentIndex":3,"pathEncrypted":"...seg0003.wav.enc","metaPath":"...seg0003.meta.json" }
```

---

## 7) OS별 구현 포인트

### 7.1 **무재생/뮤트 시 콜백·데이터 동작 차이 (중요)**
- **Windows (WASAPI Loopback)**  
  - 시스템 오디오가 **재생되지 않거나 뮤트**일 경우, **이벤트(콜백) 발생이 드물거나 없음**, 또는 `SILENT` 플래그의 패킷이 길게 이어질 수 있음.  
  - 결과적으로 **Loopback만 기준으로는 타임라인이 중단**될 수 있으므로, **반드시 “마이크=마스터 시계”** 로 고정하고 시스템 경로는 **링버퍼 + (부족분 램프 후 0)** 로 보완해야 함.  
  - *SystemOnly* 시나리오에서도 **Mic을 함께 캡처(g_mic=0)** 하여 **연속 타임라인**을 확보하는 것을 권장.

- **macOS (ScreenCaptureKit/AVAudio)**  
  - **재생 없음/뮤트** 상황에서도 **콜백/오디오 샘플이 연속으로 도착(대개 무음 샘플)**하는 동작을 보이며, 타임라인이 끊기지 않는 경우가 일반적임.  
  - 그럼에도 플랫폼/버전/권한 설정에 따라 드문 예외가 있을 수 있으므로, **Windows와 동일하게 “마이크=마스터 시계 + 링버퍼” 정책**을 유지하면 OS 간 일관성과 강건성이 높아짐.

### Windows
- **WASAPI Shared + EventCallback**  
  - System: Loopback / Mic: 선택 장치  
- **마이크=마스터**, System은 링버퍼 → 부족분 램프 후 0  
- **MMCSS(“Pro Audio”)** 스레드 우선순위  
- **장치 변경 감지** → 무중단 재초기화 (시스템 오디오만 자동 전환)
  - 마이크: 선택 마이크가 제거/비활성 되면 즉시 중지하며, 다른 마이크로 자동 전환하지 않음(폴백 금지)
  - 시스템(루프백): 기본 장치 변경을 자동 추종하여 재캡처

### macOS
- **ScreenCaptureKit(SCStream)**: 시스템 오디오(+화면)  
- **AVAudioEngine/AudioUnit**: 마이크  
- **마이크=마스터**, System 링버퍼/램프/ASRC 정책 동일  
- **권한(TCC)**: **화면 녹화(Screen Recording)**, **마이크** 권한 필요 (Info.plist 설명)  
- **배포**: 서명/하든드 런타임/공증(Notarization)  
- **구버전 macOS(<13)**: 가상 오디오 드라이버(BlackHole 등) 폴백 or 지원 범위 명시

---

## 8) Electron & Flutter 연동

- **EXE/App + IPC 권장**:  
  - Electron: `child_process.spawn()` + stdin/stdout  
  - Flutter: `Process.start()` + Stream(utf8 line)  
- **패키징**: 앱 리소스 폴더에 헬퍼 동봉, 실행 경로 동적 결정  
- **(선택)** Flutter 플러그인 래퍼: `MethodChannel(EventChannel)` 로 IPC를 감싸 재사용성↑

---

## 9) 개발 단계(Phase) 제안

- **P1**: MVP 캡처( MicOnly, SystemOnly(MicTimed) ), 레벨/프로그레스 이벤트  
- **P2**: MicPlusSystem 믹싱, 파형 이벤트  ✅ **완료 (2025-09-12)**
- **P3**: 세그먼트(시간·크기) + AES-CBC(ON/OFF), 롤오버 이벤트  
- **P4**: 무음 감지(초기 30초 알림/30초 메일 트리거)

### P2 구현 완료 상세 (2025-09-12)

**구현된 기능:**
- ✅ **마이크-마스터 믹싱**: 마이크 콜백을 기준으로 20ms 블록 단위 실시간 믹싱
- ✅ **시스템 오디오 지연 보정**: 60ms 프라임 버퍼로 시스템 오디오 지연 보상
- ✅ **무음 프레임 처리**: 마이크 무음 콜백 시에도 0 샘플을 FIFO에 푸시하여 타임라인 유지
- ✅ **상태 유지 리샘플러**: 누적 위상 오차 방지를 위한 상태 유지 리샘플링
- ✅ **드레인 모드**: 정지 시 잔여 60ms 프라임 버퍼까지 완전 방출
- ✅ **디버그 WAV 출력**: 마이크/시스템/믹스 각각의 원시 데이터 저장 (16kHz/mono/PCM16)
- ✅ **타이밍 정확도**: 마이크와 믹스 파일 길이 차이 20ms 이내 달성

**핵심 해결사항:**
- **타임라인 동기화**: 마이크를 마스터 시계로 사용하여 시스템 오디오 지연/누락 보상
- **데이터 무결성**: 무음 구간에서도 연속적인 타임라인 유지 (0 패딩 없음)
- **정확한 믹싱**: 실시간 블록 단위 믹싱으로 STT 호환성 보장

---

## 10) 테스트 체크리스트

- **MicOnly**: 장기 녹음 → 총 샘플 수 = 이론값  
- **MicPlusSystem**: 무재생/뮤트 ↔ 재생 반복 → **클릭/틱 없음**  ✅ **검증 완료**
- **SystemOnly(MicTimed)**: 시스템 무재생 구간 **자연 무음**, 재개 경계 클릭 없음  
- **세그먼트**: 시간·크기 동시 조건에서 **먼저 도달** 정확 롤오버, 암호화 ON/OFF 모두 길이/샘플 수 일관  
- **일시정지/재개** 경계 노이즈 없음  
- **장치 변경/고부하**에서도 블록 누락·타임라인 뒤틀림 없음  
// 업로드 실패/재시도 큐는 UI 전용

### P2 검증 완료 항목 (2025-09-12)

**✅ MicPlusSystem 믹싱 검증:**
- 10초/20분 장기 녹음에서 마이크-믹스 길이 차이 20ms 이내 달성
- 시스템 오디오 무재생/뮤트 구간에서도 연속적인 타임라인 유지
- 실시간 믹싱으로 STT 호환성 보장 (16kHz/mono/PCM16)
- 디버그 WAV 파일 정상 생성 (마이크/시스템/믹스 각각)
- 드레인 모드로 정지 시 데이터 손실 없음

---

## 11) 빠른 파라미터 표 (권장 초기값)

| 항목 | 값/범위 | 비고 |
|---|---|---|
| 블록 길이 | 20 ms | 레이턴시/안정성 절충 |
| 링버퍼 목표 | 150 ms | 적응형 120–300 ms |
| 램프 | 3–5 ms | 경계 클릭 방지 |
| ASRC 게이트 | ON ≥ 40 ms / OFF ≤ 20 ms | ±50~100 ppm |
| 출력 포맷 | 16 kHz / mono / PCM16 | STT 최적 |
| 게인 | mic=1.0, sys=0.7 | 변경 시 램핑 |
| 암호화 | AES-256-CBC | ON/OFF 토글 |
| 세그먼트 | 30분 & 60MB 예시 | 먼저 도달 시 롤오버 |

---

### 결론
- **Windows**는 무재생/뮤트 시 **Loopback 콜백/데이터가 누락**될 수 있으므로, **마이크=마스터 + 링버퍼 + 램프/ASRC**가 필수입니다.  
- **macOS**는 대체로 **무음 샘플이 연속 공급**되어 타임라인이 유지되지만, 일관성을 위해 동일 정책을 유지합니다.  
- Electron/Flutter 모두 **동일한 JSON-IPC** 를 사용하면, **맥·윈 공통 로직**과 **재사용성**이 극대화됩니다.

---

## 12) 현재 구현 상태 (2025-09-12)

### ✅ 완료된 기능
- **Windows AudioHelper**: 마이크+시스템 오디오 캡처 및 실시간 믹싱
- **마이크-마스터 아키텍처**: 마이크 콜백 기준 20ms 블록 단위 믹싱
- **타임라인 동기화**: 60ms 프라임 버퍼로 시스템 오디오 지연 보상
- **상태 유지 리샘플러**: 누적 위상 오차 방지
- **드레인 모드**: 정지 시 잔여 데이터 완전 방출
- **디버그 WAV 출력**: 원시 데이터 저장 및 검증
- **JSON IPC**: Electron과의 명령/이벤트 통신

### 🔄 다음 단계 (P3)
- **세그먼트 롤오버**: 시간/크기 기반 자동 분할
- **AES-256-GCM 암호화**: ON/OFF 토글 지원
- **메타데이터 관리**: 세그먼트별 정보 저장

---

## 13) 장치 변경 감지 및 자동 재연결 (2025-09-14)

### ✅ 구현 완료된 기능

**장치 변경 감지 시스템:**
- `IMMNotificationClient` 인터페이스 구현으로 Windows 시스템의 오디오 장치 변경을 실시간 감지
- 기본 출력 장치 변경 시 자동으로 콜백 호출하여 UI에 알림

**자동 재연결 메커니즘:**
- 장치 변경 감지 시 현재 시스템 오디오 캡쳐를 안전하게 중지
- 새로운 기본 출력 장치로 자동 재연결 및 WASAPI 클라이언트 재초기화
- 마이크 캡쳐는 계속 유지되어 전체 녹음이 중단되지 않음

**무중단 전환:**
- `deviceChangeRequested` 플래그를 통한 비동기 처리
- SystemCaptureThread에서 주기적으로 장치 변경 요청 확인
- 장치 재연결 실패 시에도 마이크만으로 계속 녹음 가능

### 🔧 동작 방식

1. **초기화**: 현재 기본 출력 장치 ID 저장 및 변경 알림 등록
2. **감지**: 사용자가 스피커 → 이어폰으로 변경 시 `OnDefaultDeviceChanged` 콜백 호출
3. **재연결**: SystemCaptureThread에서 변경 요청 확인 후 처리
4. **전환**: 기존 클라이언트 정리 → 새 디바이스 연결 → 캡쳐 재시작

### 📋 테스트 시나리오

**시스템 사운드 캡쳐 중 장치 변경:**
- 스피커 → 이어폰 전환
- 이어폰 → 스피커 전환  
- USB 헤드셋 → 내장 스피커 전환
- Bluetooth 장치 연결/해제

**예상 로그 출력:**
```
Default render device changed to: [새 디바이스 ID]
System device change requested
Processing system device change
Switching to new system device: [새 디바이스 ID]
System device reconnected successfully
```

**UI 이벤트:**
```json
{"ev":"device_reconnected","type":"system"}
```

### 🎯 해결된 문제

- **기존 문제**: 시스템 사운드를 스피커로 출력하다가 이어폰으로 변경하면 캡쳐가 중단됨
- **해결 방법**: 장치 변경을 실시간 감지하고 자동으로 새 장치에 재연결
- **결과**: 캡쳐 중단 없이 부드러운 장치 전환 가능

### 🔄 다음 개선 사항

- **장치별 설정 저장**: 사용자가 선택한 특정 장치로 고정 연결 옵션
- **재연결 실패 복구**: 여러 번의 재연결 시도 및 폴백 전략
- **장치 상태 모니터링**: 장치 연결 상태 지속적 확인

---

## 14) 마이크 장치 변경 감지 및 녹음 중단 (2025-09-14)

### ✅ 구현 완료된 기능

**마이크 장치 변경 감지:**
- `IMMNotificationClient::OnDeviceStateChanged` 구현으로 마이크 장치 상태 변경을 실시간 감지
- 마이크 장치가 제거되거나 비활성화될 때 즉시 감지

**녹음 중단 및 데이터 보존:**
- 마이크 장치 변경 감지 시 전체 녹음을 중단하고 사용자에게 알림
- 중단 시점까지 캡쳐된 오디오 데이터는 즉시 세그먼트로 저장
- 사용자가 마이크 문제를 인지하고 녹음을 재개할 수 있도록 안내

**에러 이벤트 전송:**
- UI에 마이크 장치 변경 에러 이벤트 전송
- 구체적인 에러 코드와 메시지로 사용자에게 상황 설명

### 🔧 동작 방식

1. **초기화**: 현재 사용 중인 마이크 장치 ID 저장
2. **감지**: 마이크 장치가 제거되거나 비활성화될 때 `OnDeviceStateChanged` 콜백 호출
3. **중단**: 녹음 중단 및 현재까지의 데이터 즉시 저장
4. **알림**: UI에 에러 이벤트 전송하여 사용자에게 상황 알림

### 📋 테스트 시나리오

**마이크 장치 변경 시나리오:**
- USB 마이크를 기본 장치로 설정 후 녹음 시작
- 녹음 중에 USB 마이크를 물리적으로 제거
- 마이크 장치를 비활성화 (Windows 사운드 설정에서)
- 마이크 드라이버 오류로 장치가 사용 불가 상태로 변경

**예상 로그 출력:**
```
Microphone device lost or disabled: [장치 ID]
Recording stopped due to microphone device change
Finalizing current segment on stop
```

**UI 이벤트:**
```json
{"ev":"error","code":"MIC_DEVICE_LOST","message":"마이크 장치가 제거되거나 비활성화되어 녹음을 중단합니다."}
```

### 🎯 해결된 문제

- **기존 문제**: 마이크가 제거되어도 녹음이 계속 진행되어 시스템 사운드만 녹음됨
- **해결 방법**: 마이크 장치 변경을 감지하고 즉시 녹음 중단
- **결과**: 사용자가 마이크 문제를 인지하고 적절한 조치를 취할 수 있음

### 📊 데이터 보존 정책

- **중단 시점까지의 데이터**: 즉시 세그먼트로 저장 (3분 미만이어도 저장)
- **세그먼트 관리**: 테스트 모드와 실제 녹음 모드 모두에서 동일하게 적용
- **파일 저장**: `test_segments` 폴더에 암호화된 세그먼트 파일 생성

### 🔄 다음 개선 사항

- **저장 공간 모니터링**: 디스크 용량 부족 시 경고 및 녹음 중단
- **배터리 레벨 체크**: 배터리 부족 시 경고 및 파워 오프 시 녹음 중단
- **장치 복구 감지**: 마이크 장치가 다시 연결되면 자동으로 녹음 재개 옵션

---

## 15) 세그먼트 관리 및 AES256 암호화 (2025-09-15)

### ✅ 구현 완료된 기능

**세그먼트 기반 파일 저장:**
- 샘플 프레임 기반 세그먼트 관리 (3분 = 2,880,000 샘플)
- 세그먼트 완료 시 자동으로 파일 저장 및 다음 세그먼트 시작
- 사용자 중지 시 미완성 세그먼트도 즉시 저장

**파일 저장 구조(현재):**
```
{output_directory}/
└── {sessionId}/
    ├── {sessionId}_0.pcm
    ├── {sessionId}_1.pcm
    └── {sessionId}_2.pcm
```

**AES256-CBC 암호화:**
- Windows CryptoAPI (BCrypt)를 사용한 실제 AES256-CBC 암호화
- 테스트용 고정 키 사용 (운영 환경에서는 안전한 키 관리 필요)
- 파일 구조: `IV(12바이트) + 암호화데이터 + 태그(16바이트)`

**암호화 ON/OFF 토글:**
- `encryption_enabled: "true"` → AES256-CBC 암호화, `.pcm` 파일
- `encryption_enabled: "false"` → Raw PCM 저장, `.raw` 파일
- UI에서 실시간으로 암호화 설정 변경 가능

### 🔧 동작 방식

1. **세그먼트 생성**: 3분(2,880,000 샘플) 단위로 오디오 데이터 수집
2. **암호화 처리**: 설정에 따라 AES256-CBC 암호화 또는 Raw 저장
3. **파일 저장**: 세션ID 폴더에 인덱스 기반 파일명(`{sessionId}_{n}.pcm`)으로 저장
4. **이벤트 전송**: UI에 `segment_ready` 이벤트로 파일 정보 전송

### 📋 테스트 시나리오 (현재 포맷)

**Raw 저장 테스트:**
```json
{
  "cmd": "set_segment_config", 
  "encryption_enabled": "false"
}
```
- 결과: `recordings/{sessionId}/{sessionId}_{n}.raw` 파일 생성
- 파일 크기: 원본과 동일 (PCM 데이터만)

### 🎯 해결된 문제

- **기존 문제**: 타이머 기반 세그먼트로 인한 파일 크기 불일치
- **해결 방법**: 샘플 프레임 기반 세그먼트로 일관된 파일 크기 보장
- **기존 문제**: 암호화 설정이 무시되고 항상 XOR 암호화 적용
- **해결 방법**: 실제 AES256-CBC 암호화 구현 및 설정 기반 분기

### 📊 세그먼트 관리 상세

**세그먼트 크기 계산:**
- 16kHz × 60초 × 3분 = 2,880,000 샘플
- 16비트 PCM = 5,760,000 바이트 (5.76MB)
- AES256-CBC 패딩 오버헤드: 평균 < 16바이트/세그먼트

**파일명 규칙(현재):**
- 형식: `{sessionId}_{n}.{pcm|raw}`
- 예시: `uuid-1234/uuid-1234_0.pcm`
- 확장자: `.pcm`(원본 PCM), 필요 시 `.raw`

### 🔄 다음 개선 사항

- **키 관리**: 환경변수 또는 안전한 키 저장소에서 키 로드
- **키 로테이션**: 세그먼트별 다른 키 사용 옵션
- **압축**: 암호화 전 데이터 압축으로 저장 공간 절약
- **무결성 검증**: 파일 저장 후 체크섬 검증

---

## 16) 프로젝트 빌드 및 배포 (2025-09-21)

### ✅ 구현 완료된 기능

**Electron 빌드 시스템:**
- `electron-builder`를 사용한 Windows 설치 파일 생성
- NSIS 기반 설치 프로그램 (사용자 설치 경로 선택 가능)
- AudioHelper.exe를 포함한 리소스 패키징

**빌드 구성:**
```json
{
  "build": {
    "appId": "com.example.meeting-recorder",
    "productName": "Meeting Recorder",
    "extraFiles": [
      {
        "from": "src/helpers/windows/AudioHelper.exe",
        "to": "helpers/windows/AudioHelper.exe"
      }
    ]
  }
}
```

**배포 파일:**
- `Meeting Recorder Setup 1.0.0.exe`: Windows 설치 파일
- `win-unpacked/`: 압축 해제된 실행 파일들
- AudioHelper.exe가 올바른 위치에 포함됨

### 📁 프로젝트 구조 현황

**소스코드 구조:**
```
src/
├── main/
│   ├── main.js          # Electron 메인 프로세스
│   └── preload.js       # 보안 컨텍스트 브리지
├── renderer/
│   ├── index.html       # UI 메인 화면
│   ├── app.js          # UI 로직
│   └── styles.css      # 스타일시트
└── helpers/
    └── windows/
        ├── AudioHelper.exe    # 컴파일된 오디오 헬퍼
        ├── AudioHelper.cpp    # 메인 구현
        ├── AudioHelper.h      # 헤더 파일
        ├── Logger.cpp/h       # 로깅 시스템
        ├── WavWriter.cpp/h    # WAV 파일 작성
        └── build/             # CMake 빌드 출력
```

**녹음 파일 구조:**
```
recordings/
└── {sessionId}/
    ├── {sessionId}_{n}.pcm  # 암호화된 세그먼트
    └── {sessionId}_{n}.raw  # 암호화되지 않은 세그먼트
```

### 🔧 현재 동작 상태

**실시간 오디오 캡처:**
- 마이크 + 시스템 사운드 동시 캡처 ✅
- 20ms 블록 단위 실시간 믹싱 ✅
- 48kHz → 16kHz 리샘플링 ✅
- 마이크-마스터 아키텍처로 정확한 타이밍 보장 ✅

**세그먼트 관리:**
- 3분(2,880,000 샘플) 단위 자동 분할 ✅
- AES256-CBC 암호화/비암호화 토글 ✅
- 샘플 정확도 기반 파일 크기 일관성 ✅

**장치 관리:**
- 시스템 오디오 장치 변경 자동 감지 및 재연결 ✅
- 마이크 장치 변경 시 녹음 중단 및 데이터 보존 ✅
- IMMNotificationClient 기반 실시간 장치 모니터링 ✅

### 📊 성능 지표 (2025-09-19 테스트 기준)

**타이밍 정확도:**
- 마이크-믹스 파일 길이 차이: 20ms 이내
- 블록 처리 지연: 평균 15ms
- 세그먼트 경계 정확도: 샘플 단위 정밀

**메모리 사용량:**
- 기본 메모리 사용: ~50MB
- 세그먼트 버퍼: ~11.5MB (3분 버퍼)
- 링버퍼 오버헤드: ~1MB

**CPU 사용률:**
- 유휴 상태: ~2-3%
- 활성 녹음: ~8-12%
- 장치 재연결: 일시적 ~15%

### 🔄 다음 개발 단계 (P4)

**무음 감지 시스템:**
- 초기 30초 무음 감지 및 7초 간격 알림
- 30초 지속 무음 시 이메일 발송 트리거
- 무음 임계값 및 행오버 시간 설정

// 업로드/재시도 큐는 Helper 비대상(UI 전용)

## 17) 디스크 용량 모니터링 및 세그먼트 가드 (2025-09-26)

### ✅ 구현 완료된 기능
- **디스크 상태 이벤트(disk_status)**: 1초 주기 여유 공간 전송(상태 변화 시에만, critical은 매초)
  - `ok` (≥500MB), `low` (≥50MB), `critical` (<50MB)
  - 필드: `{"ev":"disk_status","status":"ok|low|critical","free_bytes":123456789}`
- **임계치 가드**: 세그먼트 저장 시 여유 공간이 50MB 미만이면
  - `DISK_SPACE_CRITICAL` 에러 전송
  - 다음 세그먼트 경계에서 안전 중지 예약(`stopAtBoundary=true`)
  - RAW 저장 오픈 실패 시 `DISK_WRITE_OPEN_FAILED` 에러 전송

### 📋 테스트 시나리오
- 충분 공간(≥500MB)에서 녹음 시작 → `disk_status: ok` 수신 확인
- 공간을 줄여 100MB 근처 → `low` 전이 확인, 녹음 지속
- 50MB 미만으로 감소 → `critical` 지속 송신, 다음 세그먼트 경계에서 중지 확인
- 파일 핸들 오픈 실패 상황 모의 → 에러 이벤트 수신 확인

### 🔎 로그/이벤트 예시
```
INFO  Disk status: ok → low
WARN  Disk space critical: <50MB remaining
{"ev":"disk_status","status":"critical","free_bytes":47185920}
{"ev":"error","code":"DISK_SPACE_CRITICAL","message":"디스크 여유 공간이 50MB 미만입니다. 다음 세그먼트 경계에서 중지합니다."}
```
