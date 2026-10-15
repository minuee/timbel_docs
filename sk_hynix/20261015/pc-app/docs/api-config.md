# 서버 API 설정 가이드

> 작성일: 2026-10-12
> API 주소, 메서드, 파라미터가 바뀌면 **`src/main/services/apiEndpoints.js` 한 파일만** 고치면 됩니다.
> 서버 주소·스위치 같은 설정값은 아래 순서로 읽습니다 (앞이 이김). 전체 목록은 저장소 루트 `.env.example`.
> 1. `.env` — **개발용. 설치본(exe)에는 포함되지 않습니다**
> 2. `src/config/app.config.json` — 빌드할 때 설치본에 들어갑니다. **운영 값은 여기에**
> 3. 코드 기본값

---

## 1. 빠른 시작 — 테스트 로그인으로 녹음 → 업로드 시험

SSO 협조를 기다리지 않고 바로 시험하는 방법입니다.

1. 웹(AI회의록)에 로그인해서 accessToken 을 복사합니다.
   (브라우저 개발자도구 → Network → 아무 API 요청 → Request Headers 의 `Authorization: Bearer ...` 값)
2. 앱 로그인 화면 맨 아래 **"테스트 로그인 (토큰 직접 입력)"** 을 펼칩니다.
3. 이름, 사번, accessToken 을 넣습니다. `Bearer ` 를 붙여서 붙여넣어도 됩니다.
   서버 주소는 비우면 `DEFAULT_API_BASE_URL`(기본 `https://aimeeting.mobile.skhynix.com/m`)을 씁니다.
4. **토큰으로 로그인** → 마이크 테스트 화면으로 넘어가고, 타이틀에 이름이 붙습니다.
5. 녹음을 시작하면 부서장 안내 메일 API 가 호출되고, 녹음을 마치면 업로드됩니다.

- 수동 로그인에는 refreshToken 이 없습니다. 토큰이 만료되면 다시 입력해야 합니다.
- 입력한 이름·사번은 서버 응답보다 우선합니다. 비워 둔 칸만 "내 정보" API 결과로 채웁니다.
- **운영 빌드에서는 반드시 끄세요**: `src/config/app.config.json` 에 `"MANUAL_LOGIN_ENABLED": false`

---

## 2. API 목록 (`apiEndpoints.js`)

| 키 | 언제 호출 | 기본값 (모바일 소스 기준) | 토큰 |
|---|---|---|---|
| `userMe` | 로그인 직후 | `GET /api/auth/user/me` | O |
| `workspace` | 로그인 직후 (`userMe` 다음) | `GET /api/auth/workspace/me` | O |
| `alertRecording` | 녹음 시작 시 | `POST {모바일서버}/api/alert/recording?empno={empno}` | O |
| `upload` | 녹음 종료 후 | `POST /api/contents/upload/encryption/files` (multipart) | O |

> 메모에는 1·4번도 POST 로 적혀 있었지만, 모바일 소스는 둘 다 **GET** 입니다. 서버가 POST 를 요구하면 `method` 만 바꾸세요.

### 항목 하나의 구조

```js
userMe: {
  method: 'get',                  // 'get' | 'post' | 'put' ...
  url: '/api/auth/user/me',       // 경로. baseURL 이 없으면 로그인한 서버 주소 뒤에 붙음
  // baseURL: 'https://...',      // 다른 서버로 보낼 때만
  auth: true,                     // true 면 Authorization: Bearer {accessToken} 자동 부착
  // params: { empno: '{empno}' },// 쿼리스트링 ?empno=...
  // body:   { empno: '{empno}' },// JSON 본문
  pick: {                         // 응답에서 꺼내 보관할 값 { 이름: '응답.안의.경로' }
    name: 'data.profile.name',
  },
},
```

### 자리표시 `{...}`

`url`, `params`, `body` 안의 `{이름}` 은 호출 시점의 사용자 정보로 바뀝니다.

| 자리표시 | 값이 들어오는 곳 |
|---|---|
| `{name}` | 수동 로그인 입력 → 없으면 `userMe` 의 `name`(없으면 `nickName`) |
| `{empno}` | 수동 로그인 입력 / 사번 로그인 입력 → 없으면 `userMe` 의 `empno` |
| `{email}`, `{deptName}` | `userMe` |
| `{workspaceId}`, `{workspaceName}`, `{workspaceRole}` | `workspace` |

`pick` 에 키를 추가하면 그 이름으로 자리표시를 쓸 수 있습니다.
**값이 비어 있으면 그 API 는 호출하지 않고** 로그(`api_skipped_missing_value`)만 남깁니다. 빈 사번으로 메일이 나가는 일을 막기 위해서입니다.

---

## 3. API 별 상세

### 3-1. 내 정보 (`userMe`)
- 응답(모바일 `ResponseMember`):
  `{ httpCode, message, data: { pid, provider, profile: { name, email, nickName, company: { empno, deptName } } } }`
- 꺼내는 값: `name`, `nickName`, `email`, `empno`, `deptName`
- 쓰임: 타이틀 `AI 회의록 녹음기(이름)`, 메일 API 의 `{empno}`
- 응답 구조가 다르면 `pick` 의 경로만 고치세요. 예: 이름이 `data.userName` 이면 `name: 'data.userName'`

