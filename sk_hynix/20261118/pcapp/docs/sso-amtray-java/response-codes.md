# AM-Tray SSO 로그인 — 응답코드 정리

> 작성 2026-11-16 (ver.19 기준). 시스템 로그인(AM-Tray)에서 나오는 **모든 응답코드와 우리 앱 처리**를 한곳에 모았다.
> 흐름·배경은 `analysis.md`(2-5 가 최신), 함수 선언은 `clean/AmInterface.h`.
>
> **근거 우선순위** (서로 다르면 위가 이긴다)
> 1. **현재 소스** — `src/main/services/amTrayService.js`, `amTrayDll.js`, `src/main/ipc/handleAuth.js`
> 2. **C++ 매뉴얼 6장 응답코드 표** (11-16 옮겨 옴 — `update_20261116.md` 284행~)
> 3. **AM 명세** `window-message.md` (11-10 옮겨 옴 — GetSystemTokenIT 표·안내 문구)
> 4. 옛 Java 샘플 (11-09, 이력만)

---

## 0. 기본 규칙

- **모든 함수는 BOOL + 응답코드 두 가지를 돌려준다.**
  - BOOL = AM-Tray 서비스와 **통신이 됐는지**만. `true` 여도 실패일 수 있다(11-16 시험: `true` + `501010`).
  - 실제 결과는 **6자리 응답코드**(`lpReturnCode`)로 본다.
  - BOOL 이 `false` 면 응답코드는 **공백("")** — 명세의 "공백"이 이것.
- 코드 앞자리: **2xxxxx = 성공**, **5xxxxx = 실패**.
- 함수별로 코드 뜻이 다르다(예: `504011` 은 어디서나 "미로그인"이지만, 처리 방법은 함수마다 다름).
- **Init**: `GetSystemToken` 은 Init 을 포함 → 따로 안 부른다. `ShowSSOLoginUI`·`IsLoginIT`·`CheckLoginUserIT` 앞에는 꼭 부른다(안 부르면 `501010`).

---

## 1. 한눈에 — 코드순

