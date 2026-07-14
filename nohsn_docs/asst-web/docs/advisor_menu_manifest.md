# menu-manifest.json — 포털 메뉴 신고 (PR-B r6)

> **작성일:** 2026-07-14
> **출처 요청:** `2026-06-04_pr-b-r6-asst-web-handoff.md` (포털/auth 담당자)
> **상태:** ⚠️ **구현 완료 · 비활성(OFF) 상태로 대기 중.** 새 포털 서버가 준비되면 §0 절차로 켠다.

---

## 0. ⚠️ 현재 OFF 상태 — 활성화 절차

**이 작업은 "새로 만들 포털 서버"용 준비다. 현재 운영 배포(특히 고객사 AWS)에는 영향이 가면 안 되므로 꺼두었다.**

### 지금 상태 (= 작업 이전과 100% 동일)

| 항목 | 상태 |
|---|---|
| `webpack.config.js` `exposes` | 🔴 **리뉴얼 진입점 주석 처리** (`./AdvisorRenualComponent`) |
| `package.json` build 스크립트 | 🔴 **generator 자동 실행 제거됨** (`build:dev/prd/test/aws/ncp` 전부 원래대로) |
| `public/menu-manifest.json` | 🔴 **삭제됨** (dist 에 안 실림) |
| `scripts/generate-menu-manifest.cjs` | 🟢 완성. **아무데서도 호출되지 않음** (수동 실행만 가능) |
| `.env.5f.dev` 의 `SELF_URL`/`SELF_REMOTE_NAME` | 🟢 설정됨. 5f 로컬 전용이라 배포 빌드(`MODE=aws`)엔 안 잡힘 |

→ **generator 는 완성돼 대기 중이고, 스위치만 꺼둔 상태다.**

### 켜는 방법 (새 포털 서버 준비 후)

1. **`webpack.config.js`** — `exposes` 의 리뉴얼 진입점 **주석 해제**
   ```js
   "./AdvisorRenualComponent": "./src/view/advisor-renual/index.vue"
   ```
   ⚠️ **이걸 안 풀면**, manifest 에는 리뉴얼 메뉴 13건이 실리는데 포털이 로드할 컴포넌트가 없어
   **메뉴는 보이지만 클릭하면 죽는다.** (exposes 와 manifest 는 반드시 같이 켜고 같이 꺼야 한다)
   → 리뉴얼을 계속 감출 거면 **`mockupMenuList.ts` 에서 리뉴얼 항목을 빼고** manifest 를 생성할 것.

2. **`package.json`** — build 스크립트 앞단에 generator 물리기
   ```json
   "build:aws": "cross-env MODE=aws node scripts/generate-menu-manifest.cjs && cross-env MODE=aws webpack --config webpack.config.js",
   ```
   (`build:dev` / `build:prd` / `build:test` / `build:ncp` 도 동일 패턴)

3. **배포 환경 `.env`** 에 두 줄 추가 (§6-1)
   ```bash
   SELF_URL=https://실제-asst-web-주소
   SELF_REMOTE_NAME=advisor_app
   ```
   ⚠️ **`.env.aws` 는 레포에 없다** → AWS 고객 배포 담당자에게 전달 필요.

4. 검증: `MODE=aws npm run generate:menu-manifest` → `public/menu-manifest.json` 확인

---

## 1. 이게 뭐 하는 건가

- asst-web 이 빌드할 때 **`public/menu-manifest.json`** 을 뱉는다.
- 포털이 그 파일을 읽어서
  1) **사이드바 메뉴를 동기화**하고,
  2) `selfRemoteUrl` / `selfRemoteName` 으로 **`company_conf.advisorRemoteAppUrl` / `advisorRemoteAppName` 을 자동 UPSERT** 한다.
- 목적: **운영자가 포털 환경설정에서 advisor 앱 주소를 손으로 입력하던 것을 없애는 것.**
- ⚠️ **안 만들어도 아무것도 안 깨진다** — 포털은 no-op 처리하고 기존처럼 운영자 수동 입력 모드로 동작한다(handoff §5).

