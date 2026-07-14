# 어드바이저 리뉴얼 — 설계 브레인스토밍 정리

> 상태: **브레인스토밍 / 머릿속 정리 단계** (코드 미조사, 순수 개념 논의)
> 다음 단계: 화면기획자와 논의 → 방향 결정
> 작성 계기: 디자인 리뉴얼 예정 → 이 기회에 멀티테넌트/SI 파편화 대응 구조를 함께 심을지 고민

---

## 0. 이 문서의 목적

어드바이저(상담사 지원 어시스턴스 웹) **디자인 리뉴얼**을 앞두고,
UI뿐 아니라 **전체 구조를 어떻게 가져갈지** 설계적으로 미리 정리한다.
(아직 확정 아님. 기획자 논의 전 사고 정리용.)

---

## 1. 배경 — 근본 고민: 멀티테넌트 vs SI 파편화

- 어드바이저 = 우리 회사 **솔루션 플랫폼**. 원래는 **멀티테넌트 SaaS** 구조
  (고객사별 DB/데이터는 분리, **코드·구조는 공통**이 정석).
- 현실: **고객이 갑** → 요구 들어주다 보면 고객사마다 구조가 갈라짐 → 공통 플랫폼이
  **SI(고객사별 커스텀)** 처럼 파편화되는 딜레마.
- **리뉴얼은 이 파편화를 "감당 가능한 형태로 가둘" 드문 기회** (평소엔 "돌아가는 걸 왜 건드려" 소리 듣는 작업).

### 파편화를 가두는 3가지 방향
1. **설정으로 밀어냄** — 차이를 config/feature-flag/테넌트 설정으로 흡수 (on/off·라벨·순서). 동작 자체가 다른 요구는 못 막음.
2. **구조로 가둠** — 공통 코어 고정 + 차이는 **정해진 슬롯(오버라이드)** 에만 허용.
3. **브랜치/빌드로 분리** — 최후수단. 유지보수 지옥.

→ 이번 리뉴얼 지향: **1 + 2의 결합** (런타임 설정 + 구조적 확장 포인트).

---

## 2. 확정된 관점 (사용자 기준)

- **세계관 1 — "채팅(상담)이 왕"**: 어드바이저의 본질은 상담 작업대. 나머지는 주변부.
  - GNB 시안에서 채팅이 다른 메뉴와 평평하게 놓여 있어도 → **해석 A 확정**:
    메뉴 위치만 평평할 뿐, 들어가면 **채팅은 여전히 압도적으로 큰 작업대(왕)**. 격하 아님.
- **현재 실제 구조**: 사실상 **대시보드 + 상담(채팅)페이지 2개**가 진입점. 세부 기능들은 그 안에서 **모달**로 노출.
- **현 구조 나쁘지 않다는 판단**. 리뉴얼은 뒤엎기가 아니라 **확장**에 가까움.

### 기획자가 하려는 것의 본질
- 세부 메뉴 세분화(대시보드/이력/북마크/메모/할일/공지…)는 **기획자 안**.
- 핵심: **모달을 페이지로 "교체"하는 게 아니라, 모달은 그대로 두고 페이지(라우트)가 "추가"되는 구조.**
  - 같은 기능을 → 상담/대시보드 안 **모달로도** 열고, **독립 페이지(URL)로도** 진입. **둘 다 공존.**

---

## 3. 기획자 GNB 시안 분석 (`docs/advisor_new_gnb_menu.png`, 상담사 메뉴 기준)

3그룹 구성:

| 그룹 | 항목 | 성격 |
|---|---|---|
| **워크스페이스 (3)** | 대시보드 / **채팅(통화중)** / 통화이력 | 채팅=왕(작업대). 대시보드·이력은 주변 |
| **내 도구 (4)** | 북마크 / 메모 / 할일 / 공지사항 | 상담 중에도 뜨는 공용 기능이 독립 메뉴로 승격 |
| **코칭·설정 (3)** | 코칭 / 감지어 보기 / 설정 | 상담 안 기능 + 관리 기능의 독립화 |

- 각 메뉴에 **즐겨찾기 별(★)** + **숫자 배지**(공지 6, 코칭 3 등).
- (관리자 메뉴는 이번 논의에서 제외)

### 시안이 증명하는 것
독립 메뉴 항목들은 대부분 **채팅 작업대 안에 이미 존재하는 기능의 "독립 얼굴"**:

```
북마크(메뉴)   ↔  통화 중 북마크 저장
메모(메뉴)     ↔  통화 중 고객 컨텍스트 메모
할일(메뉴)     ↔  상담 중 자동 Todo 생성
코칭(메뉴)     ↔  상담 중 코칭 알림/요청
감지어(메뉴)   ↔  상담 중 실시간 키워드 감지
통화이력(메뉴) ↔  (상담 종료본)
```

→ 리뉴얼은 "새 기능 7개 제작"이 아니라 **채팅 안에 뭉친 능력들을 밖으로 꺼내 독립 진입점을 달아주는 것.**

---

## 4. 핵심 구조 원칙 (오늘 도출)

### 원칙 ① 코어 1벌 + 껍데기 N벌 (필수 전제)
같은 기능이 모달에도·페이지에도 있게 되므로, **기능 알맹이(로직·상태·데이터)와 껍데기(모달/페이지)를 분리**해야 함. 안 하면 복붙 2벌 → 커스텀 하나 들어올 때마다 여러 곳 수정 = 지옥.

```
[기능 코어]  ← 진짜 내용물(데이터·상태·동작) 딱 1벌 (고객사 커스텀도 여기 한 곳)
   ├── 껍데기 A: 모달  (상담/대시보드 안)
   └── 껍데기 B: 페이지 (독립 URL, 라우트 가드·on/off 부착)
```
- 코어는 한 벌, 껍데기는 얇게. 껍데기는 "어디에 담아 보여줄지"만 담당.

### 원칙 ② 기능(capability) 1개 : 노출지점(placement) N개
- on/off는 **화면마다 따로 끄는 게 아니라, 기능 단위로 끄고 여러 노출지점이 그 스위치를 구독**.
- 이게 "껐는데 딴 데서 살아있는" 죽은 토글 사고(현 repo에 실제 존재)를 구조적으로 제거.

### 원칙 ③ 2단 필터 — 테넌트 층 × 사용자 층
GNB의 별표(★)가 새 축을 염. 두 층을 반드시 구분:
- **테넌트 층 (고객사)**: 이 고객사가 어떤 메뉴/기능을 *쓸 수 있나* — on/off·권한. 관리자가 정함.
- **사용자 층 (상담사 개인)**: 쓸 수 있는 것 중 *즐겨찾기/순서/배지* — 개인 취향.

```
전체 메뉴 → [테넌트 필터: 고객사 허용?] → [사용자 필터: 즐겨찾기/순서] → 최종 노출
```
- **순서 중요: 테넌트가 먼저 자르고, 그 다음 개인 취향.** (안 그러면 "끈 메뉴를 개인이 즐겨찾기"한 모순)

### 원칙 ④ 라우트 = 제어 경계
모달은 테넌트 제어에 최악, 페이지(라우트)는 최적:

| | 모달 | 페이지(라우트) |
|---|---|---|
| on/off | 여는 버튼을 여기저기서 숨겨야(누락 쉬움) | 라우트 하나 막으면 끝 |
| 권한 게이트 | 열 때마다 코드 체크 | 라우트 가드 한 곳 |
| 지연 로딩 | 상담페이지에 다 얹혀 무거움 | 페이지별 lazy-load |
| 딥링크 | 불가(URL 없음) | 가능 |

→ 기획자의 "페이지 추가"는 UI 취향처럼 보이지만, 실은 **테넌트 on/off·권한의 그릇을 공짜로 깔아주는 변화**. 라우트 = 권한경계 = on/off단위 = 로딩경계가 한 줄로 정렬됨.

### 원칙 ⑤ on/off 단위 = 그룹 + 개별 2단
GNB 그룹 헤더(워크스페이스/내도구/코칭·설정)를 **기능 그룹 단위**로 활용 가능.
- 예: 고객사 A는 "코칭·설정" 그룹 통째 off / B는 "내 도구" 중 메모만 off.
- **그룹 단위 on/off + 개별 항목 on/off** 2단 제어.

---

## 4-1. 포털 경계 (분석 확정) — GNB는 우리 소유 아님

- 바깥 **3단 GNB(ECP 포털 셸)** 자체는 **포털 소유**. asst-web은 그 안에 끼워지는 앱(오른쪽 콘텐츠 영역만 그림).
  - 현재 포털은 asst-web을 굵은 덩어리 하나("상담어드바이저")로만 앎. 내부 대시보드·채팅·이력은 asst-web 안 모달/섹션.
- **포털이 일괄 소유:** 로그인 · 토큰(발급/갱신) · **메뉴 권한**.
  → 우리가 브레인스토밍한 **테넌트 층 on/off·권한의 소유자 = 포털**. 우리는 그 스위치를 **소비**하는 쪽.
- 앞선 "모델 A(포털이 메뉴 소유) vs B(우리 내부 네비)" → **A로 사실상 확정.**
- **우리(asst-web) 책임 범위:** 메뉴가 가리키는 **개별 페이지/기능의 알맹이** + 그것들이 **라우팅·재사용 가능하고 진입점(모달/딥링크)을 갖게** 하는 것. (코어1벌+껍데기N, 라우트=제어경계, 사용자층 즐겨찾기는 여전히 우리 영역)
- **기획자에게 설명할 이해관계(나중):** 세분화 메뉴판·메뉴 on/off·권한은 **포털 관장**이라 asst-web이 임의로 못 만든다. 우리는 **페이지와 진입 경로**를 책임진다. → 메뉴 구성 변경은 **포털팀 협의 전제**.

## 5. 리뉴얼 실제 난이도의 관건

- 난이도는 "페이지를 추가하는 것"이 아니라 **지금 모달 안에 로직·상태가 얼마나 엉겨붙어 있느냐**.
  - 이미 "얇은 껍데기 + 분리된 로직" 이면 → 페이지 추가는 껍데기 하나 더 얹기. 쉬움.
  - 모달 안에 데이터 로딩·상태·동작이 다 박혀 있으면 → **코어 먼저 떼어내는 작업**이 선행 = 리뉴얼의 실제 공수.
- → **다음 조사 대상**: 통화이력 모달(ChatHistoryModal), 상담요약 팝오버 등의 로직이 store/composable로 빠져 있는지 vs 컴포넌트에 박혀 있는지. (오늘은 코드 미조사)

