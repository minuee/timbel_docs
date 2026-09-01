# 화상회의 음성 캡처 & 다중 노드 녹음 (SystemOnly 모드)

> 작성일: 2026-09-01
> 대상: Zoom / Webex / Teams / Google Meet 등 외부 화상회의 시스템의 **상대방 목소리**를
> 독립된 녹음 노드로 확보하여, 여러 참석자의 녹음을 하나의 회의록으로 머지하기 위한 설계와 구현 정리.

---

## 1) 요구사항과 흔한 오해

### 요구사항
회의록 서비스는 웹/모바일/PC 앱에서 **최대 5명까지 각자 녹음**한 뒤, 이를 머지해 하나의 회의록을 만든다.
여기에 더해 **화상회의 너머의 원격 참석자 음성**도 하나의 노드로 확보하고 싶다.

즉 내 PC에 Zoom을 띄워두고, **그 Zoom에서 나오는 상대방 목소리를 단독 노드**로 녹음한 뒤
다른 참석자들의 녹음과 함께 머지하는 구조다.

### 오해: "Zoom을 마이크로 인식시킨다"
이렇게 표현하면 보통 **가상 오디오 드라이버**(VB-Cable, BlackHole 같은 커널 수준 장치)를 직접 만드는 것을 떠올린다.
이건 커널 확장 / 드라이버 서명까지 필요해 난이도와 배포 비용이 매우 높다.

**하지만 우리가 필요한 건 그게 아니다.**

### 실제로 필요한 것: 시스템 오디오 루프백 캡처
Zoom 상대방 목소리는 결국 **내 PC의 스피커로 출력**된다.
그 출력을 OS가 제공하는 정식 API로 가로채면 된다.

| OS | API | 추가 드라이버 |
|---|---|---|
| Windows | WASAPI Loopback (`AUDCLNT_STREAMFLAGS_LOOPBACK`) | 불필요 |
| macOS | ScreenCaptureKit (`SCStream` audio) | 불필요 (화면기록 권한만) |

**핵심: 앱별 연동이 전혀 필요 없다.**
Zoom / Webex / Teams / Meet / 유튜브 무엇이든, 스피커로 나가는 소리는 전부 동일하게 잡힌다.
회의 플랫폼 SDK 연동이나 봇 참가 방식도 필요 없다.

> 참고: 마이크로 스피커 소리를 다시 받는 방식(에어 갭)은 에코·주변소음 때문에 품질이 나쁘다.
> 이 앱은 그 방식을 쓰지 않는다.

---

## 2) 이 앱에서의 위치

이 앱은 **처음부터 3가지 캡처 모드**로 설계되어 있다.
(`docs/recording_architecture_mac_windows_v3.md` §3 참고)

| 모드 | 저장 대상 | 용도 |
|---|---|---|
| `MicOnly` | 마이크만 | 대면 회의, 내 발화만 |
| `MicPlusSystem` | 마이크 + 시스템 | 기본값. 나 + 회의 상대방을 한 파일로 |
| `SystemOnly` | **시스템만** | **← 원격 참석자 노드. 이번 작업의 대상** |

### SystemOnly = MicTimed
`SystemOnly`는 시스템 오디오만 저장하지만, **마이크도 함께 캡처한다.**
마이크를 **타임라인 시계(master clock)** 로 사용해 연속된 타임라인을 보장하기 위해서다.
재생이 없거나 뮤트여도 갭/클릭 없이 무음이 채워진다.

> 그래서 **SystemOnly에서도 마이크 장치는 반드시 필요하다.** (사용 가능한 마이크가 없으면 시작 불가)

---

## 3) 작업 전 상태

| 계층 | 상태 |
|---|---|
| 설계 문서 | 3개 모드 모두 정의됨 ✅ |
| Windows 헬퍼 | `SystemOnly` 구현 완료 ✅ (`AudioHelper.cpp` 믹싱부에서 micGain=0) |
| macOS 헬퍼 | ❌ 커맨드 검증 목록에만 존재. 녹음 시작 시 `MicPlusSystem`으로 **하드코딩** |
| UI | ❌ 3곳 모두 `MicPlusSystem` 하드코딩. 모드 선택 UI 없음 |
| UI (출력 장치) | ❌ 헬퍼가 `renderDevices`를 내려주는데 UI가 사용하지 않음 |

즉 **Windows는 이미 동작 가능한 상태였고, macOS와 UI가 막고 있었다.**

---

## 4) 이번 작업 내역

### 4-1. macOS 헬퍼 — SystemOnly 활성화
`src/helpers/macos/AudioHelper/AudioHelper/AudioHelperController.swift`

1. **모드 배선**
   - `start` 커맨드에 모드 검증 추가 (`start_test`와 동일 규칙)
   - `start()` 시그니처에 `mode` 파라미터 추가, 호출부에서 `cmd.mode` 전달
   - `self.currentMode = "MicPlusSystem"` 하드코딩 제거
   - `mode` 필드는 이미 `JSONModels.swift`에 정의되어 있었음 (파싱만 되고 전달이 누락된 상태)

