# 03. 데이터 흐름

이 문서가 이 코드베이스에서 가장 중요하다. 기능 하나를 고치려면 아래 5개 경로 중 어디에 속하는지부터 판별하면 된다.

## 0. 전체 그림

```
┌──────────────┐
│  Component   │  Pages/*, Components/*
│  (View)      │  · useXxxStore()로 상태 구독 + 액션 호출
└──────┬───────┘  · 화면 지역 상태는 useState로 따로 관리
       │ 액션 호출
       ▼
┌──────────────┐
│ Zustand      │  src/Stores/*.js  (24개)
│ Store        │  · 상태 보관 + API 호출 + 응답 파싱 + 에러 토스트까지 전부 담당
└──────┬───────┘  · 사실상 "서비스 레이어"
       │ request.GET/POST/...
       ▼
┌──────────────┐
│ requestUtil  │  src/Utils/requestUtil.js  ★ 모든 HTTP의 단일 관문
│ (axios wrap) │  · 매 요청마다 tokenStore에서 토큰 조회 → Bearer 헤더 주입
└──────┬───────┘  · baseURL = `${REACT_APP_DOMAIN}/api/`
       ▼
   Backend (master API)


   [별도 경로 — requestUtil을 안 거치는 것들]
   · Socket.IO      Libs/NotifyManager.js → Main.jsx → Store   (05번 문서)
   · 직접 axios     InboxStore, Chatbot, overrideConsole, Auth 페이지 일부
   · fetch          requestUtil.downloadFile (Blob 다운로드)
   · IndexedDB      hooks/useIndexedDB.jsx (녹음 로컬 보관)
```

---

## 1. HTTP 요청 경로

### 1-1. 진입점 — `src/Utils/requestUtil.js`

기본 URL은 **`${process.env.REACT_APP_DOMAIN}/api/`** 로 조립된다 (`requestUtil.js:9`).

> ⚠️ README에는 `REACT_APP_API_URL`, `REACT_APP_SOCKET_URL`, `REACT_APP_LOGIN_URL`, `REACT_APP_BO_ADMIN_URL`이 나오지만 **코드에서 실제로 쓰이는 건 `REACT_APP_DOMAIN` 하나뿐이다.** 나머지는 죽은 문서다. → [06-local-setup.md](./06-local-setup.md)

export 되는 메서드:

| 메서드 | 용도 |
|---|---|
| `GET(path, headers, params, responseType)` | 쿼리스트링은 `qs.stringify`(arrayFormat: brackets, skipNulls) |
| `POST/PUT/PATCH(path, data, headers)` | |
| `DELETE(path, headers)` | |
| `uploadFile(formData, onProgress)` | `contents/upload` 고정, multipart |
| `downloadFile(meta, onProgress)` | fetch + Blob + FileSaver |
| `ensureStreamGrant(contentId)` | 미디어 재생용 grant 쿠키 발급 |
| `makeStreamLink(id)` | `<audio src>`용 URL 생성 |
| `setSessionHeaders(accessToken)` | 모듈 지역 캐시 갱신 |

### 1-2. 토큰 주입 방식 ⚠️

**axios interceptor를 쓰지 않는다.** 대신 매 호출마다 `getRequestHeaders()`가 실행되어:

```js
// requestUtil.js:18-38
const token = getCookie();               // = tokenStore.getToken()
if (token?.accessToken) setSessionHeaders(token.accessToken);
else { DEFAULT_SESSION_HEADERS = {}; ACCESS_TOKEN = ''; }   // stale 캐시 제거
return { 'Content-Type': 'application/json', ...authHeaders, ...headers };
```

즉 **토큰은 요청 시점에 매번 저장소에서 새로 읽는다.** 모듈 지역 변수(`ACCESS_TOKEN`)는 캐시일 뿐이며, 토큰 부재 시 즉시 비운다. 이는 로그아웃 후 이전 신원으로 요청이 나가는 것을 막기 위한 의도적 설계다 (코드 주석에 명시).

코드 안에 `// TODO: 미들웨어 구조를 적용해 바꿔야함` 주석이 남아 있다 — 원 작성자도 임시 구조로 인지하고 있었다.

### 1-3. ★ 응답 계약 — HTTP 200 + body `httpCode`

**이 프로젝트에서 반드시 알아야 할 규칙.**

