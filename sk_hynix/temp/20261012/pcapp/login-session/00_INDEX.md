# PC 녹음앱 로그인·세션 — 작업 지시서 (INDEX)

> **작성일**: 2026-10-12
> **대상 저장소**: `recording-pc-app` (Electron)
> **기준 커밋**: `eec5a56` (fix: eCapture기능 추가)
> **사용법**: 회사 AI에게 **한 번에 파일 1개(작업 1개)씩만** 던져주세요.
> 각 작업 문서는 그것만 읽어도 수행할 수 있게 독립적으로 작성돼 있습니다.
>
> ⚠️ 이 문서 묶음은 예전 `docs/sso-login/` 지시서(2026-09-02)를 **대체**합니다.
> 그 지시서는 더 이상 쓰지 마세요.

---

## 1. 목표

```
앱 실행
  └─ 세션 없음 → 로그인 화면(login.html)
       ├─ [사번 + 비밀번호] → 로그인 버튼 → HMP API 로 토큰 발급        (경로 A)
       └─ [MyAccess 로그인] → 기본 브라우저로 SSO 페이지 열기             (경로 B)
              └─ 웹이 딥링크 호출  timbloRecApp://connect?code=..&host=..
                   └─ 앱이 code → accessToken 교환 (이미 있던 기능)
  └─ 로그인 성공 → 메인 화면(index.html, 마이크 테스트)

세션 유지
  - 토큰은 메모리에만 보관. 앱이 켜져 있는 동안 유지, 끄면 다시 로그인.
  - 만료 60초 전이면 요청 보내기 전에 미리 갱신 (JWT exp 기준)
  - 401 이 오면 refreshToken 으로 갱신 후 1회 재시도
  - 갱신까지 실패하면 세션을 버리고, 마이크 테스트 화면에 있을 때 로그인 화면으로 이동
    (녹음 화면에 있을 때는 녹음이 끊기지 않게 화면을 바꾸지 않는다)
```

---

## 2. ★ 시작 전 준비 (사람이 직접)

### 2-1. 기준 커밋 확인
```bash
git log -1 --oneline
```
`eec5a56` 이 아니면 작업 문서의 `[찾을 코드]` 가 안 맞을 수 있습니다.
그래도 진행은 가능합니다. 찾는 코드가 없으면 AI가 멈추고 보고하게 돼 있습니다.

### 2-2. 이전에 회사 AI가 만든 로그인 변경 되돌리기
이전에 로그인 화면과 리다이렉트를 일부 만들어 두셨다면, **아래 파일은 원래대로 되돌린 뒤** 시작하세요.
(이번 지시서는 깨끗한 상태를 기준으로 작성됐습니다.)
```bash
git status
git checkout -- src/main/main.js src/main/preload.js
```
- 이전 시도로 새로 만든 파일(예: `login.html`, `login.js`)은 지우지 않아도 됩니다. 작업 9·10에서 **통째로 덮어씁니다**.
- `authService.js`, `apiService.js` 도 작업 2·3에서 통째로 덮어씁니다.

---

## 3. ★ 서버 스펙 기입란 (회사에서 확인 후 작업 1 문서에 반영)

모든 값은 `src/main/services/authConfig.js` 한 곳에 모여 있습니다.
값을 몰라도 기본값으로 코드는 완성되고, 나중에 이 파일이나 `.env` 만 고치면 됩니다.

| ID | 항목 | 기본값 (확인 필요) | 근거 |
|---|---|---|---|
| **S1** | MyAccess SSO 로그인 URL (`SSO_LOGIN_URL`) | `https://amdev.skhynix.com/sso/m/login.jsp?TYPE=XX&REALMOID=XX&GUID=XX` | 쿼리스트링은 회사에서 정확히 기입 |
| **S2** | 사번 로그인 서버 (`HMP_BASE_URL`) | `https://aimeeting.mobile.skhynix.com/m` | 모바일 `api_const.dart` |
| **S3** | 사번 로그인 경로 (`HMP_LOGIN_PATH`) | `/api/auth/sso/hmp` | 모바일 `api_const.dart` ※ |
| **S4** | 토큰 갱신 메서드 (`REFRESH_METHOD`) | `put` | 모바일 `api_service.dart` 는 **PUT** ※ |
| **S5** | PC 의 `timblo-App-OS` 값 (`APP_OS`) | `WINDOWS` / `MAC` | 모바일은 `AOS`/`IOS`. 서버와 합의 |
| **S6** | 비밀번호 필드명 (`HMP_PASSWORD_FIELD`) | 빈 값 = 안 보냄 | 아래 4번 참고 |
| **S7** | 사번 로그인 폼 노출 (`EMPNO_LOGIN_ENABLED`) | `true` | 아래 4번 참고 |

