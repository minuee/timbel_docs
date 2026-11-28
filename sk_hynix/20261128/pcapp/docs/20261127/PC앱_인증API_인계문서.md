# PC 앱(AM-Tray) 인증 API 인계 문서

- 작성일: 2026-11-24
- 대상: PC 녹음앱(AM-Tray) 개발자
- 근거 코드: `backend/auth-api`, 브랜치 `origin/2-release-dev` (커밋 `b957bda`)
- 모든 내용은 코드에서 확인했습니다. 근거 줄 번호는 부록 A에 있습니다.

---

## 1. 요약

- PC 앱 로그인 API는 1개입니다: `POST /auth/sso/amtray`.
- 토큰 갱신과 로그아웃은 웹·모바일과 같은 공통 API를 씁니다.
  - 갱신: `PUT /auth/refresh`
  - 로그아웃: `DELETE /auth/logout`
- 서버는 토큰 안의 `isDesktop: true` 값으로 PC 앱을 구분합니다.
- PC 앱의 리프레시 토큰과 세션은 웹 세션과 따로 저장됩니다.
- 앱에서 부를 때는 게이트웨이 앞붙임을 씁니다(예: `/api/auth/sso/amtray`). 이 앞붙임은 auth-api 코드 밖의 설정입니다. 실제 주소는 게이트웨이 담당자에게 확인하십시오.

---

## 2. 호출 순서

```text
[PC 앱]                         [auth-api]                         [SSO 서버 ValidateToken]
   |                                |                                        |
   | 1. AM-Tray DLL GetSystemToken  |                                        |
   |    -> 인가토큰(authzToken)      |                                        |
   |                                |                                        |
   | 2. POST /auth/sso/amtray ----->|                                        |
   |    body {authzToken}           | 3. POST {systemID, authzToken} ------->|
   |    X-Device-Timezone           |<------ attr {Result, USERID(사번)} -----|
   |                                | 4. 사번 -> 사용자 찾기                    |
   |                                | 5. 약관 동의 확인                         |
   |                                | 6. PC 토큰 발급 (isDesktop: true)         |
   |<--- {httpCode:200, data:{tokens}}                                       |
   |                                |                                        |
   | 7. API 호출: X-Timblo-Token: <accessToken>                               |
   |                                |                                        |
   | 8. PUT /auth/refresh --------->| refreshTokens:pc:{pid} 와 비교          |
   |    X-Timblo-Token: <accessToken>, body {token: <refreshToken>}          |
   |<--- {data:{tokens:{accessToken}}}                                       |
   |                                |                                        |
   | 9. DELETE /auth/logout ------->| 토큰·세션 삭제, 로그인 이력 logoutAt 기록  |
   |<--- {httpCode:204}             |                                        |
```

---

## 3. 공통 규칙

### 3-1. 응답 형식

- 서버는 성공과 실패 모두 HTTP 상태 200을 보냅니다.
- 실제 결과는 본문의 `httpCode`로 판단하십시오.

```json
{ "message": "success", "httpCode": 200, "data": { } }
```

- 실패 예: `{ "message": "최신 약관에 동의하지 않았습니다.", "httpCode": 422, "data": {} }`
- 같은 IP에서 오류가 많으면 IP가 막힙니다. 이때 `httpCode: 429`, `data.reason: "IP_BLOCKED"`가 옵니다.

### 3-2. 요청 헤더

| 헤더 | 필수 | 설명 |
|---|---|---|
| `Content-Type: application/json` | 예 | 본문을 JSON으로 보냅니다. |
| `X-Timblo-Token` | 로그인 뒤 예 | 액세스 토큰 값을 그대로 넣습니다. `Bearer ` 앞붙임을 쓰지 않습니다. |
| `X-Device-Timezone` | 로그인 때 권장 | 기기 시간대(예: `Asia/Seoul`). 약관 국가 판정에 씁니다. |

