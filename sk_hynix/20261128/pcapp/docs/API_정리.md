# PC 녹음앱 API 정리 — 수정할 곳 찾기용

- 작성: 2026-11-28 (앱 0.0.17 기준)
- 목적: 백엔드·AM 담당자와 맞춰 볼 때 **헤더·바디·주소·응답 처리를 어디서 고치는지** 바로 찾기
- 줄 번호는 소스를 고치면 바뀐다. **함수 이름으로 검색**하는 게 정확하다(VS Code `Ctrl+Shift+F`).
- 표시: ✅ 코드로 확인 / 🔸 아직 서버와 맞춰 보지 않은 값

전체 구조:

```
 [AM-Tray (PC에 설치된 프로그램)]
        ▲  DLL 함수 호출 (HTTP 아님)          ← 1부
        │
 [PC 녹음앱] ── HTTP ──▶ [게이트웨이] ──▶ [auth-api / 모바일 서버]   ← 2부
                                                │
                                                └─ HTTP ─▶ [SSO 서버 ValidateToken]  ← 3부 (백엔드 몫)
```

**먼저 알아 둘 것 — 고칠 곳 3군데**

| 바꾸려는 것 | 고칠 곳 |
|---|---|
| 서버 주소, 경로(PATH), 메서드, 켜기/끄기 | **`src/config/app.config.json`** (소스 수정 없이 값만) |
| 모든 요청에 붙는 공통 헤더 | **`src/main/services/apiService.js`** `appHeaders()` · `tokenHeaders()` |
| API 하나의 바디·헤더·응답 해석 | 각 API 함수 (아래 표의 "위치") |

---

# 1부. AM-Tray (SSO) — DLL 함수 호출

> ⚠️ **HTTP API 가 아니다.** PC에 설치된 AM-Tray 의 DLL(`AmInterface_RT_X64.dll`)을 앱이 직접 부른다(koffi).
> 헤더·바디가 없고, **함수 인자(문자열)** 와 **응답코드(6자리)** 로 주고받는다.

## 1-1. 파일 구조

| 파일 | 하는 일 |
|---|---|
| `src/main/services/amTrayDll.js` | DLL 함수를 **실제로 부르는 곳**. 함수 모양(인자 순서·버퍼 크기)이 바뀌면 여기 |
| `src/main/services/amTrayWorker.js` | 별도 프로세스에서 amTrayDll 을 실행(DLL 이 죽어도 앱은 안 죽게) |
| `src/main/services/amTrayService.js` | **응답코드 → 앱 판단**(토큰/미로그인/설치 필요/권한 없음). 코드 분류가 바뀌면 여기 |
| `src/main/ipc/handleAuth.js` | 판단 결과 → 화면·팝업·로그인 흐름 |
| `docs/sso-amtray-java/response-codes.md` | 응답코드 표 전체 |
| `docs/sso-amtray-java/clean/AmInterface.h` | AM C++ 매뉴얼 정리본(함수 원형) |

## 1-2. 함수별 정리

| 함수 (DLL) | 인자 (우리가 넣는 값) | 성공 코드 | 부르는 위치 (`amTrayDll.js`) | 결과 해석 (`amTrayService.js`) |
|---|---|---|---|---|
| `Init` | `ssoKey`, `sid` | 201010 / 201011(이미 됨) | `init()` 172줄 | — |
| `GetSystemToken` | `ssoKey`, `sid`, `systemCode`(=`AMTRAY_SYSTEM_ID`) → **인가토큰** 받음 | 203030 | `getSystemToken()` 192줄 | `getSystemToken()` 234줄 |
| `ShowSSOLoginUI` | `sid` | 203012 | `showLoginUI()` 242줄 | `showLoginUI()` 278줄 |
| `IsLoginIT` | `sid` | 206030(로그인) / 504011(미로그인) | `isLogin()` 255줄 | `isLogin()` 305줄 |
| `CheckLoginUserIT` | `sid`, `userId`(=사번) | 206040(같은 사람) / 506040(다른 사람) | `checkLoginUser()` 268줄 | `checkLoginUser()` 327줄 |
| `GetReturnMessage` | 응답코드, 언어 → 안내 문구 | — | `getReturnMessage()` 310줄 | `getReturnMessage()` 363줄 |
| `GetSmSessionToken` | `sid`, `ssoKey` | — | `getSmSessionToken()` 282줄 | 로그 기록용만(쓰지 않음) |

- 함수 원형(인자 순서·버퍼 크기): `amTrayDll.js` 14~22줄 주석 + `PROTO` (67~73줄), 버퍼 크기 `SZ` (37~44줄)
- `GetSystemToken` 앞에는 `Init` 을 부르지 않는다(매뉴얼: 포함됨). 다른 함수 앞에는 부른다 → `withInit()` 225줄. 바꾸려면 `AMTRAY_DLL_INIT`