---

## 6. 다음 단계 / 남은 논의거리

- [ ] **A. 현황 진단** — 어드바이저/관리자 안 기능 인벤토리 작성 후 (화면모듈 / 채팅내 기능 / 공용기능)으로 분류. (코드 조사 필요, 요청 시 착수)
- [ ] **B. 목표 구조** — 코어/껍데기 분리 골격, 테넌트 config 스키마(메뉴 on/off·권한·순서) 설계.
- [ ] **C. 터진 사례** — 실제 고객사 커스텀으로 아팠던 구체 사례 수집 → 원칙 검증.
- [ ] 채팅=왕 유지하면서 "상담 중에도 필요한 기능(할일·메모·북마크)"의 노출 정책 확정 (이중 노출 기본).
- [ ] 테넌트 config를 서버에서 내려받는 런타임 방식으로 확정 (빌드타임 아님).
- [ ] 기획자와 세계관 1(채팅=왕) 의도 정렬 확인.

---

# 7. 구현 진행 내역 (2026-07-06 착수) — 공통 기반 구축 완료

> 방식: **껍데기(뷰)만 새로 만들고, 알맹이(store/api/plugin)는 기존 코어 재사용(복제 금지)**.
> 위치: 모든 리뉴얼 뷰는 `src/view/advisor-renual/` 아래로 격리(안전). 기존 상담사/관리자 화면 미수정.
> 배포 목업 UI(참고): `http://13.209.195.192:32010/asst-web-ui/#/agent/<기능>` (인증없음).

## 7-1. 폴더/파일 구조 (신규)
```
src/view/advisor-renual/
  index.vue                     # 허브(3그룹 nav 콘텐츠) — 현재 라우트 미연결(참고용, 놔둠)
  <기능>/index.vue              # 리프 10개 껍데기
  components/RenualPageHeader.vue        # 공통 헤더
  composables/useAdvisorBootstrap.ts     # 진입 부트스트랩
  composables/useRenualMenuBadges.ts     # 메뉴 뱃지 code→count 매핑
```
리프 10개 slug: `dashboard, chat, call-history / bookmark, memo, todo, notice / coaching, detect-word, settings`
(주의: chat 메뉴명은 "상담화면"으로 변경됨)

## 7-2. 메뉴/라우팅 (플라이아웃 3뎁스 = gnb_menu.png)
- `src/api/modules/menus/mockupMenuList.ts`: 94(리뉴얼) routePath `advisor-renual` + **자식 트리 추가** — 그룹3(951 워크스페이스/952 내도구/953 코칭·설정) → 항목10. code=`RENUAL_*`.
- `src/api/modules/menus/mockupMenu.ts`: `makeMenuOfTree` **4뎁스 루프 추가**(기존 3뎁스 한계 → 94>그룹>항목 4뎁스 지원). 기존 메뉴 무영향.
- `src/stores/modules/auth.ts`: `buildMenuItem` 의 `isHide: false` 하드코딩 → `rawItem.isHide ?? false`(하위호환).
- 렌더: 공용 `src/layouts/components/Menu/NewSubMenu.vue` three-depth 그룹렌더가 그대로 그림.
- 라우팅 근거: 라우트 가드(routers/index.ts:68)가 flatMenuList 에 있는 path만 통과 → 메뉴 등록 필수.

## 7-3. 공통 헤더 `RenualPageHeader.vue`
- 왼쪽=브레드크럼(그룹›페이지)+타이틀 / 오른쪽=이름 | 상태 | 알림.
- 재사용 코어: 이름 `userProfileStore.agent.name` / 상태 `agentStatusStore`(변경 드롭다운까지 실동작) / 알림=아이콘만(모달 미연결, 뱃지는 옵션 prop).
- ※ `alertStore` 는 파손 import(`ecp/systemNotice` 없음) 있어 **직접 구독 안 함**.
- props: `group`, `title`(페이지별 명시), `alertCount?`.

## 7-4. 부트스트랩 `useAdvisorBootstrap.ts` (세션 1회 멱등)
리뉴얼 직접진입/새로고침 대비. 헤더 onMounted 에서 `ensureBootstrapped()` 호출.
1) `initApi()` — **미초출 시 getClient throw 하던 근본원인 해결**(consultant 외 진입점 없었음)
2) `initSocket()+connect()` — 소켓(실시간 상태용)
3) `getUser()`→`setUserProfile`(없을 때만) — 이름·cc_cti_id
4) `setupAgentStatusListener()` — agent-status 룸 join, 실시간 상태 수신
5) 메뉴 뱃지 카운트 로드(role별): 공지 `fetchUnreadNotices`(상담사만) / 코칭 `refreshCoachings(isAdmin)` / 할일 `refreshTodoList(이번달)`(상담사만)
- role 판정: `agent.role === "AGENT"` = 상담사.

## 7-5. 메뉴 unread 뱃지 (공지/코칭/할일)
- `useRenualMenuBadges.ts`: `badgeForCode(code)` — 스토어 **읽기만**(API/initApi 없음).
  - `RENUAL_NOTICE`→상담사 `noticeStore.unreadCount`
  - `RENUAL_COACHING`→상담사 `unReadCoachingCount` / 관리자 `unReadRequestCount`
  - `RENUAL_TODO`→상담사 `remainingTodoCount`
- `NewSubMenu.vue`: 3뎁스 아이템 타이틀에 빨간 뱃지 `v-if badgeForCode>0` + `.renual-unread-badge` 스타일.
- **타이밍**: 카운트는 리뉴얼 페이지 1회 진입(부트스트랩) 후 채워짐 → 그 세션 내내 뱃지 유지.
- 대상 3개뿐(나머지 나중). 새 대상은 `useRenualMenuBadges` case + 부트스트랩 로드만 추가.

## 7-6. 공지 unread 스토어 연결 (첫 적용) + 버그픽스
- `notice.ts`: 액션 `fetchUnreadNotices(userKey)`(응답배열→id만) + getter `unreadCount` 신규. (기존엔 `getUnreadNoticeList` 정의만 있고 미사용이었음)
- **버그픽스** `notice.api.ts`: `NOTICES_INTERNAL` 프리픽스 `PREFIX`(`/asst/v1`, /api 누락→404) → **`API_PREFIX`(`/api/asst/v1`)** 로. unread/reads 계열 전부 정상화(기존 조용히 404였음). readNotice(읽음처리)도 이제 실동작.

## 7-7. 리프 구현 현황

### 상태 마커 범례 (2026-07-09 정리)
| 마커 | 뜻 | 판정 기준 |
|---|---|---|
| ✅ | 완료 | 화면의 모든 항목이 실동작. 남은 건 "확장/개선" 뿐 |
| 🟡 | **일부 미완료** | 화면에 **회색 `· 미구현` 표기가 실제로 떠 있음**. 값이 `—`/`[MOCK]` 플레이스홀더거나 저장이 안 되는 항목이 섞여 있음 |
| 🔵 | 구현중 | 아직 작업 진행 중 |
| ⬜ | 미착수 | 스캐폴드만 |

- **🟡 판정은 문서가 아니라 코드 기준**: `grep -rn "미구현\|\[MOCK\]" src/view/advisor-renual/` 로 확인.
- 현재 🟡 = **대시보드 / 설정 / 통화이력 3개.** (2026-07-13)
- 두 페이지의 표기용 클래스명이 다름: 대시보드 `card__wip` / 설정 `settings__todo`. 실연동 시 각 파일에서 해당 `<span>` + 플래그(`uiOnly`)/`[MOCK]` 블록을 함께 제거.

### 🟡 일부 미완료 현황 (한눈에)
| 페이지 | 미구현 항목 | 막고 있는 것 |
|---|---|---|
| 대시보드 | ④ 이슈어 Top5 / ⑤ 자주 하는 질문 Top5 | 감지 이력 집계 없음(§8-1) / FAQ 집계 없음 |
| 대시보드 | ⑦ KPI 중 평균 긍부정 · 1차 해결률 | 집계 API 없음 (응대 수·평균 응대 시간은 실연결됨) |
| 설정 | 공지 도착 알림 / 통화 종료(wrap-up) 알림 | 대응 로직·백엔드 없음 (로컬 state 만 토글) |
| 설정 | 소리 3종 (전체/코칭/SOS) | 〃 |
| 설정 | 발화 자동 스크롤 / 코칭 위스퍼 음성 | 〃 (위스퍼는 센터 정책 의존) |
| 설정 | 단축키 5개 | 실제 동작하는 건 `Ctrl+F`(헤더 메뉴검색) 하나뿐 — 표는 안내용 |
| 통화이력 | 통화 결과(완료/이관/콜백) | 필드 자체가 없음 → DB 설계 신규(§8-2) |
| 통화이력 | 감지어 N건 | 감지 이력 미저장(§8-1) |
| 통화이력 | (참고) 인입유형·의도 | 미구현 아님 — 값 적재만 되면 자동 표시(코드 준비 완료) |

### ✅ 공지사항 (완료, 2026-07-06)
- 파일: `src/view/advisor-renual/notice/index.vue`
- 목록 **lazy 페이징**(`fetchNoticesPaged(page,10)`, `hasNext` true일 때만 바닥 근처서 append)
- **아코디언**(openId 단일 — 하나 열면 나머지 닫힘)
- 본문 **HTML**(`v-html`, 신뢰 콘텐츠 가정) — `collapsed`(max-height≈5줄) + 넘칠 때만 [전체보기]/[접기]
- **읽음처리**: 토글 열 때마다 `markNoticeReadByDetail(id, agent.id)` → `GET /api/asst/v1/notices/{id}?user_key=`(멱등). isNew 가드 없음(unread 로드 레이스 대비). → 빨간점 제거 + 메뉴 뱃지 실시간 감소.
- 유형뱃지 긴급(빨강)/일반, 상대시간, "미확인 N건".
- 코어 추가분: `notice.ts` 의 `fetchNoticesPaged` / `markNoticeReadByDetail` / getter `unreadCount`.

### 🔵 상담화면 chat (구현중, 2026-07-07) — 하이브리드(복사 후 UI 리뉴얼)
> 공지사항과 다른 패턴. 상담화면은 실시간(소켓/assist-stream/VOC/감지어)이 커서, **기존 컴포넌트를 복사**해 UI만 리뉴얼하고 로직/composable/store는 원본 재사용(원본 무수정).

