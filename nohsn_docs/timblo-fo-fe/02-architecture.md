# 02. 아키텍처 · 폴더 구조 · 라우팅

## 계층 구조

```
index.js  (ReactDOM.createRoot / StrictMode 비활성)
└─ App.js  (전역 Provider + 라우트 정의)
   ├─ ThemeProvider(OldTheme) + CssBaseline
   ├─ ToastContainer (react-toastify)
   ├─ ClipboardProtector  ← 워크스페이스 정책상 복사 금지 시
   └─ ErrorBoundary → Router
      └─ <CheckUser>            ← 인증 가드 (Outlet)
         ├─ 모바일: 각 Mobile 페이지 (레이아웃 없음)
         └─ 데스크톱: <Main>    ← 공통 레이아웃 + 소켓 초기화
            ├─ <Sidebar>
            └─ <Outlet> → 각 Page
```

핵심은 **`CheckUser` → `Main` 2단 게이트**다. `CheckUser`가 토큰을 검증해 통과시키고, `Main`이 다시 쿠키를 검증하면서 Socket.IO를 연결한다. 두 곳 모두에서 인증 검사를 하므로 로컬에서 화면이 안 뜨면 이 둘을 먼저 본다. → [04-auth-session.md](./04-auth-session.md)

## 라우팅 (`src/App.js`)

라우트는 전부 `App.js` 한 파일에 평면 정의되어 있다. **코드 스플리팅(`React.lazy`) 없음** → 초기 번들이 크다.

| 경로 | 컴포넌트 | 파일 |
|---|---|---|
| `/`, `/home` | HomeV2 | `Pages/Home/HomeV2.jsx` |
| `/contents` | ContentList | `Pages/Contents/ContentList.js` |
| `/content/:contentId` | ContentDetail | `Pages/Contents/ContentDetail.jsx` (1235줄, 핵심 화면) |
| `/calendar` | CalendarPage | `Pages/Calendar/CalendarPage` |
| `/inbox` | Inbox | `Pages/Inbox/Inbox` |
| `/bookmark` | BookmarkPage | `Pages/Bookmarks/BookmarkPage` |
| `/recycle` | Recycles | `Pages/Recycles/Recycles` |
| `/search` | Search | `Pages/Search/Search` |
| `/usage` | Usage | `Pages/Usage/Usage` |
| `*` | → `/home` 리다이렉트 | |

### 개발 전용 라우트 ⚠️
`/login`, `/join`, `/findPassword`는 **`REACT_APP_IS_DEV === 'true'`일 때만 등록된다** (`App.js:79`). 운영에서는 외부 `/sign` 페이지로 풀 리다이렉트한다.
→ **로컬 개발 시 `REACT_APP_IS_DEV=true`가 사실상 필수다.**

### 모바일 분기
`useIsMobile()` 훅 결과로 **라우트 자체를 갈아끼운다**(`App.js:93`). 같은 URL이라도 모바일은 `Pages/Mobile/*`의 전혀 다른 컴포넌트가 렌더링되고, 공통 `Main` 레이아웃(=사이드바, **소켓 초기화**)을 거치지 않는다.

모바일 지원 화면은 4개뿐: `/home`, `/contents`, `/content/:contentId`, `/inbox`.

### basename
`package.json`의 `homepage` 값을 `Router basename`으로 쓴다 (`App.js:70`). 현재 `""`(빈 문자열)이라 루트 기준. 온프렘에서 서브패스(`/aimm` 등) 배포 시 이 값을 바꾼다.

## 폴더 구조