백엔드(master API)는 **에러도 HTTP 200으로 내려주고, 실제 결과 코드는 응답 body의 `httpCode` 필드**에 담는다.

```js
// 실제 응답 형태
{ httpCode: 200, message: 'ok', data: {...} }
{ httpCode: 401, message: '권한이 없습니다' }     ← HTTP status는 여전히 200
```

`requestUtil.js:191`의 주석이 이를 명시한다:
> `master 는 에러도 HTTP 200 + body.httpCode 계약(예: 권한 실패 시 200 + httpCode 401)이라, axios 예외가 아니라 body.httpCode 로 실제 발급 성공을 판정해야 한다.`

**결과적으로:**
- axios의 `catch`는 **네트워크 오류에만** 걸린다. 권한 실패·검증 실패는 `then`으로 들어온다.
- 전역 에러 인터셉터를 만들 수 없다 → **스토어의 모든 액션이 `switch (res.data.httpCode)`를 각자 반복**한다.
- 새 API를 붙일 때 `httpCode` 분기를 빠뜨리면 실패가 조용히 성공처럼 처리된다.

자주 쓰이는 코드값:

| httpCode | 의미 |
|---|---|
| 200 / 201 / 204 | 정상 |
| 401 | 권한 없음 |
| 403 | 음성인식 실패 등 |
| 404 | 리소스 없음/권한 없음 |
| 422 | 처리 중 (STT/재요약 진행 중) — fo-fe가 재매핑해 사용 |
| 506 / 511 / 512 / 517 | 로그인 제한 / 길이 초과 / 중복 / 세션 무효 |

`ContentsStore.getContents`(`ContentsStore.js:114`)는 여기서 한 발 더 나간다. 백엔드가 `STT_DONE`·`RE_SUMMARY_RUNNING` 상태를 200 + 부분데이터로 주지만, **fo-fe가 이를 422("처리 중")로 재매핑**해 상세 내용 노출을 막는다. 외부 API 호환성 때문에 프론트가 계약을 덧씌운 케이스이므로 함부로 정리하면 안 된다.

### 1-4. 스토어 → 컴포넌트 반환 규약 (2가지 혼재) ⚠️

같은 스토어 안에서도 두 스타일이 섞여 있다.

**A. Promise 스타일** — `resolve({ code, message, data })`
```js
refreshContents(params)
  .then(({ code, data }) => { ... })
  .catch((e) => ToastError(1003))
  .finally(() => setIsLoading(false));
```
주의: **실패해도 `reject`가 아니라 `resolve({code: 401})`로 오는 경우가 많다.** `catch`만 달아두면 에러를 놓친다.

**B. 콜백 스타일** — `(params, onOk, onError, onFinal)`
```js
fileUpload(file, name, folderId, option, type, auth, onOk, onError, onFinal, onProgress)
login({ email, password }, onOk, onError, onFinal)
```
`ContentsStore.fileUpload`는 인자가 10개다. 시그니처를 반드시 정의부에서 확인할 것.

일부 액션(`onResummaryContent`, `updateContentKeywords` 등)은 **A와 B를 동시에** 쓴다 — `async` 함수인데 `onSuccess`/`onError` 콜백도 받는다.

### 1-5. 에러 표시

에러 UI는 `src/Components/Feature/Common/Toast/Toast.jsx`의 `ToastError(code, message)` / `ToastInfo`로 통일되어 있다. **스토어 내부에서 직접 호출하는 경우**(`api/termStore.js`, `api/appStore.js`, `requestUtil.downloadFile`)와 **컴포넌트에서 호출하는 경우**가 섞여 있어, 같은 에러가 두 번 토스트되지 않는지 확인이 필요하다.

---

## 2. 상태 계층 — Zustand 스토어 카탈로그

`create((set, get) => ({...}))` 패턴. **미들웨어(persist / devtools / immer) 전혀 사용 안 함.**

### 2-1. 도메인 스토어 (`src/Stores/*.js`)