※ **S3**: 메모로 받은 주소는 `.../m/app/auth/sso/hmp` 였지만, 모바일 소스는 `.../m` + `/api/auth/sso/hmp` 입니다. 오타일 가능성이 높아 모바일 소스를 따랐습니다.
※ **S4**: 서버 담당자가 POST 라고 하면 `REFRESH_METHOD` 만 `'post'` 로 바꾸세요.

---

## 4. ⚠️ 보안 주의 — 사번 로그인(경로 A)

HMP API(`/api/auth/sso/hmp`)는 **body 에 `empno`(사번) 하나만 받고 비밀번호를 검증하지 않습니다.**
모바일은 사내 HMP 앱이 본인 인증을 먼저 끝내고 사번을 넘겨주니 문제가 없었지만,
PC 에서는 **남의 사번을 입력해도 그 사람으로 로그인됩니다.**

그래서 코드는 이렇게 만들어 두었습니다.
- 화면에는 비밀번호 칸이 있지만, **서버가 받지 않으므로 보내지 않습니다**(`HMP_PASSWORD_FIELD` 가 빈 값).
  검증하지 않는 서버로 평문 비밀번호를 보낼 이유가 없기 때문입니다.
- 서버가 비밀번호를 검증하게 되면 `HMP_PASSWORD_FIELD` 에 필드 이름만 넣으면 됩니다.
- **운영 배포 전까지 서버 측 검증이 없으면 `EMPNO_LOGIN_ENABLED=false`** 로 두세요. 사번 폼이 숨겨지고 MyAccess 버튼만 남습니다.

---

## 5. 작업 목록 (이 순서대로)

| # | 파일 | 작업 내용 | 손대는 파일 | 방식 |
|---|---|---|---|---|
| 1 | `01_authConfig.md` | 서버 주소·옵션 설정 모듈 | `src/main/services/authConfig.js` | 신규 |
| 2 | `02_authService.md` | 세션 보관, 사번 로그인, 토큰 갱신 | `src/main/services/authService.js` | **통째 교체** |
| 3 | `03_apiService.md` | 공통 헤더, 사전 갱신, 401 재시도 | `src/main/services/apiService.js` | **통째 교체** |
| 4 | `04_handleAuth.md` | 로그인 게이트 + 인증 IPC | `src/main/ipc/handleAuth.js` | 신규 |
| 5 | `05_main_gate.md` | main.js 에 게이트 연결 | `src/main/main.js` | 수정 3곳 |
| 6 | `06_main_home.md` | 홈 이동을 게이트 경유로 | `src/main/main.js` | 수정 3곳 |
| 7 | `07_main_deeplink.md` | 딥링크 중복 처리 수정 + 로그인 후 화면 전환 | `src/main/main.js` | 수정 3곳 |
| 8 | `08_preload.md` | 렌더러에 `authAPI` 노출 | `src/main/preload.js` | 수정 1곳 |
| 9 | `09_login_page.md` | 로그인 화면 HTML/CSS | `pages/login.html`, `styles/login.css` | 신규(덮어쓰기) |
| 10 | `10_login_script.md` | 로그인 화면 동작 | `scripts/login.js` | 신규(덮어쓰기) |
| 11 | `11_mock_test.md` | (선택) 가짜 서버로 갱신 로직 검증 | 저장소 밖 임시 폴더 | 테스트 |

- **1 → 2 → 3 → 4** 는 반드시 이 순서로 하세요. 뒤 파일이 앞 파일을 `require` 합니다.
- **5~8 은 4번이 끝난 뒤**라면 순서는 상관없습니다.
- 10번까지 끝나면 기능이 완성됩니다.

---

## 6. 회사 AI에게 줄 공통 규칙 (작업 문서와 함께 붙여넣기)

```
[공통 규칙]
1. 이 문서에 적힌 파일 외에는 절대 수정하지 마라.
2. "신규" 또는 "통째 교체"라고 적힌 파일은, 문서의 코드 블록 내용 그대로 파일 전체를 만든다.
   기존 내용이 있으면 전부 지우고 덮어쓴다. 코드를 요약하거나 생략하지 마라.
3. "수정"이라고 적힌 것은 [찾을 코드]를 파일에서 찾아 [바꿀 코드]로 교체한다.
   찾을 코드가 없거나 2군데 이상이면 아무것도 고치지 말고 멈춰서 보고해라.
4. 들여쓰기와 따옴표 종류(" 와 ')를 문서와 똑같이 유지해라.
5. 끝나면 문서의 [확인 방법]을 실행하고, 결과와 변경한 파일명만 보고해라.
   코드 전문을 다시 출력하지 마라.
```

