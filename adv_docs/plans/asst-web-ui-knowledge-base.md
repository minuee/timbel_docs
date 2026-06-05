# asst-web-ui 비개발자 인수인계: 지식베이스 구축 계획

## 목표

비개발자가 Claude에게 "이 기능 추가해줘" 라고만 해도 Claude가 스스로
어느 파일을 열어야 할지, 어떤 컴포넌트를 써야 할지, mock 데이터는 어디에
넣어야 할지 판단할 수 있도록 **컨텍스트 자동 로딩 체계**를 만든다.

---

## 핵심 설계 원칙

1. **자동 로딩 우선** — 사용자가 "읽어봐" 라고 말하지 않아도 Claude가 알아야 할 것들
2. **계층 분리** — 항상 필요한 요약 vs 특정 작업 시만 필요한 상세
3. **명령어 기반 접근** — 비개발자가 `/ui-pages` 같은 슬래시 명령으로 Claude에게 상세 컨텍스트 주입

---

## 구성 계층

```
Tier 1 (항상 자동 로드)          → CLAUDE.md @-import
Tier 2 (작업별 슬래시 명령)      → .claude/commands/*.md
Tier 3 (Claude 기억)             → memory/ 파일
```

---

## Tier 1: 상시 자동 로드 — `adv_docs/asst-web-ui/PROJECT.md`

**위치:** `c:/git/work/advisor/adv_docs/asst-web-ui/PROJECT.md`
**로딩 방식:** CLAUDE.md에 `@adv_docs/asst-web-ui/PROJECT.md` 한 줄 추가

**포함 내용 (200줄 이내):**

```
1. 프로젝트 성격
   - asst-web-ui = UI 전용 프로젝트 (API 없음, mock 데이터 사용)
   - 실제 API 연결 없이 화면만 동작하는 데모/개발용
   - Mock 데이터 위치: src/shared/lib/MockInitializer.ts

2. 페이지 목록 (URL → 파일)
   - /advisor/consultant  → src/view/advisor/consultant/index.vue  (역할별 라우팅)
   - /advisor/admin       → src/view/advisor/admin/index.vue       (관리자 화면)
   - /advisor/agent       → src/view/advisor/agent/index.vue       (상담원 화면)
   - /advisor/admin/management/user → src/view/advisor/manage/group/index.vue

3. 핵심 스토어 → 역할 매핑
   - userProfileStore  : 로그인 사용자 정보 (mock: 홍길동/AGENT)
   - userListStore     : 상담원/관리자 목록 (mock: 8명)
   - noticeStore       : 공지사항 (mock: 3개)
   - coachingStore     : 코칭 데이터
   - chatDataStore     : 채팅 메시지

4. Mock 데이터 규칙
   - 모든 API는 { status: 204, data: null } 반환
   - 화면 데이터는 MockInitializer.ts에서 주입
   - 새 mock 데이터 추가 시 이 파일 수정
```

---

## Tier 2: 슬래시 명령 — `.claude/commands/`

**위치:** `c:/git/work/advisor/.claude/commands/`

Claude Code는 `.claude/commands/*.md` 파일을 `/파일명` 슬래시 명령으로 자동 등록한다.
비개발자가 작업 시작 시 필요한 명령을 실행하면 Claude가 상세 컨텍스트를 받는다.

### 생성할 명령 4개

---

### 📄 `/ui-pages` → `.claude/commands/ui-pages.md`

**목적:** 페이지별 상세 구조 설명. 새 화면/기능을 특정 페이지에 추가할 때 사용.

**포함 내용:**
```
각 페이지마다:
- URL 경로
- 역할 (누가 보는 화면인가)
- 주요 컴포넌트 목록 (파일 경로 포함)
- 현재 표시되는 데이터 (mock 기준)
- 이 페이지에서 사용하는 Pinia store 목록
- 관련 Drawer 패널 목록

예시:
## /advisor/agent (상담원 화면)
- 첫 진입: Dashboard.vue (공지/코칭/할일 요약카드)
- "오늘의 상담 준비" 클릭 후: Chat + Knowledge 패널
- 우측 Drawer: 북마크/메모/할일/공지/키워드 탭
- 사용 스토어: userProfileStore, coachingStore, noticeStore, callHistoryStore
```

---

### 📄 `/ui-components` → `.claude/commands/ui-components.md`

**목적:** 공통 컴포넌트 사용법. 새 UI 요소 추가 시 참조.

