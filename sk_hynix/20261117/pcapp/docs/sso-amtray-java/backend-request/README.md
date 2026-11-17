# 인증서버 요청 — PC 녹음앱 시스템 로그인(AM-Tray) API

> 작성 2026-11-17 · 대상: 인증서버(`timblo-be-auth-service`, 이 저장소의 `docs/auth-api-2-release` 기준)
> 요청: **AM-Tray 인가토큰을 받아 SSO 서버(ValidateToken)로 검증하고 우리 토큰을 발급하는 API 하나**
> 초안 코드: 이 폴더의 `src/services/commonService/ssoAmTray.js` (서버 소스와 같은 폴더 구조)

---

## 1. 왜 필요한가

- PC 녹음앱은 SK하이닉스 AM-Tray(SSO 에이전트)로 로그인한다. 앱은 AM-Tray DLL 에서 **인가토큰**을 받는다.
- 인가토큰은 우리 토큰(JWT)이 아니다. 우리 서버는 Bearer 를 `JWT_ACCESS_SECRET_KEY` 로 검증하므로(`parserUtils.verifyToken`) 인가토큰으로는 API 를 쓸 수 없다.
- AM 매뉴얼 흐름: **연동 시스템 서버가 SSO 서버 `ValidateToken` 으로 인가토큰을 검증(서버 to 서버) → 사번 → 자기 시스템 토큰 발급.**
  → 이 "검증 + 발급"을 인증서버가 해 줘야 한다. (앱은 JWT 비밀키가 없어 토큰을 만들 수 없고, 앱이 검증하면 서버가 믿을 근거가 없다)

```
[PC앱]                              [인증서버 — 새 API]                         [SSO 서버]
GetSystemToken → 인가토큰
  └ POST /auth/sso/amtray {authzToken} ─▶ POST ValidateToken {systemID, authzToken} ─▶ 검증
                                         ◀── attr { Result: Success, USERID: 사번 } ──┘
                                         사번 → 사용자 찾기 → 토큰 발급
  ◀── { httpCode:200, data:{ tokens:{ accessToken, refreshToken } } }
```

---

## 2. 추가할 것 (작음 — 기존 부품 재사용)

새로 짜는 건 **ValidateToken 호출 하나**뿐이다. 나머지는 기존 함수를 쓴다.
약관 동의 확인은 **넣지 않는다** — PC앱이 로그인 뒤 따로 확인한다.

| 단계 | 쓰는 것 | 비고 |
|---|---|---|
| 인가토큰 검증 → 사번 | **새로**: `validateAuthzToken()` (초안 파일 안) | axios POST |
| 사번 → 사용자 | `findProfileByEmpno` (models/user.js) | 기존 |
| 토큰 발급 | `tokenAuthService(submitter, session, res)` | 기존 — 응답 형식도 기존 그대로 |

### 2-1. 새 파일
`src/services/commonService/ssoAmTray.js` — 이 폴더의 초안 그대로 복사

### 2-2. 라우터 한 줄 (`src/routes/commonRouter.js`)
```js
import ssoAmTray from '../services/commonService/ssoAmTray.js';
// ...
router.post(['/sso/amtray'], handleSession, ssoAmTray);
```
→ 경로 `/auth/sso/amtray` (앱에서는 `/api/auth/sso/amtray` — 다른 API 와 같은 게이트웨이 앞붙임)

### 2-3. 에러 3개 (`src/configs/error.js`)
```js
export const AmTrayValidateError = _create('AM-Tray 인가토큰 검증 API 호출 실패', 401);
export const AmTraySystemIdInvalidError = _create('AM-Tray 시스템 아이디 검증 실패', 401);
export const AmTrayTokenInvalidError = _create('유효하지 않은 AM-Tray 인가토큰', 401);
```
맨 아래 `export default { ... }` 목록에도 세 이름을 추가한다.

