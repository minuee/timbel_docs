# 09. Electron 기초

> 작성일: 2026-08-19
> 이 프로젝트가 쓰는 기술 스택을 이해하기 위한 입문 문서

---

## 1. Electron 이 뭔가

**웹 기술(HTML/CSS/JS)로 데스크톱 앱을 만드는 프레임워크**입니다.
Chromium(브라우저 엔진) + Node.js 를 하나로 묶은 것입니다.

```
Electron = Chromium(화면 그리기) + Node.js(파일·네트워크·OS 접근)
```

브라우저는 보안 때문에 파일 시스템이나 OS 기능에 마음대로 접근할 수 없습니다.
Electron 은 그 제약을 풀어서, **웹 페이지가 데스크톱 앱처럼 동작하게** 합니다.

### Node 계열이 맞나?

네, 맞습니다. 다만 정확히는:

- 패키지 관리는 **npm/package.json** 그대로 — Node 생태계를 그대로 씁니다
- 앱 로직 부분은 **Node.js 런타임 위에서** 돌아갑니다 (`fs`, `path`, `child_process` 등 사용 가능)
- 하지만 **Node.js 그 자체는 아닙니다.** Electron 이 자체 Node 를 내장하고 있어서,
  로컬에 설치된 Node 버전과 앱이 쓰는 Node 버전이 다릅니다

> 예: 로컬 Node 24.16 으로 개발해도, Electron 38 이 내장한 Node 는 22.18 입니다.
> 네이티브 모듈(C++ 로 짠 npm 패키지)을 쓸 때 이 차이가 문제를 일으킬 수 있습니다.

### 대표적인 Electron 앱

VS Code, Slack, Discord, Notion, Figma(데스크톱), Postman, Docker Desktop.

---

## 2. 왜 쓰나 — 장단점

### 장점

| | 설명 |
|---|---|
| **하나의 코드로 3개 OS** | Windows / macOS / Linux 를 같은 소스로 |
| **웹 개발자가 바로 투입** | HTML/CSS/JS 를 알면 학습 곡선이 낮음 |
| **npm 생태계** | 수십만 개 패키지를 그대로 사용 |
| **최신 웹 표준** | Chromium 최신 버전을 내장하므로 브라우저 호환성 걱정이 없음 |

### 단점

| | 설명 |
|---|---|
| **용량이 큼** | 앱마다 Chromium + Node 를 통째로 포함. **빈 앱도 100~200MB** |
| **메모리 사용량** | 브라우저 하나를 띄우는 것과 비슷 |
| **네이티브 성능 한계** | 오디오/비디오 실시간 처리 같은 건 별도 네이티브 모듈이 필요 |
| **보안 설계 필요** | 웹 페이지에 OS 권한을 주는 구조라 잘못 설정하면 위험 |

> 이 프로젝트가 마이크·시스템 오디오 캡처를 **Swift/C++ 로 따로 만든 이유**가 마지막 항목입니다.
> JS 로는 OS 레벨 오디오 캡처가 불가능합니다.

---

## 3. 핵심 구조 — 프로세스 2종류

Electron 앱은 **최소 2개의 프로세스**로 돌아갑니다. 이게 가장 중요한 개념입니다.

```
┌─────────────────────────────────────────────┐
│  메인 프로세스 (Main Process)   ← 앱당 1개    │
│  · Node.js 환경                              │
│  · 창 생성/관리, 메뉴, 트레이                  │
│  · 파일 읽기/쓰기, DB, 네트워크                │
│  · OS 기능 접근                               │
│  · 진입점: package.json 의 "main"             │
└───────────────┬─────────────────────────────┘
                │  IPC (프로세스 간 통신)
┌───────────────┴─────────────────────────────┐
│  렌더러 프로세스 (Renderer)     ← 창마다 1개   │
│  · Chromium 환경 (= 웹 페이지)                │
│  · HTML/CSS/JS 로 화면 그리기                 │
│  · 기본적으로 OS 접근 불가 (보안)              │
└─────────────────────────────────────────────┘
```

### 왜 나눠져 있나

렌더러는 **웹 페이지**입니다. 만약 여기서 `fs.unlink()` 같은 걸 바로 호출할 수 있다면,
악성 스크립트가 끼어들었을 때 사용자 파일을 지울 수 있습니다.

그래서 렌더러는 **감옥에 가둬두고**, 필요한 기능만 메인 프로세스에 요청하게 합니다.