**신규 파일 (`src/view/advisor-renual/chat/`):**
- `index.vue` — 부모 오케스트레이터: `advisor/agent/index.vue` 상담뷰 배선(Chat emit 4종→로컬ref→Knowledge props, detailItemClick 등) 발췌 재현. 식별자=userProfileStore(cc_cti_id/assigned_workspace_id/botId). onMounted ensureBootstrapped()+refreshKeywordDetect(), onUnmounted vocStore.clear().
- `components/ChatRightRail.vue` — 우측 아이콘 레일 6개(코칭요청/콜이력/메모/북마크/할일/설정). 아이콘만, hover=테마색. **모달 연동은 나중**(지금 붙이면 기존 모달과 꼬임).
- `components/RenualChatPanel.vue` — 상담내용(원본 `chat/index.vue` 복사). import 전부 `@/` 절대라 SpeechBubble/composable/store 원본 재사용.
- `components/RenualKnowledgePanel.vue` — 지식저장소(원본 `knowledge/TabTypeKnowledgeIndex.vue` 복사, 상대경로 8개 절대화).
- `components/RenualDocumentCard / RenualDocumentContentPanel / RenualDocumentDetailView / RenualContentCollapse(재귀).vue` — 지식 하위 4개 복사, 상호참조 복사본끼리 연결.

**핵심 구조 이해:**
- 지식저장소 = 탭 2종. `chat` 탭(발화 지식정보 클릭)=AI답변+상세 바로(리스트X) / `search` 탭(검색)=AI답변+DocumentCard목록→클릭 시 상세. 상세는 **공통 `DocumentContentPanel`** (검색·발화 양쪽 동일) → 한 번 리뉴얼로 둘 다 커버.
- 상세뷰 전환/뒤로가기 = 조건부렌더(`searchSelectedDoc` v-if/v-else, `=null` 인라인). 원본보기=`provide/inject(openOriginalViewer)`. 북마크=`ContentCollapse` 내부 `bookmarkStore`.

**완료:**
- 4등분 레이아웃(하나의 카드: 공유보더+바깥4모서리radius+가운데세로선+제목아래 전체폭 가로선+제목영역 44px 통일)
- 헤더 아이콘 forum/menu_book(색=info), VOC 헤더 반응형(nowrap 고정 높이+스파크라인만 축소)
- 상담원 말풍선 배경 `--color-primary-10`(테마)
- 지식: 검색input(radius6·포커스 테마색), AI요약 박스 테마색+"AI 요약" 라벨, 탭(하단 2px `--color-primary` 밑줄), 탭영역 꽉참(음수마진-20)+분리선(탭 있을때만)+여백(탭위3px·탭↔AI 20px)+AI/문서 padding 2배

**3번 상세 UI — 헤더 1줄 통합 (✅ 완료, 2026-07-07):**
> 최종 확정: 목업(`new_knowledge_1/2.png`)대로 **본문은 섹션 아코디언 없이 한 덩어리 연속(flat)**, 문서 헤더 우측 = **북마크 | 원본보기 | 토글** 3버튼. (섹션은 "여러 개 흔함"이라 아코디언 대신 연속 렌더로 결정)
> - **A. `RenualDocumentDetailView.vue`**: 헤더 우측에 북마크(문서 단위)·토글(본문 전체 접기 `isBodyCollapsed`) 추가, 원본보기 유지. 북마크 로직 일체(store/API/모달2개)를 ContentCollapse→여기로 이동. 식별자 `document_id ?? String(id)`, `content_type = doc_type.name==="지식정보"?2:1`. 본문은 `v-for ContentCollapse :flat="true"` 를 `v-show="!isBodyCollapsed"` 로 감쌈.
> - **B. `RenualContentCollapse.vue`**: `flat` prop 신규(기본 false, 하위호환). flat=true면 섹션헤더(제목+북마크+토글)·카드보더·패딩 제거하고 본문(ToastEditor)만 항상 노출, children도 flat 재귀. `contentString` 로직 재사용(복제X).
> - IDE 진단 0. **⚠️ 라이브 확인 필요**: 섹션 제목이 `outline.title`에만 있고 본문엔 없는 문서면 flat에서 제목이 사라질 수 있음 → 문서 하나 열어 제목·본문 정상 노출 확인. (이상하면 flat에 "섹션 제목 인라인" 한 줄 추가)
> - **수정1 (2026-07-07): 북마크 pill 적용** — 목업대로 `☆ 북마크`/`★ 북마크됨` 텍스트 pill(별 아이콘 `star`+`:filled`). 활성색 = **테마 `--color-primary`**(하드코딩X, 연퍼플 배경+퍼플 테두리), 미활성 = g40 별+g20 테두리. 원본보기·토글은 아이콘 유지(사용자 확정: 북마크만 pill). `.bookmark-pill` 스타일 신규.
> - **수정2 (2026-07-07): 토글 버그픽스** — 본문 감춤 `v-show` → `v-if`. 원인: 글로벌 `.flex{display:flex !important}`(global.scss:297)가 v-show의 `display:none`을 눌러 안 숨겨졌음.
>
> **⭐ 최종 상태 (2026-07-07 확정 — 위 수정1/2 이후 추가 변경, 이게 현재 코드):**
> - **토글 제거됨**: 문서상세 헤더에서 토글은 "테두리 남고 내용만 사라져 의미없음" → 제거. `isBodyCollapsed` ref·`v-if` 감쌈 전부 삭제. **본문 항상 노출.** → 헤더 우측 = **북마크 pill + 원본보기 아이콘** 2개만 (토글 없음).
> - **`RenualDocumentDetailView.vue` 헤더 바(`.detail-header`)**: 배경 `--color-primary-10`(AI요약과 동일) + `border-bottom: 1px solid --color-primary-15`. 음수마진 bleed(`margin:-8px -16px 0; padding:8px 16px`)로 카드 좌우 끝까지 채우되 **제목 가로위치는 원래 그대로**(안으로 안 밀림). 카드 outer 에 `overflow-hidden` 추가(상단 라운드 유지). ※ 처음에 full `border`(4면)로 했다가 카드 테두리와 이중선 되어 **border-bottom만**으로 확정.
> - **`RenualKnowledgePanel.vue` 검색탭 AI답변 박스**: 기존 "아이콘+텍스트 가로" → **첫 줄 `✨ AI 요약` 타이틀(아이콘+라벨) / 다음 줄부터 요약본문** 세로 배치(목업 `new_knowledge_1.png`). 컨테이너 `flex-col gap8`, 본문 래퍼 `flex-col`. (chat탭 ContentPanel 은 원래부터 이 타이틀 있었음 → 이제 검색탭도 통일)
> - IDE 진단 0. 라이브(삼성코리아 펀드 검색→문서클릭) 확인 완료.

**[이전 기록/참고] 원 계획 메모** — 헤더 1줄 통합(단일섹션 전제였음). `new_knowledge_1/2.png` 참고.
```
현재(2줄, 문서명 중복):
  [문서]배지 문서명 ............ 원본보기↗      ← DocumentDetailView 헤더
  문서명 ......... 북마크🔖  토글∧              ← ContentCollapse 섹션 헤더(아코디언)
  본문(ToastEditor)
변경(1줄 통합):
  [문서]배지 문서명 ......... 북마크 | 원본보기 | 토글
  본문
```
- 즉 **ContentCollapse 아코디언 헤더의 북마크·토글을 DocumentDetailView 헤더 우측으로 이동**(단순 UI 아님 = 로직 이동 필수).
  - 북마크 = **문서 단위**(백엔드 지원 확인됨: 북마크그룹+문서id). ContentCollapse 의 `handleBookmarkToggle/saveBookmark(모달 그룹선택)/removeBookmark/isBookmarked(content_key===documentId)/bookmarkStore/BookmarkAPI` 를 DetailView 로 이동.
  - 토글 = 문서 본문 접기/펼치기(`isCollapsed`), 화살표 up/down.
  - 원본보기 = 이미 DetailView 헤더에 있음(`open-original-btn`, `provide/inject openOriginalViewer`).
- **①(완료):** DetailView 헤더를 `flx-justify-between`으로 좌(배지+문서명)/우(`flex-shrink:0` 그룹) 분리 → 우측 그룹에 원본보기 배치. **다음엔 이 우측 그룹에 북마크+토글만 추가하면 됨.**
- ContentCollapse 는 섹션 헤더 제거하고 본문(ToastEditor)만 노출하는 방향(단일 문서 기준). 섹션 여러개 케이스 확인 필요.
- 배지(`ECPTag` doc_type.name) 스타일도 목업처럼(연회색 pill) 조정.

**기타 남음:** 우측레일 모달연동 / 고객 말풍선(SpeechBubble 복사, 배경 인라인로직) / 상담원 말풍선 배경색 실측조정 / (선택)AI요약 라벨 통일.

**🔎 미확인 이슈 — 발화내용 검색 하이라이트 (2026-07-09 기록, 원인 미확정)**
> 사용자 제보: 리뉴얼 상담화면 → "상담내용" 제목 옆 필터(tune) 아이콘 → 팝오버 "발화 내용" 탭 → 검색어 입력 후 검색 → 결과 위/아래 화살표로 이동은 되는데, **포커스/하이라이트가 되어야 할 것 같은데 안 되는 듯**. 기존 화면(`view/advisor/components/chat/index.vue`)이 어떤지는 **미확인**.

- **하이라이트 자체는 이미 구현돼 있음** — `RenualSpeechBubble.vue:31-36` 의 `getHighlightedParts()` + `.highlight-active`(현재 결과) / `.highlight-dim`(나머지 결과) 스타일(396·402줄). 부모가 검색 props 4개를 정상 전달 중(`RenualChatPanel.vue:338-342`: `appliedSearchText` / `isSearchActive` / `currentSearchIndex` / `searchResultPositions`).
- **위/아래 버튼 동작** — `useChatSearch.ts`(`view/advisor/components/chat/composables/`, 기존 것을 리뉴얼이 재사용). `goToNext/PreviousSearchResult` → `currentSearchIndex` 증감 → `scrollToCurrentSearchResult()` → `scrollToItemByIndex` → `scrollToItemById`. **즉 스크롤만 하고, 하이라이트 이동은 `currentSearchIndex` prop 변화에 의존.**
- **유력 원인 가설 (미검증): `v-memo`.** `RenualChatPanel.vue:329` 말풍선 `v-for` 의 v-memo 의존성 배열에 **검색 관련 값이 하나도 없음** → `currentSearchIndex`/`appliedSearchText` 가 바뀌어도 버블 서브트리 diff 가 skip 되어 자식 props 가 갱신되지 않음. (같은 원인으로 "지식정보 배지 토글"이 안 먹었고, `kdToggleVersion` 을 v-memo 에 추가해 해결한 전례 있음 — `CLAUDE-history.md` 12번)
- **⚠️ 가설을 흔드는 사실:** 기존 화면 `view/advisor/components/chat/index.vue:319` 의 v-memo 배열도 **리뉴얼과 완전히 동일**하고 검색 props 도 똑같이 전달함(`SpeechBubble.vue`, `highlight-active` 보유). 즉 **v-memo 가 원인이라면 기존 화면도 똑같이 깨져 있어야 함.** 리뉴얼에서만 증상이 난다면 v-memo 가 아닌 다른 원인.

