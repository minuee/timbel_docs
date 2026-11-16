# 02. 아키텍처 · 프로세스 · IPC

> 기준: 현재 소스 (2026-10-15 작업분까지). 소스 위치는 `파일 · 함수` 로 표기.

---

## 1. 전체 구성도

```
┌──────────────────────────── 사용자 PC ─────────────────────────────┐
│                                                                     │
│  ┌─────────────── Electron 앱 (timbloRecApp) ───────────────┐       │
│  │                                                          │       │
│  │  [렌더러: 화면]  login / index(마이크테스트) / recording  │       │
│  │       │  popup / summarize / uploadList / update         │       │
│  │       │  window.electronAPI 등 (preload.js 가 노출)       │       │
│  │       ▼  ipcRenderer.invoke / on                          │       │
│  │  [메인 프로세스: main.js]                                 │       │
│  │       ├─ services/ : 인증·API·로그전송·업데이트·템플릿    │       │
│  │       ├─ db/       : SQLite (app.db)                      │       │
│  │       └─ audioHelperManager ──stdin(JSON)──┐              │       │
│  └──────────────────────────────────────────── │ ────────────┘       │
│                                  stdout(JSON)▲ ▼                     │
│                         [오디오 헬퍼 프로세스]                        │
│                          Windows: AudioHelper.exe (C++/WASAPI)       │
│                          macOS  : AudioHelper.app (Swift/SCK)        │
│                                  │ 3분마다 암호화 조각 파일 저장      │
│                                  ▼                                   │
│                    문서\SKHynixRecApp\recordings\{sessionId}\*.pcm  │
└──────────────────────────────────────────────────────────────────────┘
          │ HTTPS (axios, Bearer 토큰)
          ▼
  aimeeting.mobile.skhynix.com/m  ── 업로드 · 사용자정보 · 템플릿 · 부서장메일 · 로그
  amdev.skhynix.com (MyAccess SSO) ── 브라우저로 로그인 → timbloRecApp:// 딥링크로 복귀
```

**핵심 설계 원칙**
1. **오디오는 Electron 이 아니라 별도 네이티브 프로세스가 처리한다.** 녹음 데이터는 Electron 을 거치지 않고 헬퍼가 바로 디스크에 쓴다.
   Electron 은 명령을 보내고, 이벤트(레벨·진행·조각 완성)만 받는다.
2. **화면은 메인 프로세스 기능을 preload 를 통해서만 쓴다.** `nodeIntegration:false`, `contextIsolation:true`. 모든 창이 같은 `preload.js` 를 쓴다.
3. **토큰은 메인 프로세스 메모리에만 있다.** 렌더러에는 절대 넘기지 않는다(`authService`).
4. **서버 통신은 `services/apiService.js` 의 axios 인스턴스 하나로만 한다.** 서버 주소와 토큰은 여기서 자동으로 붙는다.

---

## 2. 창(BrowserWindow) 구성

메인 창 **하나**가 페이지를 바꿔 가며 쓰이고, 보조 창 3개가 필요할 때 뜬다.

| 창 | 페이지 | 만드는 곳 | 특징 |
|---|---|---|---|
| **메인 창** | `pages/login.html` → `index.html` → `pages/recordingWindow.html` (→ `pages/update.html`) | `main.js · createWindow` | 프레임 없음, 380×436 시작. 페이지에 따라 크기를 렌더러가 바꿈. 녹음 화면은 360×320 고정 |
| 공용 팝업 | `pages/popupWindow.html` | `windows/popup.js · createPopupWindow` | **싱글턴**(이미 열려 있으면 내용만 바꿈), 항상 위. `type` 값으로 확인·경고·업로드 진행 등 15종 처리 |
| AI 요약 준비(업로드 옵션) | `pages/summarizeWindow.html` | `windows/summarize.js` | 560×500 고정. 제목·언어·참석자 수·템플릿 선택 |
| 업로드 리스트 | `pages/uploadList.html` | `windows/uploadList.js` | 메인 창 왼쪽(공간 없으면 오른쪽)에 붙음. 실패/대기 업로드 재시도·삭제 |
| 트레이 아이콘 | — | `main.js · whenReady` | 메뉴: Quit / Open |