## 1-3. 인자 값 — `app.config.json`

| 키 | dev | prod | 쓰는 곳 |
|---|---|---|---|
| `AMTRAY_SSO_KEY` | `Dev_CASSO_NF` | `Prod_CASSO_NF` | `ssoKey` |
| `AMTRAY_SID` | `AIMEETINGdev` | `AIMEETING` | `sid` (비면 `AMTRAY_SYSTEM_ID`) |
| `AMTRAY_SYSTEM_ID` | `AIMEETING` | `AIMEETING` | `systemCode` |
| `AMTRAY_ENV_CODE` | `31001` | `30001` | 윈도우 메시지 wParam (11-18부터 기대 안 함) |
| `AMTRAY_INSTALL_URL` | `https://amdev.skhynix.com/tray/view/install.jsp` | `https://csam.skhynix.com/tray/view/install.do` | 설치 안내 팝업 링크 |
| `AMTRAY_DLL_DIR` | (비움) | (비움) | DLL 폴더. 비면 설치 폴더 `helpers/windows/amtray` |
| `AMTRAY_DLL_INIT` | `false` | `false` | 토큰 전에 Init 을 부를지 |
| `AMTRAY_MOCK` | `""` | `""` | 시험용 흉내(`token`·`notlogin`·`denied` …). **빌드 전 꼭 `""`** |

## 1-4. 응답코드 → 앱 동작 (`amTrayService.js` 30~40줄 상수)

| 코드 | 앱 판단 | 화면 |
|---|---|---|
| 203030 + 토큰 | `token` | 우리 백엔드로 로그인(2부 2-1) |
| 504011, 503035 | `not_logged_in` | [AM-Tray 로그인] 버튼 → ShowSSOLoginUI |
| 509090, 공백 | `install` | 설치 안내 팝업 |
| 500001, 500003 | `unavailable` | 설치 안내 팝업 |
| 503031~034, 036 | `denied` | AM 문구 팝업, 앱은 열어 둠 |
| 그 밖 | `error` | `GetReturnMessage` 문구 |

코드 분류를 바꾸려면 `amTrayService.js` 의 `CODES_*` 배열만 고친다.

---

# 2부. 우리 백엔드 HTTP API

## 2-0. 모든 요청에 공통으로 붙는 것 — `src/main/services/apiService.js`

| 항목 | 값 | 위치 |
|---|---|---|
| `timblo-App-OS` | `AOS-WINDOWS` / `IOS-MAC` (게이트웨이 406 검사용) | `appHeaders()` 35줄. 값은 `authConfig.js` `APP_OS` |
| `x-device-timezone` | PC 시간대(예 `Asia/Seoul`) | `appHeaders()` |
| `Authorization` | `Bearer <accessToken>` | `tokenHeaders()` 56줄 |
| `X-Timblo-Token` | `<accessToken>` (Bearer 없이) | `tokenHeaders()` 56줄 |
| 기준 주소(baseURL) | 로그인할 때 쓴 주소(= `HMP_BASE_URL`, dev `https://aimeetingdev.skhynix.com`) | 요청 인터셉터 66줄 |

- 토큰 헤더는 요청 인터셉터(66줄)가 자동으로 붙인다. 붙이지 않으려면 요청 옵션에 `skipAuth: true`.
- 모바일 헤더 4개(`timblo-App-Version`·`App-Lang`·`Device` 추가)는 `mobileAppHeaders()` 46줄 — **HMP 약관 확인에만** 쓴다. 4개가 다 있으면 서버가 모바일로 판정(인계문서 3-2).
- HTTP 401 을 받으면 → 토큰 갱신 → 안 되면 AM-Tray 재로그인 → 그래도 안 되면 만료: 응답 인터셉터 91줄
- ⚠️ 인증서버는 성공·실패 모두 **HTTP 200** 이고 결과는 본문 `httpCode` 다. 그래서 각 함수가 `result.httpCode` 를 본다.

## 2-1. 인증 API (auth-api) — `src/main/services/authService.js`