| 코드 | 나오는 함수 | 뜻 | 우리 앱 처리 |
|---|---|---|---|
| **201010** | Init | 초기화 성공 | 다음 단계 |
| **201011** | Init | 이미 초기화됨 | 성공과 같음 (11-16 전에는 실패로 봤음 → 고침) |
| **203012** | ShowSSOLoginUI | 로그인 UI 요청 성공 | AM-Tray 로그인 기다림 (알림 오면 자동 / [다시 확인]) |
| **203030** | GetSystemToken | 인가토큰 발급 성공 | 백엔드로 보내 검증 → 우리 토큰 |
| **206030** | IsLoginIT | 사용자 로그인 상태 | 그대로 |
| **206040** | CheckLoginUserIT | 같은 사용자 로그인 상태 | 그대로 (미뤄 둔 로그아웃 확인도 지움) |
| 500001 | (명세) | DLL 라이브러리 로드 실패 | "연동 모듈을 실행할 수 없습니다" — 팝업 없음 |
| 500003 | (명세) | DLL API 통신 실패 | 위와 같음 |
| **501010** | Init / IsLoginIT 등 | 초기화 실패 / 연결정보 없음(Init 필요) | Init 단계면 **설치 안내 팝업**. 다른 함수에서면 Init 다시 하고 한 번 더 |
| 502011 | IsLoginIT | AM-Tray 설정 없음 (SSO-Key 확인) | 그대로 두고 로그만 (`amtray_is_login` 경고) |
| 502050 | ShowSSOLoginUI | 로그인 UI 요청 실패 | [다시 시도] / [앱 종료] 팝업 (502051 과 같게 — 우리 결정) |
| 502051 | ShowSSOLoginUI | SSO 로그인 페이지 통신 실패(SSO 서버 장애) | **[다시 시도] / [앱 종료]** 팝업 |
| 502052 | ShowSSOLoginUI | SSO 로그인 불가(Risk 평가 실패·SSO 서버 장애 등) | **[다시 시도](로그인 창 다시) / [앱 종료]** 팝업 (11-18) |
| 503031 | GetSystemToken | 접근 불가 — 사용자 신뢰 점수 미달 | **응답 메시지 팝업 [확인] → 앱 종료** |
| 503032 | GetSystemToken | 접근 불가 — 접근 권한 없음 | 위와 같음 |
| 503033 | GetSystemToken | 접근 불가 — 장기 미사용 권한 회수 | 위와 같음 |
| 503034 | GetSystemToken | 유효하지 않은 토큰(토큰 만료) | 위와 같음 |
| **503035** | GetSystemToken | 토큰 발급 API 통신 실패 | **AM-Tray 로그인 창 호출** (504011 과 같게 — 11-16 결정) |
| 503036 | GetSystemToken | 인증토큰 ID 검증 실패(토큰 탈취, ID 변경 등) | 응답 메시지 팝업 [확인] → 앱 종료 |
| **504011** | GetSystemToken | AM-Tray 미로그인 | AM-Tray 로그인 창 호출 (ver2 는 [AM-Tray 로그인] 버튼) |
| 504011 | IsLoginIT | 사용자 미로그인 | **로그아웃 확인 창** (녹음·업로드 중이면 미룸) |
| 504011 | CheckLoginUserIT | 사용자 미로그인 | **안내 [확인] 후 로그아웃** (녹음·업로드 중이면 미룸) |
| 506021 | ShowSSOLoginUI | 이미 로그인 상태 | 토큰을 **한 번만** 다시 요청 (⚠️ 방식 다시 논의 — 7장) |
| 506040 | CheckLoginUserIT | 다른 사용자 로그인 상태 | **"다른 사용자가 사용 중입니다" [로그아웃] / [취소]** |
| 506041 | CheckLoginUserIT | 체크 요청 사용자 ID 없음 | 안내 [확인] 후 로그아웃 |
| **509090** | 어디서나 | AM-Tray 서비스 통신 실패 | 토큰·Init 이면 **설치 안내 팝업**. IsLoginIT 면 그대로 |
| **"" (공백)** | 어디서나 | BOOL=false, 통신 실패 | 509090 과 같음. 로그인 창이면 502052 와 같음 |

> 매뉴얼 원문에 적힌 `503535` 는 `503035` 의 오타로 봤다. 503036 설명이 "장기 미사용"으로 적힌 것도 옮겨 적다 생긴 실수로 보고 명세("인증토큰 ID 검증 실패")를 따랐다.

---

## 2. 함수별

### 2-1. GetSystemToken — 인가토큰 요청 (로그인할 때)
| 코드 | 뜻 | 매뉴얼 대응 | 우리 처리 | 결과 이름(로그·화면) |
|---|---|---|---|---|
| 203030 | 인가토큰 발급 성공 | 서버로 전달 → SSO 서버 검증(서버 to 서버) | 🔸 11-16 밤: 인가토큰을 **그대로 사용자 토큰으로 저장 → `/me` 확인** (`AMTRAY_TOKEN_MODE: direct`). `/me` 실패면 `amtray_token_rejected` | `amtray_token_received` |
| 504011 | 미로그인 | 로그인 페이지 ShowSSOLoginUI | ver1: 로그인 창 / ver2: [AM-Tray 로그인] 버튼 | `amtray_not_logged_in` |
| 503035 | 토큰 발급 API 통신 실패 | (시스템 정책) | 504011 과 같게 → 로그인 창 | `amtray_not_logged_in` |
| 503031~503034, 503036 | 접근 불가·토큰 만료·ID 검증 실패 | 코드별 메시지 팝업 (GetReturnMessage) | 메시지 팝업 [확인] → **로그인 화면에 머묾** (11-18 변경 — 예전엔 앱 종료) | `amtray_denied` |
| 509090 / 공백 | AM-Tray 통신 실패 | 자체 로그인 또는 **설치 페이지 이동** | **설치 안내 팝업** | `amtray_install_required` |
| 500001 / 500003 | DLL 로드·API 통신 실패 | 자체 로그인 | **설치 안내 팝업** (11-18 변경 — 예전엔 "연동 모듈" 문구만) | `amtray_install_required` |
| 그 밖 | — | — | 메시지(있으면) + 코드 | `amtray_error` |