---

## 4. preload 와 IPC

렌더러가 메인에게 일을 시키는 통로입니다.

### preload 스크립트

렌더러가 로드되기 **직전에** 실행되는 특별한 스크립트입니다.
렌더러와 메인 사이의 **다리** 역할을 합니다.

```js
// preload.js
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  saveFile: (data) => ipcRenderer.invoke('save-file', data),
});
```

이렇게 하면 렌더러에서 `window.electronAPI.saveFile(...)` 로 쓸 수 있습니다.
**딱 여기 정의한 것만** 쓸 수 있고, `fs` 같은 건 여전히 접근 불가입니다.

### IPC 두 가지 방식

**① 요청–응답 (`invoke` / `handle`)** — 결과를 돌려받을 때

```js
// 렌더러 → 메인
const result = await window.electronAPI.saveFile(data);

// 메인
ipcMain.handle('save-file', async (event, data) => {
  // ... 저장 작업
  return { success: true };
});
```

**② 단방향 알림 (`send` / `on`)** — 메인이 렌더러에게 알려줄 때

```js
// 메인 → 렌더러
mainWindow.webContents.send('progress', { percent: 50 });

// 렌더러 (preload 경유)
window.electronAPI.onProgress((data) => { /* UI 갱신 */ });
```

### 보안 설정 3종 세트

창을 만들 때 이 조합이 표준입니다:

```js
new BrowserWindow({
  webPreferences: {
    nodeIntegration: false,     // 렌더러에서 Node 직접 사용 금지
    contextIsolation: true,     // 렌더러와 preload 의 실행 컨텍스트 분리
    preload: '경로/preload.js', // 허용할 기능만 노출
  },
});
```

옛날 자료에는 `nodeIntegration: true` 로 하라는 게 많은데, **지금은 보안상 금지**입니다.

---

## 5. React Native 와 비교

| | React Native | Electron |
|---|---|---|
| 대상 | 모바일 (iOS/Android) | 데스크톱 (Win/mac/Linux) |
| UI 렌더링 | JSX → **진짜 네이티브 뷰** | HTML/CSS → **Chromium** |
| 로직 실행 | JS 엔진 (Hermes 등) | **Node.js** |
| 네이티브 확장 | Native Modules (Java/Swift) | 네이티브 애드온, 또는 **별도 프로세스** |
| 통신 | Bridge / JSI | **IPC** |
| 결과물 | `.apk` / `.ipa` | `.exe` / `.dmg` / `.AppImage` |
| 배포 | **앱스토어 심사** | **파일 직접 배포** (심사 없음) |
| 앱 용량 | 수~수십 MB | **100MB~** (런타임 포함) |

**가장 큰 차이는 배포입니다.** RN 은 스토어 심사를 기다려야 하지만,
Electron 은 설치 파일을 만들어 바로 나눠주면 끝입니다.
대신 **자동 업데이트를 직접 구현**해야 하고(`electron-updater`),
macOS 는 **Apple 공증**을 받아야 사용자가 경고 없이 열 수 있습니다.

---

## 6. 자주 만나는 개념들

### `electron-builder`
설치 파일을 만들어주는 도구입니다. `package.json` 의 `build` 섹션으로 설정합니다.
- Windows → `.exe` (NSIS 설치 마법사)
- macOS → `.dmg`
- 서명, 공증, 아이콘, 자동 업데이트 설정을 여기서 다룹니다

### `asar`
앱 소스를 하나의 파일로 묶는 아카이브 포맷입니다 (`app.asar`).
파일 수를 줄여 로딩을 빠르게 하고, 소스를 조금 가리는 효과가 있습니다.

> ⚠️ **암호화가 아닙니다.** `npx @electron/asar extract` 로 누구나 풀 수 있습니다.
> 진짜 숨겨야 할 것(API 키 등)은 절대 넣으면 안 됩니다.

### 네이티브 모듈 / ABI
C++ 로 작성된 npm 패키지(`better-sqlite3` 등)는 **특정 Node 버전에 맞춰 컴파일**됩니다.
Electron 은 자체 Node 를 쓰므로 버전이 안 맞으면 이런 에러가 납니다:

```
Error: The module was compiled against a different Node.js version
NODE_MODULE_VERSION 137 vs 139
```

해결: `npx electron-rebuild` — Electron 용으로 다시 컴파일합니다.