**포함 내용:**
```
## shared/ui 공통 컴포넌트
| 컴포넌트 | 경로 | 용도 | 사용법 예시 |
|---------|------|------|------------|
| ECPButton | @/shared/ui/button | 버튼 | <ECPButton variant="primary"> |
| Loading | @/shared/ui/Loading | 로딩 스피너 | <Loading v-if="isLoading" /> |
| DevExtremeGrid | @/shared/ui/devExtreme | 데이터 그리드 | ... |
| TreeComponent | @/shared/ui/TreeComponent | 트리뷰 | ... |
| ...

## 레이아웃 컴포넌트
| 컴포넌트 | 경로 | 용도 |
|---------|------|------|
| ContentLayout | @/widgets/layout/ContentLayout | 페이지 기본 레이아웃 |
| Drawer 시스템 | @/widgets/layout/Drawer | 우측 서랍 패널 |

## Element Plus 컴포넌트 (이미 전역 등록)
- el-card, el-button, el-input, el-table, el-dialog 등
- 별도 import 없이 바로 사용 가능
```

---

### 📄 `/ui-feature-guide` → `.claude/commands/ui-feature-guide.md`

**목적:** 특정 기능을 만들거나 수정할 때 "어디를 봐야 하는지" 안내.

**포함 내용:**
```
## 기능 유형별 작업 위치

### 새 Drawer 패널 탭 추가
1. 탭 UI: src/widgets/layout/Drawer/index.vue
2. 탭 컨텐츠: src/widgets/layout/Drawer/components/[NewFeature]/
3. 데이터: src/app/stores/modules/[newFeature].ts 신규 생성
4. Mock: MockInitializer.ts에 초기 데이터 주입

### 대시보드 카드 추가
1. 파일: src/view/advisor/agent/Dashboard.vue
2. 데이터: 관련 store에서 computed로 가져옴
3. Mock: MockInitializer.ts 또는 해당 store 초기값

### 상담원 목록에 컬럼/필드 추가
1. ConsultantDrawer: src/view/advisor/components/ConsultantDrawer/index.vue
2. ConsultantCard: src/view/advisor/components/ConsultantDrawer/ConsultantCard.vue
3. Mock 데이터: MockInitializer.ts → MOCK_AGENTS 배열

### 관리자 코칭 기능 수정
1. 코칭 패널: src/widgets/layout/Drawer/components/AdminCoaching/
2. 코칭 스토어: src/app/stores/modules/coaching.ts
3. Mock: MockInitializer.ts → MOCK_COACHINGS

### 공지사항 관련 수정
1. 공지 Drawer: src/widgets/layout/Drawer/components/Notice/
2. 대시보드 공지카드: src/view/advisor/agent/Dashboard.vue (latestNotices computed)
3. 공지 스토어: src/app/stores/modules/notice.ts
4. Mock: MockInitializer.ts → MOCK_NOTICES

### 새 페이지(라우트) 추가
1. 뷰 파일 생성: src/view/advisor/[new-page]/index.vue
2. 메뉴 등록: src/shared/api/modules/menus/mockupMenuList.ts에 항목 추가
3. 자동으로 라우터에 등록됨 (dynamicRouter.ts가 view/ 폴더 스캔)
```

---

### 📄 `/ui-mock-data` → `.claude/commands/ui-mock-data.md`

**목적:** Mock 데이터 구조 설명. 데이터 추가/수정 시 참조.

**포함 내용:**
```
## Mock 데이터 중앙 관리 파일
위치: src/shared/lib/MockInitializer.ts

## 현재 Mock 데이터 목록
- MOCK_USER: 로그인 사용자 (홍길동, AGENT 역할)
- MOCK_COMPANY: 소속 회사 정보
- MOCK_AGENTS: 상담원 8명 (다양한 상태: AVAILABLE, BUSY, OFFLINE 등)
- MOCK_CENTER_TEAM_PART: 센터(2개) + 팀(3개) 조직 구조
- MOCK_COACHINGS: 코칭 3건
- MOCK_CHAT_CONTENT: 채팅 메시지 9개 (고객↔상담원↔AI)
- MOCK_NOTICES: 공지사항 3개 (긴급 1개, 일반 2개)

## Mock 사용자 역할 변경 방법
MOCK_USER.role = "ADMIN" → 관리자 화면으로 진입
MOCK_USER.role = "AGENT" → 상담원 화면으로 진입

## 새 Mock 데이터 추가 패턴
1. MockInitializer.ts 상단에 const MOCK_XXX = [...] 추가
2. initMockData() 함수에서 해당 store에 주입
3. store에 해당 데이터를 받는 action이 없으면 신규 생성

## API 동작 방식
- 모든 API: { status: 204, data: null } 반환 (no-op)
- status === 200 체크 코드 → 실행 안 됨 (정상)
- 데이터는 항상 MockInitializer.ts에서만 제공
```