### 2-2. Init — 초기화 (로그인 창·상태·사용자 확인 앞에서)
| 코드 | 뜻 | 우리 처리 |
|---|---|---|
| 201010 | 초기화 성공 | 다음 함수 |
| 201011 | 이미 초기화 진행 완료 | 다음 함수 (성공과 같음) |
| 501010 | 초기화 실패 | **설치 안내 팝업** |
| 509090 / 공백 | 통신 실패(설치 필요) | **설치 안내 팝업** |

> 한 번 성공하면 같은 작업 프로세스에서는 다시 안 부른다. 다른 함수가 `501010`(연결정보 없음 — AM-Tray 재시작 등)을 주면 Init 을 다시 하고 **한 번만** 더 부른다(로그에 `reinit: true`).

### 2-3. ShowSSOLoginUI — AM-Tray 로그인 창
| 코드 | 뜻 | 매뉴얼 대응 | 우리 처리 | 결과 이름 |
|---|---|---|---|---|
| 203012 | 로그인 UI 요청 성공 | — | 기다림 (5분, 알림 오면 자동) | `amtray_login_ui_shown` |
| 506021 | 이미 로그인 상태 | "SSO 로그인 후 재실행 안내 → 종료" | 앱 종료 대신 **토큰 한 번 더** | (그 토큰 결과) |
| 502050 | 로그인 UI 요청 실패 | — | 502051 과 같게 | `amtray_sso_page_failed` |
| 502051 | SSO 로그인 페이지 통신 실패 | 재시도 / 앱 종료 | [다시 시도] / [앱 종료] | `amtray_sso_page_failed` |
| 502052 / 공백 | SSO 로그인 불가 | 확인 → 앱 종료 | [다시 시도] / [앱 종료] (11-18) | `amtray_sso_blocked` |
| (Init 실패) | — | — | 설치 안내 팝업 | `amtray_install_required` |

### 2-4. IsLoginIT — AM-Tray 로그인 상태 (로그인 뒤 확인)
**언제:** 창이 활성화될 때(30초에 한 번까지) + 녹음 화면으로 넘어가기 전. **시스템 로그인 세션만.** 주기적으로(1분마다 등) 묻지 않는다.
| 코드 | 뜻 | 우리 처리 |
|---|---|---|
| 206030 | 로그인 상태 | 그대로 |
| 501010 | 연결정보 없음 | Init 다시 → 한 번 더 |
| 502011 | AM-Tray 설정 없음 | 그대로 (로그: ssoKey 확인) |
| 504011 | 미로그인 | **로그아웃 확인 창** [로그아웃] / [취소]. 녹음·업로드 중이면 미룸. [취소] 뒤에는 AM-Tray 가 다시 로그인될 때까지 또 안 물음 |
| 509090 | 통신 실패 | 그대로 |

### 2-5. CheckLoginUserIT — 같은 사람인지 (로그인 중 AM-Tray 로그인 알림이 왔을 때)
넘기는 값: **내 사번** (⚠️ 사번이 맞는지 11-17 시험으로 확인 — 7장)
| 코드 | 뜻 | 우리 처리 |
|---|---|---|
| 206040 | 같은 사용자 | 그대로 |
| 506040 | 다른 사용자 | **"다른 사용자가 사용 중입니다"** [로그아웃] / [취소] (녹음 중이면 미룸) |
| 506041 | 체크 요청 ID 없음 | 안내 [확인] 후 로그아웃 (녹음 중이면 미룸) |
| 504011 | 미로그인 | 위와 같음 |