---

## 2. 만든 것

| 파일 | 내용 |
|---|---|
| `scripts/generate-menu-manifest.cjs` | **신규.** 메뉴 원본을 읽어 포털 스펙으로 변환 → `public/menu-manifest.json` 생성 |
| `package.json` | **`npm run generate:menu-manifest`** 스크립트 추가 |
| `webpack.config.js` | `exposes` 에 **`./AdvisorRenualComponent`** 추가 (리뉴얼 진입점 — 기존엔 없어서 포털이 붙일 수 없었음) |
| `public/menu-manifest.json` | 생성 산출물 (메뉴 17건) |

**실행:**
```bash
SELF_URL=http://localhost:3020 SELF_REMOTE_NAME=advisor_app npm run generate:menu-manifest
```

---

## 3. 메뉴 원본은 우리 소스 안에 있다

**`src/api/modules/menus/mockupMenuList.ts`** ← 여기가 단일 원본.

- asst-web 은 메뉴를 이 **목업**에서 읽는다. (`stores/modules/auth.ts:89-92` — 서버 API 호출은 **주석 처리**돼 있고 목업을 쓰는 중)
- 즉 **메뉴를 바꾸려면 이 파일을 고치면 되고, generator 가 자동으로 manifest 에 반영한다.**
- ⚠️ 담당자에게 물어볼 필요 없다. (분석 중 "포털이 메뉴 원천"이라고 잘못 판단해 헤맸음 — **우리 소스부터 확인할 것**)

### 목업 → 포털 스펙 자동 변환 규칙

| 포털 필드 | 목업에서 | 변환 |
|---|---|---|
| `code` | `code` | **`ADVISOR_` 접두어 강제** (포털 필수 규칙, 위반 시 백엔드가 거부) → `AGENT_RENEWAL` → `ADVISOR_AGENT_RENEWAL`, `RENUAL_*` → `ADVISOR_RENUAL_*` |
| `parentCode` | `parentId` (숫자) | 해당 항목의 `code` 로 변환. **최상위는 포털 시드 루트(`ADVISOR_HUB`)에 붙임** |
| `name` | `name` | 그대로 |
| `iconName` | `iconName` | 그대로 (목업이 전부 `dashboard`) |
| `sortOrder` | `sortOrder` | 그대로 |
| `routeType` | — | `component` 있으면 **`FEDERATION`**, 없으면(그룹헤더) `DEFAULT` |
| `routePath` | `routePath` | 앞에 `/` 부여 (`advisor/consultant` → `/advisor/consultant`) |
| `component` | — | **`COMPONENT_BY_CODE` 매핑 테이블**(스크립트 상단)에서 부여 |
| `isVisible` | `isActive` | 이름만 매핑 |
| `description` | `description` | 있으면 그대로 |

**정렬:** 부모 → 자식 순으로 평탄화. (포털이 배열 순서대로 넣으며 `parentCode` 로 부모를 찾기 때문에 **순서가 곧 계약**이다)

**`checksum`:** `menus` 를 `JSON.stringify` 해 sha256 → `sha256-<64 hex>`.
포털은 **`version` / `serviceType` / `menus` 가 배열인지 3가지만 얕게 검증**하고 checksum 은 그대로 echo back 한다(담당자 확인). 그래도 관례상 정확히 계산해 넣는다.

---

## 4. 생성 결과 (메뉴 17건)