- PC 앱은 `timblo-app-os`, `timblo-app-version`, `timblo-app-lang`, `timblo-device` 헤더 4개를 함께 보내지 마십시오. 4개가 모두 있으면 서버는 요청을 모바일로 판정합니다.

---

## 4. 엔드포인트

| # | 메서드 | 경로 | 헤더 | 본문 | 성공 응답 `data` |
|---|---|---|---|---|---|
| 1 | POST | `/auth/sso/amtray` | `X-Device-Timezone`(권장) | `{ "authzToken": "<인가토큰>" }` | `{ tokens: { accessToken, refreshToken }, is2FA }` |
| 2 | PUT | `/auth/refresh` | `X-Timblo-Token: <accessToken>` | `{ "token": "<refreshToken>" }` | `{ tokens: { accessToken } }` |
| 3 | DELETE | `/auth/logout` | `X-Timblo-Token: <accessToken>` | 없음 | `{}` (`httpCode: 204`, `message: "OK"`) |

### 4-1. 로그인 `POST /auth/sso/amtray`

서버는 다음 순서로 처리합니다.

1. 쿼리 문자열에 `authzToken`이 있으면 거절합니다(401). 인가토큰은 본문으로만 보내십시오.
2. 본문에 `authzToken`이 없으면 거절합니다(500).
3. SSO 서버 ValidateToken으로 인가토큰을 확인합니다. 시간 상한은 10초입니다.
4. 결과의 `USERID`(사번)로 사용자를 찾습니다. 없으면 403입니다.
5. 약관 동의를 확인합니다(5장).
6. PC 토큰을 발급합니다. 토큰에 `isDesktop: true`가 들어갑니다.

주의 사항:

- 새 사용자는 이 API로 만들 수 없습니다. ValidateToken은 사번만 줍니다. 사용자는 먼저 웹 SSO로 한 번 로그인해야 합니다.
- `refreshToken`은 `refreshTokens:pc:{pid}` 키가 Redis에 없을 때만 새로 발급됩니다. 키가 이미 있으면 응답의 `refreshToken`은 없습니다(값이 `undefined`라 JSON에서 빠집니다). 앱은 받은 리프레시 토큰을 안전하게 저장하고, 응답에 없으면 저장한 값을 계속 쓰십시오.
- 요청에 아직 유효한 `X-Timblo-Token`이 있고 만료까지 30분 넘게 남았으면, 서버는 새 토큰 대신 기존 액세스 토큰을 돌려줍니다. 이때 `message`는 `This user is not eligible for session renewal.`입니다. 로그인 때는 `X-Timblo-Token`을 보내지 않는 것을 권장합니다.

### 4-2. 토큰 갱신 `PUT /auth/refresh`

- `X-Timblo-Token`에 현재(만료되었어도 됨) 액세스 토큰을 넣습니다. 이 경로에서는 서버가 서명만 풀고 만료를 확인하지 않습니다.
- 본문 `token`에 리프레시 토큰을 넣습니다.
- 서버는 `refreshTokens:pc:{pid}`의 값과 본문 값을 비교합니다. 같고 서명이 맞으면 새 액세스 토큰을 줍니다.
- 기존 액세스 토큰은 삭제됩니다. 리프레시 토큰은 새로 주지 않습니다.

### 4-3. 로그아웃 `DELETE /auth/logout`

- 서버는 액세스 토큰, `refreshTokens:pc:{pid}`, `sessions:{pid}:pc`의 해당 항목을 지웁니다.
- 로그인 이력에 `logoutAt`을 기록합니다.
- 웹 세션과 웹 리프레시 토큰은 지우지 않습니다.

---

## 5. 로그인 때 약관 동의 확인

PC 앱과 모바일 HMP SSO는 같은 함수(`checkLoginAgreement`)를 씁니다.