**다음에 확인할 것 (순서대로):**
1. **기존 상담화면에서 같은 검색을 해보고 하이라이트가 뜨는지** — 여기서 갈림. 뜨면 v-memo 가설 폐기, 안 뜨면 v-memo 확정(양쪽 공통 버그).
2. 리뉴얼에서 정확한 증상 구분: **(a) 하이라이트가 아예 안 뜸** vs **(b) `highlight-dim` 은 뜨는데 위/아래 눌러도 `highlight-active` 가 안 옮겨감.** 원인이 다를 수 있음.
3. 원인이 v-memo 로 확정되면 조치는 배열에 `currentSearchIndex` · `isSearchActive` · `appliedSearchText` 추가(단, 이 셋은 버블별 값이 아니라 전역이라 **검색 시 전체 버블 리렌더**됨 — `kdToggleVersion` 같은 버블 단위 우회가 어려움. 성능 트레이드오프 판단 필요).

**참고 — 같은 팝오버의 드래그 기능:** 팝오버 본문 전체가 드래그 핸들(`@mousedown.prevent="startSearchPopoverDrag"`, `useChatPopoverDrag.ts`). 기존 화면에도 원래 있던 의도된 기능. 다만 ⑴ `getPopoverElement()` 이 `.adv-popper-container` 중 **마지막 요소**를 집어 팝오버 2개 이상 열리면 오작동 여지, ⑵ `.prevent` 가 early-return 과 무관하게 항상 `preventDefault()` 를 걸어 팝오버 내 `ElInput` 포커스가 막힐 가능성 → **둘 다 미확인, 지금 터지는 문제 아님.**

**원칙:** 색은 테마변수(`--color-primary`계열/`--color-gNN`), 특히 hover. 하드코딩 금지.

### 🟡 대시보드 (UI+실연결 1차 완료, 2026-07-07) — **일부 미구현** (이슈어 / FAQ / KPI 2개)
- 파일: `src/view/advisor-renual/dashboard/index.vue`
- 방식: **종합(집계) API 신설 안 함 → 기존 전용 스토어/API 그대로 재사용**(코어 재사용 원칙). 진입(onMounted)에서 `ensureBootstrapped()`(멱등) 후 실데이터 4개만 병렬 로드(`Promise.allSettled`). 대시보드 진입마다 갱신(오늘 통화·미확인 코칭 등은 최신값이어야 의미).
- 목업 UI(배포 `/agent/dashboard`) 재현: 인사말 → 긴급공지 배너 → (코칭·오늘통화·이슈어) 3열 → (자주하는질문·자주열람지식) 2열 → 오늘 KPI 4스탯. 색 전부 테마변수, 반응형(960px↓ 1열 / 720px↓ KPI 2열).

**✅ 실연결 4개 (기존 소스 재사용):**
- ① 긴급공지: `noticeStore.fetchDashboardNotices(agentId)` → `dashboardNotices` 최신순 [0] 1건(긴급/일반 무관). `type==='urgent'`이면 "긴급 공지" 아니면 "공지". 본문 `stripHtml`. 없으면 배너 미노출. 클릭→`/advisor-renual/notice`.
- ② 코칭: `coachingStore.refreshCoachings(false)` → `unReadCoachingCount`(미확인 수, 전용 API) + `receiverCoachings[0].content`(최근 문구, stripHtml). 없으면 "받은 코칭 없음". 클릭→`/advisor-renual/coaching`.
- ③ 오늘통화: `CallStatAPI.getAgentSummaryStats({agent_id:cc_cti_id, 오늘})` → `total_calls` + `callHistoryStore.fetchRecentCallHistory(이번달)` → `getSortedRecentCalls("new")[0].callId`(마지막 통화). 없으면 "최근 통화 이력 없음". 클릭→`/advisor-renual/call-history`.
- ⑥ 자주 열람 지식: `DashboardAPI.getPopularDocuments(workspaceId, 5)` → `mapToPopularDocItem`. 표시=문서명 + `storeName(·카테고리경로)`(현 운영 대시보드와 동일 표기). 최대 5, 없으면 빈상태 문구. (제목 "최근 업데이트된 지식 문서"→**"자주 열람 되는 지식"**으로 변경, 날짜 대신 저장소명)
  - ⚠️ **버그픽스**: 처음에 `agent.assigned_workspace_id`만 봐서 목업/mock 계정(프로필 workspace 미할당)에선 0건이었음 → `resolveWorkspaceId(...)`(설정 탭 저장값/`VITE_MOCK_WORKSPACE_ID` override 우선, 없으면 프로필)로 교체(chat 리뉴얼·운영 대시보드와 동일 우선순위).

**⛔ 미구현 (제목에 회색 `· 미구현` 텍스트만, 내용은 `[MOCK]` 플레이스홀더 유지):**
- ④ 이슈어(최근 감지 Top 5) — 감지 이력 집계 없음(문서 8-1 참고).
- ⑤ 자주 하는 질문 Top 5 — FAQ 집계 미구현.
- → 실데이터 연동 시 각 `[MOCK]` 블록 + 제목의 "· 미구현" 삭제(파일 내 주석 명시).

**🟡 ⑦ 오늘 KPI — 일부 실연결 (2026-07-08):** `kpis` 하드코딩 배열 → computed 교체.
- **응대 수** = `todayCallCount`(③ 오늘 통화수와 동일 소스) ✅
- **평균 응대 시간** = `getAgentSummaryStats` 응답의 `avg_duration_ms` → `fmtDurationMs`로 `m:ss`(0/비정상=`—`) ✅. (기존 오늘통화 조회 1콜에서 함께 확보 — 추가 API 없음, `todayAvgDurationMs` ref)
- **평균 긍부정 / 1차 해결률** = 미구현 → 값 `—` + 라벨에 `(미구현)`. 카드 제목 `· 일부 미구현` 유지.

**나중에 보완:** 코칭 `content` 실제 형식(HTML/텍스트) 라이브 확인 후 stripHtml 조정 / 지식 `storeName`이 `store_id` 폴백이라 ID로 보일 수 있음(실 저장소명 매핑 필요) / 미구현 3개 실API 연동 / (선택) 진입마다 4콜 → 세션 캐시 고려.

### ✅ 할 일 todo (완료, 2026-07-08) — 코어 재사용, UI 신규 + 기한(due_date) 실연동

> 파일: `src/view/advisor-renual/todo/index.vue` (스캐폴드 → **실구현 완료**).
> 방식: 기존 `todoListStore`·`TodoAPI` 그대로 구독(복제 금지) + **기한(due_date) 기능은 백엔드 신규 필드 실연동**.
> 참고 목업 `/agent/todo`. dev 실측 확인 완료(CDP), IDE 진단 0.

**구현한 것 (요구사항 매핑):**
1. ✅ 데모 레이아웃 + **테마색** — 필터 on / 체크박스 on = `--color-primary`(native checkbox `accent-color`), 하드코딩 없음.
2. ✅ **우측 필터 버튼 `전체 / 완료 / 미완료`** — 로컬 `filter` 상태로 항목 필터. 요약줄 `진행 N · 완료 N · 통화 N`(통화=그룹 수).
3. ✅ **미완료 필터** 시 완료 항목 숨김 → 그룹 항목이 전부 완료되면 그룹째 사라짐(`groupsView` computed: 필터 후 빈 그룹 제거). 삭제 아님(state만 1).
4. ✅ **기한(due_date) 표시 + 편집** — `el-date-picker`(미래 날짜 허용, `AdvisorDatePicker`는 미래 막혀서 안 씀). `value-format="YYYY-MM-DD"`, `clearable`. 지정/변경 → `{due_date:"..."}`, 비우면 → `{due_date:null}`. **완료 토글은 `{state}`만 보내 기한 안 건드림.**
5. ✅ **조회 기간(from~to) + 조회 버튼** — 데모엔 없지만 추가(필터 버튼 왼쪽). `AdvisorDatePicker` 2개, 기본값 **최근 한 달**(오늘−1개월 ~ 오늘). 진입 시 이 기간으로 `refreshTodoList`.
6. ✅ **그룹 헤더** = `call_id · 전화번호 · 등록일` 순(없으면 `-`). 미완료/전체 카운트 + 접기(체브론).

**백엔드 신규 필드 (실연동, 배포·테스트 완료):**
- `due_date`: `string|null`, `YYYY-MM-DD`. `PUT /todos/:id` 에 **`{due_date}`만 담으면 기한만 갱신**(title/state 불변). `null`=해제. 형식 틀리면 400.
- `call_id`: 표시용 콜 ID(예: `call-000003`). 응답에 있으면 헤더에 노출, 없으면 `-`.

**코드 변경 (3파일):**
- `src/api/types/todo.type.ts` — `TodoItem.due_date?`, `call_id?` 추가 / `CreateTodoReq.due_date?` / `UpdateTodoReq.due_date?` 추가.
- `src/stores/modules/todoList.ts` — `parseTodoData`에서 `dueDate = item.due_date || ""`(기존 통화일 더미 제거), 그룹에 `callId = item.call_id ?? ""` 추가 / **신규 액션 `updateTodoDueDate(todoId, dueDate|null)`**(성공 시 로컬 `dueDate` 갱신) + export. `TodoGroup`에 `callId` 필드.
- `src/view/advisor-renual/todo/index.vue` — 전체 UI(요약줄/조회기간/필터/그룹카드/체크박스/기한피커).

