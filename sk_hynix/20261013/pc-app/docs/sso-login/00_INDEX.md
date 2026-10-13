# PC 녹음앱 SSO 로그인 도입 — 작업 지시서 (INDEX)

> **작성일**: 2026-09-02
> **대상 저장소**: `recording-pc-app` (Electron)
> **사용법**: 회사 AI에게 **한 번에 파일 1개(작업 1개)씩만** 던져주세요.
> 각 작업 문서는 그것만 읽어도 수행 가능하도록 독립적으로 작성돼 있습니다.
>
> 전체를 한 파일로 합친 `ALL_IN_ONE.md` 도 같은 폴더에 있습니다.
> **사람이 훑어보거나 파일 반입이 어려울 때만** 쓰세요. AI에게 통째로 주면 안 됩니다(1,500줄 이상).

---

## 1. 목표

설치형 앱(timbloRecApp)에 로그인 단계를 만든다.

```
앱 실행
  └─ 인증정보 없음
       └─ 로그인 대기 화면 표시 + 기본 브라우저 자동 실행
            └─ 브라우저에서 회사 SSO 로그인
                 └─ 웹이 딥링크 호출  timbloRecApp://connect?code=..&host=..
                      └─ 앱이 code → accessToken 교환   ← ★ 이미 구현되어 있음
                           └─ 내 정보 조회 → 메인 화면(index.html)으로 이동
```

이번 범위는 **로그인 단계까지**. 부가 목표로 타이틀의 하드코딩된 이름을
로그인한 사용자 이름으로 바꾼다.

---

## 2. 현재 코드 상태 (이미 되어 있는 것 / 없는 것)

### 이미 구현됨 — 건드리지 말 것
| 내용 | 위치 |
|---|---|
| 딥링크 스킴 등록 (`timbloRecApp`) | `src/main/main.js:176`, `scripts/register-protocol.js` |
| 딥링크 수신 (mac `open-url` / win `second-instance`) | `src/main/main.js:1198~1236` |
| 딥링크 파싱 + 토큰 교환 | `src/main/main.js:224` `processDeepLink()` |
| 토큰 교환 API 호출 | `src/main/services/authService.js:52` `exchangeToken()` |
| 토큰 메모리 보관 | `src/main/services/authService.js` |
| 요청에 Authorization 자동 부착 | `src/main/services/apiService.js` |
| 렌더러로 결과 통지 채널 | `main.js:283` `auth-exchanged` → `preload.js:21` |

### 없어서 만들어야 하는 것 — 이번 작업
1. 앱이 **브라우저를 여는 코드** (`shell.openExternal`이 프로젝트 전체에 하나도 없음)
2. 인증 전/후를 가르는 **로그인 게이트 화면**
3. **내 정보 / 워크스페이스 / 관리자 메일** 조회 API 호출부
4. `auth-exchanged` 이벤트를 **실제로 받는 렌더러 코드** (preload에만 있고 아무도 안 씀)

### 이번 범위에서 제외 (결정 사항)
- **토큰 영속 저장 안 함.** 메모리 보관 유지 → 앱 재시작 시 재로그인.
  (`docs/server_spec_questions.md` Q4-5 답변 후 별도 작업으로 진행)
- 토큰 갱신(refresh) 안 함. (Q4-1/Q4-3 답변 대기)
- 로그인 콜백은 **기존 딥링크를 재사용**한다. 로컬 루프백 서버 만들지 않는다.

---

## 3. ★ 서버 스펙 기입란 (회사에서 먼저 채울 것)

각 작업 문서는 아래 `S1~S7`을 참조합니다. **여기를 먼저 채우고 시작하세요.**
값을 모르면 각 문서에 적힌 기본값(placeholder)으로 두고 진행해도 코드는 완성됩니다.

| ID | 항목 | 값 |
|---|---|---|
| **S1** | SSO 로그인 페이지 경로 (예: `/login`) | ` ` |
| **S2** | 로그인 URL에 붙일 쿼리 파라미터 (예: `redirect=recorder`) | ` ` |
| **S3** | 내 정보 조회 API (메서드 + 경로) | ` ` |
| **S4** | 내 정보 응답에서 **사용자 이름** 필드명 (예: `data.userName`) | ` ` |
| **S5** | 워크스페이스 목록 조회 API | ` ` |
| **S6** | 관리자 메일주소 조회 API | ` ` |
| **S7** | 웹 서비스 기본 호스트 (온프레미스별) | 기본 `dev.timblo.io` |

### 참고 — 이미 아는 스펙 (토큰 교환)
```
GET {host}/api/auth/recorder/exchange/{code}
응답: { "message": "Success", "httpCode": 200, "data": { "accessToken": "..." } }
```
→ 다른 API들도 **같은 `{ message, httpCode, data }` 봉투 형식**일 가능성이 높음.
  작업 문서의 응답 파싱 코드는 이 형식을 전제로 작성돼 있습니다.

---

## 4. 작업 목록 (이 순서대로 진행)

