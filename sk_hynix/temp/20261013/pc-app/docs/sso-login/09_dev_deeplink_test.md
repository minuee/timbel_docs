# 작업 9 — 개발 모드에서 딥링크 테스트하기

**손대는 파일**
- `src/main/main.js` — **수정 2곳**
- `src/main/preload.js` — **수정 1곳**

**다른 파일은 건드리지 않는다.**

> ⚠️ **작업 4가 끝난 뒤에 진행할 것.** (`authConfig` require 가 필요하다)
> 이 작업은 **기능이 아니라 테스트 수단**이다. 로그인 자체는 작업 7까지로 이미 완성이다.

---

## 왜 필요한가

로그인은 `브라우저 → 딥링크 → 앱` 순서로 동작하는데,
**개발 모드에서는 딥링크가 앱까지 도달하지 않는다.** 그래서 개발 중에는
로그인 완료 이후를 테스트할 방법이 없다.

원인은 `main.js:1265` 다.

```js
// 프로토콜 기본 앱 등록 (빌드 환경에서만)
if (!process.defaultApp) {          // 패키징된 앱일 때만 true
  app.setAsDefaultProtocolClient(PROTOCOL_SCHEME);
}
// 개발 모드에서는 등록하지 않음 (LaunchServices 충돌 방지)
```

`electron .` 으로 실행하면 `process.defaultApp === true` 라서 등록을 건너뛴다.
**의도적으로 막아둔 것이고, macOS 에서는 이 판단이 맞다.**

### OS 별 사정이 다르다

| | 개발 모드 딥링크 | 이유 |
|---|---|---|
| **Windows** | **되게 만들 수 있음** | 레지스트리에 `electron.exe + 앱경로` 형태로 등록 가능 |
| **macOS** | **사실상 불가** | 아래 참고 |

**macOS 가 안 되는 이유**: macOS 는 URL 스킴 주인을 **앱 번들의 `Info.plist`
(CFBundleURLTypes)** 로 판단한다. 개발 모드의 번들은
`node_modules/electron/dist/Electron.app` 인데, 여기에 스킴을 등록하면
스킴 주인이 "Electron.app" 이 되어 **빌드본으로 가야 할 딥링크까지 가로챈다.**
`main.js` 주석의 "LaunchServices 충돌"이 이 얘기다.

그래서 이 문서는 **Windows 는 실제 딥링크를, macOS 는 시뮬레이션을** 쓴다.

---

## 할 일 — 3군데 수정

### 9-1. Windows 개발 모드 프로토콜 등록 (`main.js`)

**[찾을 코드]**
```js
  // 프로토콜 기본 앱 등록 (빌드 환경에서만)
  try {
    if (!process.defaultApp) {
      // 프로덕션 빌드에서만 등록
      app.setAsDefaultProtocolClient(PROTOCOL_SCHEME);
    }
    // 개발 모드에서는 등록하지 않음 (LaunchServices 충돌 방지)
    // 빌드 후 자동 등록: scripts/register-protocol.js (afterPack 훅)
  } catch (_) {}
```

**[바꿀 코드]**
```js
  // 프로토콜 기본 앱 등록
  try {
    if (!process.defaultApp) {
      // 프로덕션 빌드에서만 등록
      app.setAsDefaultProtocolClient(PROTOCOL_SCHEME);
    } else if (process.platform === "win32") {
      // Windows 개발 모드: 레지스트리는 "실행파일 + 인자" 형태로 등록할 수 있어,
      // electron.exe 에 앱 경로를 붙여두면 개발 중에도 실제 딥링크를 받을 수 있다.
      // argv[1] 은 electronmon 이 끼워넣는 --require 등에 밀릴 수 있어 신뢰하지 않는다.
      app.setAsDefaultProtocolClient(PROTOCOL_SCHEME, process.execPath, [app.getAppPath()]);
    }
    // macOS 개발 모드에서는 등록하지 않는다.
    // macOS 는 앱 번들 Info.plist 로 스킴 주인을 정하는데, 개발 번들
    // (node_modules/electron/dist/Electron.app)로 주인이 바뀌면 빌드본으로 가야 할
    // 딥링크까지 가로챈다(LaunchServices 충돌).
    // → macOS 는 아래 dev:simulate-deeplink 로 테스트한다.
    // 빌드 후 자동 등록: scripts/register-protocol.js (afterPack 훅)
  } catch (_) {}
```