| 워크스페이스 설정 | 판정 |
|---|---|
| 국가 동의 모드 꺼짐 | 사용자 이메일의 최신 동의가 있고, 그 약관이 `PUBLISHED`이면 통과합니다. |
| 국가 동의 모드 켜짐 | `X-Device-Timezone`으로 국가를 정합니다. 그 국가의 `PUBLISHED` 필수 약관에 모두 동의했으면 통과합니다. |

국가 판정(국가 동의 모드 켜짐):

- 허용 목록에 있는 시간대이면 그 국가(KR 또는 US)를 씁니다.
- 다음 경우에는 KR을 씁니다: 헤더 없음, 목록에 없음, 규칙 꺼짐, 잘못된 값, 값 충돌.

동의가 없을 때:

| 경우 | 오류 | httpCode |
|---|---|---|
| 동의 내역이 전혀 없음 | `NotFoundAgreementError` (약관 동의 내역이 존재하지 않습니다.) | 404 |
| 국가 동의 모드 켜짐에서 필수 약관 미동의 | `NotPublishedAgreementError` (최신 약관에 동의하지 않았습니다.) | 422 |
| 국가 동의 모드 꺼짐에서 최신 동의 약관이 `PUBLISHED` 아님 | `NotPublishedAgreementError` | 422 |

- 404 또는 422를 받으면 토큰은 발급되지 않습니다. 앱은 사용자에게 약관 동의를 안내해야 합니다. 동의 화면의 위치(웹 또는 앱)는 열린 질문입니다(8장).

---

## 6. 토큰과 세션

| 항목 | 값 | 비고 |
|---|---|---|
| 리프레시 토큰 Redis 키 | `refreshTokens:pc:{pid}` | 웹 `refreshTokens:{pid}`, 모바일 `refreshTokens:m:{pid}`와 따로 있습니다. |
| 세션 Redis 키 | `sessions:{pid}:pc` (해시, 필드 = loginHistoryId) | 웹 `sessions:{pid}:web`, 모바일 `sessions:{pid}:mobile`과 따로 있습니다. |
| 액세스 토큰 Redis 키 | `accessTokens:{token}` | 공통 |
| PC 구분 값 | 토큰 클레임 `isDesktop: true` | 갱신·로그아웃 때 이 값으로 PC 키를 고릅니다. |
| 로그인 이력 `device` | `PC_APP` | 웹 `PC`, 모바일 `Mobile`. 값은 밑줄을 쓴 `PC_APP`입니다(공백 아님). |
| 액세스 토큰 Redis 만료 | `ACCESS_EXP_SECOND`, 기본 86400초(1일) | |
| 리프레시 토큰 Redis 만료 | `REFRESH_EXP_SECOND`, 기본 `ACCESS_EXP_SECOND × 90`(약 3개월) | |
| JWT `exp` | `ACCESS_EXP_SECOND` / `REFRESH_EXP_SECOND`. 설정 변경 이벤트 뒤 기본값은 `24h` / `30d` | 실제 운영값은 환경 설정에 있습니다. 코드로 확정할 수 없습니다. |

- 중복 세션 정리는 기기 종류별로 합니다. PC 로그인은 웹 세션을 끊지 않습니다.
- 액세스 토큰이 Redis에서 만료되면 서버가 로그인 이력에 로그아웃 시각을 기록하고 세션 항목을 지웁니다.

---

## 7. 오류 목록

모든 오류는 HTTP 200과 본문 `httpCode`로 옵니다.

### 7-1. 로그인 API에서 나올 수 있는 오류

