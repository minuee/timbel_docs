# 05. 실시간 통신 (Socket.IO)

## 구조

```
src/Libs/NotifyManager.js        소켓 래퍼 (모듈 지역 싱글턴 `socket` 변수)
        ▲ init(accessToken, callback)
        │
src/Components/Layout/Main/Main.jsx   ★ 유일한 초기화 지점 & 유일한 수신 핸들러
        │
        ├─ useMessageStore.onMessage()      모든 메시지를 큐에 적재
        └─ 이벤트별 → ContentsStore / NoteCollaboStore / authLayoutStore / 모달
```

**`NotifyManager`는 React 바깥의 모듈 싱글턴**이다. `socket`, `isConnected`가 모듈 지역 변수라 앱 전체에 커넥션이 하나뿐이다.

## 연결

```js
// NotifyManager.js:82
socket = io(process.env.REACT_APP_DOMAIN, {
  auth: { token: accessToken },
  path: process.env.REACT_APP_SOCKET_PATH,          // 기본 /socket.io
  pingInterval: Number(REACT_APP_SOCKET_PING_INTERVAL) || 50000,
  pingTimeout:  Number(REACT_APP_SOCKET_PING_TIMEOUT)  || 5000,
});
```

- 인증은 헤더가 아니라 **`auth.token`** 핸드셰이크로 전달한다.
- 연결 직전 **브라우저 알림 권한**(`Notification.requestPermission`)을 요청한다.
- `Main.jsx`의 `initNotifySocket()`은 항상 `webSocket.disconnect()`를 먼저 호출한 뒤 재연결한다.

> ⚠️ 버그 소지: `disconnect()`가 `socket.destroy()`를 호출하는데(`NotifyManager.js:181`), `destroy()`는 socket.io-client v4 공개 API가 아니다(v2 잔재). 정상 종료는 `socket.disconnect()` 또는 `socket.close()`여야 한다. 재연결 시 이전 커넥션이 남을 수 있으니 소켓 중복 수신이 의심되면 여기부터 볼 것.

## 수신 채널 (2종)

| 소켓 이벤트 | 상수 | 용도 |
|---|---|---|
| `message` | `SECTION_MESSAGE` | 일반 알림 (콘텐츠 상태, 세션, 권한) |
| `collaboration` | `SECTION_COLLABORATION` | 노트 공동 편집 |
| `history` | — | 콘솔 로그만 (미사용) |

콜백은 `{ section, message }` 형태로 `Main.jsx`에 전달된다.

## 메시지 타입 (`WEBSOCKET_TYPE`)

| 타입 | 처리 |
|---|---|
| `CONTENTS_CHANGED` | `ContentsStore.onSttProgressUpdate(data)` + status ≠ `'PROGRESS'`면 `onContentsChanged(data)` |
| `DUPLICATE_SESSION_EXPIRED` | 기존 사용자에게 세션 모달(새 세션 IP 표시) + 쿠키 제거 |
| `DUPLICATE_SESSION_CLEARED` | 중복 세션 해제 |
| `ACCESS_TOKEN_EXPIRED` | 토큰 만료 |
| `PERMISSION_UPDATED` | 회의록 편집 권한 변경 |
| `NOTE_UPDATED` | 노트 갱신 → `setRefreshNoteTrigger` |
| `COLLABORATOR` | 공동 편집자 목록 변경 |
| `WORKSPACE_SETTINGS_UPDATED` | 관리자 설정 변경 → UI 권한(`allowUIRoles`) 갱신 |

## 발신 (emit) — 노트 공동 편집

`collaboration` 이벤트 하나에 `type`으로 구분해 보낸다.

| 함수 | emit payload |
|---|---|
| `requestNoteCollaboration(contentId)` | `{ type: 'CONNECT', data: { contentId } }` |
| `requestPermission(contentId)` | `{ type: 'REQUEST_PERMISSION', data: { contentId, task: 'NOTE_UPDATED' } }` |
| `revokePermission(contentId)` | `{ type: 'REVOKE_PERMISSION', data: { ... } }` |
| `collaboDisconnect(contentId)` | `{ type: 'DISCONNECT', data: { contentId } }` |

모두 `socket.connected`를 확인하고 미연결이면 `false`를 반환한다(예외를 던지지 않음).

### 공동 편집 모델
CRDT/OT 방식이 아니라 **단일 편집자 잠금(권한 이양)** 방식이다.
- 편집하려면 `REQUEST_PERMISSION` → 서버가 승인하면 편집 가능
- 다른 사용자는 대기열(`waitingMembers`)에 들어감 → `Stores/NoteCollaboStore.js`
- 편집자 표시는 `CURRENT_EDITING_USER = 'NOTE_UPDATED'` 키로 `Components/Common/CollaborativeBox`가 렌더
- 편집 상태는 `NOTE_UPDATE_INIT_TIME = 3초`(`Main.jsx:59`) 후 초기화된다

## 소켓을 쓰는 컴포넌트

| 파일 | 용도 |
|---|---|
| `Components/Layout/Main/Main.jsx` | ★ init + 전체 수신 핸들러 |
| `Components/Layout/Sidebar/Sidebar.jsx` | 연결 상태 확인 |
| `Pages/Contents/ContentDetail.jsx` | 공동 편집 연결/해제 |
| `Components/Feature/Content/Note/Note.jsx` | 편집 권한 요청/반납 |
| `Components/Common/CollaborativeBox/index.jsx` | 편집자 아바타 표시 |
| `Components/Feature/Content/Share/Share.jsx` | 권한 상수만 참조 |

## ⚠️ 알아둬야 할 제약

1. **모바일 라우트는 소켓이 없다.** `App.js`에서 모바일은 `Main` 레이아웃을 거치지 않으므로 `initNotifySocket()`이 호출되지 않는다. 모바일에서 STT 진행률·알림이 실시간으로 안 오는 것은 버그가 아니라 현재 구조의 결과다.
2. **수신 핸들러가 `Main.jsx` 한 곳뿐**이라, 새 메시지 타입을 추가하려면 반드시 이 파일의 `switch`를 수정해야 한다.
3. `disconnect()`의 `socket.destroy()` 문제(위 참조).
4. 연결 실패/재연결 실패에 대한 사용자 알림이 없다. `console.log`만 남는다.
5. `pingTimeout` 기본값이 코드(5000)와 `.env` 값(20000~30000)이 다르다. env 미설정 시 훨씬 공격적으로 끊긴다.

## 디버깅 팁

브라우저 콘솔에서 다음 로그를 확인한다.
```
[NotifyManager] init to https://dev.timblo.io /socket.io
connect ::
[Main] initNotifySocket
[useMessageStore] onMessage {...}
```
`connect ::`가 안 찍히면 → 핸드셰이크 인증 실패(토큰) 또는 `REACT_APP_SOCKET_PATH` 불일치.
`onMessage`는 찍히는데 화면이 안 바뀌면 → `Main.jsx`의 `action` 분기에 해당 타입이 없거나, 스토어 반영 후 컴포넌트가 그 필드를 구독하지 않는 것.
