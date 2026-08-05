# asst-web 서버별 메뉴 / 배포 구조 정리

> 한 소스(asst-web)를 **5f · 106 · aws** 3서버로 배포하는데 **서버마다 메뉴 노출 구조가 다르다.**
> 106이 특히 특수 케이스. 이 문서는 그 구조와 "서버별로 다르게 하되 브랜치는 안 따는" 방법을 정리한다.

---

## 1. 배포 방식이 서버마다 다르다 (핵심)

메뉴가 서버별로 갈리는 근본 이유는 **각 서버가 배포될 때 하는 일이 다르기 때문**이다.

| 서버 | 배포 파일 | 실행 커맨드 | `generate-menu-manifest` | devServer 설정(CORS 등) |
|------|-----------|-------------|:---:|:---:|
| **106** | `docker-compose.dev.106.yml` | `generate-menu-manifest.cjs` **+** `webpack serve` (MODE=106.dev) | ✅ 실행 | ✅ 적용 |
| **5f** | `docker-compose.dev.5f.yml` | `webpack serve` 만 (MODE=5f.dev) | ❌ **미실행** | ✅ 적용 |
| **aws** | `Dockerfile` → `build:aws` | `generate-menu-manifest.cjs` + `webpack` **빌드** → nginx (MODE=aws) | ✅ 실행 | ❌ 무시(build라서) |

**여기서 나오는 중요한 결론:**
- `mockupMenuList.ts`(메뉴 원본)를 수정하면
  - **106** → manifest 재생성하므로 포털 메뉴에 **반영됨**
  - **5f** → generator를 안 돌리므로 포털 메뉴 **무영향** (재생성이 없음)
  - **aws** → 다음 빌드 때 **반영됨**
- `webpack.config.js`의 `devServer` 블록(CORS 헤더 등)은 **`webpack serve`(5f·106)에만** 적용되고, **aws는 `webpack` 빌드 + nginx**라 통째로 무시된다. (aws의 CORS/캐시는 `nginx.conf` 담당)

---

## 2. 메뉴 파이프라인

```
src/api/modules/menus/mockupMenuList.ts   ← 메뉴 트리 원본(블록/그룹/리프, routePath)
        │  scripts/generate-menu-manifest.cjs (배포 시 webpack 앞단에서 실행)
        │  · .env.{MODE} 읽어 SELF_URL 등 주입
        │  · 메뉴 code → COMPONENT_BY_CODE 로 MF 컴포넌트 매핑
        ▼
public/menu-manifest.json                 ← 빌드 산출물(커밋 안 함). 포털이 {SELF_URL}/menu-manifest.json 로 가져감
        ▼
포털(:32000) 사이드바                       ← manifest 기반으로 3단 패널 메뉴 렌더
        ▼
webpack.config.js exposes                  ← FEDERATION 메뉴가 클릭 시 실제로 로드할 컴포넌트
```

- **메뉴 링크·이름·순서**는 `mockupMenuList.ts`에서 나온다. (`exposes`가 아님)
- **런타임도 이 파일을 쓴다**: `mockupMenu.ts` → `getAuthMenuListMockup()` → `auth.ts` 스토어. (단, 포털 임베드 모드에선 사이드바는 포털이 그리므로 런타임 메뉴는 standalone 용)
- 블록/그룹 헤더는 자체 페이지가 없어 `COMPONENT_BY_CODE`에 매핑 안 함 → `routeType: DEFAULT`. 실제 리프만 `FEDERATION`.

---

## 3. 106 메뉴 구조 (4블록)

106은 최상위를 **블록 4개**로 나눈다. (`mockupMenuList.ts` 상단 주석 참고)

```
상담원 페이지          → 상담 어드바이저(현행)
상담원 리뉴얼 페이지    → 워크스페이스 / 내 도구 / 코칭·설정
관리자 페이지          → 상담 어드바이저 관리자(현행) / 사용자 관리 페이지
관리자 리뉴얼 페이지    → 모니터링 / 관리 / 설정
```