```
src/
├── App.js                  라우트 + 전역 Provider
├── index.js                엔트리
├── Assets/fonts/           웹폰트 (woff 9개)
├── icons/svg/              SVG 아이콘 379개  (@icon alias)
├── Components/
│   ├── Common/             범용 UI 원자 — Button, Input, Checkbox, Modal, Tooltip,
│   │                       Loading, BrandingLogo, CollaborativeBox
│   ├── Feature/            도메인 기능 컴포넌트 (화면별 분류)
│   │   ├── Common/         기능 레벨 공용  (@feat-common alias)
│   │   │   ├── ContentGrid/    ← ag-grid 회의록 목록 (AgGrid.js 1153줄)
│   │   │   ├── Toast/         ← ToastError/ToastInfo, 전역 에러 표시 진입점
│   │   │   ├── PageLoading/, PageEmpty/, Chip/, HighlightText/ ...
│   │   ├── Content/        ★ 회의록 상세의 기능 단위
│   │   │   ├── Transcription/  전사(STT) 뷰 + MediaPlayer + AiCorrect
│   │   │   ├── EditableBlock/  요약/타임블록 편집
│   │   │   ├── SummaryBlock/, Memo/, Note/, Bookmark/, Share/,
│   │   │   ├── SpeakerEdit/, Template/, Chatbot/, ConsultationAnalysis/,
│   │   │   ├── MeetingTime/, ContextMenu/
│   │   ├── Sidebar/        Address(주소록), Dictionary(용어사전) 등
│   │   ├── Home/, Inbox/, Search/, Calendar/, Bookmark/, Recycles/, Header/
│   ├── Layout/
│   │   ├── Main/Main.jsx       ★ 공통 레이아웃 + 소켓 + 세션 모달 (595줄)
│   │   ├── Sidebar/Sidebar.jsx ★ 사이드바 (1316줄)
│   │   └── Header/
│   └── app/                앱 레벨 모달/기능 — Record(녹음), Term(약관),
│                           SessionExpired, Notice
├── Pages/                  라우트 단위 화면
│   ├── Auth/               LoginPage, JoinPage, FindPassword, CheckUser,
│   │                       CheckCookies, Action.js(공통 인증 액션 훅)
│   ├── Home/, Contents/, Calendar/, Inbox/, Bookmarks/, Recycles/,
│   ├── Search/, Usage/
│   └── Mobile/             모바일 전용 화면 (Home, Contents, Inbox)
├── Stores/                 Zustand 스토어 → 03-data-flow.md 참조
│   ├── *.js                도메인 스토어 (17개)
│   ├── api/                순수 API 스토어 (3개)
│   └── ui/                 UI 상태 전용 스토어 (4개)
├── Libs/
│   ├── NotifyManager.js    Socket.IO 래퍼 → 05-realtime-socket.md
│   ├── overrideConsole.js  console.* 하이재킹 + 서버 로그 전송
│   └── ClipboardProtector.jsx  복사 방지
├── Themes/                 OldTheme.js(사용중), BasicTheme.js, ReactQuill.css
├── Utils/
│   ├── requestUtil.js      ★ API 게이트웨이 (모든 HTTP가 여기 통과)
│   ├── tokenStore.js       ★ 토큰 저장/조회 (sessionStorage + 쿠키)
│   ├── jwtUtil.js, apiUtil.js, brand.js, domainTerms.js,
│   ├── mediaUtil.js(548줄), timeUtil.js, logUtil.js, debugger.js,
│   └── ssoFilename.js, Util.js, DrawContentIcon.js
└── hooks/                  useIsMobile, useIndexedDB, useDeviceSize,
                            useBlockRedirect, useFocusOut, useTitle,
                            useDomObserver, useTraceLog, useURIScheme
```

## 컴포넌트 분류 관습

| 위치 | 성격 | 예시 |
|---|---|---|
| `Components/Common/` | 도메인 무관 UI 원자 | Button, Modal |
| `Components/Feature/Common/` | 도메인은 알지만 여러 화면에서 공용 | ContentGrid, Toast |
| `Components/Feature/<화면>/` | 특정 화면 전용 | Content/Transcription |
| `Components/Layout/` | 라우트를 감싸는 껍데기 | Main, Sidebar |
| `Components/app/` | 앱 전역 모달/오버레이 | Term, SessionExpired, Record |
| `Pages/` | 라우트 1:1 매핑 진입점 | ContentDetail |

각 컴포넌트 폴더에 `img/` 하위 폴더를 두고 이미지를 지역 배치하는 패턴이 일관되게 쓰인다.

## 핵심 화면: 회의록 상세 (`/content/:contentId`)

이 앱의 무게중심. `Pages/Contents/ContentDetail.jsx`(1235줄)가 다음을 조립한다.

- **전사(Transcription)** — STT 결과 문장 목록(`SttRow`), 화자 편집, AI 교정(`AiCorrect`), 미디어 플레이어 연동(문장 클릭 → 해당 시점 재생)
- **요약(SummaryBlock / EditableBlock)** — 블록 단위 편집, 타임블록
- **노트(Note)** — Quill 에디터 + **Socket.IO 기반 공동 편집 권한 제어**
- **메모(Memo) / 하이라이트 / 북마크**
- **공유(Share)** — 사용자별 OWNER/EDITOR/VIEWER 권한
- **챗봇(Chatbot)** — 별도 LLM 호스트 호출
- **다운로드** — 원본 미디어 / 문서(docx·xlsx 등)

수정 작업 시 대부분 이 폴더 트리(`Components/Feature/Content/*`)와 `Stores/ContentsStore.js`를 함께 건드리게 된다.

## 도메인 용어 치환 (`Utils/domainTerms.js`)

"회의록", "전체 회의록" 같은 명칭이 하드코딩이 아니라 `useDomainTerms()` 훅으로 주입된다 (`Main.jsx:45`의 메뉴 라벨 등). 납품처(SK/하이닉스 등)별로 용어를 바꾸기 위한 장치이므로, UI 문구를 고칠 때 여기를 먼저 확인할 것.

브랜딩(로고/파비콘)도 유사하게 `Stores/BrandingStore.js`가 서버에서 받아 런타임 주입한다 (`App.js:51`).