**해결한 함정:**
- **가로 스크롤**: `.todo`가 `width:100%`+`padding:28px`인데 `box-sizing` 없어 패딩만큼 넘침 → `box-sizing:border-box`. (+ flex 축소 위해 `.renual-page{min-width:0}`)
- **`keyboard_arrow_up` 텍스트 그대로 노출**: `material-icons` 폰트 미로드 → **`ECPIcon`(전역 등록)** 으로 교체.
- **el-date-picker 기본 220px** 과폭 → `:deep(.el-date-editor.el-input){ width:110px !important }` 로 절반.

**⚠️ 데이터 현실 (목업과 차이 — 코드 정상, 데이터 문제):**
- 그룹핑 기준 = 콜ID 아님, **전화번호+날짜(YYYYMMDD)** (store `parseTodoData`). 헤더의 call_id는 표시용.
- 실 응답에 `consumer_phonenumber`가 **일부 항목엔 없음** → 그 그룹은 전화번호 `-`. `call_id`도 응답에 없으면 `-`.
- 서버 `id`는 **문자열 UUID**(`todo_...`)인데 store/type은 `number`로 선언 — 런타임 정상(문자열 그대로 흐름), **타입만 정리 여지**(추후 `string|number`).

**확장 (미착수, 나중):** 상담화면 우측 `ChatRightRail.vue`의 "할 일" 아이콘 → 모달/패널 미연동 상태. 이 할일 UI를 **패널로 재사용**해 붙이는 방향.

### ✅ 북마크 bookmark (완료, 2026-07-08) — 코어 재사용, UI 신규

> 파일: `src/view/advisor-renual/bookmark/index.vue` (스캐폴드 → **실구현 완료**).
> 방식: 기존 `useBookmarkStore`(`convertedBookmarkGroups` getter = 그룹→카드 트리) + `BookmarkAPI`/`BookmarkGroupAPI` 그대로 구독. dev 실측 확인(CDP), IDE 진단 0.

**⭐ 분류축 판정(중요):** 북마크는 **"타입(문서/스니펫/AI)"이 아니라 "사용자가 만든 그룹명(bookmark_groups_id)"** 으로 분류됨. 데모의 타입탭은 목업 전용 → **그룹명 탭**으로 대체. `content_type`은 분류가 아니라 **배지(지식정보/스크립트)용 부가값**. 실제 북마크 대상 = 지식(문서/섹션)만(통화·AI 없음). 백엔드에 검색·기간 필터 파라미터 없음 → **전량 로드 후 클라이언트 필터**.

**구현:**
- 상단 좌측 = **그룹명 탭** `전체(N) · 그룹명(n)…`, 넘치면 **hover 시 좌우 화살표 스크롤**(위치 감지: 시작이면 ←숨김/끝이면 →숨김). 스크롤바는 숨김.
- 상단 우측 = **제목 검색(실시간)** + **기간조회 from~to + 조회버튼**(기본 최근 한 달, 카드 date 클라 필터).
- 리스트 카드 = `[배지 지식정보/스크립트]  📁 그룹명  제목 ……… 날짜`. (그룹명 앞 **폴더 아이콘**으로 "그룹"임을 명확화)
- 필터: 그룹 탭 + 검색 + 기간 조합, 그룹 탭 카운트는 기간·검색 반영.
- 반응형(프로젝트 표준 **768px**): 좁아지면 `[그룹 탭] / [검색·기간]` **2줄 분리**(`flex-wrap` + `flex-basis:100%`).

**코드 변경:**
- `src/stores/modules/bookmark.ts` — **배지 매핑 버그픽스**: `content_type===1 ? knowledge` → **`===2`** (저장 코드가 지식정보=2로 넣는데 표시가 반대였음. 리뉴얼+기존 Drawer 배지 동시 정상화).
- `src/view/advisor-renual/bookmark/index.vue` — 전체 UI 신규.

**해결한 함정:**
- 가로 넘침: `.bm{box-sizing:border-box}` + `.renual-page{min-width:0}`.
- 컨트롤 높이 정렬: 탭 상하 대칭 패딩으로 검색/날짜/버튼과 수직 중앙 일치.
- 날짜폼 104px(80%)에서 `YYYY-MM-DD` 잘림 → `:deep(.el-input__wrapper) padding` 축소로 폭 유지한 채 해결.
- **화살표 아이콘 hover 시 투명**: ui-kit `ECPButton`이 hover에 `opacity:0.8` + `inheritAttrs:false`(scoped 안 먹음) → **`:deep(.bm-arrow)` + `opacity:1 !important`**. (⚠️ `:deep(...)` 뒤 `&--suffix` 중첩 불가 → suffix를 괄호 안에 넣어 평면 규칙으로)

**남은 참고(나중):** 카드 클릭 → 상세 열기(기존 `BookmarkDetailModal` 재사용) / 카드에 그룹명 중복(좌측 탭과) 정리 여부 / 통화·스니펫 등 다종 북마크 확장(현재 지식만).

### ✅ 메모 memo (완료, 2026-07-08) — 코어 재사용, UI 신규 + 확장뷰/핀/수정/삭제 실동작

> 파일: `src/view/advisor-renual/memo/index.vue` (스캐폴드 → **실구현 완료**).
> 방식: 기존 `useMemoStore.loadMemoGroups()`(→ `memoGroups[{groupName,groupId,cards[]}]`) 구독(복제 금지). 참고 목업 `/agent/memo`. dev 실측(CDP), IDE 진단 0.

**⭐ 구성:** 데모는 **메모 말풍선 카드 그리드**가 본체 + 상단 컨트롤(그룹탭/검색/기간)은 **북마크 페이지 툴바 재사용**. 즉 **[북마크 툴바] + [메모 말풍선 카드]** 조합.
- 데이터 매핑(MemoCard): `title`(=name) / `description`(=content, **원본 HTML**) / `date`(=create_at) / `bookmarkId` / `isPinned`.
- 데모의 `↳ 통화·고객` 은 우리 데이터에 없음 → 제거. 노출 = 그룹명 배지 + 날짜 + 핀(별) + 케밥 + 제목 + 내용.

**A. 조회 (레이아웃/필터):**
- 상단 = 북마크와 동일: 그룹명 탭(가로스크롤·hover 화살표) + 검색(**제목·내용**) + 기간조회(최근 한 달, `create_at` YYYY-MM-DD 정규화 후 클라 필터).
- 리스트 = **3열 masonry**(CSS `column-count:3`, 반응형 1200→2 / 768→1). 카드 = `[그룹 pill] … [날짜·핀·케밥] / 제목(굵게) / 내용`.
- 내용 = **HTML → plain text**(`htmlToText`: `<br>/<li>/블록` 줄바꿈·`<li>`는 `·`, 엔티티 디코드). 기존 Drawer 메모(`getPreviewText`)와 같은 방향이나 줄바꿈 보존.

**B. 확장뷰 (FLIP, 본문 접힘/확대):**
- 카드 본문 `max-height:190px`, 넘치면 **하단 페이드 + 우하단 확대 아이콘(open_in_full)**. 넘침 감지 = body `scrollHeight>clientHeight`(함수 ref + ResizeObserver로 measure).
- 확대 클릭 → 원본 카드 **제자리 유지**, 그 위에 확장뷰가 **원위치에서 스르륵 커져 떠오름**(Teleport fixed 오버레이, left/top/width/height transition 0.24s + 2패스 measure로 목표 height 확정). **재배치 없음(다른 카드 위로 올라탐).**
- 방향 = 클릭 시 `getBoundingClientRect`로 열 판정: 왼쪽→오른쪽 / 오른쪽→왼쪽 / 가운데→좌우 균등. 폭 2배(컨테이너 clamp), 화면 하단 초과 시 내부 스크롤. 닫기(×)·바깥클릭 시 원위치 축소.

**C. 핀(고정) — 백엔드 신규 API 실연동 (2026-07-08 배포):**
- `PATCH /memos/:id` body `{ is_pinned: true|false }` (부분 업데이트). 목록 응답에 `is_pinned` 포함, 서버가 핀 우선 정렬.
- **별(⭐) 클릭 = 핀 토글**: 켜면 맨 위 고정 + 별 채움(primary) + **테마색 테두리 강조**. 정렬 = 핀 우선 + 최신순(우리도 명시 정렬, flatten 때문).

**D. 수정/삭제 — 코어 재사용:**
- 카드 우측 **케밥(⋯) 메뉴**(상시 노출)에 수정·삭제 통합(`onCardCommand` 분기). hover 시 빈칸 어색함 방지로 케밥 채택.
- 수정 = 기존 `MemoEditorModal.vue` 재사용(Drawer 의존 없음, `memo.id`면 수정모드, 원본 HTML 에디터 로드) → `memoStore.updateMemo`.
- 삭제 = `ElMessageBox.confirm`(프로젝트 표준, window.confirm 아님) → `memoStore.deleteMemo`.

**코드 변경(3파일):**
- `memo.api.ts` — `setMemoPinned(memoId, isPinned)` 신규(`PATCH {is_pinned}`).
- `memo.ts` — `MemoCard.isPinned` + 매핑(`is_pinned ?? false`), 신규 액션 `togglePin`(setMemoPinned→loadMemoGroups) + export.
- `memo/index.vue` — 전체 UI(툴바/3열 카드/htmlToText/확장뷰 FLIP/핀 토글/케밥 수정·삭제).

**⚠️ 라이브 확인 필요(추가 시):** 데이터 다건일 때 masonry 팩킹, 긴 내용 확장뷰 내부 스크롤.
**남은 참고(나중):** 확장뷰에서 직접 수정/삭제 / 상담화면 우측레일 "메모" 아이콘에 이 UI 패널 재사용 / 카드 클릭(케밥 외) 상세 열기 여부.

### 🟡 설정 settings (UI 완료, 2026-07-09) — **일부 미구현** (알림 2 / 소리 3 / 통화중화면 2 / 단축키)

> 파일: `src/view/advisor-renual/settings/index.vue` (스캐폴드 → **UI 구현 완료**).
> 방식: 데모 `/agent/settings` 구성을 그대로 재현(**테마 섹션만 제외** — 사용자 지시).
> 기존 설정 모달(`Drawer/components/Setting/Setting.vue`) 의 코어를 그대로 구독(복제 금지). dev 실측(MCP), IDE 진단 0.