### 2-4. 설정 (`.env`)
```
# AM-Tray 인가토큰 검증 (SSO 서버, 서버 to 서버)
AMTRAY_VALIDATE_URL=https://samlamdev.skhynix.com/tray/api/ValidateToken   # 운영: https://csam.skhynix.com/tray/api/ValidateToken
AMTRAY_SYSTEM_ID=AIMEETING
```

---

## 3. ValidateToken 명세 (AM 담당자 자료)

| 항목 | 값 |
|---|---|
| 주소 | 개발 `https://samlamdev.skhynix.com/tray/api/ValidateToken` / 운영 `https://csam.skhynix.com/tray/api/ValidateToken` |
| 방식 | `POST`, JSON |
| 요청 | `{ "systemID": "AIMEETING", "authzToken": "<앱이 보낸 인가토큰>" }` |
| 응답 | `{ "status": 200, "attr": { "Result": "Success", "USERID": "<사번>" } }` |
| 실패(샘플) | `attr.RESULTID` = `SYSTEMID_INVALID` / `TOKEN_INVALID` |

> 자료마다 표기가 다르다(`Result`/`RESULTID`, `Success`/`SUCCESS`/`SUCCES`, 경로 `ValidateToken`/`validateToken`).
> 초안은 대소문자를 가리지 않고 모두 받는다. 실제 응답을 한 번 찍어 보고 맞추면 된다(로그 `[SSO_AMTRAY] ValidateToken 응답`).

---

## 4. 응답 (앱이 기대하는 것 — 기존 로그인과 같음)

| 경우 | httpCode | 앱 처리 |
|---|---|---|
| 성공 | 200, `data.tokens.accessToken / refreshToken` | 로그인 → `/api/auth/user/me` |
| 인가토큰 검증 실패 | 401 (`AmTray*Error`) | 서버 메시지 그대로 표시 |
| 사용자 없음 | 403 (`NotFoundUserInfo`) | 서버 메시지 그대로 표시 |

---

## 5. 확인 부탁 (🔸 아직 모르는 것)

1. **서버에서 SSO 서버로 접속이 되나** — `samlamdev` / `csam` 으로 나가는 길(방화벽·IP 등록). 웹 SSO 용 `SSO_URL` 과 같은 망인지.
2. **HTTPS 인증서** — AM 샘플(Java)은 별도 SSL 설정(`getSSLRestTemplate`)을 썼다. 사내 인증서라 axios 에서 막히면 CA 설정이 필요할 수 있다.
3. **USERID = 사번(EMP_NO) 인가** — 초안은 `findProfileByEmpno(USERID)` 로 찾는다. 웹 SSO `userInfo` 에는 `USER_ID` 와 `EMP_NO` 가 따로 있어서, ValidateToken 의 USERID 가 어느 쪽인지 실제 값으로 확인 필요.
4. **신규 사용자** — ValidateToken 은 사번만 주므로 이 API 에서는 계정을 만들 수 없다. 웹 SSO 로 한 번 로그인한 사람만 된다(지금 초안). 처음 쓰는 사람도 되어야 하면 사번으로 SSO 사용자 정보를 받을 방법이 필요하다.

---

## 6. 시험 (서버 반영 뒤)

인가토큰은 회사 PC 에서 PC앱 시험 도구로 받는다(AM 등록 — GetSystemToken 502011 — 이 풀린 뒤):
```
node scripts\amtray-koffi-test.js token --dll-dir src\helpers\windows\amtray\bin --sso-key Dev_CASSO_NF --sid AIMEETINGdev --system-id AIMEETING --show-token
```
그 값으로:
```
curl -X POST https://<인증서버>/auth/sso/amtray -H "Content-Type: application/json" -d "{\"authzToken\":\"<인가토큰>\"}"
```
→ `httpCode: 200` 과 `data.tokens.accessToken` 이 오면 끝. 앱은 설정 두 개(`AMTRAY_TOKEN_MODE: "backend"`, `AMTRAY_LOGIN_PATH: "/api/auth/sso/amtray"`)만 넣으면 이 API 를 쓴다.