| 오류 이름 | httpCode | message | 원인 |
|---|---|---|---|
| `UnauthorizedError` | 401 | Unauthorized error | 쿼리에 `authzToken` 있음, 또는 `X-Timblo-Token` 파싱 실패 |
| `ParamsUndefinedError` | 500 | Parameters Undefined .. | 본문에 `authzToken` 없음 |
| `AmTrayValidateError` | 401 | AM-Tray 인가토큰 검증 API 호출 실패 | 서버 설정 없음, ValidateToken 호출 실패·시간 초과, 알 수 없는 결과 |
| `AmTraySystemIdInvalidError` | 401 | AM-Tray 시스템 아이디 검증 실패 | ValidateToken 결과 `SYSTEMID_INVALID` |
| `AmTrayTokenInvalidError` | 401 | 유효하지 않은 AM-Tray 인가토큰 | ValidateToken 결과 `TOKEN_INVALID` |
| `NotFoundUserInfo` | 403 | Not found Email error | 사번에 맞는 사용자 없음 |
| `NotFoundAgreementError` | 404 | 약관 동의 내역이 존재하지 않습니다. | 5장 참고 |
| `NotPublishedAgreementError` | 422 | 최신 약관에 동의하지 않았습니다. | 5장 참고 |
| `UnauthorizedUserError` | 401 | Unauthorized user error | 토큰 발급 중 내부 오류 |
| `DeleteTokenUsingError` | 517 | Error Using Deleted Access Token | 삭제된 액세스 토큰을 보냄 |

### 7-2. 갱신·로그아웃에서 나올 수 있는 오류

| 오류 이름 | httpCode | message | 원인 |
|---|---|---|---|
| `UnauthorizedUserError` | 401 | Unauthorized user error | 로그인 상태 아님 |
| `NotFoundRefreshTokenError` | 529 | Not Found Refresh Token Error | `refreshTokens:pc:{pid}` 없음(만료 또는 로그아웃) |
| `ParamsUndefinedError` | 500 | Parameters Undefined .. | 본문 `token` 없음 |
| `RefreshTokenMissMatchError` | 530 | Refresh Token Miss Match Error | 저장 값과 다름 |
| `RefreshTokenVerifyError` | 531 | Refresh Token Verify Error | 서명 오류 또는 만료 |
| `DeleteTokenUsingError` | 517 | Error Using Deleted Access Token | 삭제된 액세스 토큰 사용 |
| `NoSessionError` | 500 | No Session Error | 로그아웃 때 토큰 없음 |

- 529, 530, 531을 받으면 AM-Tray 인가토큰으로 다시 로그인하십시오.

---

## 8. curl 예

```bash
# 1) 로그인 (AUTH 는 auth-api 주소, 예: https://<dev-host>/api)
curl -s -X POST "$AUTH/auth/sso/amtray" \
  -H 'Content-Type: application/json' \
  -H 'X-Device-Timezone: Asia/Seoul' \
  -d '{"authzToken":"<AM-Tray 인가토큰>"}'

# 2) 토큰 갱신
curl -s -X PUT "$AUTH/auth/refresh" \
  -H 'Content-Type: application/json' \
  -H "X-Timblo-Token: $ACCESS" \
  -d "{\"token\":\"$REFRESH\"}"

# 3) 로그아웃
curl -s -X DELETE "$AUTH/auth/logout" \
  -H "X-Timblo-Token: $ACCESS"
```

---

## 9. 배포 상태 (증거 기준)

| 항목 | 상태 | 근거 |
|---|---|---|
| 로그인 API (`a0062e9`) | `origin/2-release-dev`에 있음 | git log |
| PC 리프레시 키·로그인 이력 `PC_APP` (`588b2b1`) | `origin/2-release-dev`에 있음 | git log |
| PC 세션 키 `sessions:{pid}:pc` (`29533b7`) | `origin/2-release-dev`에 있음 | git log |
| 국가 동의 판정 (`98680b2`) | `origin/2-release-dev`에 있음 | git log |
| dev 서버에서 실행 중인 버전 | 확인 안 함 | 이 작업에서 dev 서버 버전·이미지를 조회하지 않았습니다. |
| 운영 배포 | 확인 안 함 | 근거 없음 |

