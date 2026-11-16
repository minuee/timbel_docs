# 05. 인증 · 세션 · 서버 API

> 기준: 현재 소스 (2026-10-15 작업분까지). 소스 위치는 `파일 · 함수` 로 표기.
> 관련 최근 문서: `docs/login-session.md`, `docs/api-config.md` (2026-10-12~15, 현재 소스와 대체로 일치)

---

## 1. 담당 파일

| 파일 | 역할 |
|---|---|
| `services/authService.js` | 토큰·프로필을 메모리에 보관. 토큰 교환, 사번 로그인, 갱신, 세션 만료 |
| `services/authConfig.js` | 로그인 관련 주소와 옵션 (설정 파일에서 읽음) |
| `services/apiService.js` | axios 인스턴스. 서버 주소·토큰·앱 헤더 자동 부착, 401 처리 |
| `services/apiEndpoints.js` | **서버 API 목록** (주소·메서드·파라미터·응답에서 꺼낼 값). API 가 바뀌면 이 파일만 고친다 |
| `services/userService.js` | `apiEndpoints` 항목을 호출하는 공통 함수(`callApi`), 로그인 직후 프로필 조회, 부서장 메일 |
| `ipc/handleAuth.js` | 로그인 화면 ↔ 홈 전환(`loadHome`), 인증 IPC |
| `main.js · processDeepLink` | SSO 딥링크 처리 |

---

## 2. 로그인 방법 3가지

### A. MyAccess(SSO) — 정식 경로
```
[MyAccess 로그인] 버튼 → auth:open-sso → shell.openExternal(SSO_LOGIN_URL)  (기본 브라우저)
   → 사용자가 브라우저에서 로그인
   → 웹이 timbloRecApp://connect?code=<1회용코드>&host=<base64(서버주소)> 호출
   → (Windows) 두 번째 인스턴스 인자 / (mac) open-url 이벤트로 앱이 받음
   → main.js processDeepLink: host 를 base64 디코드 → GET {host}/api/auth/recorder/exchange/{code}
   → 응답 data.accessToken / refreshToken → 세션 저장 → 'auth-exchanged' → onAuthenticated()
```
- 같은 code 를 두 번 교환하지 않도록 처리한 code 를 기억해 둔다(`handledDeepLinkCodes`). 창 로딩 중에 들어온 딥링크가 두 번 처리되던 문제를 막기 위한 것이다.
- 딥링크 프로토콜은 **빌드본에서만** 등록된다(`app.setAsDefaultProtocolClient`). 개발 모드(`npm run dev`)에서는 SSO 복귀를 시험할 수 없다.
- **서버 주소는 딥링크의 host 값을 그대로 쓴다.** 이후 업로드 등 모든 API 가 그 서버로 간다.

### B. 사번 직접 로그인 (HMP)
- `POST {HMP_BASE_URL}{HMP_LOGIN_PATH}` = `https://aimeeting.mobile.skhynix.com/m/api/auth/sso/hmp`
- body `{ empno }`. `HMP_PASSWORD_FIELD` 를 설정한 경우에만 비밀번호를 같이 보낸다(현재는 비어 있음).
- 응답 `data.tokens.accessToken / refreshToken`
- ⚠ **이 API 는 비밀번호를 검증하지 않는다. 남의 사번으로도 로그인된다.** 모바일은 사내 HMP 앱이 본인 인증을 먼저 끝내서 문제가 없었다. 운영 배포에서는 `EMPNO_LOGIN_ENABLED=false` 로 막아야 한다(현재 설정값은 true).

### C. 테스트 로그인 (수동)
- 이름·사번·accessToken·서버 주소를 직접 입력한다. refreshToken 이 없어서 토큰이 만료되면 다시 입력해야 한다.
- SSO 연동 전에 녹음 → 업로드를 시험하기 위한 것이다. **운영 빌드에서는 `MANUAL_LOGIN_ENABLED=false` 필수**(현재 설정값은 true).

### 로그인 후 공통 (`handleAuth.onAuthenticated`)
1. `GET /api/auth/user/me` → 이름, 닉네임, 이메일, 사번, 부서 (프로필)
2. `GET /api/auth/workspace/me` → 워크스페이스(현재는 로그로만 남김)
3. 템플릿 목록을 미리 받아 둔다(기다리지 않음)
4. 로그인 화면에 있을 때만 홈으로 전환한다. 녹음 중에 딥링크가 다시 와도 화면을 빼앗지 않는다.

프로필 조회가 실패해도 로그인은 성공으로 본다. 타이틀에 이름이 안 나올 뿐이다.

---

## 3. 세션 정책