| 스토어 | 줄수 | 역할 |
|---|---|---|
| **ContentsStore.js** | **1440** | ★ 회의록 전반. 목록/검색/홈/북마크/휴지통/캘린더/업로드/STT진행/상세편집/메모/하이라이트/공유/다운로드/이용현황 — **거의 모든 도메인 로직의 집합소** |
| AuthStore.js | 307 | 로그인/로그아웃/토큰갱신/내 정보/닉네임·비밀번호·썸네일 변경 |
| RecorderStore.js | 248 | 녹음 상태 |
| DictionaryStore.js | 212 | 용어 사전 |
| AddressStore.js | 164 | 주소록 |
| FilterStore.js | 160 | 목록 필터 조건 |
| FolderStore.js | 154 | 폴더 트리 / 폴더 내 회의록 |
| MessageStore.js | 143 | 소켓 메시지 큐(최대 20) + 알림함(inbox) |
| ShareFilterStore.js | 128 | 공유 필터 |
| AttendeeStore.js, TemplateStore.js, FunctionStore.js, ContactStore.js, NoteCollaboStore.js, BrandingStore.js, MemberStore.js, InboxStore.js | ~20-73 | 각 기능 단위 |

### 2-2. API 스토어 (`src/Stores/api/`)
`appStore.js`(녹음기 URL scheme), `termStore.js`(약관 동의), `noticeStore.js`(공지).
`dbg.wrap('액션명', fn)`(`Utils/debugger.js`)으로 감싸 호출 추적을 붙이는 **신규 컨벤션**이 적용된 영역이다. 새 스토어는 이 패턴을 따르는 것이 좋다.

### 2-3. UI 스토어 (`src/Stores/ui/`)
`authLayoutStore.js`(권한 기반 UI 노출 — 챗봇/클립보드 허용 여부), `floatLayerStore.js`(모달·팝오버 열림 목록), `recorderStore.js`, `selectStore.js`.

서버 데이터가 아닌 **UI 상태만** 담는 계층으로 분리하려는 시도가 보이나, 도메인 스토어(`ContentsStore`)에도 `isCollapsed`, `searchModalOpen`, `isLoading` 같은 UI 상태가 남아 있어 경계가 완전하지 않다.

### 2-4. 구독 패턴 ⚠️ 성능 주의

대부분의 컴포넌트가 **셀렉터 없이 통째로 구조분해**한다.

```js
// ContentList.js:21 — 나쁜 예 (스토어의 어떤 필드가 바뀌어도 리렌더)
const { contents, refreshContents, applyedFilters, setRefreshForceTrigger, deleteContents } = useContentsStore();
```

셀렉터를 쓰는 곳도 일부 있다.
```js
// App.js:48 — 좋은 예
const faviconUrl = useBrandingStore((state) => state.branding.faviconUrl);
```

`ContentsStore`는 1440줄에 수십 개 필드를 가진 거대 스토어이므로, 통째 구독은 불필요한 리렌더의 주원인이다. **성능 이슈를 만나면 여기부터 셀렉터로 좁힐 것.**

### 2-5. 리프레시 트리거 안티패턴 ⚠️

데이터를 다시 불러오기 위해 **불린 플래그를 토글**하는 패턴이 쓰인다.

```js
refreshForceTrigger / setRefreshForceTrigger   // ContentsStore.js:72
refreshNoteTrigger  / setRefreshNoteTrigger    // ContentsStore.js:76
```

이 값을 `useEffect` 의존성에 넣어 재조회를 유발한다. 호출 순서에 따라 무한 루프나 이중 호출이 생기기 쉬우니 수정 시 주의. (`ContentList.js:63`에서 `gridData` 변경마다 트리거를 켜는 구조)

---

## 3. 실시간(WebSocket) → 스토어 반영 경로

상세는 [05-realtime-socket.md](./05-realtime-socket.md). 데이터 흐름 관점 요약:

```
Socket.IO 'message' 이벤트
  → NotifyManager 콜백
  → Main.jsx initNotifySocket()의 핸들러       ← 유일한 수신부
      ├─ useMessageStore.onMessage(message)     항상 큐에 적재(최대 20)
      └─ action별 분기:
          CONTENTS_CHANGED  → ContentsStore.onSttProgressUpdate(data)
                              + status !== 'PROGRESS'면 onContentsChanged(data)
          DUPLICATE_SESSION_EXPIRED → 세션 모달 + 쿠키 제거
          PERMISSION_UPDATED / NOTE_UPDATED / COLLABORATOR → 노트 공동편집 상태
          WORKSPACE_SETTINGS_UPDATED → UI 권한 갱신
```