### `app.getPath()`
OS 별로 다른 표준 폴더를 알려줍니다. 경로를 직접 하드코딩하면 안 됩니다.

```js
app.getPath('userData')   // 앱 설정/DB 저장용 (권장)
app.getPath('documents')  // 사용자 문서 폴더
app.getPath('temp')       // 임시 폴더 (재부팅 시 지워질 수 있음)
```

### 딥링크 (Custom Protocol)
`myapp://...` 같은 주소로 앱을 실행시키는 기능입니다.
웹 페이지에서 데스크톱 앱을 깨우고 데이터를 넘길 때 씁니다.

### 단일 인스턴스 잠금
앱이 두 번 실행되는 걸 막는 장치입니다.

```js
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) app.quit();   // 두 번째 인스턴스는 즉시 종료
```

> 개발 중인 앱과 설치한 앱을 동시에 켜면 나중 것이 바로 꺼지는 이유가 이것입니다.

---

## 7. 자동 업데이트 (`electron-updater`)

### 왜 필요한가

여기가 RN 과 크게 다른 지점입니다.

| | React Native | Electron |
|---|---|---|
| 업데이트 | 스토어가 알아서 배포·갱신 | **아무도 안 해줌** |

설치 파일을 나눠주고 끝이면 사용자는 새 버전이 나온 줄도 모릅니다.
매번 공지하고, 사용자가 직접 지우고 다시 깔아야 합니다. 사용자가 늘수록 감당이 안 됩니다.

`electron-updater` 는 **앱이 스스로 새 버전을 확인하고 갱신**하게 해줍니다.
`electron-builder` 를 만든 팀의 짝꿍 패키지입니다.

### RN 의 CodePush 와 비교

RN 을 해보셨다면 **CodePush** 를 떠올리시면 맥락이 같습니다 —
"스토어를 거치지 않고 앱을 갱신한다" 는 목적이 동일합니다.

다만 **갱신 범위가 다릅니다.**

| | CodePush | electron-updater |
|---|---|---|
| 갱신 대상 | **JS 번들만** | **앱 전체** (런타임·네이티브 포함) |
| 네이티브 코드 변경 | ❌ 불가 — 스토어 재심사 필요 | ✅ 가능 |
| 스토어 심사 | 우회하는 것이 목적 | 애초에 심사가 없음 |
| 자동 롤백 | ✅ 지원 | ❌ 없음 (수정본을 새로 배포) |

CodePush 가 JS 만 바꿀 수 있었던 것은 **네이티브 바이너리를 건드리지 않아야
심사를 우회**할 수 있었기 때문입니다. 네이티브 모듈 하나 추가하려면 결국 스토어를 거쳐야 했습니다.

Electron 은 그 제약이 없습니다. 심사 자체가 없으니 앱을 통째로 갈아끼웁니다.
**이 프로젝트로 치면 `AudioHelper` 같은 네이티브 헬퍼도 자동 업데이트로 갱신 가능**하다는 뜻입니다.
CodePush 방식이었다면 손댈 수 없는 영역입니다.

> 대신 **자동 롤백이 없는 것이 약점**입니다. CodePush 는 새 번들이 크래시하면 이전 버전으로
> 되돌렸지만, electron-updater 에는 그런 안전장치가 없습니다. 문제 버전이 나가면
> 수정본을 새로 올리는 수밖에 없으므로 **배포 전 검증이 더 중요합니다.**

> 참고: App Center CodePush 는 2025년 3월 서비스가 종료되어, 현재는 Expo Updates 나
> 자체 호스팅 방식으로 대체되었습니다.

### 동작 흐름

```
① 앱 실행 → 서버의 버전 정보 파일(latest-mac.yml / latest.yml) 확인
② 내 버전보다 높으면 → 백그라운드로 차이분 다운로드
③ 완료되면 → 사용자에게 "재시작할까요?" 알림
④ 재시작 시 교체 완료
```

**전체가 아니라 차이분만 받습니다.** `electron-builder` 가 만드는 `.blockmap` 파일이
이걸 가능하게 합니다. 100MB 앱이라도 변경된 부분만 받아 수 MB 로 끝납니다.

### 코드

```js
const { autoUpdater } = require('electron-updater');

app.whenReady().then(() => {
  autoUpdater.checkForUpdatesAndNotify();   // 사실상 이 한 줄
});
```

