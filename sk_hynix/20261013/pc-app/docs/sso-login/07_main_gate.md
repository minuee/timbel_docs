# 작업 7 — 로그인 게이트 연결 (마지막 조립 단계)

**손대는 파일**: `src/main/main.js` — **수정**
**다른 파일은 건드리지 않는다.**

> ⚠️ **작업 1~6이 모두 끝난 뒤에 진행할 것.** 이 작업이 앞의 조각들을 이어 붙인다.

---

## 왜 필요한가

지금까지 만든 것들(설정, 조회 모듈, IPC, preload, 로그인 화면)은
아직 아무도 부르지 않는다. 두 가지를 연결하면 로그인이 동작한다.

1. **앱 시작 시** — 로그인 안 되어 있으면 `index.html` 대신 `login.html` 을 띄운다
2. **토큰 교환 성공 시** — 내 정보를 조회해서 저장한 뒤 화면에 알린다

---

## 할 일 — 2군데 수정

### 7-1. 시작 화면 분기

토큰은 메모리에만 보관하므로, 앱을 새로 켜면 항상 로그인 화면부터 시작한다.

**[찾을 코드]** (306번째 줄 근처, `createWindow()` 함수 안)
```js
  mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  try { logger.logInfo('window_created', { windowId: mainWindow.id, route: 'index.html' }); } catch (_) {}
```

> 주의: `loadFile(... "../renderer/index.html")` 은 이 파일에 4군데 있다.
> **바로 아래 줄에 `window_created` 로그가 붙어 있는 것**만 고친다.

**[바꿀 코드]**
```js
  // 토큰은 메모리에만 보관하므로(앱 종료 시 소멸) 새로 켜면 항상 로그인 화면부터 시작한다.
  // 인증 후에는 login.js 가 load-index IPC 로 index.html 을 띄운다.
  const startRoute = authService.isAuthenticated()
    ? "../renderer/index.html"
    : "../renderer/pages/login.html";
  mainWindow.loadFile(path.join(__dirname, startRoute));
  try { logger.logInfo('window_created', { windowId: mainWindow.id, route: startRoute }); } catch (_) {}
```

---

### 7-2. 토큰 교환 성공 직후 내 정보 조회

`processDeepLink()` 함수 안(268번째 줄 근처)을 고친다.

**[찾을 코드]**
```js
    authService.setSession({
      accessToken: exchangeResult.result,
      refreshToken: exchangeResult.refreshToken,
      endpoint,
    });
    try { logger.logInfo('deeplink_exchange_success'); } catch (_) {}

    broadcastAuthExchanged({ success: true, endpoint });
```

**[바꿀 코드]**
```js
    authService.setSession({
      accessToken: exchangeResult.result,
      refreshToken: exchangeResult.refreshToken,
      endpoint,
    });
    try { logger.logInfo('deeplink_exchange_success'); } catch (_) {}

    // 사용자 정보를 미리 받아둔다.
    // 실패해도 로그인 자체는 성공으로 처리한다 — 이름 표시가 안 될 뿐,
    // 토큰은 유효하므로 녹음·업로드는 정상 동작해야 한다.
    try {
      const meResult = await userService.fetchMyInfo();
      if (meResult.success) {
        authService.setProfile(userService.toProfile(meResult.data));
        try { logger.logInfo('auth_profile_loaded'); } catch (_) {}
      } else {
        try { logger.logWarn('auth_profile_load_failed', { error: meResult.error }); } catch (_) {}
      }
    } catch (err) {
      try { logger.logWarn('auth_profile_load_error', { message: err && err.message }); } catch (_) {}
    }

    broadcastAuthExchanged({
      success: true,
      endpoint,
      profile: authService.getProfile(),
    });
```

---

## 확인 방법

### 1) 문법 검사
```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/main.js','utf8')); console.log('문법 OK')"
```

### 2) 화면 확인
```bash
yarn start
```
- 로그인 대기 화면("로그인이 필요합니다")이 뜬다
- 기본 브라우저가 자동으로 열린다
- 브라우저 주소가 `작업 1`에서 설정한 로그인 URL 인지 확인

### 3) 로그인 완료 확인

브라우저 로그인 완료 후 앱이 **자동으로 마이크 테스트 화면으로 전환**되면 성공.

단, 개발 모드에서는 OS마다 딥링크가 도달하는 방식이 다르다.
**자세한 절차는 `09_dev_deeplink_test.md` 를 볼 것.**

| 환경 | 방법 |
|---|---|
| Windows 개발 | 작업 9의 등록 수정 후 실제 딥링크로 테스트 |
| macOS 개발 | 딥링크가 안 온다. 작업 9의 시뮬레이션 훅 사용 |
| 빌드본 | `npm run build` (macOS는 `npm run register-protocol` 추가) |

> 실행은 `npm start -- --dev` 로 한다. `npm run dev`(electronmon)는
> argv에 플래그가 섞여 딥링크 등록 경로가 어긋날 수 있다.

### 4) 로그로 확인
성공 시 아래 순서로 로그가 찍힌다.
```
deeplink_received
deeplink_exchange_begin
exchange_token_success
deeplink_exchange_success
fetch_my_info_success       ← 내 정보 조회 API 경로가 맞을 때만
auth_profile_loaded
```

`fetch_my_info_failed` 가 나오면 **작업 3의 `ME_PATH` 값이 틀린 것**이다.
그 경우 서버 담당자에게 실제 경로를 확인해 `userService.js` 의 `ME_PATH` 만 고친다.
로그인 자체는 그대로 성공한다.

---

## 문제가 생겼을 때

| 증상 | 원인 | 조치 |
|---|---|---|
| 로그인 화면이 안 뜨고 바로 메인 화면 | 7-1이 적용 안 됨 | `startRoute` 코드가 들어갔는지 확인 |
| 브라우저가 안 열림 | `shell` import 누락 | 작업 4-1 확인 |
| 화면이 하얗게 뜸 | `login.js` 경로 오류 | `login.html` 의 `<script src="../scripts/login.js">` 확인 |
| 로그인 후 화면이 안 넘어감 | `auth-exchanged` 미수신 | 개발 모드에서 딥링크가 안 온 것 → `09_dev_deeplink_test.md` 참고 |