2. **믹싱에 모드별 게인 적용** (`tryMixAndBuffer()`)
   ```swift
   // 변경 전
   let mixed = (sysBufferF32[i] + micBufferF32[i]) / 2.0

   // 변경 후
   let mixed = (sysBufferF32[i] * sysGain + micBufferF32[i] * micGain) * norm
   ```

3. **⚠️ -6dB 감쇠 함정 해결**
   Windows는 `mic + sys` **합산**인데 macOS는 `(mic + sys) / 2` **평균**이었다.
   여기서 게인만 0으로 죽이면 단일 소스 모드에서 소리가 **절반(-6dB)** 으로 줄어든다.
   → **활성 소스 개수로 정규화**하도록 변경.
   - `MicPlusSystem`: `/2` (기존 동작 그대로 유지 — 회귀 없음)
   - `SystemOnly` / `MicOnly`: `/1` (감쇠 없음)

4. **무음 감지를 모드 인식하도록 수정** (`effectiveSilenceRms()`)
   기존에는 `max(마이크 RMS, 시스템 RMS)`로 판정했다.
   `SystemOnly`에서 회의 소리가 없는데 내가 말하고 있으면 "무음 아님"으로 오판정되어,
   **캡처 대상을 잘못 골라 무음이 녹음되는 상황을 놓친다.**
   → 현재 모드에서 실제로 저장되는 소스만 반영하도록 변경.
   (Windows는 믹스 출력 버퍼로 판정하므로 원래 모드가 반영된다. 그 동작에 맞춤)

5. **스레드 안전성** (`captureModeCode`)
   `currentMode`(String)는 MainActor에서 갱신되는데, 믹싱/레벨 콜백은 `audioQueue`에서 읽는다.
   String을 그대로 공유하면 데이터 레이스가 되므로 **워드 크기 정수 사본**을 함께 유지하도록 분리.

### 4-2. UI — 모드 선택 + 출력 장치 선택
- `src/renderer/index.html` — "녹음 대상" 셀렉트 + 도움말 툴팁, 스피커 선택 행(기본 숨김), 안내 문구 영역
- `src/renderer/styles/micTest.css` — 관련 스타일
- `src/renderer/index.js`
  - `getCaptureMode()` / `getRenderDeviceId()` — `localStorage` 영속화, 잘못된 값은 기본값으로 복구
  - `start_test`의 하드코딩 제거
  - 마이크/모드/스피커 변경 시 `stop_test → start_test` 재시작 로직을 `restartTest()`로 통합
  - `SystemOnly` 선택 시 안내 문구 노출
- `src/renderer/scripts/recording.js` — `start` 커맨드가 저장된 모드/출력 장치를 사용

**UI 최종 형태**
```
녹음 대상:  [ 내 목소리 + 회의 소리 ▾ ]   ← MicPlusSystem / MicOnly / SystemOnly
마이크:     [ MacBook Pro 마이크    ▾ ]
시스템 사운드                              (레벨미터)
스피커:     [ 기본 출력 장치        ▾ ]   ← Windows에서만 표시
```

### 4-3. 스피커 선택이 Windows 전용인 이유
- **Windows**: `list_devices`가 `renderDevices`를 함께 내려주고, `start`/`start_test`가 `render` 파라미터를 받는다.
- **macOS**: ScreenCaptureKit이 **시스템 믹스를 통째로** 캡처한다. 출력 장치를 고르는 개념 자체가 없다.

→ UI는 플랫폼 분기 대신 **`renderDevices` 응답 유무로 자동 판별**한다.
목록이 오면 표시, 안 오면 숨기고 `"default"`로 동작. (macOS 헬퍼는 이 필드를 보내지 않음)

> **CSS 주의**: `.sound-group { display: flex }`가 UA의 `[hidden] { display: none }`을 이긴다.
> `.sound-group[hidden] { display: none }`을 명시하지 않으면 macOS에서도 스피커 행이 보인다.

---

## 5) 다중 노드 머지 설계 시 반드시 짚어야 할 문제

캡처 자체보다 **머지 쪽이 실제 난제**다. 아래 4가지는 설계 단계에서 정책을 정해야 한다.

### ① 이중 계상 (double counting)
원격 참석자 A가 **자기 앱으로도 녹음 중**이면, A의 목소리는
`A의 노드` + `내 PC의 SystemOnly 노드` 양쪽에 들어간다. → 회의록에 **중복 발화**가 생긴다.

**대응 방향(택1 또는 병행)**
- SystemOnly 노드는 "다른 노드가 커버하지 않는 참석자"만 담당하도록 운영 규칙 수립
- 머지 단계에서 시간 정렬 + 텍스트 유사도 기반 중복 발화 제거

### ② SystemOnly 노드는 화자 1명이 아니다
Zoom 너머에 3명이 있으면 **3명이 한 트랙에 섞여** 들어온다.
"노드 = 화자 1명"이라는 가정이 이 노드에서만 깨진다.
→ **이 노드에는 화자분리(diarization)를 반드시 적용**해야 한다.

