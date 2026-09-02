# 작업 5 — preload 에 authAPI 노출

**손대는 파일**: `src/main/preload.js` — **수정**
**다른 파일은 건드리지 않는다.**

---

## 왜 필요한가

이 앱은 `contextIsolation: true` 라서(`main.js:302` 근처) 렌더러가
`ipcRenderer` 를 직접 쓸 수 없다. preload 에서 `contextBridge` 로
노출한 함수만 화면에서 쓸 수 있다.

작업 4에서 만든 IPC 창구 3개를 화면이 부를 수 있게 연결한다.

> `auth-exchanged` 이벤트 수신은 **이미 `electronAPI.onAuthExchanged` 로
> 노출되어 있다**(preload.js 21번째 줄 근처). 새로 만들지 말고 그걸 그대로 쓴다.

---

## 할 일 — 1군데 추가

`contextBridge.exposeInMainWorld('dbAPI', {` 라는 줄을 파일에서 찾는다.
**그 줄 바로 위에** 아래 코드를 통째로 삽입한다.

```js
// 인증 관리
// - accessToken 자체는 절대 렌더러로 넘어오지 않는다.
//   화면은 "로그인 상태인지"와 "사용자 표시 정보"만 받는다.
// - 로그인 완료 통지는 기존 electronAPI.onAuthExchanged 를 쓴다.
contextBridge.exposeInMainWorld('authAPI', {
  // 기본 브라우저로 SSO 로그인 페이지 열기
  openLogin: () => {
    return ipcRenderer.invoke('auth:open-login')
  },

  // 현재 로그인 상태 조회 → { success, authenticated, profile }
  getStatus: () => {
    return ipcRenderer.invoke('auth:get-status')
  },

  // 로그인 사용자 정보 조회 → { success, profile }
  getProfile: () => {
    return ipcRenderer.invoke('auth:get-profile')
  },
});
```

---

## 확인 방법

```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/preload.js','utf8')); console.log('문법 OK')"
grep -n "authAPI" src/main/preload.js
```

`문법 OK` 와 `authAPI` 가 들어간 줄이 보이면 성공.