### 2-6. GetReturnMessage — 코드 → 안내 문구
| 결과 | 우리 처리 |
|---|---|
| true + 문구 | 그 문구를 팝업에 |
| false / 공백 | 우리 문구(`amtray.code_*`) + "(코드 ○○○○○○)" |

### 2-7. GetSmSessionToken — 쓰지 않음 (11-16 밤: 모양만 로그 `amtray_smsession_shape`, 인가토큰과 비교용)
웹 SSO(SiteMinder) 세션값(`SMSESSION`). 우리 흐름(인가토큰 → ValidateToken)에는 필요 없다.
true = 세션값 / false = 504011 미로그인, 509090 통신 실패.

---

## 3. 팝업 문구 (ko — `src/locales/ko.json`)

| 팝업 | 제목 | 본문 | 버튼 |
|---|---|---|---|
| 설치 안내 | AM-Tray 설치 필요 | AM-Tray가 설치되어 있지 않거나 실행되고 있지 않습니다. / [설치 페이지로 이동]을 누르면 브라우저에서 설치 페이지가 열리고 앱이 종료됩니다. | [설치 페이지로 이동] [닫기] |
| 접근 불가 | 시스템 접근 불가 | (AM 문구 또는 아래 코드별 문구) / [확인]을 누르면 앱이 종료됩니다. | [확인] |
| SSO 페이지 실패 | AM-Tray 로그인 | 로그인 페이지를 불러오는 중 에러가 발생하였습니다. 재시도 또는 관리자에게 문의해 주세요. | [다시 시도] [앱 종료] |
| SSO 불가 | AM-Tray 로그인 | SSO 로그인이 불가합니다. 관리자에게 문의해 주세요. / [확인]을 누르면 앱이 종료됩니다. | [확인] |
| AM-Tray 로그아웃 | AM-Tray 로그아웃 | AM-Tray에서 로그아웃되었습니다. / 이 앱에서도 로그아웃할까요? [취소]를 누르면 로그인 상태가 유지됩니다. | [로그아웃] [취소] |
| 다른 사용자 | 다른 사용자 로그인 | 다른 사용자가 사용 중입니다. / AM-Tray에 다른 사용자가 로그인했습니다. … | [로그아웃] [취소] |
| 사용자 정보 없음 | AM-Tray 로그아웃 | AM-Tray 로그인 정보를 확인할 수 없습니다. / [확인]을 누르면 이 앱에서 로그아웃합니다. | [확인] |

**코드별 문구** (명세 그대로, `amtray.code_*`)
| 코드 | 문구 |
|---|---|
| 503031 | 접속환경 Risk평가 결과 허가된 접근 범위를 초과하여 접속이 차단되었습니다. |
| 503032 | 시스템 접근 권한이 없습니다. |
| 503033 | 시스템 장기 미사용으로 인하여 권한이 회수되었습니다. |
| 503034 | 사용자 인증 정보가 만료되어 AM-Tray 로그아웃 후 재로그인이 필요합니다. |
| 503035 | 인가토큰 발급에 실패하였습니다. |
| 503036 | 인증토큰 ID 검증에 실패하였습니다. |
| 504011 | 통합인증이 필요합니다(미 로그인 상태) — 명세 문구. 우리 화면은 "AM-Tray 통합 SSO 로그인을 진행해 주세요" |
| 509090 | AM-Tray가 설치되지 않았습니다. — 우리 화면 제목과 같음 |

> 팝업은 메인 프로세스 대화상자(`handleAuth.js` `showAmResultDialog`·`askAmLogout`) — 로그인 화면 ver1·ver2 모두 같다.
> `_NF` 키를 쓰므로 AM-Tray 자기 팝업은 안 뜨고 **우리 팝업만** 뜬다(11-17 시험으로 확인 예정).

---

## 4. 그 밖의 값

