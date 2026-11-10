# 작업 8 — 렌더러에 authAPI 노출

**손대는 파일**: `src/main/preload.js` — **수정 1곳**
**다른 파일은 건드리지 않는다.**

## 왜 필요한가
로그인 화면(`login.js`)이 메인 프로세스의 인증 기능을 부를 수 있게 `window.authAPI` 를 연다.
토큰은 메인 프로세스에만 있고, 여기서는 성공 여부만 오간다.

## 할 일
`// 데이터베이스 관리` 주석(147번째 줄 근처)을 찾는다.

**[찾을 코드]**
```js
// 데이터베이스 관리
contextBridge.exposeInMainWorld('dbAPI', {
```

**[바꿀 코드]**
```js
// 로그인/인증 (토큰은 메인 프로세스에만 있고, 여기서는 성공 여부만 오간다)
contextBridge.exposeInMainWorld('authAPI', {
  getStatus: () => ipcRenderer.invoke('auth:get-status'),
  openSso: () => ipcRenderer.invoke('auth:open-sso'),
  loginWithEmpno: (empno, password) => ipcRenderer.invoke('auth:login-empno', { empno, password }),
});

// 데이터베이스 관리
contextBridge.exposeInMainWorld('dbAPI', {
```

## 확인 방법
```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/preload.js','utf8')); console.log('문법OK')"
node -e "const s=require('fs').readFileSync('src/main/preload.js','utf8'); console.log(s.includes('authAPI'), s.includes('auth:login-empno'))"
```
문법OK 와 `true true` 가 나오면 성공.
