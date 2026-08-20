# 01. 기술 스택

## 한 줄 정의

**CRA(react-scripts 5.0.1) + CRACO 기반 React 18 SPA (순수 JavaScript)** — MUI 중심 UI에 Zustand 전역 상태, axios 직접 래핑 API 레이어, Socket.IO 실시간 채널을 얹은 회의록/STT 서비스의 프론트오피스.

## 코어

| 영역 | 기술 | 비고 |
|---|---|---|
| 런타임 | Node **22.13.1** (`.nvmrc`) | Dockerfile은 node:20 사용 — 불일치 |
| 빌드 | `react-scripts` 5.0.1 + `@craco/craco` 7.1 | eject 안 함. webpack 5 |
| 언어 | **순수 JS(ESM)** — `.js` 155개 / `.jsx` 104개 | TypeScript 파일 0개 |
| UI | React **18.3.1** | `StrictMode`는 `src/index.js:11`에서 주석 처리됨 |
| 라우팅 | `react-router-dom` v6 | `src/App.js`에 전체 라우트 평면 정의, lazy/code-splitting 없음 |
| 전역 상태 | **Zustand 4.5** | `src/Stores/` 24개 스토어 |
| HTTP | `axios` 1.x + 자체 래퍼 | `src/Utils/requestUtil.js` (220줄) |
| 실시간 | `socket.io-client` 4 | `src/Libs/NotifyManager.js` 단일 진입점 |
| 인증 | `jwt-decode` + `js-cookie` / `react-cookie` | `src/Utils/tokenStore.js`, `jwtUtil.js` |

`.js`와 `.jsx` 확장자가 규칙 없이 섞여 있다. 같은 성격의 파일도 제각각이므로(`ContentList.js` / `ContentDetail.jsx`) import 시 확장자를 가정하지 말 것.

## UI / 기능 라이브러리

### 디자인 시스템
- **MUI v7** (`@mui/material`) — **161개 파일에서 사용, 사실상 표준**
- **MUI X Pro (유료)** — `@mui/x-data-grid-pro`, `@mui/x-date-pickers-pro`. `src/App.js:35`에서 `LicenseInfo.setLicenseKey(process.env.REACT_APP_MUI_LICENSE_KEY)` 호출
- 테마: `src/Themes/OldTheme.js`(현재 사용), `BasicTheme.js`(미사용에 가까움)

### 그리드 — 2종 병존 ⚠️
- `ag-grid-community` / `ag-grid-react` 33 — 메인 회의록 목록 (`src/Components/Feature/Common/ContentGrid/AgGrid.js`, 1153줄)
  - 특이사항: `public/index.html`에서 `ag-grid-community.js`를 **`<script>` 태그로 별도 로드**한다
- `@mui/x-data-grid-pro` — 6개 파일 (사용자/공유 관련 그리드)

### 미디어 · 녹음
`extendable-media-recorder` + `extendable-media-recorder-wav-encoder`, `react-audio-voice-recorder`, `react-voice-visualizer`, `audio-resampler`, `public/worklets/`(AudioWorklet 프로세서)

### 문서 · 에디터
`react-quill-new`(노트 에디터), `dompurify`(XSS 방어), `html-to-text`, `jszip`, `file-saver`

### 기타
`echarts` + `echarts-for-react`(이용 현황 차트), `@fullcalendar/*`(캘린더), `react-virtuoso`(가상 스크롤), `idb`(IndexedDB 래퍼), `react-toastify`(토스트), `react-error-boundary`, `re-resizable`, `reactjs-popup`, `uuid`, `qs`

## 스타일링 — 혼재 상태 ⚠️

| 방식 | 규모 |
|---|---|
| MUI `sx` prop + `ThemeProvider` | 주축 (161파일) |
| plain CSS import | 46곳 (`.css` 34개) |
| `styled-components` 6 | 16개 파일 |
| `@emotion/styled` | 1개 파일 |
| `.scss` | 2개 (`sass`는 devDependency) |

단일 규칙이 없다. 새 컴포넌트는 MUI `sx` 기준으로 통일하는 것을 권장.

## 코드 품질 도구

- **Prettier 3.5** — `.prettierrc` (printWidth 120, singleQuote, semi, trailingComma all, LF)
- **ESLint** — `.eslintrc.js`: `react-app` + `plugin:prettier/recommended`
  - ⚠️ `react-hooks/exhaustive-deps`, `react-hooks/rules-of-hooks` **둘 다 off**
  - ⚠️ `npm run lint`가 `eslint . --fix || true` — **항상 성공으로 끝난다**