### 4-1. 설정값 (`src/config/app.config.json` — 개발/운영 묶음)
| 설정 | 개발 | 운영 |
|---|---|---|
| ssoKey `AMTRAY_SSO_KEY` | `Dev_CASSO_NF` | `Prod_CASSO_NF` |
| sid `AMTRAY_SID` | `AIMEETINGdev` | `AIMEETING` |
| systemID `AMTRAY_SYSTEM_ID` | `AIMEETING` | `AIMEETING` |
| 윈도우 메시지 환경값 `AMTRAY_ENV_CODE` | `31001` | `30001` |
| 설치 페이지 `AMTRAY_INSTALL_URL` | `https://amdev.skhynix.com/tray/view/install.jsp` | `https://csam.skhynix.com/tray/view/install.do` |

`_NF` 가 없는 `Dev_CASSO`/`Prod_CASSO` 는 AM-Tray 가 자기 안내 팝업도 띄운다.

### 4-2. 윈도우 메시지 (AM-Tray → 앱)
| 알림 | Message | wParam | 데이터 |
|---|---|---|---|
| 로그인 | `WM_COPYDATA` (0x004A) | 30001 / 31001 | `lpData` = 사용자 ID SHA-256 |
| 로그아웃 | `WM_USER` (0x0400) + 30001 / 31001 | 30001 / 31001 | 없음 |

wParam 이 우리 환경값과 다르면 무시(로그 `amtray_copydata_ignored`).

### 4-3. 서버 검증 API (백엔드 → SSO 서버, 앱이 직접 부르지 않음)
- 개발 `https://samlamdev.skhynix.com/tray/api/ValidateToken` / 운영 `https://csam.skhynix.com/tray/api/ValidateToken` (11-14 갱신 — 예전 samlam 아님)
- POST JSON `{ systemID: "AIMEETING", authzToken }` → 응답 `attr` 의 `RESULT`·`USERID` (명세 예: `status: 200` — 11-17 오타 바로잡음, `Result: "Success"`)
- 서버 샘플(11-16, `server-api-sample.md`) 기준 결과값:

| `RESULT` | 뜻 | 백엔드 처리 |
|---|---|---|
| `SUCCESS` + USERID 있음 | 검증 성공 | USERID 로 우리 토큰 발급 |
| `TOKEN_INVALID` | 유효하지 않은 인가토큰 | 실패(401 등) |
| `SYSTEMID_INVALID` | 시스템 ID 검증 실패 | 실패(설정 오류) |
| 그 밖 / HTTP 204 | 통신 실패 / 잘못된 요청 | 실패 |

> ⚠️ 표기가 자료마다 다르다: 키 `systemID`(명세) / `SystemID`(11-09 샘플) / `systemId`(11-16 샘플), 결과 `Success`(명세) / `SUCCESS`(샘플), 경로 `ValidateToken` / `validateToken`. 백엔드가 실제 응답으로 맞춰야 한다(대소문자 무시 비교 권장).

---

## 5. 로그·화면에서 보는 결과 이름 (`amtray_*`)

| 결과 이름 | 언제 | ver2 화면 | ver1 문구 줄 |
|---|---|---|---|
| `amtray_not_logged_in` | 504011·503035 (로그인 창 안 띄울 때) | [AM-Tray 로그인] 버튼 | AM 로그인이 확인되지 않았습니다 |
| `amtray_login_ui_shown` | 203012 | "AM-Tray에서 로그인을 진행해 주세요" | AM 로그인 창에서 로그인해 주세요 |
| `amtray_install_required` | 509090·공백·Init 실패 | 팝업 → [닫기] 면 "AM-Tray가 설치되지 않았습니다" | 같은 문구 + 코드 |
| `amtray_denied` | 503031~034·036 | 팝업 → 로그인 화면에 머묾 (11-18) | 서버 문구 + 코드 |
| `amtray_sso_page_failed` | 502050·502051 | 팝업 [다시 시도]/[앱 종료] | 같은 문구 + 코드 |
| `amtray_sso_blocked` | 502052·공백 | 팝업 [다시 시도]/[앱 종료] (11-18) | 같은 문구 + 코드 |
| `amtray_unavailable` | 500001·500003 | "연동 모듈을 실행할 수 없습니다" | 시스템 로그인을 사용할 수 없습니다 |
| `amtray_error` | 표에 없는 코드 | AM 문구 + 코드 | 같음 |
| `amtray_helper_error` | 작업 프로세스·DLL 문제(파일 없음·죽음·시간 초과) | "연동 모듈을 실행할 수 없습니다" | 시스템 로그인 모듈을 실행할 수 없습니다 |
| `amtray_server_not_ready` | 토큰은 받았지만 백엔드 API 없음 | "로그인 서버가 아직 준비 중" | 같음 |