**섹션 6개** (데모 4개 + 우리 추가 2개):
1. 알림 — 코칭 메시지 도착 알림 / 지식 자동 검색 / 공지 도착 알림 / 통화 종료(wrap-up) 알림 (+저장)
2. 소리 — 알림 사운드(전체) / 코칭 도착 시 소리 / SOS 응답 시 소리
3. 통화 중 화면 — 발화 자동 스크롤 / 코칭 위스퍼 음성 (+ 센터 설정 안내문)
4. 단축키 — `Ctrl+M/I/K/F//` 표(읽기전용)
5. **WorkSpace** (데모엔 없음) — 프리셋 셀렉트 + 직접입력, 저장 시 `window.location.reload()`
6. **카테고리(지식 검색 범위)** (데모엔 없음) — 그룹/리프 체크박스 트리(indeterminate)

**실동작 여부 (중요):**
- 서버 저장(`ConfigAPI.upsertConfig`): `코칭 알림` / `지식 자동 검색` — `settingsStore`. store 의 `label` 이 곧 서버 `alias` 키라, 화면 라벨("코칭 메시지 도착 알림")만 spread 로 덮고 저장은 store label 사용.
- localStorage: WorkSpace(`workspaceStore`) / 카테고리(`categoryStore`)
- ⛔ **UI 전용(저장 안 됨)**: 공지 도착 알림 / wrap-up / 소리 3종 / 발화 자동 스크롤 / 위스퍼
  → `CheckItem.uiOnly` 플래그 + 회색 `· 미구현` 표기(대시보드와 동일 패턴). 실연동 시 플래그·표기 제거.
- 단축키: 실제 동작하는 건 `Ctrl+F`(헤더 메뉴검색 `SearchMenu.vue`) 하나뿐 — 나머지는 목록만.

**레이아웃 — grid 대신 masonry:**
- `display:grid` 2열은 **행 높이가 그 행의 큰 카드에 맞춰져** 짧은 카드(통화 중 화면) 옆에 큰 빈 공간이 생김(MCP 실측 확인).
- → `column-count:2` masonry(메모 페이지와 동일) + `break-inside:avoid` + 카드 `margin-bottom`(column 은 gap 안 먹음) + `box-sizing:border-box`. 768px↓ 1열.
- ⚠️ `column-count` 는 좌→우가 아니라 **위→아래**로 채움 → 향후 **카드 드래그앤드롭 정렬** 요구 시 DOM 순서 ≠ 시각적 배치라 계산이 지저분. 그땐 grid + 정렬 라이브러리로 교체 권장.
- **`max-width:1200px` 제거 (2026-07-10)** — 원래 `.settings` 에 상한이 걸려 있어 **LNB 를 접어도 카드가 안 커지고 늘어난 폭이 전부 오른쪽 빈 공간**으로 갔음(왼쪽 정렬, `margin:0 auto` 없음). 1200px 아래로만 반응하고 위로는 안 자라는 구조. → 상한 삭제, 이제 `width:100%` 로 콘텐츠 영역을 꽉 채우고 두 열이 항상 정확히 반반.
  - `.settings` 에 **min-width 는 원래 없음.** (451줄 `min-width:0` 은 바깥 `.renual-page` 것으로, 하한이 아니라 **flex 자식 축소 허용**=가로 스크롤 방지용. 의미 정반대라 혼동 주의) → 좁아지면 카드가 끝까지 같이 줄고, 유일한 방어선은 768px↓ `column-count:1`.
  - 나중에 와이드 모니터에서 카드가 과하게 넓으면 상한 재도입(예: 1600px), 좁은 폭에서 답답하면 브레이크포인트 상향. 대시보드는 아직 `max-width:1280px` 유지 중(같이 뺄지는 미결).

**⚠️ 작업 중 실수(반복 금지):** 사용자가 "일단 UI만" 이라 명확히 지시했는데, 내가 "실동작 되는 것만 노출할까요?" 선택지를 던져 데모 기능이 통째로 빠진 결과물을 냄 → 즉시 원복. **목업 재현 작업에서 "미구현 항목 뺄까요" 류 질문 금지.**

### ✅ 코칭 coaching (완료, 2026-07-09) — 코어 재사용, UI 신규 + 읽음처리

> 파일: `src/view/advisor-renual/coaching/index.vue` (스캐폴드 → **실구현 완료**).
> 방식: `coachingStore` 그대로 구독(복제 금지). 참고 목업 `/agent/coaching`. dev 실측(MCP), IDE 진단 0.

**⭐ role 에 따라 스토어 필드 의미가 정반대 (`coaching.ts:36-46`) — 최대 함정**
| | 상담사(isAdmin=false) | 관리자(isAdmin=true) |
|---|---|---|
| `requestCoachings` | 내가 **요청한** 코칭 | 내가 **지시한** 코칭 |
| `receiverCoachings` | 내가 **받은** 코칭 | 내가 **요청받은** 코칭 |
→ 화면은 sent/received 두 축만 알면 됨. **탭 라벨만 role 로 갈아끼움.** role 판정 `agent.role === "AGENT"`.

**상태 판정 — `status` 필드 안 씀** (기존 `parseCoachingData` 와 동일):
응답 없음=대기 / 응답 있고 미확인=진행중 / 응답 있고 확인=완료. 응답 = `receiverCoachings` 중 `coaching_request_id === 요청.id`.
⚠️ `is_read` 가 서버에서 **문자열 `"true"/"false"`** 로 옴 → `isRead()` 로 방어.

**UI:** 탭3(받은/요청한/완료 — 완료는 양축 완료건 모아보기, 중복 노출) + 검색·기간조회(북마크 툴바 패턴). 데모의 "라이브 코칭/SOS 응답"은 실데이터에 없는 개념 → `priority_type`(1=긴급/0=일반) 배지로 대체. `call_id` 옆 **[보기]** → **`RenualCallDetailModal`**(2026-07-13 교체, 이전엔 기존 `ChatHistoryModal`). 미확인 카드 클릭 = 읽음처리.

**페이지네이션:** 서버 기본 `limit=10` 에 조용히 잘리고 있었음. 부분 로드면 **상태 판정이 깨짐**(응답이 11번째면 "대기"로 오표시) → lazy·페이지UI 부적합. `refreshCoachings(isAdmin, params?)` 에 **선택 인자** 추가, 리뉴얼만 `{page:1,limit:100}` 명시. **기존 호출부 10곳은 인자 없이 호출 → 무영향**(전수 확인). `warnIfTruncated()` 로 잘림 경고.

**부트스트랩 중복 호출 제거:** `isBootstrapStarted()` 신규 export. ⚠️ **반드시 setup 시점에 읽을 것** — 자식 `RenualPageHeader` 의 `onMounted` 가 부모보다 먼저 돌아 부트스트랩을 시작시키므로 `onMounted` 에서 읽으면 판별 불가.

**⛔ 미해결(기존 구조 문제, 그대로 둠):** `From./To. 알 수 없음` 다수. 이름은 백엔드가 안 주고 프론트가 `get_managers` 로 조인. dev 발신자 7명 전원이 관리자 목록에 없음(97건 중 88건 `sender_name: null`). 근본원인 = 이름 저장이 프론트 payload 취향(`AdminCoachingCard.vue:236` 만 넣음). → 백엔드에 `sender_name`/`receiver_name` 요청서 전달. **프론트 폴백은 제거 금지**(하위호환).

### 🟡 통화이력 call-history (완료, 2026-07-13) — **일부 미구현** (통화결과 / 감지어 집계)

> 파일: `src/view/advisor-renual/call-history/index.vue`(목록) + `components/RenualCallDetailModal.vue`(상세 모달, 신규)
> 방식: 목록·상세 모두 **데모(`/agent/history`) 재현**. 코어(store/composable) 재사용, 상세 모달만 새로 제작.

**⭐ 신규 백엔드 API (2026-07-13 배포) — `GET {API_PREFIX}/callstat/call-history`**
- 요청 파라미터는 `agent-summary` 와 **완전히 동일**(agent_id/start_date/end_date/page/limit/고객명·전화번호·키워드).
- 응답 = 기존 항목 **+ `summary`(md) / `keywords[]` / `external_categories`(string[]) / `voc` / `intent` / 요약4필드**.
  - 요약 4필드: `customer_inquiry`(고객문의) / `handling_result` / `follow_up` / `notes` — **상세 API(`/summary/data/:id`)에도 동일 포함**.
  - `voc` 는 상세 API 의 voc 와 **구조 동일** → `VocDetailBox` / `resolveVocView` 그대로 재사용.
- ⚠️ **요약이 생성된 콜에만 값이 있음.** 요약 미실행 콜(테스트 콜 등)은 `null` / `[]` 가 정상 → 화면엔 `-`.
- 기존 `agent-summary` 는 그대로 유지 → **기존 Drawer/대시보드 무영향.**

**목록 (`index.vue`)**
- 코어 재사용: `useCallHistoryStore`(페이징·필터·무한스크롤) + `useFavoritesStore`(관심콜).
- store 확장: 신규 액션 **`fetchCallHistoryWithSummary()`** + state `useCallHistoryApi` 플래그.
  **리뉴얼만 신규 엔드포인트를 타고**, 기존 호출부(Drawer/대시보드 10여 곳)는 인자 없이 호출 → `agent-summary` 그대로.
  `loadMoreCallHistory()` 도 이 플래그를 이어받아 같은 엔드포인트로 페이징.
- 매핑 확장(`mapCallHistoryItems`): `intentText`(= `customer_inquiry || intent`) / `categoryPaths`(= `external_categories`) / `voc` / `direction`.
- 툴바 **한 줄**: `[검색(가변)] [전체콜·관심콜 탭] [기간 from~to] [결과·인입(비활성)] [정렬] [조회]`.
  검색만 `flex:1 1 auto`(min 120px)로 줄고 나머지는 `flex-shrink:0` 고정. **768px↓ 2단**(1단=검색+탭 / 2단=기간~조회).
- 검색어 라우팅: 숫자·하이픈만이면 `phone_number`, 아니면 `keyword` 로 보냄(서버가 두 파라미터를 나눠 받음).
- 정렬(최신/오래된/길이순) = **클라이언트 정렬** — 서버에 `sort_order` 없음(무한스크롤과 조합 시 부분 정렬).
- 관심콜: 별 = `icon="star" :filled="isImportant"`(기존 `CallHistoryCard` 와 동일). 진입 시 `fetchFavoriteCallIds()` **선행 필수**(안 하면 별 상태 복원 안 됨).
  ⚠️ 관심콜 탭은 **로드된 페이지 범위 내 클라 필터**(서버에 favorite-only 조회 없음).