| API | 메서드·경로 (설정 키) | 헤더 | 바디 | 응답에서 보는 것 | 위치 |
|---|---|---|---|---|---|
| **시스템 로그인** | `POST /api/auth/sso/amtray` (`AMTRAY_LOGIN_PATH`, 주소 `AMTRAY_LOGIN_BASE_URL` 비면 `HMP_BASE_URL`) | 공통만. **토큰 헤더 안 붙임** | `{ authzToken }` | `httpCode` 200 → `data.tokens.accessToken`·`refreshToken` / 404·422 → 약관 미동의 / 그 밖 → 실패 | `loginWithAmToken()` 182줄 |
| **토큰 갱신** | `PUT /api/auth/refresh` (`REFRESH_PATH`, `REFRESH_METHOD`) | 공통 + 토큰 헤더(만료된 토큰) | `{ token: refreshToken, fcmToken: '' }` | `httpCode` 200 → `data.tokens.accessToken` / 529·530·531 → 재로그인 | `doRefresh()` 308줄 |
| **로그아웃** | `DELETE /api/auth/logout` (`LOGOUT_PATH`, `LOGOUT_METHOD`) | 공통 + 토큰 헤더 | 없음 | `httpCode` 204 (실패해도 앱은 로그아웃) | `logoutOnServer()` 384줄 |
| **약관 확인 (HMP)** | `POST /api/auth/sso/hmp` (`HMP_LOGIN_PATH`) | **모바일 헤더 4개** | `{ empno }` | `httpCode` 200 동의 / 404·422 미동의 | `checkTermsAgreed()` 242줄 — 로그인 유지 복원·테스트 로그인 뒤에만 |
| **이용 권한 확인** 🔸 | (`ACCESS_CHECK_PATH`, 비어 있음 = 안 부름) | 공통 + 토큰 | 없음 | `httpCode` 403 또는 `data.hasAuth/authorized/allowed` false → 권한 없음 | `checkMinutesAccess()` 273줄 ("★ 응답 해석" 부분) |

흐름(언제 부르는지)은 `src/main/ipc/handleAuth.js`:

| 흐름 | 함수 |
|---|---|
| AM-Tray 토큰 → 로그인 | `runAmLogin()` 469줄 |
| 갱신 실패 → AM-Tray 조용한 재로그인 | `silentAmReauth()` 595줄 |
| 사용자 로그아웃 | `ipcMain.handle('auth:logout')` 790줄 |
| 로그인 뒤 약관 확인 | `passTermsCheck()` 92줄 |

**자주 바꿀 만한 것 → 고칠 곳**

| 담당자가 이렇게 말하면 | 고칠 곳 |
|---|---|
| "로그인 경로가 바뀌었다" | `app.config.json` `AMTRAY_LOGIN_PATH` |
| "로그인 바디 키 이름이 다르다" (예 `token`) | `authService.js` `loginWithAmToken()` 안 `{ authzToken }` |
| "토큰이 응답의 다른 위치에 있다" | `authService.js` `pickTokens()` (`data.tokens.*` 를 꺼냄) |
| "갱신은 POST 다" | `app.config.json` `REFRESH_METHOD: "post"` |
| "갱신 바디에 fcmToken 빼라" | `authService.js` `doRefresh()` 안 `data:` |
| "Bearer 빼라 / X-Timblo-Token 만 써라" | `apiService.js` `tokenHeaders()` |
| "헤더 ○○ 를 더 보내라 / 빼라" | `apiService.js` `appHeaders()` |
| "약관 미동의 코드가 다르다" | `authService.js` `isTermsNotAgreedCode()` (404·422) |

## 2-2. 업무 API — `src/main/services/apiEndpoints.js` 한 파일에 목록

> 주소·메서드·쿼리·응답 경로를 **이 파일의 표 항목만** 고치면 된다. 실제 호출은 `userService.js` `callApi()` 36줄.
> `{empno}` `{name}` `{email}` 은 호출할 때 사용자 값으로 바뀐다.

| 이름 | 메서드·경로 | 서버 | 보내는 것 | 꺼내는 것 (`pick`) | 언제 | 위치 (`apiEndpoints.js`) |
|---|---|---|---|---|---|---|
| `userMe` 내 정보 | `GET /api/auth/user/me` | 로그인 서버 | 토큰 | 이름·닉네임·이메일·사번·부서 (`data.profile.*`) | 로그인 직후 | 26줄 |
| `workspace` | `GET /api/auth/workspace/me` | 로그인 서버 | 토큰 | `data.workspace.id/name`, `data.role` | 로그인 직후 | 52줄 |
| `alertRecording` 부서장 메일 | `POST /api/alert/recording?empno={empno}` | 모바일 서버(`MOBILE_SERVER_URL`) | 토큰 | — | 녹음 시작 (`ALERT_ON_RECORDING_START`) | 42줄 |
| `templates` 요약 템플릿 | `GET /api/template?type=normal` | 모바일 서버 | 토큰 | 목록 `data`, 항목 `code`·`name` | 로그인 직후·업로드 팝업 | 77줄 |
| `upload` 녹음 업로드 | `POST /api/contents/upload/encryption/files` | 로그인 서버 | 토큰 + multipart (아래) | 아래 | 업로드 | 67줄 (경로만) |