```
ADVISOR_HUB (포털 시드 루트 — 우리가 만들지 않음)
├─ ADVISOR_CONSULTANT          상담어드바이저          FEDERATION  ./AdvisorConsultantComponent
├─ ADVISOR_ADMIN               상담어드바이저 관리자    FEDERATION  ./AdvisorConsultantComponent
├─ ADVISOR_ADMIN_GROUP         사용자 관리 페이지       FEDERATION  ./AdvisorManagementUser
└─ ADVISOR_AGENT_RENEWAL       상담원 페이지 리뉴얼     FEDERATION  ./AdvisorRenualComponent
   ├─ ADVISOR_RENUAL_G_WORKSPACE   워크스페이스   DEFAULT (그룹헤더)
   │  ├─ ADVISOR_RENUAL_DASHBOARD      대시보드
   │  ├─ ADVISOR_RENUAL_CHAT           상담화면
   │  └─ ADVISOR_RENUAL_CALL_HISTORY   통화 이력
   ├─ ADVISOR_RENUAL_G_TOOLS       내 도구        DEFAULT (그룹헤더)
   │  ├─ ADVISOR_RENUAL_BOOKMARK / MEMO / TODO / NOTICE
   └─ ADVISOR_RENUAL_G_COACHING    코칭·설정      DEFAULT (그룹헤더)
      └─ ADVISOR_RENUAL_COACHING / DETECT_WORD / SETTINGS
```

### `component` 매핑 (`generate-menu-manifest.cjs` 상단 `COMPONENT_BY_CODE`)

| 메뉴 | component | 비고 |
|---|---|---|
| `ADVISOR_CONSULTANT` | `./AdvisorConsultantComponent` | |
| `ADVISOR_ADMIN` | `./AdvisorConsultantComponent` | ⭐ **CONSULTANT 와 같은 컴포넌트.** `consultant/index.vue` 가 `getUser().agent.role` 로 **관리자/상담사 화면을 자체 분기**하기 때문(`:10-11`, `:77`). 포털이 두 개를 따로 로드하는 게 아니라, **같은 MF 컴포넌트가 로그인 권한에 따라 다른 얼굴을 보여주는 구조** |
| `ADVISOR_ADMIN_GROUP` | `./AdvisorManagementUser` | |
| `ADVISOR_AGENT_RENEWAL` + 리뉴얼 리프 전부 | `./AdvisorRenualComponent` | 진입점 하나가 `routePath` 로 내부 라우팅 |
| `ADVISOR_RENUAL_G_*` (그룹헤더) | **없음** | 자체 페이지가 없는 헤더 → `routeType: DEFAULT` |

---

## 5. ⚠️ 내가 임의로 정한 값 — 확인/수정 필요

### 5-1. `PORTAL_ROOT_CODE = "ADVISOR_HUB"`
- handoff 문서에 *"root는 `ADVISOR_HUB`**(또는 `AICC_PLATFORM`)**"* 라고 **둘 다** 적혀 있어 앞의 것을 택했다.
- **틀리면 `scripts/generate-menu-manifest.cjs` 상단 `PORTAL_ROOT_CODE` 한 줄만 고치면 된다.**

### 5-2. 리뉴얼을 `exposes` 에 추가한 것
- 기존 `exposes` 는 2개뿐이라(`AdvisorConsultantComponent`, `AdvisorManagementUser`) **리뉴얼은 포털이 로드할 수 없는 상태**였다.
- → `webpack.config.js` 에 `./AdvisorRenualComponent` 를 추가했다.
- ⚠️ **리뉴얼 하위 리프(대시보드/상담화면/…)를 전부 같은 컴포넌트로 매핑**했다. 포털이 `FEDERATION` 메뉴 클릭 시 `component` 를 로드한 뒤 `routePath` 로 내부 라우팅한다는 **전제**다. 포털이 메뉴마다 **별도 컴포넌트를 요구**한다면 리프별로 `exposes` 를 늘려야 한다. → **담당자 확인 필요.**

### 5-3. 메뉴 통합 예정
- 사용자 방침: **나중에 리뉴얼이든 현재든 하나만 남긴다.**
- 그때는 **`mockupMenuList.ts` 에서 해당 항목만 지우면** generator 가 알아서 반영한다. (manifest 를 직접 손댈 필요 없음)

### 5-4. `iconName`
- 목업이 전부 `dashboard` 라 그대로 나간다. 바꾸려면 **목업에서** 고칠 것.
- 포털 규칙: 소문자+`_` (예: `support_agent`)