**중요:** 소켓 수신부가 `Components/Layout/Main/Main.jsx` **한 곳뿐**이다. 따라서
- 모바일 라우트는 `Main`을 거치지 않아 **실시간 갱신이 동작하지 않는다.**
- 실시간 반영이 안 되는 버그는 대부분 `Main.jsx`의 `initNotifySocket` 핸들러를 보면 된다.

### STT 진행률 흐름 (대표 사례)

```
파일 업로드/녹음
  → ContentsStore.fileUpload()
      → uploads.list 에 임시 항목(tempId=uuid) 추가 → 화면에 즉시 표시(낙관적 UI)
      → request.uploadFile(onUploadProgress) → 업로드 %  
      → 응답 200: uploads.list에서 제거 + contents.list / home.contents 맨 앞에 삽입
  → (서버가 STT 처리 시작)
  → WS: CONTENTS_CHANGED { contentId, status:'PROGRESS', percentage }
      → onSttProgressUpdate: sttProgress.list 갱신
         · percentage는 scaleNumber(x, 100, 80)로 **80% 상한으로 축소**해 표시
           (STT 100% ≠ 전체 완료. 이후 요약 단계가 남아 있어 UX상 80까지만 채운다)
      → status 'DONE'이면 sttProgress.list에서 제거
      → status !== 'PROGRESS'면 onContentsChanged로 sttStatus.list도 갱신
         (DONE/ERROR 처리 후 removeSttStatus로 반드시 제거 — 남으면 이후 무관한 push마다 재적용됨)
```

`sttStatus`와 `sttProgress` **두 개의 리스트가 별도로 존재**한다는 점이 헷갈리기 쉽다.
- `sttProgress.list` = 진행률 바 표시용 (`contents.list`에 이미 있는 항목만 대상)
- `sttStatus.list` = 상태 전이 감지용(신규 표시 등)

---

## 4. requestUtil을 우회하는 경로 (예외 목록) ⚠️

이 5곳은 공통 관문을 안 거치므로 인증/에러 처리가 별도다. 리팩터링 시 누락되기 쉽다.