---

## Tier 3: Claude 기억 — Memory 파일

**위치:** `~/.claude/projects/c--git-work-advisor/memory/`

### 추가할 memory 파일: `project_asst_web_ui.md`

```markdown
---
name: asst-web-ui 프로젝트 컨텍스트
description: asst-web-ui UI 전용 프로젝트의 핵심 파일 위치 및 작업 방식
type: project
---

asst-web-ui는 c:/git/work/advisor/asst-web-ui/에 위치한 Vue 3 UI 전용 프로젝트.
API 없이 MockInitializer.ts로 데이터를 주입하는 데모/개발용 빌드.

**슬래시 명령어:**
- /ui-pages: 페이지별 컴포넌트 구조
- /ui-components: 공통 컴포넌트 목록
- /ui-feature-guide: 기능 구현 위치 가이드
- /ui-mock-data: mock 데이터 구조 및 수정 방법

**Why:** 비개발자 인수인계 후 Claude가 매 세션마다 이 명령어들을 안내할 수 있도록
```

---

## CLAUDE.md 수정 계획

현재 CLAUDE.md에 없는 `asst-web-ui` 관련 내용을 추가:

```markdown
## asst-web-ui (UI 전용 프로젝트)

@adv_docs/asst-web-ui/PROJECT.md

작업 시작 전 `/ui-pages`, `/ui-components`, `/ui-feature-guide` 명령 참고.
```

단, 현재 CLAUDE.md가 전체 모노레포 대상이므로 asst-web-ui 섹션은
조건부로 간략하게만 추가 (3~5줄).

---

## 구현 순서 (Task 목록)

### Task 1: 디렉토리 생성
```
mkdir -p c:/git/work/advisor/adv_docs/asst-web-ui
mkdir -p c:/git/work/advisor/.claude/commands
```

### Task 2: PROJECT.md 작성
파일: `adv_docs/asst-web-ui/PROJECT.md`
- 실제 파일 경로 확인하며 작성 (페이지 URL ↔ 파일 매핑)
- 스토어 목록 및 역할 요약

### Task 3: 슬래시 명령 4개 작성
파일들: `.claude/commands/ui-*.md`
- 각 파일은 Claude가 읽을 마크다운
- 실제 코드 스니펫과 파일 경로 포함

### Task 4: Memory 파일 작성
파일: `~/.claude/projects/c--git-work-advisor/memory/project_asst_web_ui.md`
- 명령어 안내 포함

### Task 5: CLAUDE.md에 @-import 추가
- `@adv_docs/asst-web-ui/PROJECT.md` 한 줄 추가
- 슬래시 명령 안내 3줄 추가

### Task 6: 검증
- 새 세션에서 "asst-web-ui 프로젝트에서 대시보드 카드를 추가하려면?" 질문
- Claude가 올바른 파일 위치를 안내하는지 확인

---

## 비개발자 사용 시나리오

```
비개발자: "공지사항 목록에 작성자 이름도 보여줬으면 좋겠어"

Claude (자동으로):
1. PROJECT.md에서 noticeStore 위치 확인
2. /ui-feature-guide의 "공지사항 관련 수정" 섹션 참조
3. Notice Drawer 컴포넌트와 Dashboard 공지카드 위치 파악
4. MockInitializer.ts의 MOCK_NOTICES에 author 필드 추가 필요 확인
5. 작업 시작
```

---

## 파일 크기 목표

| 파일 | 목표 줄수 |
|------|---------|
| adv_docs/asst-web-ui/PROJECT.md | ~150줄 |
| .claude/commands/ui-pages.md | ~150줄 |
| .claude/commands/ui-components.md | ~120줄 |
| .claude/commands/ui-feature-guide.md | ~200줄 |
| .claude/commands/ui-mock-data.md | ~80줄 |

총 약 700줄 — 슬래시 명령별로 필요 시만 로드하므로 한 번에 context를
전부 소비하지 않음.