---

## 7. 완료 확인 (10번까지 끝난 뒤, 사람이 직접)

```bash
npm start -- --dev
```
1. 앱이 켜지면 **로그인 화면**이 뜬다 (사번/비밀번호 칸, 로그인 버튼, MyAccess 로그인 버튼)
2. **경로 A**: 사번 입력 → 로그인 → 마이크 테스트 화면으로 넘어가면 성공
   - 실패하면 화면에 사유가 빨간 글씨로 나온다. 서버 메시지가 있으면 그대로 보여준다(예: 약관 동의 필요)
3. **경로 B**: MyAccess 로그인 → 브라우저가 열린다 → 로그인 → 앱이 마이크 테스트 화면으로 넘어가면 성공
   - 딥링크는 빌드본(`npm run build`)에서 확실히 동작합니다. 개발 모드에서 안 오면 빌드본으로 확인하세요.
4. 로그 파일에서 아래가 찍히는지 확인 (로그 위치는 `src/main/logger.js` 참고)
   - 경로 A: `hmp_login_begin` → `hmp_login_success` → `load_home`
   - 경로 B: `sso_browser_opened` → `deeplink_received` → `exchange_token_success` → `deeplink_exchange_success` → `load_home`
   - 갱신 시: `token_refresh_success` / 실패 시 `token_refresh_failed` → `session_expired`

### 잘 안 될 때

| 증상 | 원인/조치 |
|---|---|
| 앱이 바로 마이크 테스트 화면으로 뜸 | 작업 5가 안 들어감. `loadHome();` 이 `createWindow()` 안에 있는지 확인 |
| 로그인 화면이 하얗게 뜸 | 작업 8(preload) 누락이거나 `login.js` 경로 오류. 개발자도구 콘솔 확인 |
| 사번 로그인 시 `network_error` | 사내망/인증서 문제일 수 있음. 로그의 `hmp_login_network_error` 의 `code` 확인. `UNABLE_TO_VERIFY_LEAF_SIGNATURE`, `SELF_SIGNED_CERT_IN_CHAIN` 이면 사내 인증서 문제이므로 **인증서 검증을 끄지 말고** 담당자에게 사내 루트 인증서를 받아 `NODE_EXTRA_CA_CERTS` 로 지정 |
| 사번 로그인 시 `invalid_response` | 서버가 JSON 대신 HTML 을 돌려줌(주소 오류 또는 리다이렉트 페이지). S2/S3 주소 확인 |
| MyAccess 로그인 후 "로그인 응답이 올바르지 않습니다" | 딥링크의 `host` 가 base64 가 아님. 웹 담당자에게 확인 |
| 로그인은 됐는데 업로드가 401 | 토큰을 발급한 서버와 업로드 서버가 다를 수 있음. 아래 8번 질문 참고 |

---

## 8. 서버 담당자에게 확인할 것

1. **[보안] HMP API 에 비밀번호 검증을 추가할 수 있는가?** 안 되면 PC 의 사번 로그인은 운영에서 막아야 함
2. HMP API 정확한 경로: `/m/api/auth/sso/hmp` 가 맞는가? (메모로 받은 주소는 `/m/app/...`)
3. 토큰 갱신은 `PUT` 인가 `POST` 인가? body `{ token, fcmToken }` 형식 그대로인가?
4. `GET /api/auth/recorder/exchange/{code}` 응답에 `refreshToken` 도 들어오는가?
   (없으면 MyAccess 로그인 쪽은 토큰이 만료되면 다시 로그인해야 함)
5. accessToken 은 JWT 인가? 유효시간은? (JWT 면 만료 60초 전에 자동 갱신, 아니면 401 받은 뒤 갱신)
6. PC 의 `timblo-App-OS` 값은 무엇으로 보낼까? (모바일은 `AOS`/`IOS`)
7. 사번 로그인으로 받은 토큰으로 `https://aimeeting.mobile.skhynix.com/m/api/contents/upload/encryption/files` 업로드가 되는가?

---

## 부록. 이번 작업에서 함께 고친 기존 버그

**딥링크가 두 번 처리되던 문제** (작업 7에 포함)
앱이 꺼진 상태에서 딥링크로 실행되면(창 로딩 중), 같은 딥링크가 `processDeepLink()` 를 두 번 탔습니다.
`code` 는 1회용이라 두 번째 교환이 실패하고, **로그인 성공 직후 "실패" 통지가 화면에 날아갔습니다.**
이미 처리한 `code` 는 다시 교환하지 않도록 고쳤습니다.