**상세 모달 (`RenualCallDetailModal.vue`, 신규)** — 데모 3열
| 열 | 내용 | 상태 |
|---|---|---|
| ① 좌(300px) | 고객 기본정보 / 상담 시간 / 감지·감정 요약 | 연락처·상담시간·감정(VOC)=실데이터. 이름·등급·고객번호·이메일·지역·인입·90일통화 = 미구현 |
| ② 중(flex) | 스크립트(말풍선 + 발화별 지식정보 snapshot) + 오디오 플레이어 | **전부 실동작** |
| ③ 우(300px) | 주요 의도(`customer_inquiry`→`intent`) / 상담 요약 / 상담 유형(복수) / 핵심 키워드 | **전부 실데이터** |
- 방식 = 상담화면과 동일한 **"복사 후 UI 리뉴얼"**. 로직은 원본 `ChatHistoryModal` 것을 가져오되
  composable(`useAudioPlayer`/`useKeywordDetail`)·자식(`SpeechBubble`/`VocDetailBox`/`VocHistoryModal`/`DocumentDetailModal`)은 **원본 import 재사용**. **원본 파일 무수정.**
- 레이아웃 규칙: **제목은 보더 밖 + 데이터 영역만 보더**(`.rcd-sec__title` + `.rcd-box`). 제목 `height:20px`+동일 마진으로 **3열 첫 제목이 같은 라인**.
- 모달 **고정폭 1130px**. 좌·우 300px 고정 + 중앙 `flex:1` → **모달 폭만 조절하면 중앙 스크립트 폭만 변함.**
- **적용처 2곳**: 통화이력 목록 / **코칭 페이지 [보기]** (2026-07-13 기존 `ChatHistoryModal` → 이걸로 교체).
  ※ 기존 화면(상담사 Drawer 등)은 여전히 원본 `ChatHistoryModal` 사용 — 건드리지 않음.

**⛔ 미구현 2개 (DB 설계부터 필요 — §8-2)**
- **통화 결과**(완료/이관/콜백): 목록·상세 어디에도 **필드 자체가 없음**. 값 정의 + DB + 입력 경로(CTI/상담사) 전부 신규.
- **감지어 집계**(감지어 N건): 감지 이력 미저장(§8-1) → 집계 불가.
- (참고) **인입유형 `direction`**: 컬럼은 있고 **값이 안 채워짐**. `raw_call.callstats_call` 적재 담당 영역이라 asst-service 작업 아님.
  스펙 `"I"`(인바운드)/`"O"`(아웃바운드) → 프론트에 **`I/B`·`O/B` 매핑 미리 심어둠**. 적재 시작되면 코드 수정 없이 자동 표시.
- (참고) **의도 `intent`**: 원본(`callstats_turn.intent`) 미적재라 항상 null. 대신 **`customer_inquiry` 를 1순위**로 써서 화면은 정상 동작.

### ⬜ 나머지 리프 (미착수)
감지어보기
→ 공지사항 패턴(단순 리프). 배포 시안 `/agent/keyword` 는 관리자 등록 감지어 **조회 전용**(read-only) — 난이도 낮음.

---

# 9. ⚙️ 개발환경 메모 — 데모 목업을 MCP(Playwright)로 보기 (2026-07-08)

> **문제:** 데모(`13.209.195.192:32010/asst-web-ui`)를 MCP 격리 크롬으로 열면 **사용자가 보는 화면과 통째로 다름**. 원인 = **서비스워커 캐시**(사용자 크롬엔 옛 SW 번들, MCP 새 크롬엔 최신). 하드리로드(`Cmd+Shift+R`)로도 SW는 안 지워져 그대로. URL은 양쪽 동일 확인됨.
>
> **해결 = CDP 연결** (MCP를 실제 크롬에 붙임):
> - `~/.claude.json` → 이 프로젝트 `mcpServers.playwright.args` 에 `--cdp-endpoint http://localhost:9222` **추가 완료**(백업 `~/.claude.json.bak-cdp`).
> - Chrome **149**라 보안상 **기본 프로필로는 원격 디버깅 거부** → **별도 프로필**로 띄워야 함:
>   ```
>   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
>     --remote-debugging-port=9222 --user-data-dir="/tmp/chrome-cdp-profile" \
>     --no-first-run --no-default-browser-check \
>     "http://13.209.195.192:32010/asst-web-ui/#/agent/todo" &
>   ```
> - ⚠️ 별도 프로필이라 **서비스워커 없음 → "최신" 화면이 뜸**(사용자가 보던 옛 SW 화면과 다를 수 있음). 재시작 후 화면 확인해서 **어느 버전을 정답으로 삼을지** 먼저 합의 필요.
> - **설정 적용은 Claude Code 재시작 필요** → `claude --continue`(대화 이어짐).
>
> **재시작 후 체크리스트:** ① `curl -s localhost:9222/json/version` 로 포트 확인 → ② playwright `browser_navigate`로 데모 열어 화면 확인 → ③ 사용자와 "정답 디자인" 합의 → ④ 할 일(todo) 페이지 구현 착수.
> **스크린샷 저장 위치:** `asst-web/v2_image/` (`filename: "v2_image/이름.png"`).

## 7-8. 공통/기타 남은 작업
- [ ] 헤더/네비 폰트·색상 톤을 배포 UI 기준으로 정렬(기획자/협력업체 피드백 후).
- [ ] 뱃지 대상 확장(공지/코칭/할일 3개 외 생기면 `useRenualMenuBadges` + 부트스트랩에 추가).
- [ ] 공지 본문 외부입력 섞일 여지 생기면 `v-html` sanitize(DOMPurify).
- [ ] (선택) 허브 `advisor-renual/index.vue` 활용 여부 결정.

---

# 8. 기획 협의 / 신규 설계 필요 항목 (현실-기획 갭)

> 리뉴얼 리프를 파다 발견한 "현재 소스로는 안 되는 / 신규 개발이 필요한" 지점들.
> **기획자·백엔드 협의 전제.** 지금 당장 개발 아님 — 근거 자료용.

## 8-1. 감지어(키워드) — "대화 중 감지 결과 저장" 기능 없음 ★신규설계
**현황 (프론트 소스 + 백엔드 회신 기준)**
- 감지어 **분류: 3종** — 금칙어(`forbiddenWord`) / 이슈어(`issueWord`) / 비속어(`profanityWord`).
  (관리자가 "4분류"로 알고 있었으나 **코드·정책상 3분류**가 맞음 → 인식 정렬 필요)
- 감지어 **정의 등록/관리 API 존재**: `KeywordDetectAPI` = `GET/POST/PATCH/DELETE {API_PREFIX}/keyword-detects`, 데이터 `{ keyword, type, creator_key }` (키워드 1건마다 분류 지정).
- **실시간 감지 동작 방식**: assist-stream(서버)은 발화 **원문만** 전송 → **감지는 프론트가 클라이언트에서** 수행(`useTextRenderer` + `keywordDetectStore`, `text.includes`/정규식). 발화 렌더 시 **자동**으로 이슈어 하이라이트 / 금칙어 마스킹.
  - `refreshKeywordDetect()` 로 목록 로드(상담사 화면 진입 `agent/index.vue:466`), 이후 발화마다 `SpeechBubble`이 자동 매칭.
  - ⚠️ 단순 문자열 매칭(AI/의미분석 아님).

**갭 (없는 것)**
- **대화내용(발화) 중 감지된 키워드를 등록/저장하는 API·기능이 없음.** 현재 감지는 **화면 표시만, DB 저장 0(휘발)** → "이 통화에서 금칙어 N회" 같은 **감지 이력/집계가 남지 않음.**
- 백엔드 회신: 키워드 감지 관련 API는 여럿 있으나, **"우리가 체크하는 대화내용 중 감지 키워드 등록" API는 없음 → 신규 개발 필요.**

**협의/설계 포인트**
- (기획) 감지 이력을 남길지, 남긴다면 무엇을(통화별 감지 키워드/횟수/시점) 어디에 노출할지(리포트/통화이력/감지어보기 페이지).
- (백엔드) 감지 이벤트 저장 API 신규 설계(엔드포인트/스키마/분류 3종 정합).
- (프론트) 감지 시점에 저장 호출 추가(현재 감지 로직에 persist 연결).
- 참고: 배포 시안 `/agent/keyword`(감지어 보기)는 **관리자 등록 감지어 "조회"용**(read-only) — 감지를 *하는* 페이지가 아니라 *목록 보여주는* 페이지. (이 자체는 리프 중 난이도 낮음)

## 8-2. 통화 결과(완료/이관/콜백) — 필드 자체가 없음 ★신규설계 (2026-07-13 발견)

**현황**
- 데모 통화이력 카드엔 `완료 / 이관 / 콜백 요청` 배지가 있으나, **목록·상세 API 어디에도 해당 필드가 없음**(빈 컬럼조차 없음).
- 인입유형(`direction`)과 **다른 건**: direction 은 컬럼이 있고 값만 안 채워지는 상태(적재만 되면 표시됨).

**협의/설계 포인트**
- (기획) 값 정의: `완료/이관/콜백` 3종이 맞는지, 코드값 체계, 누가 언제 정하는지(상담사 입력? CTI 이벤트? 후처리?).
- (백엔드) 컬럼·API 신설(목록 응답에 포함 필요 — 카드에 배지로 노출).
- (프론트) 값 스펙 확정 시 카드 배지 + 목록 필터("전체 결과" 셀렉트, **현재 비활성 상태로 자리만 잡아둠**) 연결.

## 8-3. 할 일 — 통화 중 등록 불가 (callstats_id 발급 시점) ★백엔드 협의 (2026-07-13 발견)

**현황 (조사 근거)**
- 할일의 키는 `call_id` 가 **아니라** `callstats_id` 다 — `CreateTodoReq { user_key, callstats_id(필수), title, due_date? }` (`api/types/todo.type.ts`).
  `call_id` 는 `TodoItem` 에 **표시용 옵셔널**로만 있음. 두 값은 별개 식별자이고 생기는 시점이 다르다.