- 이 PC의 로컬 체크아웃(`2-release-dev`, `96812aa`)은 `origin/2-release-dev`(`b957bda`)와 다릅니다. 이 문서는 `origin/2-release-dev` 기준입니다.
- 로그인 API는 서버 설정 `AMTRAY_VALIDATE_URL`이 있어야 동작합니다. 없으면 401(`AmTrayValidateError`)입니다. dev 설정에 값이 있는지는 확인하지 않았습니다.

---

## 10. 열린 질문

1. 게이트웨이를 지난 실제 dev·운영 주소(앞붙임 `/api` 포함)는 무엇입니까?
2. dev 서버의 `ACCESS_EXP_SECOND`, `REFRESH_EXP_SECOND` 값은 무엇입니까?
3. 약관 미동의(404/422) 때 PC 앱은 사용자를 어느 동의 화면으로 보냅니까?
4. 요청 문서의 로그인 이력 값은 `PC APP`이지만 코드 값은 `PC_APP`입니다. 이력 조회 화면이 `PC_APP`을 맞게 표시하는지 확인이 필요합니다.
5. 다시 로그인할 때 리프레시 토큰이 응답에 빠지는 동작(4-1)을 그대로 둘지 정해야 합니다.

---

## 부록 A. 코드 근거 (`origin/2-release-dev`, `backend/auth-api`)

| 내용 | 파일:줄 |
|---|---|
| PC 라우터, `POST /sso/amtray` | `src/routes/pcAuthRouter.js:5-10` |
| 라우터 연결 `/auth/` | `src/app.js:55-56` |
| 갱신·로그아웃 경로 | `src/routes/commonRouter.js:34`, `:37` |
| 쿼리 인가토큰 거절, 본문 필수 | `src/services/commonService/ssoAmTray.js:70-72` |
| ValidateToken 호출, 10초 상한 | `src/services/commonService/ssoAmTray.js:24`, `:36-65` |
| 사번 → 사용자, 403 | `src/services/commonService/ssoAmTray.js:80-88` |
| 약관 확인 호출 | `src/services/commonService/ssoAmTray.js:84` |
| `isDesktop` 설정 | `src/services/commonService/ssoAmTray.js:91` |
| 토큰 클레임 `isDesktop` | `src/services/tokenService/tokenAuthService.js:57` |
| 리프레시 토큰 기존 키 있으면 미발급 | `src/services/tokenService/tokenAuthService.js:65-66` |
| 기존 토큰 반환(갱신 대상 아님) | `src/services/tokenService/tokenAuthService.js:74-82` |
| 응답 형식 | `src/handlers/handleResponse.js:13-22`, `:58-62` |
| IP 차단 429 | `src/handlers/handleResponse.js:42-51` |
| 약관 판정 | `src/services/commonService/checkLoginAgreement.js:12-36` |
| 리프레시 키 `pc:{pid}` | `src/utils/redis/tokenUtils.js:14-17` |
| 만료 기본값 | `src/utils/redis/tokenUtils.js:2-3`, `src/services/tokenService/tokenHandler.js:4-11` |
| 세션 키 `sessions:{pid}:pc` | `src/utils/redis/sessionUtils.js:33-42` |
| 로그인 이력 `PC_APP` | `src/models/loginHistory.js:4-7`, `:27` |
| `X-Timblo-Token` 읽기 | `src/handlers/handleSession.js:45-54` |
| 갱신 경로는 서명만 풀기 | `src/utils/parserUtils.js:5-8`, `src/handlers/handleSession.js:6-8` |
| 만료 30분 전 판정 | `src/utils/parserUtils.js:16-33` |
| 모바일 판정 헤더 4개 | `src/utils/parserUtils.js:54-62` |
| 토큰 클레임 → PC 판정 | `src/handlers/handleBearerSession.js:12` |
| 갱신 처리 | `src/services/commonService/refreshAccessToken.js:18-58` |
| 로그아웃 처리 | `src/services/commonService/logout.js:15-36` |
| 오류 정의 | `src/configs/error.js:10-14`, `:28`, `:38-41`, `:69-74` |