로그 줄: `amtray_token_code`(실패 코드), `amtray_token_received`(토큰 길이만), `amtray_show_ui`(`status`), `amtray_is_login`, `amtray_check_user`, `amtray_session_check`(`reason: focus / before_recording`), `amtray_logout_message`(`kind`).

---

## 6. 코드가 어디 적혀 있나 ("하드코딩")

응답코드는 **AM 이 정한 고정 명세**라 코드 안에 상수로 둔다. 회사·환경마다 바뀌는 값(키·sid·주소)은 설정 파일에 있다.
| 무엇 | 위치 |
|---|---|
| Init 성공·재초기화 (201010·201011·501010), 토큰 성공 203030 | `src/main/services/amTrayDll.js` 맨 위 상수 |
| 토큰 결과 분류 (504011·503035·설치·접근 불가·모듈) | `src/main/services/amTrayService.js` `CODES_*` 상수 + `getSystemToken()` |
| 로그인 창 분류 (203012·506021·502052…) | `amTrayService.js` `classifyShowUi()` |
| 상태·사용자 확인 (206030·206040·506040·506041) | `amTrayService.js` `isLogin()` · `checkLoginUser()` |
| 결과 → 팝업 | `src/main/ipc/handleAuth.js` `showAmResultDialog()` · `askAmLogout()` |
| 팝업·화면 문구 | `src/locales/ko.json`, `en.json` (`amtray.*`, `loginV2.*`, `login.msg_amtray_*`) |
| ssoKey·sid·systemID·환경값·설치 주소 | `src/config/app.config.json` (`dev` / `prod` 묶음) |

> 코드 처리 방식을 바꾸려면 위 표의 해당 줄만 고치면 된다. 새 코드가 생기면 1장 표와 함께 갱신.

---

## 7. 바뀐 이력 · 남은 것

**이력**
| 날짜 | 바뀐 것 |
|---|---|
| 11-09 | Java 샘플 기준: 509090·503035·503034·500003 → 자체 로그인 |
| 11-10 | 명세(`window-message.md`) 표 반영, 결정 A~D (509090 → 안내 팝업만) |
| 11-14 | 503034·503035 를 "코드별 안내"로 옮김, 함수 모양 확정 |
| **11-16** | 매뉴얼 6장 응답코드 표 반영: 503035 → 로그인 창, 509090·공백·Init 실패 → **설치 페이지 팝업**, 503031~ → 팝업 후 앱 종료, ShowSSOLoginUI 코드별 팝업, IsLoginIT·CheckLoginUserIT 사용 시작, Init 201011 = 성공, `_NF` 키 |

**남은 것**
- **506021(이미 로그인)** — 지금은 토큰을 한 번만 다시 요청. 방식은 다시 논의하기로 함(11-16).
- **CheckLoginUserIT 에 넘기는 ID** — 사번으로 넘김. 11-17 `check-user` 시험에서 내 사번이 206040 이면 확정.
- **`_NF` 팝업 차이** — 11-17 시험(일반 키와 비교)으로 확인.
- **설치 페이지 주소** — `https://` 로 열리는지.
- 504011 일 때 명세의 다른 선택지(자체 로그인 전환, 대기)는 안 씀 — ver2 는 AM-Tray 전용.
