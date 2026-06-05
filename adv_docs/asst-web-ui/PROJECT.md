# asst-web-ui 프로젝트 컨텍스트

> Claude가 세션 시작 시 자동으로 읽는 파일입니다.
> asst-web-ui 작업 시 이 파일을 참고하세요.

---

## 프로젝트 성격

- **위치:** `c:/git/work/advisor/asst-web-ui/`
- **성격:** UI 전용 데모 프로젝트 — 실제 API/소켓 연결 없음
- **동작 방식:** 모든 화면 데이터는 `src/shared/lib/MockInitializer.ts`에서 주입
- **모든 API 응답:** `{ status: 204, data: null }` (no-op)
- **개발 서버:** `npm run dev` → `http://localhost:9001`
- **빌드 도구:** Webpack 5, Vue 3 Composition API, TypeScript, Pinia, Element Plus

---

## 페이지 목록 (URL → 파일 경로)

| URL | 파일 | 역할 |
|-----|------|------|
| `/advisor/consultant` | `src/view/advisor/consultant/index.vue` | 역할 분기 라우터 (AGENT→상담원화면, ADMIN→관리자화면) |
| `/advisor/agent` | `src/view/advisor/agent/index.vue` | 상담원 메인 화면 (대시보드 + 채팅 + 지식검색) |
| `/advisor/admin` | `src/view/advisor/admin/index.vue` | 관리자 메인 화면 (상담원 목록 + 채팅 모니터링) |
| `/advisor/admin/management/user` | `src/view/advisor/manage/group/index.vue` | 사용자/그룹 관리 |
| `/advisor/admin/management/role` | `src/view/advisor/manage/role/index.vue` | 권한 관리 |

> 라우트 등록 위치: `src/shared/api/modules/menus/mockupMenuList.ts`
> 새 페이지 추가 시 이 파일에 항목 추가 → 자동으로 라우터에 등록됨

---

## 핵심 컴포넌트 구성

### 상담원 화면 (`/advisor/agent`)
```
src/view/advisor/agent/index.vue          ← 메인 진입점
  ├── Dashboard.vue                        ← 첫 화면 (공지/코칭/통화이력 요약)
  ├── src/view/advisor/components/chat/   ← 통화중 채팅 패널
  └── src/view/advisor/components/knowledge/ ← 지식검색 패널
```

### 관리자 화면 (`/advisor/admin`)
```
src/view/advisor/admin/index.vue
  ├── src/view/advisor/components/ConsultantDrawer/  ← 좌측 상담원 목록
  └── src/view/advisor/components/chat/              ← 상담원 채팅 모니터링
```

### 우측 Drawer 패널 (공통 — 모든 화면에서 열림)
```
src/widgets/layout/Drawer/
  └── components/
      ├── Bookmark/         ← 북마크
      ├── Memo/             ← 메모
      ├── Todo/             ← 할 일
      ├── Notice/           ← 공지사항
      ├── Keyword/          ← 키워드 감지
      ├── Setting/          ← 설정
      ├── Listening/        ← 청취 기능
      ├── AdminCoaching/    ← 관리자 코칭 패널
      └── CoachingRequest/  ← 코칭 요청
```

### 레이아웃 공통 컴포넌트
```
src/widgets/layout/
  ├── ContentLayout/    ← 페이지 기본 레이아웃 래퍼
  ├── HeaderContents/   ← 상단 헤더 (제목/브레드크럼)
  ├── HeaderSubContents/ ← 헤더 서브 메뉴
  ├── HeaderActionBar/  ← 헤더 우측 액션 버튼
  ├── Drawer/           ← 우측 서랍 전체
  └── AdminDrawerHost/  ← 관리자용 서랍 호스트
```

---

## Pinia 스토어 역할 요약

| 스토어 파일 | 담당 데이터 |
|------------|------------|
| `userProfile.ts` | 로그인 사용자 (agent, company) |
| `user.ts` | 사용자 기본 정보 (이름, 계정, 회사ID 등) |
| `userList.ts` | 상담원 목록(agents), 관리자 목록(admins) |
| `centerTeamPart.ts` | 센터/팀/파트 조직 구조 |
| `coaching.ts` | 코칭 목록, 코칭 요청 |
| `chatData.ts` | 채팅 메시지, 활성 상담원 |
| `notice.ts` | 공지사항 (팝오버, 대시보드) |
| `callHistory.ts` | 최근 통화 이력 |
| `bookmark.ts` | 북마크 / 북마크 그룹 |
| `memo.ts` | 메모 / 메모 그룹 |
| `todoList.ts` | 할 일 목록 |
| `favorites.ts` | 관심 상담원, 관심 콜 |
| `keywordDetect.ts` | 키워드 감지 설정 |
| `settings.ts` | 개인 설정 |
| `agentStatus.ts` | 상담원 상태 (AVAILABLE/BUSY 등) |
| `auth.ts` | 메뉴 권한, 라우트 목록 |

---

## Mock 데이터 규칙

- **중앙 주입 파일:** `src/shared/lib/MockInitializer.ts`
- `initMockData()` 가 `app.mount()` 직전에 실행되어 스토어에 데이터 주입
- **현재 Mock 사용자:** 홍길동 / `role: "AGENT"` → 상담원 화면으로 진입
- **역할 변경:** `MOCK_USER.role = "ADMIN"` → 관리자 화면으로 변경

```
현재 Mock 데이터:
  MOCK_AGENTS       : 상담원 8명 (다양한 상태)
  MOCK_COACHINGS    : 코칭 3건
  MOCK_CHAT_CONTENT : 채팅 메시지 9개
  MOCK_NOTICES      : 공지사항 3개
  MOCK_CENTER_TEAM_PART : 센터 2개, 팀 3개
```

---

## 공통 컴포넌트 (전역 등록)

```
Element Plus  → el-card, el-button, el-input, el-table, el-dialog 등 (import 불필요)
El Icons      → <Phone />, <User />, <ArrowRight /> 등 (import 불필요)
HeaderContents, HeaderSubContents, DevExtremeGrid, ButtonContents (전역 등록됨)
```

---

## 슬래시 명령어 안내

작업 유형에 따라 아래 명령을 실행하면 Claude가 상세 가이드를 받습니다:

| 명령 | 언제 사용 |
|------|----------|
| `/ui-pages` | 특정 페이지의 컴포넌트 구성을 알고 싶을 때 |
| `/ui-components` | 공통 컴포넌트 목록과 사용법이 필요할 때 |
| `/ui-feature-guide` | 새 기능을 어느 파일에 만들어야 할지 모를 때 |
| `/ui-mock-data` | mock 데이터를 추가/수정할 때 |
