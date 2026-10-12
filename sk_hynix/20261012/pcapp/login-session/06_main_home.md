# 작업 6 — 홈으로 돌아갈 때도 로그인 게이트를 거치게

**손대는 파일**: `src/main/main.js` — **수정 3곳**
**다른 파일은 건드리지 않는다.**
**선행 작업**: 작업 5 (`loadHome` 을 불러오는 줄이 있어야 한다)

## 왜 필요한가
녹음 화면이나 업로드 후에 홈으로 돌아갈 때 `index.html` 을 직접 띄우는 곳이 3군데 있다.
세션이 만료된 상태라면 홈 대신 로그인 화면이 떠야 하므로, 모두 `loadHome()` 으로 바꾼다.

## 할 일

### 6-1. `load-index` 핸들러

**[찾을 코드]**
```js
ipcMain.handle("load-index", () => {
  try {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
      return { success: true };
    }
    return { success: false, error: "mainWindow_unavailable" };
  } catch (err) {
```

**[바꿀 코드]**
```js
ipcMain.handle("load-index", () => {
  try {
    // 로그인이 풀린 상태면 로그인 화면으로 간다.
    return loadHome();
  } catch (err) {
```

### 6-2. 업로드 성공 후 홈 이동 (`goHomeAfterUpload`)
`serverUpload` 함수 안, `// 장치 끊김 후 업로드 성공 시 홈으로 이동(goHomeAfterUpload)` 주석 바로 아래에 있다.

**[찾을 코드]**
```js
          mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
        }
      } catch (_) {}
```

**[바꿀 코드]**
```js
          loadHome();
        }
      } catch (_) {}
```

### 6-3. `go-home` 핸들러

**[찾을 코드]**
```js
ipcMain.handle("go-home", (e) => {
  mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
```

**[바꿀 코드]**
```js
ipcMain.handle("go-home", (e) => {
  loadHome();
```

## 확인 방법
```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/main.js','utf8')); console.log('문법OK')"
node -e "const s=require('fs').readFileSync('src/main/main.js','utf8'); console.log('index.html 직접 로드 남은 수:', s.split('../renderer/index.html').length-1)"
```
문법OK 와 `index.html 직접 로드 남은 수: 0` 이 나오면 성공.
(작업 5까지 끝났다면 0 이어야 한다. 1 이상이면 5-3 또는 6-x 중 빠진 곳이 있다.)