- 블록 code: `AGENT_PAGE` / `AGENT_RENUAL_PAGE` / `ADMIN_PAGE` / `ADMIN_RENUAL_PAGE`
  (generator가 `ADVISOR_` 접두어 부여 → `ADVISOR_AGENT_PAGE` …). role 매핑은 포털이 code로 처리.
- 리프 code(`ADVISOR_CONSULTANT`, `RENUAL_*`, `RENUAL_ADMIN_*`)는 `COMPONENT_BY_CODE`에서 아래 3개로 매핑:
  - `./AdvisorConsultantComponent` (현행 상담사/관리자 — role 자체 분기)
  - `./AdvisorManagementUser` (사용자 관리)
  - `./AdvisorRenualComponent` (리뉴얼 전체 — 진입점 하나가 내부에서 분기)

> ⚠️ **5f·aws는 아직 이 4블록이 아니다.** 5f는 generator 미실행이라 무영향, aws는 "당분간 건드리지 않음"으로 합의됨. 나중에 서버별로 구조를 더 갈라야 하면 4번 방식 사용.

---

## 4. 서버별로 다르게 하는 방법 (브랜치 금지)

**브랜치를 따로 따는 건 금지(관리 극악).** 서버별 차이는 아래 두 통로로만 만든다.

### (A) `.env.{MODE}` 값 — 서버별로 이미 갈리는 정식 파일
`webpack.config.js:14-15`에서 `MODE`로 `.env.{MODE}`를 읽어 `DefinePlugin`으로 `process.env.KEY` 주입.
→ SELF_URL, API URL 등 **환경값**은 여기서 서버별로 갈린다.

### (B) 공용 코드 + `.env` 플래그 게이팅 — 동작 차이를 서버별로
공용 컴포넌트(예: `AdvisorRenualComponent`)는 **모든 서버 번들에 박히므로**, 코드에 직접 넣으면 5f·aws도 바뀐다.
그래서 **플래그로 감싸고, 그 플래그를 특정 서버 `.env`에만** 넣는다.

**원칙: 플래그가 없거나 `undefined`면 반드시 "수정 전 기본 동작"으로 폴백.** (특수 서버만 opt-in)

**실제 예 — 리뉴얼 리프 라우팅 (106 전용):**
- `src/view/advisor-renual/index.vue`:
  ```js
  // 없으면 undefined → false → 기존 사이트맵 유지 (106만 opt-in)
  const LEAF_ROUTING = process.env.VITE_RENUAL_LEAF_ROUTING === "true";
  const activeLeaf = computed(() => {
    if (!LEAF_ROUTING) return null;            // 5f·aws: 기존 허브(사이트맵)
    const m = route.path.match(/advisor-renual\/(.+)$/);
    return m ? (LEAF[m[1].replace(/\/+$/, "")] ?? null) : null;
  });
  ```
- `.env.106.dev`에만:
  ```
  VITE_RENUAL_LEAF_ROUTING = true
  ```

결과: **106** = 리프 클릭 시 실제 페이지 / **5f·aws** = 기존 사이트맵 허브 그대로.

---

## 5. 오늘(2026-07-15) 작업 내역

| # | 이슈 | 수정 | 서버 스코프 |
|---|------|------|-------------|
| 1 | 배포 후 `remoteEntry.js` / API **CORS 차단** | `webpack.config.js` `devServer.headers`에 `Access-Control-Allow-Origin` 등 추가 | 5f·106(serve 공통). aws는 nginx라 무관. 백엔드(:32025) CORS는 백엔드가 별도 처리 |
| 2 | 106 메뉴를 **4블록 구조**로 | `mockupMenuList.ts` 재구성 + `generate-menu-manifest.cjs`/`advisor-renual/index.vue` 주석 정리 | 106 반영(5f 무영향 / aws 다음 빌드) |
| 3 | 리뉴얼 리프 클릭 시 **사이트맵 대신 실제 페이지** | `advisor-renual/index.vue` route-aware(+`VITE_RENUAL_LEAF_ROUTING` 게이트), `.env.106.dev` 플래그 | **106만** (5f·aws는 플래그 없어 기존 사이트맵) |