---

### 9-2. 딥링크 시뮬레이션 IPC 추가 (`main.js`)

`ipcMain.handle("load-index", () => {` 를 파일에서 찾는다.
**그 줄 바로 위에** 아래 코드를 통째로 삽입한다.

> 작업 4에서 넣은 인증 IPC 들도 같은 위치에 넣었으므로,
> 이 코드는 그 아래·`load-index` 위에 자리하게 된다. 순서는 상관없다.

```js
// --- 개발용 딥링크 시뮬레이션 -------------------------------------------
// macOS 개발 모드에서는 실제 딥링크가 앱까지 오지 않는다(위 프로토콜 등록 주석 참고).
// 브라우저에서 받은 code 만 넣으면 딥링크가 온 것처럼 처리해서,
// OS 라우팅을 제외한 전 과정(토큰 교환 → 내 정보 조회 → 화면 전환)을 검증할 수 있다.
// --dev 플래그로 실행했을 때만 등록되므로 프로덕션 빌드에는 존재하지 않는다.
if (process.argv.includes("--dev")) {
  ipcMain.handle("dev:simulate-deeplink", async (event, input) => {
    try {
      const value = String(input || "").trim();
      if (!value) return { success: false, error: "empty_input" };

      // 전체 URL 을 그대로 넣어도 되고, code 값만 넣어도 된다.
      // code 만 준 경우 host 는 authConfig 의 기본 주소를 base64 로 붙인다.
      const isFullUrl = value
        .toLowerCase()
        .startsWith((PROTOCOL_SCHEME + "://").toLowerCase());

      const url = isFullUrl
        ? value
        : `${PROTOCOL_SCHEME}://connect?code=${encodeURIComponent(value)}` +
          `&host=${Buffer.from(authConfig.WEB_BASE_URL, "utf8").toString("base64")}`;

      try { logger.logInfo("dev_simulate_deeplink", { isFullUrl }); } catch (_) {}
      await processDeepLink(url);
      return { success: true, url };
    } catch (err) {
      return { success: false, error: err && err.message };
    }
  });
}
```

---

### 9-3. 렌더러에 시뮬레이션 함수 노출 (`preload.js`)

이미 있는 `developerAPI` 안에 함수 하나만 추가한다. 새 API 를 만들지 않는다.

**[찾을 코드]** (파일 맨 끝)
```js
  sendDebug: (message, context) => {
    ipcRenderer.invoke('send-debug', message, context)
  },
});
```

**[바꿀 코드]**
```js
  sendDebug: (message, context) => {
    ipcRenderer.invoke('send-debug', message, context)
  },

  // 개발용 딥링크 시뮬레이션.
  // 개발자도구 콘솔에서 직접 호출한다:
  //   developerAPI.simulateDeepLink('브라우저에서받은code')
  // main 쪽 핸들러가 --dev 실행일 때만 등록되므로, 프로덕션에서는 호출해도 실패한다.
  simulateDeepLink: (input) => {
    return ipcRenderer.invoke('dev:simulate-deeplink', input)
  },
});
```

---

## 실행 방법 — 이 프로젝트의 스크립트 2개 구분

`package.json` 에 실행 스크립트가 두 개 있다.

```json
"start": "electron .",            // 순수 electron
"dev":   "electronmon . --dev",   // 핫리로드 + 개발자도구
```

| 용도 | 명령 |
|---|---|
| 평소 개발 (파일 저장 시 자동 재시작) | `npm run dev` |
| **딥링크 / 로그인 테스트** | `npm start -- --dev` |
| 최종 검증 | `npm run build` 후 빌드본 실행 |

**딥링크 테스트에 `npm start -- --dev` 를 쓰는 이유**:
`electronmon` 은 electron 을 감싸 실행하면서 `--require` 같은 인자를 끼워넣는다
(`main.js:1231` 주석에 이미 기록되어 있음).
Windows 레지스트리 등록 시 경로가 어긋날 수 있어, 딥링크를 볼 때는
`electron .` 을 직접 쓰는 편이 안전하다.
`--dev` 를 붙여야 개발자도구가 열리고(`main.js:1327`) 시뮬레이션 IPC 도 등록된다.

---

## 테스트 절차

### macOS — 시뮬레이션으로 테스트

1. 앱 실행
   ```bash
   npm start -- --dev
   ```
2. 로그인 대기 화면이 뜨고 브라우저가 자동으로 열린다
3. 브라우저에서 SSO 로그인을 끝까지 진행한다
4. 로그인 완료 후 **브라우저 주소창의 `code` 값**을 복사한다
   - 웹이 `timbloRecApp://connect?code=XXXX&host=...` 로 넘어가려다 실패하면
     그 URL 이 주소창이나 브라우저 경고창에 보인다. 거기서 `code` 를 꺼낸다