| 항목 | 정책 |
|---|---|
| 보관 | **메모리에만.** 디스크에 쓰지 않는다. 앱을 끄면 다시 로그인해야 한다 (PC 공용 사용 대비) |
| 렌더러 노출 | 토큰은 절대 렌더러로 넘기지 않는다. 화면에는 프로필(이름·사번 등)만 준다 |
| 미리 갱신 | 토큰이 JWT 이고 만료 60초 전이면 요청 직전에 갱신한다(`ensureFreshToken`). **업로드는 파일 스트림이라 401 뒤에 다시 보낼 수 없어서다** |
| 401 처리 | refreshToken 으로 갱신한 뒤 1회 재시도. 동시에 여러 요청이 401 을 받아도 갱신은 한 번만 나간다(`refreshInFlight`) |
| 갱신 방식 | `PUT /api/auth/refresh`, body `{ token: refreshToken, fcmToken: '' }`, 헤더에 만료된 accessToken |
| 갱신 실패 | 네트워크 오류: 세션 유지. 서버가 거절했거나 갱신 수단이 없을 때: 세션 폐기 + `expired` 이벤트 |
| 만료 시 화면 | **마이크 테스트 화면에 있을 때만** 로그인 화면으로 보낸다. 녹음 화면은 건드리지 않는다(녹음이 끊기면 안 되므로). 업로드가 실패하면 업로드 리스트에 남고, 홈으로 돌아오는 순간 로그인 화면이 뜬다 |
| 로그 | 토큰 값은 로그에 남기지 않는다(길이만). 로그 서버로 보낼 때도 token/password 등이 들어간 키는 `***` 로 가린다 |

> 녹음 중 토큰 만료는 아직 완전히 정리되지 않은 주제다. 녹음이 3시간 이어지는 동안 토큰이 만료되면 업로드 직전 갱신에 의존한다.
> refreshToken 이 없는 경로(테스트 로그인, 또는 exchange 응답에 refreshToken 이 없을 때)는 업로드가 실패하고 업로드 리스트에 남는다.

---

## 4. 모든 요청에 붙는 것 (`apiService.js`)

| 헤더 | 값 |
|---|---|
| `Authorization` | `Bearer {accessToken}` (`skipAuth` 가 아닐 때) |
| `timblo-App-OS` | `APP_OS` 설정값. **현재 `AOS`(안드로이드) 임시값** |
| `timblo-App-Version` | `app.getVersion()` (현재 0.0.1) |
| `timblo-App-Lang` | OS 언어 (예: ko) |
| `timblo-Device` | `Windows_NT 10.0.xxxxx` (기기 모델명 성격. 고유 ID 아님) |

- 기본 서버 주소(baseURL)는 로그인할 때 정해진 세션 endpoint 다. 항목에 `baseURL` 이 있으면 그 주소를 쓴다.
- **axios 타임아웃이 없다.** 업로드가 수십 분 걸릴 수 있어서 일부러 뺐다. 부가 API(`userService.callApi`)만 8초, 로그 전송은 5초 타임아웃이 있다.

---

## 5. 서버 API 목록

| # | 용도 | 메서드 · 경로 | 서버 | 토큰 | 호출 시점 |
|---|---|---|---|---|---|
| 1 | 토큰 교환 | GET `/api/auth/recorder/exchange/{code}` | 딥링크 host | X | SSO 복귀 |
| 2 | 사번 로그인 | POST `/api/auth/sso/hmp` | HMP_BASE_URL | X | 사번 로그인 |
| 3 | 토큰 갱신 | PUT `/api/auth/refresh` | 세션 서버 | (만료 토큰) | 만료 임박 / 401 |
| 4 | 내 정보 | GET `/api/auth/user/me` | 세션 서버 | O | 로그인 직후 |
| 5 | 워크스페이스 | GET `/api/auth/workspace/me` | 세션 서버 | O | 로그인 직후 |
| 6 | 부서장 녹음 안내 메일 | POST `/api/alert/recording?empno={사번}` | MOBILE_SERVER_URL | O | **녹음 start 때 1회** (재개 때는 안 보냄, 기다리지 않음) |
| 7 | 템플릿 목록 | GET `/api/template?type=normal` | MOBILE_SERVER_URL | O | 로그인 직후, 업로드 창을 열 때 |
| 8 | **녹음 업로드** | POST `/api/contents/upload/encryption/files` (multipart) | 세션 서버 | O | 업로드 |
| 9 | 로그 전송 | POST `LOG_SERVER_URL` (`/m/api/pcapp/log`) | 설정 주소 | O | 3초마다 묶어서 |

- 서버 응답은 공통 형식 `{ httpCode, message, data }` 를 쓴다. 성공 여부는 HTTP 상태가 아니라 본문의 `httpCode` 로 판단하는 곳이 많다.
- `{empno}` 같은 자리 표시자에 넣을 값이 비어 있으면 API 를 부르지 않고 로그만 남긴다(빈 사번으로 메일이 나가는 것을 막기 위해).
- 템플릿 응답의 모양(`list: 'data'`, `codeKey: 'code'`, `nameKey: 'name'`)은 회사 서버에서 실제로 확인한 값이 아니다. 다르면 `apiEndpoints.templates` 만 고치면 된다.
- 업로드 요청 본문은 `06_저장_DB_업로드.md` 에 정리했다.