**페이지 전환 규칙**
- "홈으로"는 항상 `ipc/handleAuth.js · loadHome()` 을 거친다. 로그인 상태면 `index.html`, 아니면 `login.html`.
- `index.html` → `recordingWindow.html` 이동만은 렌더러가 직접 한다(`window.location.href`).
- 업데이트 화면은 `services/updateService.js` 가 로그인 화면 또는 마이크 테스트 화면일 때만 덮어쓴다. 녹음 화면은 건드리지 않는다.

---

## 3. 앱 시작 순서 (`main.js · app.whenReady`)

```
1. 단일 인스턴스 잠금 (두 번째 실행 → 기존 창 포커스 + 딥링크 전달)
2. logger 초기화 → logShipper(로그 서버 전송) 시작 → 'app_started' 로그
3. AudioHelperManager 생성 (헬퍼 실행은 아직 안 함. 화면이 start-audio-helper 를 부를 때 실행)
4. timbloRecApp:// 프로토콜 등록 (빌드본만)
5. 복구 스캔 (recoveryService.scanAndAutoQueue)
     업로드 작업이 없는 녹음이 남아 있으면 → 업로드 대기열에 넣고 "복구되지 않은 녹음" 팝업
     → 사용자 응답을 기다린 뒤 다음 단계로
6. 메인 창 생성 → loadHome() → (세션은 메모리에만 있으므로) 항상 로그인 화면부터
7. 트레이 생성
8. (팝업에서 "업로드 리스트 열기"를 골랐으면) 업로드 리스트 창
9. 최초 실행 인자로 딥링크가 왔으면 처리 (Windows)
10. 자동 업데이트 확인 (Windows 빌드본 + UPDATE_SERVER_URL 이 있을 때만)
```

종료할 때(`window-all-closed`, `before-quit`)는 헬퍼 프로세스를 **kill** 하고, 남은 로그를 로그 서버로 한 번 더 보낸다.

---

## 4. preload 가 노출하는 API

`src/main/preload.js` 가 `window.` 아래에 8개 묶음을 노출한다. 요청은 모두 `ipcRenderer.invoke`, 수신은 `ipcRenderer.on` 이다. `send` 는 쓰지 않는다.

| 묶음 | 용도 | 주요 함수 → IPC 채널 |
|---|---|---|
| `electronAPI` | 헬퍼 · 창 · 업로드 흐름 | `startAudioHelper`→`start-audio-helper`, `sendHelperCommand`→`send-helper-command`, `onHelperEvent`←`helper-event`, `openPopupWindow`, `openSummarize`, `requestUpload`/`onRequestUpload`, `deleteRecording`, `toggleUploadList`, `setWindowConstraints`, `loadIndex`, `getAppVersion`, `createSystemNotification` 등 |
| `authAPI` | 로그인 | `getStatus`→`auth:get-status`, `openSso`→`auth:open-sso`, `loginWithEmpno`→`auth:login-empno`, `loginManual`→`auth:login-manual` |
| `templateAPI` | 요약 템플릿 목록 | `getCached`→`templates:cached`, `refresh`→`templates:refresh` |
| `updateAPI` | 업데이트 화면 | `onStatus`←`update-status` |
| `dbAPI` | 로컬 DB | `insertRecording`, `upsertRecording`, `enqueueUpload`, `removeJob`, `onJobsUpdated` (메모·태그 함수는 남아 있지만 화면에서 안 씀) |
| `serviceAPI` | 서버 업로드 | `serverUpload`→`server-upload`, `retryServerUpload`→`retry-server-upload`, `retryServerUploads`→`retry-server-uploads` |
| `windowAPI` | 창 조작 | `minimizeWindow`, `closeWindow`, `topWindow`(항상 위 토글), `appQuit`, `goHome`, `sendAppCloseRecording`, `sendMaxDurationStopped` 등 |
| `developerAPI` | 렌더러 로그 | `sendInfo/Warn/Error/Debug`→`send-*`, `logAction`→`log-user-action` |