- `call_id` : `call:start` 즉시 채워짐 (`useChatMessageParser.ts:219`).
- `callstats_id` : `call:start` 때는 오히려 `""` 로 **비워지고**(`:220`), 통화 종료 후 **`orchestrator:persisted`** 이벤트에서야 채워진다(`:639`).
- 기존 상담화면도 같은 이유로 **`할일 등록` 버튼을 `v-if="isCallEnded"` 로 감싸 둠** (`view/advisor/components/chat/index.vue:513`). 즉 통화 중 등록은 원래부터 없다.
- 배포 목업의 안내문 `"통화 중 또는 후처리 단계에서만 등록할 수 있습니다"` 는 **전반부가 사실과 다름**.

**⚠️ 기존 코드 잠재 버그 (미수정)**
- `할일 등록` 버튼은 `call:end`(=`isCallEnded=true`) 에 노출되는데 `callstats_id` 는 그보다 **늦게 오는** `orchestrator:persisted` 에서 채워진다.
  → 그 사이에 저장하면 `callstats_id: ""` 로 등록이 날아감 (`useChatTodo.ts` `handleTodoAddModalSave`).
  → **리뉴얼 레일 할일 패널은 `callStatsId` 가 실제로 있을 때만 입력을 활성화**해 이 구간을 원천 차단했다. 기존 화면은 그대로 둠.

**협의 포인트**
- (기획/백엔드) 통화 중 할일 등록이 필요하면 **`call:start` 시점에 `callstats_id` 를 선발급**해야 한다. 현재는 불가능.
- 실사용상 후처리에 **AI 자동등록(`POST /todos/auto-create`)이 메인**이고 수동은 보조라, 통화 중 등록의 실익이 크지 않을 수 있음(사용자 의견) → 우선순위 낮음.

**리뉴얼 레일 할일 패널의 4상태 (구현 완료)**
| 상태 | 조건 | 화면 |
|---|---|---|
| 통화 중 | `isCalling` | "통화가 끝나면 이 콜의 할 일을 등록할 수 있어요" (입력 비활성) |
| 후처리 준비중 | 콜 컨텍스트 있음 + `callStatsId` 아직 없음 | "통화 요약을 준비하는 중입니다…" (입력 비활성) ← 위 버그 구간 차단 |
| 후처리 | `callStatsId` 있음 | AI 자동생성 할일 목록 + 수동 추가 ✅ |
| 대기 | 콜 없음 | "진행 중인 통화가 없습니다" + 전체 보기 |

## 8-4. 코칭 — 기획자는 "채팅"을 의도, 현 구조는 "요청 1건 : 응답 1건" ★설계 협의 (2026-07-13)

**관찰 (사용자 지적)**
- 배포 데모 `/agent/chat` → 레일 "코칭요청" 클릭 시 뜨는 화면 제목이 **"코칭 대화"** 이고, 형태가 **연속 채팅 스레드**다.
  - 메시지가 시간순으로 죽 쌓임 (`나 7/6` → `나 3일 전` → `나 1일 전` → `정민호 19분 전` → `정민호 16분 전` …)
  - 하단에 **상시 입력창** (`"요청 또는 답글을 입력하세요. (Ctrl+Enter 로 보내기)"`) + `보내기` 버튼
  - 즉 **한 스레드 안에서 요청·답글을 계속 주고받는** 메신저 모델.
- 반면 **현 구현/백엔드는 "요청 1건 : 응답 1건" 단발 모델**이다.
  - `coaching_requests`(내가 보낸 요청) ↔ `coachings`(관리자 응답), 연결은 `coaching_request_id` **1:1**.
  - 상태도 그 전제 위에 있다: 응답없음=대기 / 응답+미확인=진행중 / 응답+확인=완료. (`advisor-renual/coaching/index.vue`)
  - `확인완료` 버튼(읽음처리)도 "응답 1건을 확인했다" 는 개념. 대화가 이어지면 의미가 모호해진다.

**즉 데모는 UI만 다른 게 아니라 데이터 모델이 다르다.** 채팅으로 가려면:
- (백엔드) 스레드 개념 신설 — `coaching_threads` + `messages[]`(sender/보낸시각/읽음). 현재의 1:1 링크로는 N턴을 표현할 수 없음.
- (기획) 상태(대기/진행중/완료)를 스레드에서 어떻게 정의할지 재정의 필요. 읽음(확인완료)도 "메시지 단위"인지 "스레드 단위"인지.
- (기획) 수신자(관리자) 선택은 여전히 필요 — 데모는 이 단계가 빠져 있음(아래 참고).

**현재 리뉴얼 레일 코칭 패널의 선택 (구현 완료)**
- **현 백엔드 모델(1:1)에 맞춰 구현.** 3뷰 드릴다운: 목록 / 새 요청(관리자 선택 필수) / 스레드 상세(내 요청 + 관리자 응답 + 확인완료 버튼).
- 데모의 "수신자 선택 없이 바로 대화 진입" 은 **상담사↔관리자 1:1 고정** 전제라야 성립하는데 실제는 1:N → 관리자 선택 단계를 복원함.
- **채팅 모델로 갈지 여부는 백엔드 설계가 먼저 결정돼야 한다.** 결정되면 이 패널의 `thread` 뷰가 그대로 대화창이 되는 구조라 교체 비용은 크지 않음.

## 8-5. 상담유형 "수정" — 통 교체 구조라 개별수정 불가 → **버튼 숨김** (2026-07-14) 🔴 미구현

**발단**
상담요약 팝오버(`docs/advisor_after.png`)의 상담유형 **수정** 버튼을 누르면 모달이 **상위에 작게** 뜨고 **내용이 비어** 있음. API 호출도 안 됨.

**분석 — `counselingTypes` 는 배열이지만 전 구간이 "길이 1 고정"**
| 지점 | 파일:라인 | 실태 |
|---|---|---|
| 수신 | `CounselingStatus.vue:312~320` | 백엔드가 N개를 줘도 **`allCounselingTypes[0]` 만** 꺼내 원소 1개 배열로 만듦. 2·3번째는 **버려짐** |
| 렌더 | `CounselingStatus.vue:61~68` | `v-for` 아님. **`counselingTypes[0]` 하드코딩** → 수정 버튼도 화면에 **1개뿐**, 항상 첫 번째만 가리킴 |
| 저장 | `CounselingStatus.vue:520`, `:338` | `external_categories_id: [counselingTypes[0].category]` — 배열이나 **원소 항상 1개** |
| 모달 저장 | `CounselingStatus.vue:404~418` | `counselingTypes.value = [{...selectedItem}]` — **배열 통째 교체** → 다시 1개 |

⭐ **상담유형은 콜당 2~3개가 올 수 있는데(사용자 확인), 현 구조는 개별 수정이 불가능하고 "통 교체"만 된다.**

**부수적으로 발견된 것 (`CounselingTypeModal.vue`)**
- `:2`, `:140` — **이 모달만 `append-to-body: false`.** 다른 모달(ChatHistoryModal/VocHistoryModal/MemoEditorModal/RenualCallDetailModal)은 전부 `true`.
  → 팝오버 DOM 내부에 렌더돼 팝오버 폭에 갇힘 = **"작게 뜨는" 원인.**
- `:259`, `:289` — 목록(`counselingTypeList`)은 **`handleSearch()` 로만** 채워지고, 그건 **"조회" 버튼/Enter 로만** 호출됨.
  → 모달 열 때 자동 호출 없음 = **"내용 없음 / API 안 나감" 원인.**
- `:309` — `handleSearch` 가 API 에 보내는 건 `{ workspaceId, page:1, limit:20 }` 뿐.
  **셀렉트 4개(`counselingType1~4`)도 검색어(`searchText`)도 API 에 안 넘어감** → 뭘 고르든 결과가 항상 같음. 검색·필터가 UI만 있고 동작 안 함.
- `CounselingStatus.vue:489` — `editCounselingType(id)` 가 `editingCounselingTypeId` 에 id를 넣지만 **모달에 전달하지 않음** → 기존 값 프리필 없음. 사실상 **죽은 변수**.

**DB 실태 (사용자 확인)**
```
call_57338dec_..._8ddf34b35dd8 | 교환/반품 > 교환 > 교환신청 | 2026-07-14 01:00:17.964 | ...
```
- 필드명은 `external_categories_id` 지만 **실제로 보내는 값은 경로 텍스트(`category`)** 다 (id 아님).
- 즉 **프론트가 넣은 문자열이 검증 없이 그대로 저장**된다. 잘못 넣으면 그대로 들어감.
- (현재 안전장치: 모달 저장 버튼은 `selectedItem` 있어야 활성 → API가 내려준 `categoryPath` 중 **목록에서 클릭한 것만** 저장됨. 셀렉트/검색창에 친 값은 저장 경로에 없음.)

**조치 (2026-07-14): 수정 버튼 숨김**
- 개별수정으로 가려면 **수신·렌더·저장·모달저장 4곳을 전부** 다중 배열로 바꿔야 하는데, 현 시점 애매 → **일단 버튼만 숨김.**
- `CounselingStatus.vue` 의 수정 버튼 블록을 **주석 처리** (핸들러 `editCounselingType` 는 남겨둠).

**되살릴 때 결정해야 할 것**
1. 백엔드에 상담유형 개별 수정 API 가 있는가? (사용자 확인 예정)
2. 2~3개일 때 **항목마다 수정 버튼**을 달 것인가?
3. 모달에서 고른 값이 **그 항목만 교체**인가, **전체 목록 재선택**인가?
4. `CounselingTypeModal` 의 `append-to-body` 를 `true` 로 (작게 뜨는 문제) + 모달 열 때 `handleSearch()` 자동 호출 + 셀렉트/검색어를 실제 API 에 연결.

**조치 추가 (2026-07-14): "상담유형 추가" 버튼도 숨김**
- `CounselingStatus.vue:91` 의 `[상담유형 추가]` 버튼(상담유형 **0개**일 때 뜨는 `v-else` 분기)도 **같은 `CounselingTypeModal` 을 열기 때문에** 함께 주석 처리.
- ⚠️ 단, **추가 기능 자체는 "통 교체" 문제와 무관하다.** 0개 → 1개는 현 구조(길이 1)로도 성립.
  막힌 건 **모달의 3가지 결함**(작게 뜸 / 열 때 목록 조회 안 함 / 셀렉트·검색어 API 미연결)뿐이므로,
  그 3개만 고치면 **추가는 현 구조 그대로 되살릴 수 있다.** (개별수정은 여전히 4곳 배열화 필요)
- 남은 잔재: 버튼을 감춘 자리에 **"직접 선택해 주세요."** 문구가 그대로 남아 있다(`:89`). 되살리지 않을 거면 이 문구도 정리 필요.