- **테스트 없음** — `@testing-library/*`는 설치되어 있으나 테스트 파일 0개

## 경로 alias

`craco.config.js`와 `jsconfig.json`에 **이중 정의**되어 있다 (webpack 해석용 + 에디터 자동완성용). 하나만 고치면 런타임 또는 IDE 중 한쪽이 깨지니 항상 같이 수정할 것.

| alias | 실제 경로 |
|---|---|
| `@/` | `src/` |
| `@assets/` | `src/Assets/` |
| `@icon/` | `src/icons/svg/` |
| `@feat-common/` | `src/Components/Feature/Common/` |

## 빌드 · 배포

### 스크립트
```
npm start   → craco start   (dev server, PORT=3000)
npm run build → craco build
npm test    → craco test    (테스트 파일 없음)
npm run format → prettier . --write
npm run lint   → eslint . --fix || true
```

### Docker
`Dockerfile`은 멀티스테이지지만 **builder 스테이지에서 빌드하지 않는다.** 소스와 node_modules를 그대로 런타임 이미지에 복사하고, 컨테이너 기동 시 `scripts/start.sh`가 `npm run build`를 수행한 뒤 `serve -s build -l 3000`으로 서빙한다.

```
scripts/start.sh:
  NODE_OPTIONS="--max-old-space-size=8192 --max-semi-space-size=1024" npm run build
  serve -s build -l 3000
```
→ 컨테이너 첫 기동이 매우 느리고 메모리를 많이 쓴다. (이미 `build/`가 있으면 건너뜀)

`server.js`(express)는 **어디에서도 참조되지 않는 사문화 코드**다. 실제 서빙은 `serve`가 한다.

### CI/CD — GitLab과 GitHub 병존 ⚠️
- **GitLab CI** (`.gitlab-ci.yml`) — 현재 주 파이프라인
  - `apps/timblo/aimm-release-ci-templates` v1.2.0 템플릿 include
  - `v*` 태그 push → GHCR 이미지 빌드/릴리즈
  - `release-dev` 브랜치 push → 로컬 빌드 & docker compose 배포 (`COMPOSE_SERVICE: fe-master`)
- **GitHub Actions** (`.github/workflows/`) — 4종 (`common-docker-deploy`, `pr-docker-deploy`, `hynix-deploy`, `nexus-image-deploy`). 온프렘(하이닉스/Nexus) 납품용으로 보인다.
- `build.sh` — 로컬에서 버전 입력받아 `docker-compose build` 후 GHCR push

### 배포 환경
`REACT_APP_*` 환경변수로 분기하며 브랜치별로 타깃이 다르다 (README 기준: dev / stg / poc / azure(amm) / demo, 그 외 온프렘). 원격 브랜치가 수십 개 있는 장수 브랜치 운영 방식.

## 규모 · 이력

- `src/` 692파일 / JS·JSX **45,288줄** / SVG 아이콘 379개
- 최대 파일: `Stores/ContentsStore.js` 1440줄, `Layout/Sidebar/Sidebar.jsx` 1316줄, `Pages/Contents/ContentDetail.jsx` 1235줄
- 기여자 10명, 최근 3개월 120커밋 (활발)

## 의존성 주의사항

### 중복 라이브러리
- **날짜 7종**: `moment` + `dayjs` + `react-datepicker` + `react-datetime` + `@iftek/react-datetime` + `react-multi-date-picker` + `@mui/x-date-pickers-pro`
  - `ContentsStore.js`는 **한 파일에서 dayjs와 moment를 동시에 import**한다
- **그리드 2종**: ag-grid + MUI DataGrid Pro
- **프로그레스바 3종**: `@ramonak/react-progress-bar`, `react-progress-bar`, `react-spinners`/`spinners-react`
- **스타일링 3종**: MUI(emotion) + styled-components + plain CSS

### package.json에 없는데 코드가 쓰는 것 (전이 의존성) ⚠️
- `qs` — `src/Utils/requestUtil.js:1`
- `@mui/x-license` — `src/App.js:33`

둘 다 다른 패키지의 하위 의존성으로 우연히 hoisting되어 동작 중이다. 상위 패키지 버전이 바뀌면 갑자기 빌드가 깨질 수 있으니 명시적 의존성으로 승격 권장.

### 패키지 매니저 3중 혼선 ⚠️
`package-lock.json`(820KB) + `bun.lock`(473KB)이 **동시에 커밋**되어 있고, README는 npm/yarn을 안내하며, Dockerfile은 `npm install --force`를 쓴다. 기준 lock 파일을 팀에서 확정해야 한다. (본 문서는 `package-lock.json` 기준으로 설명)