---

## 6. 배포 연결

### 6-1. 환경변수 2개 — ✅ 설정 방식 확정

| 변수 | 값 | 비고 |
|---|---|---|
| `SELF_REMOTE_NAME` | **`advisor_app`** | `webpack.config.js:92` 의 MF `name` 과 **반드시 동일**. 환경 무관 고정 |
| `SELF_URL` | **asst-web 자신이 뜨는 외부 URL** | 포털이 `{SELF_URL}/remoteEntry.js` 를 가지러 온다. 환경마다 다름 |

⚠️ **`SELF_URL` 은 백엔드(`LANGSA_GATEWAY_URL`)가 아니라 프론트(asst-web) 주소다.** 헷갈리기 쉬움.

**설정 예시** (`.env.5f.dev`):
```bash
# 메뉴적용
SELF_URL=http://124.194.32.36:32026
SELF_REMOTE_NAME=advisor_app
```

**generator 는 webpack 과 동일하게 `.env.{MODE}` 를 읽는다.** (`generate-menu-manifest.cjs` 상단)
generator 는 webpack 과 별도 프로세스라 dotenv 로딩을 직접 해야 한다. 셸에서 준 env 가 우선한다.

**env 미설정 시:** 경고만 찍고 `selfRemoteUrl`/`selfRemoteName` 을 **생략**한 채 정상 생성된다(handoff §3.2 정합).
**빌드는 깨지지 않고**(exit 0) 메뉴 부분도 정상이다. 포털은 기존처럼 **운영자 수동 입력 모드**로 동작.

⚠️ **`.env.aws` 는 레포에 없다.** `Dockerfile` 이 `yarn build:aws`(`MODE=aws`)로 빌드하므로,
**AWS 고객 배포 시에는 배포 담당자가 `.env.aws` 에 위 두 줄을 추가해야** `advisorRemoteAppUrl` 자동 UPSERT 가 동작한다.
(안 넣어도 빌드는 정상 — 수동 입력 모드로 남을 뿐)

### 6-2. 빌드 자동 생성 — ✅ 적용 완료

`package.json` 의 모든 build 스크립트 앞단에 generator 를 물렸다:
```json
"build:dev":  "cross-env MODE=dev  node scripts/generate-menu-manifest.cjs && cross-env MODE=dev  webpack …",
"build:prd":  "cross-env MODE=prd  node scripts/generate-menu-manifest.cjs && cross-env MODE=prd  webpack …",
"build:test": "cross-env MODE=test node scripts/generate-menu-manifest.cjs && cross-env MODE=test webpack …",
"build:aws":  "cross-env MODE=aws  node scripts/generate-menu-manifest.cjs && cross-env MODE=aws  webpack …",
"build:ncp":  "cross-env MODE=ncp  node scripts/generate-menu-manifest.cjs && cross-env MODE=ncp  webpack …",
```
→ 빌드마다 **최신 메뉴 + 그 환경의 `SELF_URL`** 로 manifest 가 자동 생성되고,
webpack 이 `public/` 을 `dist/` 로 복사하므로 **배포물에 함께 실린다.**

수동 실행도 가능: `MODE=5f.dev npm run generate:menu-manifest`

### 6-3. 🔲 포털이 이 파일을 어떻게 읽어가는지 미확인
- `public/` 에 두면 `https://{asst-web}/menu-manifest.json` 으로 노출되긴 한다(nginx `location /` 서빙).
- 그런데 **포털이 그 URL 을 fetch 하는지 / 주기적으로 sync 하는지 / 배포가 포털로 push 해야 하는지** handoff 문서에 없다.
- ⚠️ **닭-달걀 의문:** 포털이 manifest 를 읽으려면 asst-web 주소를 이미 알아야 하는데, 이번 작업의 목적이 바로 **그 주소(`advisorRemoteAppUrl`)를 자동으로 채우는 것**이다. 순환이다.
  → 실제로는 포털이 별도 경로(배포 설정/CI 변수/k8s 서비스명)로 base URL 을 알고 있을 가능성이 크다. **담당자 확인 필요.**