5. 앱의 **개발자도구 콘솔**에 입력한다
   ```js
   developerAPI.simulateDeepLink('복사한code값')
   ```
   URL 전체를 복사했다면 그대로 넣어도 된다.
   ```js
   developerAPI.simulateDeepLink('timbloRecApp://connect?code=XXXX&host=aHR0cHM6...')
   ```
6. 앱이 마이크 테스트 화면으로 전환되면 성공

### Windows — 실제 딥링크로 테스트

1. 앱 실행 (한 번 실행해야 레지스트리에 등록된다)
   ```bash
   npm start -- --dev
   ```
2. 앱을 켜 둔 채로, 다른 터미널에서
   ```cmd
   start "" "timbloRecApp://connect?code=test&host=aHR0cHM6Ly9kZXYudGltYmxvLmlv"
   ```
3. 로그에 `deeplink_received` 가 찍히면 **OS 라우팅 성공**
   (`code=test` 는 가짜라서 교환은 실패한다. 여기서는 라우팅만 확인하는 것)
4. 실제 로그인은 브라우저에서 끝까지 진행하면 자동으로 앱까지 들어온다

> `host` 값은 서버 주소를 base64 로 인코딩한 것이다.
> `aHR0cHM6Ly9kZXYudGltYmxvLmlv` = `https://dev.timblo.io`
> 다른 주소가 필요하면:
> ```bash
> node -e "console.log(Buffer.from('https://내서버주소').toString('base64'))"
> ```

### 빌드본으로 최종 확인 (양쪽 OS 공통)

```bash
npm run build
npm run register-protocol    # macOS 전용. LaunchServices 에 빌드본 등록
```

macOS 에서는 빌드본을 한 번 실행하거나 위 명령을 돌려야
`timbloRecApp://` 의 주인이 빌드본으로 잡힌다.

---

## 확인 방법

```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/main.js','utf8')); console.log('main OK')"
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/preload.js','utf8')); console.log('preload OK')"
grep -n "dev:simulate-deeplink" src/main/main.js src/main/preload.js
```

`main OK`, `preload OK` 와 함께 두 파일에서 `dev:simulate-deeplink` 가 보이면 성공.

---

## 문제가 생겼을 때

| 증상 | 원인 | 조치 |
|---|---|---|
| 콘솔에서 `developerAPI is not defined` | preload 수정 누락 | 9-3 확인 |
| `No handler registered for 'dev:simulate-deeplink'` | `--dev` 없이 실행함 | `npm start -- --dev` 로 재실행 |
| Windows에서 `deeplink_received` 가 안 찍힘 | 레지스트리 등록 실패 | 앱을 한 번 실행했는지, 9-1이 적용됐는지 확인 |
| Windows에서 앱이 새로 하나 더 뜸 | 단일 인스턴스 락 미동작 | `main.js:1198` `requestSingleInstanceLock()` 결과 확인 |
| macOS에서 `open` 하면 dist 빌드본이 뜸 | 정상 동작 | macOS 는 시뮬레이션으로 테스트할 것 |

> **미검증 사항**: Windows 에서 딥링크가 들어올 때 새 electron 프로세스가
> 기존 개발 인스턴스와 같은 앱으로 인식되어 `second-instance` 가 발생하는지는
> Windows 실기에서 확인이 필요하다. 로그에 `deeplink_received` 가 찍히면 정상이다.