**주의**: preload 에는 있는데 메인에 핸들러가 없는 채널이 있다(`mark-deleted`, `list-pending-uploads`, `mark-uploaded`, `list-jobs`, `maximize-window`). 지금은 아무도 부르지 않아서 문제가 없지만, 부르면 오류가 난다.

---

## 5. 메인 프로세스가 특별 처리하는 헬퍼 명령

렌더러는 `sendHelperCommand(obj)` 로 헬퍼 명령을 보내고, 메인은 대부분 그대로 넘긴다. 아래 두 명령만 메인이 중간에서 처리한다(`main.js · send-helper-command` 핸들러).

| 명령 | 메인이 하는 일 |
|---|---|
| `set_output_dir` | ① 상대경로(`"recordings"`)를 절대경로로 바꾼다. Windows: `recordingDir.getRecordingBase()` + `recordings`, macOS: `/tmp/recordings`. ② 헬퍼가 `output_dir_set` 을 돌려줄 때까지 최대 5초 기다린다(`waitForHelperEvent`). 순서를 보장하기 위해서다. |
| `start` | ① 새 `sessionId`(uuid)를 만든다. ② 녹음 이름(`A.Biz_pcapp_rec_YYYYMMDD_HHmmss`, KST)을 정한다. ③ 렌더러에 `session_created` 이벤트를 직접 보낸다. ④ 헬퍼에 start 를 전달한다. ⑤ 부서장 안내 메일 API 를 호출한다(기다리지 않음). |

모든 명령에는 `audioHelperManager.sendCommand` 가 현재 `sessionId` 를 덧붙인다.

헬퍼에서 온 이벤트도 렌더러로 보내기 전에 메인이 손본다(`main.js · normalizeHelperEventPaths`).
- `output_dir_set` 의 경로가 비어 있으면 메인이 보낸 경로로 채운다. 회사 PC 에서 `undefined` 로 온 사례가 있어서다.
- `segment_ready` 의 경로가 상대경로면 헬퍼 작업 폴더 기준 절대경로로 바꾸고, `dir` 필드를 덧붙인다.

---

## 6. 메인 → 렌더러 이벤트 (주요한 것)

| 채널 | 언제 | 받는 화면 |
|---|---|---|
| `helper-event` | 헬퍼 stdout 한 줄마다 + `session_created`, `helper_status` | index, recording |
| `auth-exchanged` | SSO 딥링크 토큰 교환 결과 | login |
| `request-upload` | summarize 창의 "AI요약 시작"을 메인 창으로 중계 | recording |
| `delete-recording-result` | 녹음 파일 삭제 결과 | recording |
| `app-close-recording`, `max-duration-stopped` | 팝업에서 고른 결과를 메인 창으로 중계 | recording |
| `upload-progress`, `upload-failed` | 업로드 진행률/실패 | popup |
| `jobs-updated`, `upload-list-open` | 업로드 목록 변경 | uploadList |
| `upload-list-state` | 업로드 리스트 창 열림/닫힘 | recording |
| `update-status` | 업데이트 다운로드·설치 단계 | update |
| `deep-link` | 딥링크 원문 | (구독하는 화면 없음. 실제 처리는 메인에서) |

---

## 7. 창 사이 통신 패턴

보조 창(팝업, summarize)에서 고른 결과는 **메인을 거쳐 메인 창(recording.js)으로 다시 보내진다**. 녹음 상태는 recording.js 가 들고 있기 때문이다.

```
summarize 창 "AI요약 시작"
  → electronAPI.sendHelperCommand({cmd:'stop'})      (헬퍼 정지)
  → electronAPI.requestUpload({lang, attendeeNum, title, templateId})
       → main 'request-upload' → 메인 창으로 'request-upload' 재전송
            → recording.js onRequestUpload → dbAPI.enqueueUpload → (조각 저장 완료되면) serviceAPI.serverUpload
```
팝업에서 "삭제"·"업로드"를 고르는 것도 같은 방식으로 중계된다(`send-app-close-recording`, `send-max-duration-stopped`).
