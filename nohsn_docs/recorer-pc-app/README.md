# newDocs — Windows 이관 작업 문서

> 작성일: 2026-08-18
> 대상: `timbloRecApp` (recording-pc-app) 을 **Windows에서 동작시키는 것**
> 배경: 기존 `docs/` 는 macOS 배포 기준으로 작성되어 있어, Windows 관점으로 재정리함

---

## 한 줄 결론

**현재 저장소 소스만으로 Windows 빌드·녹음이 가능합니다.**
새로 개발할 것은 없고, **빌드 환경 구성 → 검증 → 배포 서명** 단계입니다.

가장 큰 걸림돌로 보이던 WebRTC 프리빌트 라이브러리는 **필수가 아닙니다.**
코드에 자체 AEC 폴백(NLMS)이 이미 구현되어 있습니다. → [02번 문서](02-Windows-빌드-가이드.md)

---

## 문서 목록

| 문서 | 내용 | 언제 보나 |
|---|---|---|
| [01-프로젝트-분석.md](01-프로젝트-분석.md) | 아키텍처, 오디오 파이프라인, 데이터 흐름 전반 | 구조 파악할 때 |
| [02-Windows-빌드-가이드.md](02-Windows-빌드-가이드.md) | **Windows 랩탑에서 실제로 따라할 절차** | 내일 제일 먼저 |
| [03-Windows-검증-체크리스트.md](03-Windows-검증-체크리스트.md) | 단계별 동작 검증 항목 | 빌드 성공 후 |
| [04-알려진-이슈.md](04-알려진-이슈.md) | 코드에서 발견한 실제 문제/리스크 | 문제 생겼을 때 + 이후 개선 |
| [05-ReactNative-검토.md](05-ReactNative-검토.md) | RN 이식 가능성 검토 결과 | 참고용 |
| [06-빌드-산출물과-실행-형태.md](06-빌드-산출물과-실행-형태.md) | 빌드하면 어떤 앱이 나오는지 (Edge 와 비교) | 배포 형태 정할 때 |
| [07-macOS-헬퍼-복구-작업기록.md](07-macOS-헬퍼-복구-작업기록.md) | **[2026-08-19]** macOS 소스 확보 · 녹음 검증 · Electron 연결 완료 | macOS 작업 이어갈 때 |
| [08-배포-가이드.md](08-배포-가이드.md) | **[2026-08-19]** 일반 사용자 배포 방법 · 배포 전 체크리스트 3건 | 배포본 만들 때 |
| [09-Electron-기초.md](09-Electron-기초.md) | **[2026-08-19]** Electron 입문 — 프로세스 구조 · preload/IPC · RN 과 비교 | 기술 스택 공부할 때 |

---

## 지금 상태 요약

### 있는 것 ✅

| 항목 | 상태 |
|---|---|
| Windows 네이티브 헬퍼 **소스 전체** | `src/helpers/windows/` — C++ 3,828줄, v0.4.2, P4 완료 |
| Electron 앱 소스 전체 | `src/main/`, `src/renderer/` |
| Windows 분기 처리 | 경로/알림/딥링크 등록 전반에 `win32` 분기 존재 |
| 빌드 리소스 | `electron-resources/logo.ico` 존재 |
| 빌드 훅 안전성 | `afterPack`/`afterSign` 모두 non-darwin 조기 반환 → Windows 빌드 안 깨짐 |

### 없는 것 / 만들어야 하는 것 ⚠️

| 항목 | 대응 |
|---|---|
| `AudioHelper.exe` 바이너리 | `.gitignore`의 `*.exe` 로 제외됨 → **직접 빌드** (02번 문서) |
| `WebRTCLib/` 실제 라이브러리 | gitignore 됨 → **없어도 빌드 가능** (NLMS 폴백) |
| `node_modules` | `npm install` |
| Windows 코드 서명 | 미설정 → SmartScreen 경고 발생 (04번 문서) |
| 서버 계정 / 딥링크 `code` | 업로드 end-to-end 검증에 필요 (외부 의존) |

### 검증 가능 범위

```
장치 열거 → 녹음 → 믹싱 → 세그먼트 생성/암호화 → 로컬 저장
  └─ 현재 소스만으로 100% 검증 가능 ✅

로그인(딥링크 토큰 교환) → 서버 업로드
  └─ 유효한 인증 code 를 발급하는 웹 서비스 접근 필요 ⚠️
```

즉 **오프라인 단독으로 "녹음이 되는가"까지는 내일 바로 확인 가능**하고,
업로드는 서버/계정이 준비된 다음 단계입니다.

---

## 참고: 기존 docs/ 와의 관계

기존 `docs/` 는 폐기 대상이 아니며, 아래는 여전히 유효한 1차 자료입니다.

- `docs/electron_helper_interface.md` — **JSON-IPC 프로토콜 명세 (필독)**
- `docs/recording_architecture_mac_windows_v3.md` — 오디오 아키텍처 설계
- `docs/windows/DEVELOPMENT_STATUS.md` — Windows 헬퍼 구현 현황 (v0.4.2 / 2025-10-31)
- `docs/windows/CHANGELOG.md` — Windows 헬퍼 변경 이력

반면 `docs/INSTALLATION_GUIDE.md`, `docs/CERTIFICATE_GUIDE.md`, `docs/BUILD_GUIDE.md` 는
**macOS 전용**이므로 Windows 작업 시 참고하지 마세요.
