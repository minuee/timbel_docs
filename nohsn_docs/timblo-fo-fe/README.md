# timblo-fo-fe 인수인계 문서

Timblo(SK A.Biz) 프론트오피스 웹 애플리케이션(`timblo-fe-master-service`)의 인수인계용 분석 문서입니다.
2026-08-14 기준 `release` 브랜치 소스를 읽고 작성했습니다.

## 문서 목록

| 문서 | 내용 | 이럴 때 본다 |
|---|---|---|
| [01-tech-stack.md](./01-tech-stack.md) | 기술 스택, 라이브러리 인벤토리, 빌드/배포 파이프라인 | 뭘로 만들어졌는지 알고 싶을 때 |
| [02-architecture.md](./02-architecture.md) | 폴더 구조, 라우팅, 레이아웃 계층, 화면 목록 | 코드 어디를 열어야 할지 찾을 때 |
| [03-data-flow.md](./03-data-flow.md) | **데이터 흐름 전체** — API 계약, 스토어, 상태 전파 | 기능 수정/디버깅할 때 (제일 먼저) |
| [04-auth-session.md](./04-auth-session.md) | 인증·토큰·SSO·세션 만료 처리 | 로그인 관련 이슈, 로컬에서 화면이 안 뜰 때 |
| [05-realtime-socket.md](./05-realtime-socket.md) | Socket.IO 실시간 알림, STT 진행률, 노트 공동편집 | 실시간 갱신이 안 될 때 |
| [06-local-setup.md](./06-local-setup.md) | 로컬 구동 절차, 환경변수, 트러블슈팅 | 처음 셋업할 때 |
| [07-risks-todo.md](./07-risks-todo.md) | 기술 부채, 리스크, 개선 우선순위 | 리팩터링 계획 세울 때 |
| [08-content-detail-loading.md](./08-content-detail-loading.md) | 회의록 상세 로딩 지연 원인 분석 (API·렌더 게이트 구조) | 상세 페이지가 느리거나 로딩이 안 풀릴 때 |

## 30초 요약

- **CRA(react-scripts 5) + CRACO 기반 React 18 SPA.** TypeScript 없음, 전부 JS/JSX.
- **상태는 Zustand 24개 스토어**, API는 `src/Utils/requestUtil.js` 한 곳에서 axios로 직접 호출.
- **백엔드는 HTTP 200 + body `httpCode`** 계약이라 axios interceptor가 아니라 스토어마다 `switch (res.data.httpCode)`로 분기한다. 이게 이 코드베이스의 가장 중요한 관습이다.
- **핵심 도메인은 "회의록(Content)"** — 업로드/녹음 → STT → 요약 → 상세 편집(전사·요약·메모·노트·하이라이트) → 공유.
- 실시간 갱신(STT 진행률, 세션 만료, 공동편집)은 **Socket.IO 단일 커넥션**(`src/Libs/NotifyManager.js`)이 `Main.jsx`에서 초기화되어 스토어로 흘러간다.

## 읽는 순서 (신규 투입자 기준)

1. [06-local-setup.md](./06-local-setup.md) 로 일단 띄운다
2. [02-architecture.md](./02-architecture.md) 로 화면-파일 매핑을 잡는다
3. [03-data-flow.md](./03-data-flow.md) 로 데이터가 어디서 와서 어디로 가는지 이해한다
4. 실제 기능 하나(예: 회의록 목록)를 따라가며 04·05를 참조한다