| # | 파일 | 작업 내용 | 손대는 파일 | 크기 |
|---|---|---|---|---|
| 1 | `01_authConfig.md` | 로그인 URL 조립 설정 모듈 신규 | `services/authConfig.js` (신규) | 소 |
| 2 | `02_authService_profile.md` | 사용자 프로필 보관 기능 추가 | `services/authService.js` | 소 |
| 3 | `03_userService.md` | 내정보/워크스페이스/관리자메일 조회 모듈 신규 | `services/userService.js` (신규) | 중 |
| 4 | `04_main_ipc.md` | 인증 IPC 핸들러 3개 추가 | `main/main.js` | 소 |
| 5 | `05_preload.md` | 렌더러에 `authAPI` 노출 | `main/preload.js` | 소 |
| 6 | `06_login_page.md` | 로그인 대기 화면 신규 | `renderer/pages/login.html`, `renderer/scripts/login.js` (신규) | 중 |
| 7 | `07_main_gate.md` | 시작 화면 분기 + 교환 성공 후 처리 | `main/main.js` | 중 |
| 8 | `08_title_username.md` | 타이틀에 사용자 이름 노출 | `renderer/index.html`, `renderer/index.js` | 소 |
| 9 | `09_dev_deeplink_test.md` | 개발 모드 딥링크 테스트 수단 | `main/main.js`, `main/preload.js` | 중 |

**1~7이 로그인 기능. 8은 부가 작업. 9는 테스트 수단.**
7번까지 끝나면 로그인이 동작합니다. 시간이 없으면 8번은 버려도 됩니다.

**9번은 먼저 해도 됩니다.** macOS에서 개발하신다면 7번을 검증하려면 9번이 필요하므로,
`7 → 9 → 검증` 또는 `4 → 9 → 5~7` 순서로 진행하세요.

---

## 5. 회사 AI에게 줄 공통 규칙 (작업 문서와 함께 붙여넣기)

```
[공통 규칙]
1. 이 문서에 적힌 파일 외에는 절대 수정하지 마라.
2. 기존 코드를 삭제하지 마라. 지시된 위치에 "추가"만 해라.
3. 문서에 "신규 파일"이라고 적힌 것은 파일 전체를 그대로 생성해라.
4. 문서에 "수정"이라고 적힌 것은 [찾을 코드]를 파일에서 찾아
   [바꿀 코드]로 교체해라. 찾는 코드가 없으면 멈추고 보고해라.
5. 주석은 한국어로, 기존 파일의 주석 스타일(왜 그렇게 했는지 설명)을 따라라.
6. 작업이 끝나면 변경한 파일명과 줄 수만 보고해라. 코드 전문을 다시 출력하지 마라.
```

---

## 6. 완료 확인 방법 (7번 작업 후)

1. `yarn start` (또는 `npm start`) 로 앱 실행
2. 로그인 대기 화면이 뜨고, 기본 브라우저가 자동으로 열리는지 확인
3. 브라우저에서 SSO 로그인 완료
4. 앱이 자동으로 메인 화면(마이크 테스트)으로 전환되는지 확인
5. 로그 확인: `deeplink_exchange_success`, `auth_profile_loaded` 가 찍히는지
   - 로그 위치는 `src/main/logger.js` 참고

> **딥링크 테스트 방법은 OS마다 다릅니다.** `09_dev_deeplink_test.md` 를 참고하세요.
> - **Windows**: 개발 모드에서도 실제 딥링크 테스트 가능 (작업 9에서 등록 조건 1줄 수정)
> - **macOS**: 개발 모드에서는 불가. 작업 9의 시뮬레이션 훅으로 테스트
> - **양쪽 공통**: 최종 확인은 `npm run build` 후 빌드본으로
>
> 실행 명령도 구분해서 씁니다.
> - 평소 개발: `npm run dev`
> - **딥링크/로그인 테스트: `npm start -- --dev`**

---

## 부록 A. 작업 중 발견한 기존 이슈 (참고용 · 이번 범위 아님)

### 딥링크가 두 번 처리될 수 있음

`main.js:177~205` 를 보면 딥링크 하나가 `processDeepLink()` 를 **두 번** 탈 수 있다.

```js
function sendDeepLinkToRenderer(url) {
  if (!mainWindow) { deepLinkQueue.push(url); return; }
  if (mainWindow.webContents.isLoading()) {
    deepLinkQueue.push(url);      // ← 큐에 넣고
  } else { ... }
  processDeepLink(url).catch(() => {});   // ← 여기서 이미 처리하는데
}

function flushDeepLinks() {
  for (const url of deepLinkQueue) {
    mainWindow.webContents.send("deep-link", url);
    processDeepLink(url).catch(() => {});  // ← 큐에서 또 처리
  }
}
```

**언제 문제가 되나**: 앱이 꺼진 상태에서 딥링크로 실행될 때(=창 로딩 중).
`code` 는 1회용이므로 두 번째 교환은 실패하고,
`broadcastAuthExchanged({ success: false })` 가 화면으로 날아간다.

**영향**: 로그인 성공 직후 화면에 로그인 실패 문구가 뜰 수 있다.
(작업 6의 `login.js` 는 성공 시 곧바로 화면을 넘기므로 대부분 묻히지만,
타이밍에 따라 보일 수 있다)

**한 줄 수정안** — 이미 처리한 URL은 건너뛴다.
```js
const processedDeepLinks = new Set();

async function processDeepLink(url) {
  if (processedDeepLinks.has(url)) return;   // 함수 맨 앞에 추가
  processedDeepLinks.add(url);
  ...
}
```

> 이번 로그인 작업과 별개 건이라 지시서에 넣지 않았다.
> 로그인 테스트 중 "로그인은 됐는데 실패 문구가 뜬다"는 증상이 보이면 이걸 적용할 것.