### CORS 배경
- webpack-dev-server **v5.2.1+** 부터 기본 permissive CORS(`ACAO:*`)가 제거됨 → 호스트 포털(:32000)이 다른 origin의 remote(:32026) `remoteEntry.js`를 못 가져와 차단. 그래서 `devServer.headers`로 명시적으로 열어야 함.

---

## 6. 배포 / 확인

**106 반영:** `docker-compose.dev.106.yml` 컨테이너 재기동
→ generator가 manifest 새로 굽고 `webpack serve` 재기동.
→ 브라우저 **강력 새로고침**(캐시된 remoteEntry 때문).

**확인 포인트:**
- remoteEntry / get_user CORS 에러 사라졌는지 (콘솔)
- 사이드바 4블록 구조로 뜨는지
- 리뉴얼 리프(통화이력/대시보드 등) 클릭 시 실제 페이지로 가는지 (사이트맵 아님)

---

## 7. role별 메뉴 노출 — 상담사에게 관리자 메뉴 노출 이슈 (2026-07-16 분석)

**증상:** localhost:8173(standalone)에서 **상담사 계정으로 로그인해도 관리자 메뉴**(관리자 페이지 · 관리자 리뉴얼 페이지 블록)가 그대로 노출됨.

**원인 = 우리(프론트). 포털/백엔드 무관.**
- `auth.ts getAuthMenuList()`가 포털 API(`getAuthMenuListApi` — **이름만 있고 구현체 없음**, 89줄 주석)가 아니라 **`getAuthMenuListMockup()`**(프론트 목업)을 사용.
- 목업(`mockupMenuList.ts`)엔 **role/permission 필드 자체가 없고**, `makeMenuOfTree()`/`buildMenuItem()` 어디에도 **role 필터 로직이 전무** → 상담사·관리자 구분 없이 **4블록 전부** 노출.
- 백엔드 게이트웨이(`path.ts`)에 **메뉴 엔드포인트 0개**, 프론트에도 메뉴 수신 API 배선 없음(메뉴는 100% 목업).
- 목업 상단 주석이 설계의도 명시: "role별 노출은 포털이 code로 매핑. manifest엔 role 필드 없어 **지금은 네 블록 모두 보임(=폴백)**."

**포털(106) 확인(super4 메뉴관리, MCP):** `AICC 플랫폼 › 상담 어드바이저(6)`에 asst-web 4블록이 매니페스트 동기화돼 있음. **메뉴 상세엔 role 매핑 필드 없음**(노출여부 스위치만) → role별 노출은 메뉴관리가 아니라 계정/권한 영역.

**✅ 해결 방향(확정) — 백엔드 새 API 불필요:**
- `get_user` 응답의 **`agent.role`** 로 프론트에서 목업 블록을 필터. 상담사(`role === "AGENT"`)면 ADMIN 블록(id **95 `ADMIN_PAGE`** · **96 `ADMIN_RENUAL_PAGE`**) 제외, 관리자면 전체 노출.
- 적용 위치: `auth.ts getAuthMenuList()` **한 곳**(목업 로드 후 role 필터).
- role 위치 확인됨: admin 페이지들이 이미 `agent.role !== "AGENT"` 로 분기 중.

**⏸ 대기 사유 (2026-07-16 기준):** 현재 **`get_user` 가 403** → role 을 못 받아 필터 기준이 없어 무의미. **get_user 403 정상화 후** role 필터 1곳 추가 예정.
- (참고) 현재 메뉴 전량 노출 자체는 **role 필터 부재** 탓이지 403 탓은 아님. 다만 정석 필터는 role 값이 있어야 동작하므로 403 선결 필요.
