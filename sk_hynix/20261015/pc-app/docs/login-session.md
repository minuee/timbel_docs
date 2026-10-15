# 로그인 · 세션

> 작성일: 2026-10-12
> 관련 문서: `docs/api-config.md`(API 주소·테스트 로그인), `.env.example`(설정 전체 목록)

## 1. 전체 흐름

```
앱 실행
  ├─ (Windows 빌드본) 업데이트 확인 → 새 버전이면 업데이트 화면 (docs/auto-update.md)
  └─ 세션 없음 → 로그인 화면 (src/renderer/pages/login.html)
        ├─ A. 사번 + 비밀번호 → [로그인]           → HMP API 로 토큰 발급
        ├─ B. [MyAccess 로그인] → 기본 브라우저로 SSO 페이지
        │       └─ 웹이 딥링크 호출 timbloRecApp://connect?code=..&host=..
        │            └─ GET {host}/api/auth/recorder/exchange/{code} → 토큰
        └─ C. 테스트 로그인(펼침) → 이름·사번·accessToken 직접 입력
  └─ 로그인 성공 → 내 정보 + 워크스페이스 조회 → 메인 화면(index.html), 타이틀에 이름
```

## 2. 세션 규칙

| 항목 | 동작 |
|---|---|
| 보관 위치 | **메모리만.** 디스크에 저장하지 않는다. 앱을 끄면 다시 로그인 |
| 렌더러 노출 | 토큰은 메인 프로세스 밖으로 나가지 않는다. 화면에는 이름·사번 등 프로필만 |
| 미리 갱신 | accessToken 이 JWT 이고 만료 60초 이내면 요청 직전에 갱신 (업로드는 재전송이 안 되므로) |
| 401 | refreshToken 으로 갱신 후 1회 재시도. 동시에 여러 요청이 401 이어도 갱신은 1번만 |
| 갱신 실패 | 세션 폐기 → **마이크 테스트 화면에 있을 때만** 로그인 화면으로. 녹음 화면은 건드리지 않음 |
| 갱신 수단 없음 | refreshToken 이 없으면(테스트 로그인, 또는 exchange 가 안 내려줄 때) 만료 시 재로그인 |
| 홈 이동 | `index.html` 을 직접 띄우던 4곳 모두 `loadHome()` 을 거친다 → 세션이 없으면 로그인 화면 |

## 3. 로그인 경로별 상세

### A. 사번 로그인 (HMP)
- `POST {HMP_BASE_URL}{HMP_LOGIN_PATH}` = `https://aimeeting.mobile.skhynix.com/m/api/auth/sso/hmp`
- body `{ "empno": "사번" }`, 헤더 `timblo-App-OS / Version / Lang / Device`
- 응답 `{ httpCode, message, data: { is2FA, tokens: { accessToken, refreshToken } } }`
- 거절 시 서버 메시지를 그대로 보여준다 (모바일 기준 404/422 = 약관 미동의)

> ⚠️ **보안**: 이 API 는 **비밀번호를 검증하지 않는다.** 남의 사번으로도 로그인된다.
> 화면의 비밀번호 칸은 서버로 보내지 않는다(`HMP_PASSWORD_FIELD` 가 빈 값).
> 서버가 검증을 추가하기 전에는 운영 빌드에서 `EMPNO_LOGIN_ENABLED=false`.

### B. MyAccess (SSO)
- 버튼 → `shell.openExternal(SSO_LOGIN_URL)`
- 딥링크 수신은 기존 코드(`main.js` `processDeepLink`). 성공하면 로그인 화면에서 자동으로 넘어간다
- **같이 고친 버그**: 앱이 꺼진 상태에서 딥링크로 실행되면 같은 code 를 두 번 교환해서,
  로그인 성공 직후 "실패" 통지가 날아가던 문제. 처리한 code 는 다시 교환하지 않는다

### C. 테스트 로그인
`docs/api-config.md` 1장 참고. 운영 빌드에서는 `MANUAL_LOGIN_ENABLED=false`.

### 토큰 갱신
- `PUT {세션 서버}/api/auth/refresh`, body `{ token: refreshToken, fcmToken: "" }`, `Authorization: Bearer {만료된 accessToken}`
- 응답 `data.tokens.accessToken` (refreshToken 도 오면 교체)
- 메서드는 모바일 소스 기준 PUT. 서버가 POST 면 `REFRESH_METHOD=post`

## 4. 파일

| 파일 | 역할 |
|---|---|
| `src/main/services/authConfig.js` | 로그인 관련 설정값 |
| `src/main/services/authService.js` | 세션 보관, 사번 로그인, code 교환, 갱신, 수동 세션 |
| `src/main/services/apiService.js` | 공통 헤더, 사전 갱신, 401 재시도 |
| `src/main/ipc/handleAuth.js` | 로그인 게이트(`loadHome`), 인증 IPC |
| `src/renderer/pages/login.html`, `scripts/login.js`, `styles/login.css` | 로그인 화면 |
| `src/main/preload.js` | `window.authAPI` |

로그 이벤트: `hmp_login_success` / `hmp_login_failed` / `sso_browser_opened` / `deeplink_exchange_success` /
`manual_session_started` / `token_refresh_success` / `token_refresh_failed` / `session_expired` / `load_home`

## 5. 서버 담당자에게 확인할 것

1. **[보안] HMP API 에 비밀번호 검증 추가 가능한가?** 안 되면 PC 사번 로그인은 운영에서 막는다
2. HMP 경로 `/m/api/auth/sso/hmp` 가 맞는가? (메모로 받은 주소는 `/m/app/...`)
3. 토큰 갱신이 `PUT` 인가 `POST` 인가? body `{ token, fcmToken }` 그대로인가?
4. `GET /api/auth/recorder/exchange/{code}` 응답에 refreshToken 이 오는가?
5. accessToken 이 JWT 인가? 유효시간은?
6. PC 의 `timblo-App-OS` 값은? (모바일 `AOS`/`IOS`)
7. 사번 로그인 토큰으로 `.../m/api/contents/upload/encryption/files` 업로드가 되는가?
8. 내 정보·워크스페이스 API 가 GET 인가 POST 인가? (모바일은 GET)
9. 부서장 메일 제목이 "모바일 녹음 시작 안내"로 고정 — PC 용 문구가 필요한가?

## 6. 검증

- 가짜 서버 테스트(사번 로그인, 401 갱신·동시성, 사전 갱신, 갱신 거절, 스트림 미재전송, 화면 전환 규칙, 테스트 로그인, 프로필, 메일 API) 28건 통과
- 실제 앱 실행: 로그인 화면 표시까지 확인. **실서버 로그인·SSO 딥링크는 미확인**(사내망 필요)