### 3-2. 워크스페이스 (`workspace`)
- 응답(모바일 `ResponseWorkspaceMember`): `{ data: { id, role, workspace: { id, name, ... } } }`
- 꺼내는 값: `workspaceId`, `workspaceName`, `workspaceRole`
- 지금은 세션에 보관하고 로그에만 남깁니다. 업로드에 필요해지면 `main.js` 의 업로드 폼에 추가하면 됩니다.

### 3-3. 부서장 녹음 시작 안내 메일 (`alertRecording`)
요청하신 "2. 사번으로 부서장 이메일 조회"와 "3. 그 이메일로 발송"을 **서버가 한 번에** 처리합니다.

```
PC 앱 ── POST /api/alert/recording?empno=사번 ──▶ 모바일 서버 (docs/hynix-mobile)
                                                   ├─ 사번으로 사용자 프로필 조회
                                                   ├─ 사내 API 로 부서장 메일 조회 (gaia .../manager-email/{empno})
                                                   └─ 부서장에게 "[AI회의록] 사번_이름 (부서) 녹음 시작 안내" 발송
```

- 부서장 메일 조회 API 는 사내망 전용이라, 앱이 직접 부르지 않고 서버가 대신 부릅니다.
- 녹음 시작 명령(`start`) 때 1번만 호출합니다. 일시정지 후 재개(`resume`)할 때는 다시 보내지 않습니다.
- 녹음을 늦추지 않도록 응답을 기다리지 않습니다. 결과는 로그(`api_success` / `api_failed`)로 확인하세요.
- 끄려면 `ALERT_ON_RECORDING_START=false`
- ⚠️ 서버 메일 제목은 지금 "**모바일** 녹음 시작 안내"로 고정돼 있습니다. PC 에서 보내도 "모바일"로 나갑니다. PC 용 문구가 필요하면 서버 쪽 수정이 필요합니다.

### 3-4. 녹음 업로드 (`upload`) — 이미 구현돼 있음
`main.js` 의 `serverUpload()` 가 multipart 로 보냅니다. 경로만 `apiEndpoints.upload.url` 에서 읽습니다.

| 필드 | 값 |
|---|---|
| `files` | 녹음 폴더 안의 파일 전부 |
| `lang` | 요약 언어 |
| `attendeeNum` | 참석자 수 |
| `deviceId` | 지금은 `'1'` 고정. 실제 기기 ID 는 `docs/device-id.md` |
| `fileName` | `aimm_w_rec_YYMMDD_HHmmss` |
| `totalNum` | 파일 개수 |
| `manual` | `{ tag: [...], memo: [{ text, time }] }` JSON |

- 서버 주소: 로그인한 서버 주소 + 경로
- 토큰 만료가 60초 이내면 보내기 전에 미리 갱신합니다(refreshToken 이 있을 때만).

---

## 4. 설정 스위치 (`.env` / `src/config/app.config.json`)

| 이름 | 기본값 | 설명 |
|---|---|---|
| `MANUAL_LOGIN_ENABLED` | `true` | 테스트 로그인 폼 표시. **운영은 false** |
| `DEFAULT_API_BASE_URL` | `https://aimeeting.mobile.skhynix.com/m` | 테스트 로그인에서 서버 주소를 비웠을 때 쓰는 값 |
| `ALERT_ON_RECORDING_START` | `true` | 녹음 시작 시 부서장 메일 |
| `EMPNO_LOGIN_ENABLED` | `true` | 사번 로그인 폼 표시. 비밀번호 검증이 없어 **운영은 false 권장** |
| `SSO_LOGIN_URL` | (자리표시 값) | MyAccess 로그인 페이지 |
| `HMP_BASE_URL` / `HMP_LOGIN_PATH` | 모바일 서버 / `/api/auth/sso/hmp` | 사번 로그인 API |
| `REFRESH_PATH` / `REFRESH_METHOD` | `/api/auth/refresh` / `put` | 토큰 갱신 |
| `MOBILE_SERVER_URL` | `https://aimeeting.mobile.skhynix.com/m` | 부서장 메일 API 를 보낼 서버 |
| `LOG_SERVER_URL` / `LOG_SERVER_MIN_LEVEL` | `.../m/api/pcapp/log` / `info` | 로그 서버 전송 (`docs/logserver`) |
| `UPDATE_SERVER_URL` | 빈 값(=꺼짐) | 자동 업데이트 (`docs/auto-update.md`) |

---

## 5. 로그로 확인하기

| 로그 메시지 | 의미 |
|---|---|
| `manual_session_started` | 테스트 로그인 성공 |
| `api_success` (`api: 'userMe'` 등) | API 성공. `pickedKeys` 에 꺼낸 값 이름이 나옴 |
| `api_failed` | 서버가 오류 응답. `status`, `httpCode`, `message` 확인 |
| `api_network_error` | 연결 실패. `code` 가 인증서 오류면 사내 루트 인증서 문제 |
| `api_skipped_missing_value` | 자리표시 값이 없어서 호출 안 함 (예: 사번 모름) |
| `profile_loaded` | 로그인 직후 사용자 정보 정리 완료 |
