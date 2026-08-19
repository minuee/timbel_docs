# 05. React Native 이식 가능성 검토

> 참고용 문서입니다. **현재 우선순위는 Windows 이관**이며, RN 이식은 권장하지 않습니다.

---

## 결론 요약

| 목적 | 판단 |
|---|---|
| 데스크톱 앱을 RN 으로 재작성 | ❌ **비추천** — 기술적으로 가능하나 실익 없음 |
| 모바일(iOS/Android) 앱 추가 | ⚠️ **조건부 가능** — 마이크 전용으로 스펙 축소 시에만 |
| 번들 크기/성능 개선이 목적 | → RN 이 아니라 **Tauri** 검토 |
| 데스크톱+모바일 코드 공유 | → UI 가 아니라 **도메인 로직**을 공유해야 함 |

---

## 전제: 이 앱은 이식하기 유리한 구조다

오디오 엔진이 **별도 프로세스로 완전히 분리**되어 있고
통신이 **JSON-line(stdin/stdout)** 이라, UI 프레임워크를 바꿔도
`AudioHelper.exe` 를 그대로 재사용할 수 있습니다.

즉 **이 앱에서 가장 어려운 부분(오디오)의 이식 비용은 0** 입니다.
이식 비용은 전부 "Electron 이 공짜로 주던 것" 에서 발생합니다.

---

## A. RN 으로 데스크톱 앱 대체 (react-native-macos / react-native-windows)

### 항목별 이식 비용

| 현재 Electron 제공 | RN 데스크톱 | 비용 |
|---|---|---|
| 헬퍼 JSON-line 프로토콜 | ✅ 그대로 재사용 | **0** |
| 오디오 엔진 자체 | ✅ 헬퍼 바이너리 그대로 | **0** |
| `child_process.spawn` + stdio 파이프 | ❌ 없음 → **Turbo Module 직접 작성** (win: `CreateProcess` + 파이프) | 중 (핵심) |
| `fs` (세그먼트 폴더 스캔, 스트림 업로드) | ❌ → 네이티브 모듈 | 중 |
| `better-sqlite3` | ❌ RN용 SQLite 는 모바일 위주, RN-Windows 지원 빈약 | 중 |
| **멀티 윈도우 (4개)** | ⚠️ RN-macOS 멀티윈도우 취약, RN-Windows 부분 지원 | **대** |
| frameless / alwaysOnTop / 트레이 / 창 제약 | ❌ 전부 네이티브 코드 | 대 |
| 업로드 진행률(바이트 단위) | ⚠️ fetch 는 업로드 진행률 없음 → XHR 또는 네이티브 | 소 |
| 커스텀 프로토콜 딥링크 | ⚠️ 네이티브 처리 | 소 |
| 시스템 알림 | ⚠️ 네이티브 | 소 |
| electron-builder (NSIS + 서명 자동화) | ❌ → WiX/MSIX 직접 구성 | 중 |
| **UI (현재 vanilla DOM)** | ❌ **100% 재작성** — React 도 아니라 재사용분 0 | 대 |

### 판단

- 얻는 것: 거의 없음
- 잃는 것: 멀티 윈도우 · 트레이 · 딥링크 · 패키징 · Node API 를 전부 다시 구현
- 추가 리스크: RN-macOS/Windows 는 out-of-tree 라 **코어 RN 대비 버전 랙이 상시 존재**

**견적: 4~7 man-month + 지속적 유지보수 부담**

### 대안

**번들 크기/성능이 목적이라면 Tauri** 가 훨씬 적합합니다.
- 멀티 윈도우 / 트레이 / 딥링크 / **사이드카 프로세스** 모두 1급 지원
  (사이드카 = 정확히 AudioHelper.exe 같은 동봉 실행 파일 실행 기능)
- UI 가 웹 기술이라 현재 HTML/CSS 를 상당 부분 이관 가능
- 번들 수십 MB

---

## B. RN 으로 모바일 앱 (iOS / Android)

### 결정적 제약: 시스템 사운드 캡처가 불가능

이 앱의 존재 이유는 **회의 앱 소리 + 내 목소리 동시 녹음** 인데,
모바일 OS 는 이것을 원천 차단합니다.

**iOS**
- 다른 앱의 오디오를 캡처하는 공개 API가 **없습니다.**
- ReplayKit Broadcast Upload Extension 으로 앱 오디오를 받는 경로가 있으나
  - 사용자가 매번 "방송 시작" 을 눌러야 함
  - 통화 앱이 오디오 세션을 배타적으로 점유하므로 회의 소리는 못 얻음
- → `MicPlusSystem` / `SystemOnly` 재현 **불가**

**Android**
- `MediaProjection` + `AudioPlaybackCapture` (API 29+) 로 가능은 함
- 그러나 **캡처 대상 앱이 `AllowedCapturePolicy` 로 허용해야만** 잡힘
- `USAGE_VOICE_COMMUNICATION` 스트림은 규격상 캡처 대상에서 제외
- 회의 앱들은 대개 캡처를 차단
- → 실전에서 **실패**

### 나머지는 문제없음

| 항목 | RN 모바일 |
|---|---|
| 마이크 녹음 (16k/mono/PCM16) | ✅ 네이티브 모듈 (AVAudioEngine / AudioRecord) |
| 3시간 백그라운드 녹음 | ✅ iOS audio background mode / Android foreground service |
| 3분 세그먼트 + AES-256 | ✅ |
| SQLite | ✅ op-sqlite 등 성숙 |
| 진행률 있는 multipart 업로드 | ✅ react-native-blob-util |
| 딥링크 인증 | ✅ Linking |
| 시스템 알림 | ✅ notifee 등 |
| 오프라인 재시도 큐 | ✅ |

### 판단

**마이크 전용 녹음기**로 스펙을 재정의하면 가능합니다. **견적 2~3 man-month.**
단 이것은 "동일한 앱" 이 아니라 **기능이 축소된 자매 앱**입니다.

---

## C. 코드 공유를 원한다면

RN 데스크톱을 도입해도 UI 코드 공유 이득은 크지 않습니다
(현재 UI 가 React 도 아닌 vanilla DOM 이라 어차피 전면 재작성).

**현실적인 공유 대상은 UI 가 아니라 도메인 로직입니다:**

- 세그먼트 정책 (길이/크기 계산, 롤오버 조건)
- 업로드 / 재시도 큐 상태 머신
- DB 스키마 및 마이그레이션
- 딥링크 인증 플로우
- 헬퍼 JSON-IPC 타입 정의 및 클라이언트

이것들을 순수 TypeScript 패키지로 분리하면
Electron / RN / Tauri 어디에 얹어도 재사용됩니다.
**이 작업은 RN 도입 여부와 무관하게 지금 해도 이득입니다.**

---

## D. 전제 조건

어떤 경로를 택하든 **[04번 문서 B-1](04-알려진-이슈.md) (macOS 헬퍼 소스 심볼릭 링크)
은 먼저 해결**해야 합니다.

이식의 대전제가 "헬퍼를 그대로 재사용한다" 인데,
헬퍼 소스가 저장소에 없으면 그 전제가 성립하지 않습니다.

Windows 는 소스가 전부 있으므로 이 문제에서 자유롭습니다.
