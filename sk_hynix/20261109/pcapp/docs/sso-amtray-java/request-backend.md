# 백엔드 API 요청서 — AM-Tray 시스템 로그인

> PC 녹음앱에 SK하이닉스 AM-Tray(SSO 에이전트) 시스템 로그인을 붙입니다.
> 앱은 AM DLL 에서 **인가토큰(authzToken)** 을 받습니다. 이 토큰은 **서버에서 SSO 서버로 검증**해야 사용자 ID 를 알 수 있어서
> **"인가토큰 → 우리 토큰" API 를 새로 만들어 주셔야 합니다.**

## 1. 흐름
```
PC앱 ──① POST {새 API} { authzToken } ──▶ 백엔드
                                        ② POST https://samlam(dev).skhynix.com/tray/api/ValidateToken
                                           { systemID, authzToken }  → attr.RESULTID == SUCCESS, attr.USERID
                                        ③ USERID(사번)로 사용자 확인 → 우리 accessToken / refreshToken 발급
PC앱 ◀──④ { httpCode, message, data: { empno, tokens: { accessToken, refreshToken } } }
```

## 2. 요청드리는 API (제안 — 경로·이름은 편하신 대로)

| 항목 | 제안 |
|---|---|
| 경로 | `POST /api/auth/sso/amtray` (모바일 서버, 사번 로그인 `/api/auth/sso/hmp` 와 같은 곳) |
| 인증 | 없음 (로그인 API) |
| 요청 | `{ "authzToken": "<AM 인가토큰>" }` |
| 성공 응답 | 사번 로그인(HMP)과 **같은 봉투** → 앱 코드를 그대로 씀 |

```json
{
  "httpCode": 200,
  "message": "Success",
  "data": {
    "empno": "<USERID 로 찾은 사번>",
    "tokens": { "accessToken": "...", "refreshToken": "..." }
  }
}
```

| 경우 | httpCode (제안) | 앱 동작 |
|---|---|---|
| 성공 | 200 | 로그인 |
| 약관 미동의 | 404 / 422 (HMP 와 같게) | 약관 안내 팝업 |
| 토큰 검증 실패 (`TOKEN_INVALID`) | 401 | "시스템 로그인 실패" + 서버 message 표시 |
| 시스템 ID 오류 (`SYSTEMID_INVALID`) / SSO 통신 실패 | 500 계열 | 같음 (message 표시) |

> 발급 토큰은 **지금 웹·테스트 로그인에서 쓰는 Bearer accessToken 과 같은 것**이면 됩니다(앱은 그대로 `Authorization: Bearer` 로 씀). refreshToken 도 주시면 자동 갱신됩니다.

> 경로·필드가 달라져도 괜찮습니다. 앱은 설정값(`AMTRAY_LOGIN_PATH`)과 한 함수(`authService.loginWithAmToken`)만 맞추면 됩니다. **확정되면 요청·응답 예시를 그대로** 보내 주세요.

## 3. SSO 서버 검증 API (AM 측 자료 정리)

| 항목 | 값 |
|---|---|
| URL 개발 | `https://samlamdev.skhynix.com/tray/api/ValidateToken` |
| URL 운영 | `https://samlam.skhynix.com/tray/api/ValidateToken` |
| Method / 형식 | `POST` / JSON (`application/json; charset=UTF-8`) |
| 요청 | `{ "systemID": "<우리 시스템 ID>", "authzToken": "<토큰>" }` |
| 응답 | `{ "status": 300, "attr": { "RESULTID": "SUCCESS", "USERID": "<사용자 ID>" } }` |
| RESULTID | `SUCCESS` / `SYSTEMID_INVALID` / `TOKEN_INVALID` / 그 밖 = 통신 실패 |

- Spring 샘플 코드(AM 측 제공, 손으로 옮긴 것): `clean/ServerValidateSample.java`, `clean/SslRestTemplate.java`
- ⚠️ 샘플은 **SSL 인증서 검증을 끈 채(trust all)** 호출합니다(사내 인증서 때문으로 보임). 운영에서 그대로 쓸지 판단 부탁드립니다 — 사내 CA 를 truststore 에 넣는 방식 권장.
- 확인 중(AM 담당에게 질문함): 요청 키 `systemID`/`SystemID`, 응답 `RESULTID`/`Result`·값 대소문자, `status: 300` 의 의미, `USERID` 가 사번인지 AD 계정인지.

## 4. 필요한 것 / 확인 부탁
1. **우리 시스템 ID** — AM 담당자에게 발급 (개발·운영). 앱과 백엔드가 같은 값을 씁니다(앱은 DLL 호출에, 백엔드는 검증에).
2. 백엔드 서버 → samlam(dev/운영) **방화벽**.
3. `USERID` → 사번 매핑 (USERID 가 AD 계정이면 사번 조회 필요).
4. 사번만으로 토큰을 발급하는 것과 같은 성격이므로, **반드시 ValidateToken 성공일 때만** 발급해 주세요(앱이 보낸 사번을 믿지 않음 — 앱은 사번을 보내지 않습니다).
5. 일정 공유 부탁드립니다. 그 전까지 앱은 토큰을 받아도 "시스템 로그인 서버 준비 중" 으로 안내합니다.