| 위치 | 방식 | 비고 |
|---|---|---|
| `Stores/InboxStore.js` | axios 직접 | `${REACT_APP_DOMAIN}/api/inbox`를 직접 호출하고 **accessToken을 인자로 받는다**. `MessageStore.refreshInbox`가 동일 기능을 `request.GET('inbox')`로 이미 구현 중 → **중복 구현** |
| `Components/Feature/Content/Chatbot/Chatbot.js:148` | axios 직접 | **다른 호스트**(`REACT_APP_SK_API_HOST`)의 `/llm_api/chat`. 인증 헤더 없음, timeout 180초 |
| `Libs/overrideConsole.js` | axios 직접 | `/api/bo/log/error`로 로그 전송 (아래 6번) |
| `Pages/Auth/*` (LoginPage, FindPassword, join/*, Action.js) | axios 직접 | 로그인 전이라 토큰이 없는 구간 |
| `requestUtil.downloadFile` | `fetch` | 아래 5번 |

---

## 5. 미디어 · 파일 특수 경로

### 다운로드 — 왜 `fetch` + Blob인가
`requestUtil.js:118`의 주석에 이유가 적혀 있다.
> 자체서명 등 미신뢰 인증서 origin에서는 브라우저 다운로드 매니저(URL 직접 다운로드)가 페이지의 인증서 예외를 물려받지 못해 네트워크 오류로 실패한다.

그래서 URL을 `<a download>`에 넘기지 않고 **페이지에서 fetch → Blob → FileSaver.saveAs**로 저장한다. 온프렘 자체서명 인증서 환경을 위한 필수 우회이므로 제거 금지.

- 토큰은 호출 시점에 새로 조회하고, 없으면 중단 (stale 토큰으로 이전 신원 다운로드 방지)
- `credentials: 'omit'` — 전역 grant 쿠키가 동승해 Bearer 신원을 덮는 것을 차단
- 파일명은 서버 `Content-Disposition` 우선, 없으면 `fileName` → `title` 순
- `onProgress` + `Content-Length`가 있으면 스트리밍 리더로 % 갱신 (정수 % 변화시에만 콜백)

### 재생 — grant 쿠키
`<audio src>`는 헤더를 실을 수 없어 Bearer 인증이 불가능하다. 그래서 상세 진입 시 `ensureStreamGrant(contentId)`를 호출해 **콘텐츠별 서명 쿠키**(`streamGrant_<contentId>`, path=`/api/contents/download`, 10분)를 미리 발급받는다. 실패해도 기존 세션 경로로 폴백한다.

### 업로드
`uploadFile`은 `multipart/form-data`. 전역 캐시 토큰을 쓰지 않고 **요청 시점 토큰**을 직접 조회한다(주석: "상담 컨텍스트 오귀속 방지 핵심 경로"). FormData 필드: `file`, `folderId`, `type`, `isRecord`, `lang`, `attendeeNum`, `summary`.

---

## 6. 클라이언트 로깅 흐름 (`Libs/overrideConsole.js`)

**`console.info` / `console.warn` / `console.error`를 전역 하이재킹**한다. `Main.jsx:8`에서 import되는 순간 IIFE로 적용된다.

```
console.warn('메시지', 'GROUP')       ← 인자 2개가 모두 string일 때만 그룹 로깅
  → logStorage[GROUP]에 {date, message} 적재 (그룹당 최대 256개, FIFO)
  → chalk로 색상 입혀 원본 console.log 출력
  → GROUP이 RECORD이고 level이 warn이면 즉시 서버 전송(flush)
console.send(GROUP) / console.flush(GROUP, email, accessToken)
  → POST ${REACT_APP_DOMAIN}/api/bo/log/error
     { email, group, transaction: [...logs] }
  → 응답 httpCode 201이면 해당 그룹 로그 삭제
```

또한 `console.setUserInfo({email, accessToken})`라는 **비표준 메서드를 console 객체에 심는다**. `AuthStore.getMyInfo`(`AuthStore.js:278`)가 로그인 직후 이를 호출해 로그 전송용 신원을 주입한다.

> ⚠️ 함정: 인자가 정확히 2개의 문자열일 때만 그룹 처리되고, **그 외에는 `args[0]`만 출력하고 나머지는 버린다.** `console.error('실패', errorObject)` 같은 호출은 두 번째 인자가 사라진다. 디버깅 시 `console.log`(원본 유지)를 쓰는 게 안전하다.

## 7. 로컬 영속 저장소

| 저장소 | 용도 | 위치 |
|---|---|---|
| **Cookie** | 인증 토큰(일반 로그인), grant 쿠키 | `Utils/tokenStore.js` |
| **sessionStorage** | SSO 토큰(창 단위 격리), SSO 모드 표식 | `Utils/tokenStore.js` |
| **IndexedDB** | 녹음/로그 데이터 로컬 보관 | `hooks/useIndexedDB.jsx` (`idb`, DB v1, keyPath `id`) |
| 메모리 | 소켓 메시지 큐(최대 20), 로그 버퍼(그룹당 256) | MessageStore / overrideConsole |

Zustand `persist` 미들웨어는 쓰지 않으므로 **새로고침하면 전역 상태는 전부 초기화**되고 API를 다시 호출한다.

---

## 8. 데이터 흐름 관점 요약 진단

**좋은 점**
- 모든 HTTP가 `requestUtil` 한 곳을 지나므로 인증/헤더 정책을 한 파일에서 바꿀 수 있다
- 토큰을 캐시하지 않고 매번 조회하는 규칙이 일관되게 지켜져 신원 오귀속 방어가 견고하다
- 인증서/스트리밍 관련 우회 코드에 "왜"가 주석으로 남아 있다

**문제**
1. `httpCode` 계약 탓에 **전역 에러 처리가 불가능** → 스토어마다 `switch` 중복 (수백 줄)
2. **`ContentsStore` 1440줄 God Store** — 회의록의 모든 것이 한 파일
3. **Promise/콜백 반환 규약 이원화** + 실패도 `resolve`로 오는 경우 → `catch` 누락 버그 유발
4. **셀렉터 없는 통째 구독**으로 리렌더 과다
5. **requestUtil 우회 5곳** — 인증 처리 불일치 (특히 `InboxStore`는 `MessageStore`와 기능 중복)
6. 서버 상태 캐싱/무효화 계층 부재 → `refreshXxx` 수동 호출과 불린 트리거로 관리
7. `console.*` 전역 하이재킹으로 두 번째 인자 유실