---

## 6-4. 메뉴별 role 접근권한 — **포털이 관리한다 (확정)**

> **방침 확정(2026-07-14):** 메뉴별 권한 노출은 **포털 쪽에서 관리**한다. asst-web 은 메뉴를 *신고*만 하고,
> "어떤 role 에게 어떤 메뉴를 보여줄지"는 포털 담당자가 설정한다. → **프론트 추가 작업 없음.**

### 현재 상태 (참고)

**role 은 5개인데 화면 분기는 2개다.**

| role | 우선순위 | (`management/user/index.vue:70-82`) |
|---|---|---|
| `SYSTEM` | 5 | |
| `ADMIN` | 4 | |
| `NORMAL` | 3 | |
| `SUPERVISOR` | 2 | |
| `AGENT` | 1 | |

```js
// consultant/index.vue:77 — AGENT 면 상담사 화면, 그 외 전부(SYSTEM/ADMIN/NORMAL/SUPERVISOR) 관리자 화면
resolvedRole.value = userResponse.agent?.role === "AGENT" ? "agent" : "admin";
```

**asst-web 자체의 메뉴 권한 필터는 꺼져 있다.**
- 원래 설계: `dynamicRouter.ts:22` 가 `authStore.getAuthMenuList()` 로 **서버가 role 에 맞는 메뉴만 내려주면**
  그걸로 동적 라우터를 생성 → **"메뉴 목록 = 권한"** 구조. 메뉴의 `isReadonly` 로 읽기전용 권한까지 표현 가능
  (`routers/index.ts:80` → `authStore.setIsReadOnly(to.meta.isReadonly)`).
- 그런데 **`auth.ts:89-92` 에서 서버 API 호출이 주석 처리**되고 목업을 쓰는 중이라,
  **누가 로그인하든 동일한 메뉴 17건이 전부 내려온다.** → role 필터링 무력화 상태.
- ⚠️ handoff 의 `menus[]` 스펙엔 **권한 필드가 아예 없다** (`isVisible` 은 단순 boolean).
  → 권한 매핑은 manifest 밖(포털)에서 이뤄진다는 뜻이고, 위 확정 방침과 일치한다.

**나중에 asst-web 자체 권한 제어가 필요해지면:** `auth.ts` 의 주석을 풀어 서버 API 로 메뉴를 받아오게 하고,
서버가 role 별로 메뉴를 걸러 내려주면 된다(원래 설계 복원). 백엔드 작업 필요.

---

## 7. 담당자에게 물어볼 것 (남은 3개)

1. **`PORTAL_ROOT_CODE` 는 `ADVISOR_HUB` 인가 `AICC_PLATFORM` 인가?** (문서에 둘 다 적혀 있음)
2. **포털이 `menu-manifest.json` 을 어디서/언제 읽어가나?** (`public/` 배포로 끝인지, push 가 필요한지)
3. **`FEDERATION` 메뉴는 리프마다 별도 `component` 가 필요한가?** 아니면 진입점 하나 + `routePath` 내부 라우팅으로 되나? (리뉴얼 13개 메뉴가 여기에 걸림 — §5-2)

---

## 8. 교훈

- **남에게 묻기 전에 우리 소스부터 grep 할 것.** 메뉴 원본(`mockupMenuList.ts`)이 레포 안에 있었는데, "포털이 원천"이라고 단정하고 담당자에게 되묻느라 시간을 버렸다.
- handoff 문서는 **"이미 generator 가 있는 프로젝트"를 전제로** 쓰여서, `menus` / `checksum` 처럼 **원래 있던 항목의 설명이 통째로 생략**돼 있었다. 없는 걸 처음 만드는 쪽은 그 생략된 부분이 전부 미지수가 된다.