### ★ 별도의 배포 서버가 필요합니다

이게 핵심입니다. **앱이 "새 버전 있나요?" 하고 물어볼 대상이 있어야 합니다.**

`package.json` 에 그 주소를 적습니다:

```json
"publish": {
  "provider": "generic",
  "url": "https://다운로드서버/updates"
}
```

빌드하면 설치 파일과 함께 **버전 정보 파일**이 생성되고, 이 묶음을 서버에 올려둡니다:

```
dist/
├── timbloRecApp-1.0.0-arm64.dmg
├── timbloRecApp-1.0.0-arm64.dmg.blockmap    ← 차이분 계산용
└── latest-mac.yml                            ← "최신 버전은 1.0.0" 이라는 정보
```

### 서버 선택지

거창한 서버가 아니어도 됩니다. **정적 파일만 서빙되면 충분**합니다.

| provider | 형태 | 비고 |
|---|---|---|
| `generic` | 아무 웹서버 / 사내 파일서버 | **온프레미스에 적합** |
| `github` | GitHub Releases | 무료, 공개 저장소면 가장 간단 |
| `s3` | AWS S3 | 사용량 과금 |

> 이 프로젝트는 **온프레미스 제품**이라 고객사마다 서버가 다를 수 있습니다.
> 도입한다면 업데이트 서버 주소를 어떻게 정할지(고정 / 고객사별 / 딥링크처럼 주입)
> 설계가 먼저 필요합니다.

### 도입 시 주의

- **`publish: null` 이면 버전 정보 파일이 생성되지 않습니다.** 이것부터 바꿔야 합니다
- **macOS 는 코드 서명이 필수입니다.** 서명되지 않은 앱은 자동 업데이트가 아예 동작하지
  않습니다 — 교체 시점에 서명을 검증하기 때문입니다
- 버전 번호(`package.json` 의 `version`)를 올리지 않으면 업데이트로 인식되지 않습니다

### 이 프로젝트 현황 (2026-08-19)

```
electron-updater      미설치
autoUpdater 코드      없음
package.json:91       "publish": null     ← 자동 업데이트 비활성화
```

**현재는 완전 수동 배포**입니다. 새 버전마다 사용자에게 직접 전달해야 합니다.

> 참고: `electron-log` 가 이미 설치돼 있는데, `electron-updater` 와 함께 쓰는 조합으로
> 흔히 쓰입니다. 다만 현재 코드에 업데이터 흔적은 없습니다.

---

## 8. 개발 흐름

```bash
npm install          # 의존성 + Electron 런타임(수백 MB) 내려받기
npm start            # electron .           — 그냥 실행
npm run dev          # electronmon . --dev  — 파일 저장 시 자동 재시작
npm run build        # electron-builder     — 설치 파일 생성
```

### 디버깅

- **렌더러**: 크롬 개발자 도구 그대로 (`Cmd+Opt+I`). 웹 개발과 동일합니다
- **메인**: `console.log` 는 앱을 띄운 **터미널**에 찍힙니다. 브라우저 콘솔이 아닙니다

이 둘을 헷갈리는 게 입문자가 가장 자주 겪는 혼란입니다.
**"로그가 안 보인다"면 대부분 반대쪽을 보고 있는 것**입니다.

### 크로스 플랫폼 빌드의 한계

`electron-builder` 는 기본적으로 **실행 중인 OS 용만** 빌드합니다.
`--win`, `--mac` 플래그로 지정할 수 있지만:

- macOS 앱 서명은 **맥에서만** 가능합니다
- 네이티브 모듈이 있으면 **해당 OS 에서 컴파일**해야 합니다

> 그래서 이 프로젝트는 Windows 용 `AudioHelper.exe` 를 맥에서 만들 수 없습니다.
> Windows 장비가 필요합니다.

---

## 9. 더 볼 것

- 공식 문서: https://www.electronjs.org/docs/latest
- 보안 체크리스트: https://www.electronjs.org/docs/latest/tutorial/security
- electron-builder: https://www.electron.build

- electron-updater: https://www.electron.build/auto-update

입문 시 **가장 먼저 확실히 잡아야 할 것은 3장(프로세스 2종)과 4장(preload/IPC)** 입니다.
나머지는 필요할 때 찾아봐도 되지만, 이 둘을 모르면 코드가 왜 이렇게 나뉘어 있는지 이해가 안 됩니다.