**업로드 바디·응답은 `src/main/main.js`**

| 항목 | 위치 |
|---|---|
| multipart 필드: `files`(조각 여러 개), `lang`, `attendeeNum`, `deviceId`, `fileName`, `totalNum`, `title`(선택), `templateId`(선택) | `form.append(...)` 527~536줄 |
| 보내기 | `apiClient.post(apiEndpoints.upload.url, form, …)` 620줄 |
| 응답 해석: `errorCode` 있거나 `httpCode` ≥ 400 → 거절 / `data.missingFiles` → 누락 조각만 다시 보냄(최대 3번) | 500~512줄 (주석 490줄~) |
| 전체 흐름 | `serverUpload()` 631줄 |

## 2-3. 그 밖의 서버 호출

| 이름 | 주소 (설정 키) | 보내는 것 | 위치 |
|---|---|---|---|
| 로그 서버 | `POST {LOG_SERVER_URL}` dev `…/m/api/pcapp/log` | `{ logs: [...] }` + 공통·토큰 헤더. 로그인 전엔 안 보냄 | `src/main/services/logShipper.js` 23줄(주소), 89줄(보내기) |
| 자동 업데이트 | `{UPDATE_SERVER_URL}/latest.yml` dev `…/downpcapp` | GET (헤더 없음, electron-updater) | `src/main/services/updateService.js` 22줄, 87줄 |

---

# 3부. SSO 서버 검증 (참고 — 백엔드 몫, 앱 코드 아님)

| 항목 | 값 |
|---|---|
| 누가 부르나 | 인증서버(auth-api)가 2-1 시스템 로그인 안에서 |
| 주소 | dev `https://samlamdev.skhynix.com/tray/api/ValidateToken` / 운영 `https://csam.skhynix.com/tray/api/ValidateToken` (auth-api `.env` `AMTRAY_VALIDATE_URL`) |
| 바디 | `{ systemID: "AIMEETING", authzToken }` — 🔸 **키 대소문자 확인 중**(11-27 status 500) |
| 응답 | `attr.RESULT`(`SUCCESS`/`TOKEN_INVALID`/`SYSTEMID_INVALID`), `attr.USERID`(사번) |
| 위치 | auth-api `src/services/commonService/ssoAmTray.js` `validateAuthzToken()` (집 사본 `docs/sso-amtray-java/backend-request/…/ssoAmTray.js` 36~65줄) |
| 회사 시험 순서 | `docs/update_20261128.md` 6장 |

---

## 부록. 설정값 한눈에 (`src/config/app.config.json`, dev 기준)

| 키 | 값 | 2부 어디 |
|---|---|---|
| `HMP_BASE_URL` | `https://aimeetingdev.skhynix.com` | 로그인 서버 주소(로그인 뒤 모든 요청의 기준 주소) |
| `AMTRAY_LOGIN_PATH` | `/api/auth/sso/amtray` | 2-1 시스템 로그인 |
| `REFRESH_PATH` / `REFRESH_METHOD` | `/api/auth/refresh` / `put` | 2-1 갱신 |
| `LOGOUT_PATH` / `LOGOUT_METHOD` | `/api/auth/logout` / `delete` | 2-1 로그아웃 |
| `HMP_LOGIN_PATH` | `/api/auth/sso/hmp` | 2-1 약관 확인 |
| `TERMS_CHECK_ENABLED` | `true` | 약관 확인 켜기 |
| `ACCESS_CHECK_PATH` / `_METHOD` / `_MOCK` | (없음) / `get` / `""` | 2-1 권한 확인 |
| `MOBILE_SERVER_URL` | `https://aimeetingdev.skhynix.com/m/api` | 2-2 메일·템플릿 |
| `DEFAULT_API_BASE_URL` | `https://aimeetingdev.skhynix.com/m/api` | 테스트 로그인 기본 주소 |
| `ALERT_ON_RECORDING_START` | `true` | 2-2 부서장 메일 |
| `LOG_SERVER_URL` / `LOG_SERVER_ENABLED` | `…/m/api/pcapp/log` / `true` | 2-3 로그 |
| `UPDATE_SERVER_URL` / `UPDATE_ENABLED` | `https://aimeetingdev.skhynix.com/downpcapp` / `true` | 2-3 업데이트 |

- `app.config.json` 의 `dev`·`prod` 묶음에 값이 있으면 그 값이 우선이다. 빌드는 `npm run build:dev` / `build:prod`.
- 값을 바꾼 뒤에는 앱을 다시 켜야 적용된다(빌드본은 다시 빌드).