### ③ 잡음 유입
시스템 루프백은 Zoom만이 아니라 **슬랙 알림음, 유튜브, 음악**까지 전부 잡는다.

앱 단위로 좁히려면:
- macOS: `SCContentFilter`로 특정 앱만 필터링 가능
- Windows: 프로세스 루프백 (`ActivateAudioInterfaceAsync` + `AUDIOCLIENT_ACTIVATION_PARAMS`, Win10 20H1+) **별도 구현 필요**

### ④ 노드 간 동기화
노드마다 독립된 클럭이라 **시작 시각 오프셋 + 클럭 드리프트**가 발생한다.
머지 품질은 여기서 결정된다. 서버 기준 시각 스탬프 또는 공통 신호 기반 정렬 전략이 필요하다.

---

## 6) 한 PC를 몇 개 노드로 볼 것인가 (미결정)

현재 구조는 **헬퍼 1개 = 출력 스트림 1개**(믹스된 결과)다.

| 안 | 내용 | 장단점 |
|---|---|---|
| **A안** | 이 PC = 노드 1개 (`SystemOnly`). 로컬 사용자는 폰/웹으로 별도 녹음 | 추가 구현 없음. 이번 작업만으로 즉시 가능 |
| **B안** | 이 PC = 노드 2개 (마이크 트랙 + 시스템 트랙 동시 출력) | 듀얼 트랙 출력 구현 필요. 대신 **같은 시계를 써서 두 트랙이 샘플 단위로 정렬** → 머지 품질 최상 |

> 헬퍼 프로세스를 2개 띄우는 편법보다 **B안(듀얼 트랙)** 을 권장한다.
> 별도 프로세스는 장치 경합과 클럭 분리 문제를 다시 만든다.

**A/B안은 미결정 상태.** 이번 작업은 두 안 모두에 필요한 선행 작업이다.

---

## 7) 검증 필요 항목 (미완료)

> **현재 코드 검증 수준**: Swift 구문 검사(`swiftc -parse`) 및 JS 구문 검사(`node --check`) 통과.
> **전체 빌드 및 실동작 검증은 아직 수행하지 못했다.**

### 빌드 선행 조건
macOS 헬퍼 전체 타입체크/빌드가 아직 안 된 상태다. Xcode 라이선스 미동의로 `xcodebuild`가 막힌다.

```bash
sudo xcodebuild -license          # 라이선스 동의
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

이후 `yarn build-helper`(Windows) / Xcode 빌드(macOS) 진행.

### 테스트 체크리스트
- [ ] macOS `SystemOnly`: 실제 Zoom 통화에서 상대방 목소리만 녹음되는지
- [ ] macOS `SystemOnly`: 내 목소리가 섞이지 않는지
- [ ] macOS `MicPlusSystem`: **기존 녹음과 음량/품질 동일한지 (회귀 확인)**
- [ ] 단일 소스 모드에서 -6dB 감쇠가 없는지 (파형 레벨 비교)
- [ ] 화면기록 권한 거부 시 동작 (무음 이벤트가 뜨는지)
- [ ] `SystemOnly` + 마이크 없음 → `NO_MIC_DEVICE` 정상 반환
- [ ] `SystemOnly`에서 회의 소리가 없을 때 무음 알림이 뜨는지 (내가 말해도 무음 판정되어야 함)
- [ ] Windows: 스피커 선택 드롭다운 표시 및 비기본 출력 장치 캡처
- [ ] macOS: 스피커 선택 행이 **숨겨져 있는지**
- [ ] 모드 변경 후 재시작 없이 즉시 반영되는지
- [ ] 모드 선택이 앱 재실행 후에도 유지되는지

---

## 8) 남은 과제 (후속)

| 항목 | 내용 | 우선순위 |
|---|---|---|
| A/B안 결정 | 한 PC를 노드 1개로 볼지 2개로 볼지 | 높음 |
| 듀얼 트랙 출력 | B안 채택 시 헬퍼가 2개 스트림 출력 | B안 시 높음 |
| 머지 정책 | 이중 계상 / 화자분리 / 동기화 전략 | 높음 |
| 앱 단위 캡처 | Zoom 소리만 골라 담기 (Windows 프로세스 루프백) | 중간 |
| 믹싱 정책 통일 | Windows 합산(`1.0` / `0.7`) vs macOS 평균(`0.5` / `0.5`) 불일치 | 중간 |
| 기능 패리티 | 덕킹 / AEC / 경계 페이드인이 Windows에만 존재 | 중간 |

> **믹싱 정책 불일치 주의**: 이번 작업에서는 회귀를 피하기 위해 `MicPlusSystem`의 기존 동작을
> 플랫폼별로 그대로 유지했다. 두 플랫폼의 음량 특성이 다르므로, 통일 여부는 별도 판단이 필요하다.

---

## 9) 한 줄 요약

> 회사 요구는 무리한 것이 아니라 **이 앱이 원래 그렇게 설계된 것**이다.
> Windows는 이미 되어 있었고, macOS와 UI의 하드코딩만 풀면 되는 작업이었다.
> 진짜 난이도는 캡처가 아니라 **다중 노드 머지 정책**에 있다.
