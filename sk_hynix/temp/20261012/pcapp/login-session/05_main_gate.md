# 작업 5 — main.js 에 로그인 게이트 연결

**손대는 파일**: `src/main/main.js` — **수정 3곳**
**다른 파일은 건드리지 않는다.**
**선행 작업**: 작업 4 (`src/main/ipc/handleAuth.js`) 가 있어야 한다.

## 왜 필요한가
앱을 켜면 무조건 `index.html`(마이크 테스트)을 띄우던 것을,
로그인 여부에 따라 로그인 화면 또는 메인 화면을 띄우도록 바꾼다.

## 할 일

### 5-1. 모듈 불러오기
파일 위쪽(45번째 줄 근처)에서 찾는다.

**[찾을 코드]**
```js
const { client: apiClient } = require("./services/apiService");
```

**[바꿀 코드]**
```js
const { client: apiClient } = require("./services/apiService");
const { registerAuthIpc, loadHome, onAuthenticated } = require("./ipc/handleAuth");
```

### 5-2. 인증 IPC 등록
`// IPC 핸들러들` 주석(330번째 줄 근처)을 찾는다.

**[찾을 코드]**
```js
// IPC 핸들러들
// 홈(index.html)으로 이동
```

**[바꿀 코드]**
```js
// IPC 핸들러들
// 로그인 게이트/인증 IPC (auth:get-status, auth:open-sso, auth:login-empno)
registerAuthIpc({ getMainWindow: () => mainWindow });

// 홈(index.html)으로 이동
```

### 5-3. 시작 화면을 게이트로
`createWindow()` 함수 안(306번째 줄 근처)에서 찾는다.
`loadFile(... "../renderer/index.html")` 은 파일에 여러 군데 있으니 **바로 아래 줄에 `window_created` 로그가 있는 것**만 고친다.

**[찾을 코드]**
```js
  mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  try { logger.logInfo('window_created', { windowId: mainWindow.id, route: 'index.html' }); } catch (_) {}
```

**[바꿀 코드]**
```js
  // 세션은 메모리에만 있으므로 새로 켜면 로그인 화면부터 시작한다(loadHome 이 판단).
  loadHome();
  try { logger.logInfo('window_created', { windowId: mainWindow.id }); } catch (_) {}
```

## 확인 방법
```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/main.js','utf8')); console.log('문법OK')"
node -e "const s=require('fs').readFileSync('src/main/main.js','utf8'); console.log(s.includes('./ipc/handleAuth'), s.includes('registerAuthIpc({ getMainWindow: () => mainWindow });'), /loadHome\(\);\s+try \{ logger.logInfo\(.window_created/.test(s))"
```
문법OK 와 `true true true` 가 나오면 성공.
