# Module Federation 실측 기록 (개발 서버)

> 개념·설계는 `module-federation-개념과-구조-가이드.md` 참고. **이 문서는 실제 배포된 개발 서버를 브라우저로 접속해 측정한 원본 기록**이다.
> MF는 정합성 검증이 런타임에만 가능하므로(빌드로는 알 수 없다), 이런 실측 스냅샷이 유일한 근거 자료가 된다.
> 값이 바뀌었는지 비교할 수 있도록 **측정값을 가공 없이 남긴다.**

---

## 측정 이력

| 회차 | 일자 | 계정 | 권한 범위 | 비고 |
|---|---|---|---|---|
| 1차 | 2026-08-03 | `agent01` (상담사) | **어드바이저 앱만 접근 가능** | 아래 1차 결과 |
| 2차 | 2026-08-03 | `system` (관리자) | 전체 메뉴 (113개) | **remote 7개 전수 측정.** 1차 미해결 과제 확정 |

> ⚠️ **1차의 한계**: `agent01` 은 어드바이저 앱만 구동되는 계정이라, **포털에 붙는 다른 remote 앱은 측정 범위에 없다.**
> 따라서 아래 결과는 "host_app ↔ advisor_app 2자 관계"에 한정된 것이며, 앱이 늘어나면 결론이 달라질 수 있다.

---

# 1차 측정 — 2026-08-03 / `agent01`

## 1. 측정 환경

| 항목 | 값 |
|---|---|
| 포털(host) | `http://124.194.32.36:62000` |
| 로그인 계정 | `agent01` (상담사, 어드바이저 앱 전용) |
| 측정 방법 | Chrome DevTools Protocol (별도 프로필로 띄운 Chrome, 기존 브라우저 미간섭) |
| 측정 경로 | `#/advisor/consultant` → `#/advisor-renual/chat` |

## 2. 페더레이션 구성 (실측)

```
MF 컨테이너 (window):  host_app, advisor_app

remoteEntry:
  http://124.194.32.36:62000/remoteEntry.js                      ← host
  http://124.194.32.36:62020/remoteEntry.js?t=1785724856534      ← advisor remote

리소스 오리진 분포:
  http://124.194.32.36:62000  : 22건   (host 정적 자원)
  http://124.194.32.36:62009  : 34건   (API 게이트웨이)
  http://124.194.32.36:62020  : 30건   (advisor remote 청크)
  https://code.highcharts.com :  1건
```

**확인된 사실**

- **우리 remote 배포 주소는 `62020`.** `62009` 는 API 게이트웨이이며 정적 자원 출처가 아니다
  (로컬 `.env.*` 의 `LANGSA_GATEWAY_URL`/`DEV_PROXY_TARGET` 이 가리키는 곳과 역할이 다르다).
- remote 청크가 **62020(자기 도메인)에서** 내려온다 → `output.publicPath: "auto"` 가 의도대로 동작 중.
- 포털이 remoteEntry 에 **`?t=<타임스탬프>` 캐시 버스터**를 붙이고 있다.
  → 페이지 로드마다 최신 청크맵을 받으므로 host 쪽에서도 ChunkLoadError 위험을 완화하고 있다.
  (관련: `webpack-mf-chunkload-fix-guide.md`)

## 3. shared 협상 결과 — ✅ 정상

```
vue 앱 인스턴스 수 : 1
vue 버전          : ["3.5.18"]     ← 우리 package.json 의 vue 와 정확히 일치
```

Vue 인스턴스가 **하나**이므로 pinia·vue-router 도 단일 인스턴스로 동작 중이다.
`webpack.config.js:117-121` 의 `singleton: true` 설정이 host와 정상 협상되었다는 뜻.

> `__webpack_share_scopes__` 는 webpack 런타임 내부 변수라 **window 로는 접근 불가**였다(`shareScopeAccessible: false`).
> 따라서 협상 결과는 **"Vue 앱 인스턴스 수 = 1"** 로 간접 확인하는 것이 현실적인 방법이다.
> (가이드 11-4 ①의 콘솔 명령은 host 빌드에 따라 안 통할 수 있음 — 이 방법을 우선 쓸 것)

## 4. 다크모드 — ✅ 정상

```
<html class="dark">          ← host 가 설정. body class 는 없음
--el-color-primary        : #1B3A5C
--el-bg-color             : #141414
--el-text-color-primary   : #e5eaf3
--el-mask-color           : #000c
```

- element-plus **다크 CSS 변수가 정상 로드**되어 있다 → host 가 dark css-vars 를 공급 중.
- `<html>` 클래스가 `dark` 단독이다. 우리 `useTheme.ts:20-24` 는 `"highcharts-dark dark"` 를 넣으므로,
  **임베드 환경에서 `useTheme` 가 실행되지 않는다는 것이 실측으로 확인**되었다 (가이드 12-2 ①과 일치).

## 5. 리프 라우팅 — ✅ 정상

```
이동: location.hash = "#/advisor-renual/chat"
결과: hasHub=false, adv-remote-scope 존재, 브레드크럼 "상담원 리뉴얼 페이지 / 워크스페이스 / 상담화면"
```

배포된 62020 빌드에도 `VITE_RENUAL_LEAF_ROUTING` 이 켜져 있고, 허브가 아니라 **리프(상담화면)가 정상 렌더**된다.

## 6. element-plus — ⚠️ 이중 카운터 관측

### 6-1. 원본 측정값

**`#/advisor/consultant` (상담화면) 시점 — 인라인 z-index**

```
3003 el-overlay el-modal-dialog
3004 el-popper ... el-dropdown__popper
3005 el-overlay el-modal-dialog
3006 el-popper ... el-dropdown__popper
3007 el-popper ... el-popover adv-popper…
3008 el-popper ... el-picker__popper
3009 el-popper ... el-picker__popper
3010 el-overlay adv-modal-container el-modal-dialog
3011 el-popper ... adv-popper…
3012 el-popper ... adv-popper…
3013 adv-memo-editor-modal el-modal-dialog
3014 adv-bookmark-detail-modal el-modal-dialog
3015 adv-memo-editor-modal el-modal-dialog
9999 el-overlay adv-modal-container chat-history-overlay   (×3)
```

**`#/advisor-renual/chat` 이동 후**

```
2001 el-overlay adv-modal-container   (부모: ecp-container adv-page-content adv-chat-…)
2002 el-overlay adv-modal-container   (부모: ecp-container adv-page-content renual-ch…)
2003 el-overlay adv-modal-container   (부모: ecp-container adv-page-content renual-ch…)
3003 el-overlay el-modal-dialog
3004 el-popper ... el-dropdown__popper       "refresh 새로고침 fullscreen 최대…"
3005 el-overlay el-modal-dialog
3016 el-popper ... status-dropdown           "대기 중 후처리 휴식 업무 외"
3017 el-popper ... rnb-popover               "알림 미확인 2건 코칭…"
3018 el-popper ... adv-popper-container
3019 el-overlay voc-history-overlay
3020 el-overlay adv-modal-container el-modal-dialog
3021 el-popper ... el-autocomplete__popper adv-know…
3022 el-overlay el-modal-dialog
9999 el-overlay adv-modal-container chat-history-overlay
```

**기타 지표**

```
element-plus id 네임스페이스 : { "3580": 10 }      ← 1개
포퍼 컨테이너                : ["el-popper-container-3580"]   ← 1개
--el-color-primary 포함 style 태그 : 4개
CSS link 태그               : 4개 (전부 62000/css/*.css)
el- 클래스 요소 총계         : 407 (그중 adv-remote-scope 내부 115)
미해석 el- 태그              : 0개   ← 전역 등록이 정상 동작 중
```

### 6-2. 관측된 이상

**두 개의 독립된 z-index 시퀀스가 존재한다.**

| 대역 | 진행 | 대상 |
|---|---|---|
| **3000 기반** | 상담화면 3003→3015, 리뉴얼 이동 후 **3016→3022 로 연속** | 포털 UI + 우리 팝오버/일부 모달 |
| **2000 기반** | 리뉴얼 진입 후 **2001 부터 새로 시작** | 우리 리뉴얼 인라인 모달 |

element-plus 는 전역 카운터를 증가시키며 z-index 를 발급한다.
카운터가 하나라면 리뉴얼 진입 시점(이미 15까지 소진)에 새 팝업은 **16 이후**를 받아야 한다.
그런데 2000 대역은 **1 부터 다시 시작**했다 → **카운터가 두 개**라는 뜻.

### 6-3. 해석 (확정 아님)

가장 설명력 있는 가설:

| 작성 방식 | 사용되는 element-plus | 결과 |
|---|---|---|
| `<el-dialog>` 등 **전역 태그** | **host 의 element-plus** | base 3000, 카운터 22까지 진행 |
| `import { ElDialog } from "element-plus"` | **우리 번들의 element-plus** | base 2000, 카운터 1부터 시작 |

**반증 요소**: id 네임스페이스와 포퍼 컨테이너가 **각각 1개뿐**이다.
인스턴스가 둘이면 보통 2개가 관측된다. 우리 쪽 인스턴스가 아직 id·popper 를 만든 적이 없어서
안 보이는 것으로 설명은 되지만 **확증은 아니다.**

> **가이드 11-3 의 권고("전역 태그 대신 명시적 import")와 상충할 수 있는 결과**다.
> 명시적 import 는 host 의존은 끊어주지만, 이 가설이 맞다면 **우리 번들 copy 를 쓰게 되어 z-index 정합은 오히려 어긋난다.**
> 2차 측정에서 확정할 것.

### 6-4. 실질 영향

- 2000 대역(우리 리뉴얼 인라인 모달)은 3000 대역(포털 드롭다운·팝오버)보다 **아래에 깔린다.**
  겹치는 위치에서 동시에 열리면 포털 팝업이 우리 모달을 가린다.
- 현재 화면이 깨져 보이지는 않는다. 실제 겹침 상황이 아직 발생하지 않았을 뿐이다.

## 7. 하드코딩 z-index 9999 — ⚠️ 확인 필요

```
9999  el-overlay adv-modal-container chat-history-overlay
```

출처는 SCSS 가 아니라 **컴포넌트에 명시된 prop** 이다.

```
src/view/advisor/components/ChatHistoryModal.vue:2        :z-index="9999"
src/view/advisor/components/chat/ManageWorkspace.vue:2     :z-index="9999"
```

측정된 element-plus 최대값이 **3022** 이므로, `9999` 는 **포털의 어떤 요소보다도 위**에 놓인다.
"우리가 안 가려지는" 이유이자, 동시에 **포털 모달이 떠야 할 때도 우리가 덮어버리는** 원인이다.
의도된 값인지 확인이 필요하다.

## 8. 1차 종합

| 항목 | 판정 | 근거 |
|---|:---:|---|
| vue / pinia / vue-router 공유 | ✅ | vue 앱 1개, 3.5.18 단일 |
| 다크모드 | ✅ | `html.dark` + el 다크 변수 정상 |
| 리프 라우팅 | ✅ | `#/advisor-renual/chat` 리프 렌더 |
| publicPath | ✅ | remote 청크가 62020 에서 로드 |
| 청크맵 캐시 | ✅ | host 가 `?t=` 캐시 버스터 사용 |
| 전역 el- 태그 해석 | ✅ | 미해석 태그 0개 (host 가 전역 등록 중) |
| element-plus z-index 정합 | ⚠️ | 이중 카운터. 우리 인라인 모달이 포털 팝업 아래 |
| 하드코딩 9999 | ⚠️ | 포털 전체를 덮음 |

**결론: 치명적 문제 없음.** 프레임워크 공유는 정상이고, 관측된 이상은 element-plus z-index 정합 하나뿐이며 현재 화면 오류로 이어지지는 않았다.

---

# 2차 측정 — 2026-08-03 / `system` (전체 권한)

전체 조회 계정으로 **포털에 붙는 remote 앱 전부**를 로드하며 측정했다. 1차의 미해결 과제(element-plus 중복 여부)가 확정되었다.

## 9. 전체 페더레이션 지형도 (실측)

포털에 붙는 remote는 **총 6개 + host 1개 = 7개**다.

| 컨테이너명 | remoteEntry 주소 | 담당 영역 | 메뉴 수 |
|---|---|---|---:|
| `host_app` | `62000/remoteEntry.js` | 포털 셸 | — |
| `aicc_user_service` | `62000/mf-app/remoteEntry.js` | 관리(메뉴/권한/계정/라이선스) | 9 (BASIC 11) |
| **`advisor_app`** | **`62020/remoteEntry.js`** | **상담 어드바이저 (이 저장소)** | ADVISOR 31 |
| `qa_app` | `62041/remoteEntry.js` | QA 평가 | QA 32 |
| `ta_app` | `62031/remoteEntry.js` | TA 분석 | TA 17 |
| `aicm_app` | `62056/remoteEntry.js` | 지식/문서 관리 | AICM 8 |
| `ce_app` | `62010/remoteEntry.js` | AI 에이전트/워크플로우 | AI 14 |

> `aicc_user_service` 만 **host와 같은 오리진(62000)의 `/mf-app` 경로**에 배포되어 있다. 나머지는 전부 별도 포트.

**메뉴 구성** (`/aicc/portal-service/api/portal/v1/menus`)

```
총 113개  ·  routeType: FEDERATION 81 / DEFAULT 32
serviceType: QA 32, ADVISOR 31, TA 17, AI 14, BASIC 11, AICM 8
```

메뉴 레코드에 `remoteName` / `remoteUrl` / `component` / `federationAppId` 필드가 있지만,
**값이 채워진 것은 `aicc_user_service` 9건뿐**이고 나머지 72건은 `remoteName: null` 이다.
→ 나머지 앱은 **host 빌드에 정적으로 박힌 매핑**으로 해석된다 (`serviceType` 기준 분기 추정).
`GET /menus/federation-apps` 와 `/custom-remote-apps` 는 **둘 다 빈 배열**이었다.

우리 앱 관련 메뉴의 `component` 값 (= host가 호출하는 exposes 이름):

```
/advisor/consultant        → ./AdvisorConsultantComponent
/advisor-renual/dashboard  → ./AdvisorRenualComponent
/advisor-renual/chat       → ./AdvisorRenualComponent
/advisor-renual/call-history → ./AdvisorRenualComponent
```

**리뉴얼 메뉴 전부가 `./AdvisorRenualComponent` 하나를 가리킨다는 것이 서버 데이터로 확인**되었다.
가이드 6-2의 "진입점 1개 + 내부 라우팅" 설계 전제가 실제 운영 데이터와 일치한다.

## 10. shared 협상 — ✅ remote 7개 전부 정상

앱을 하나씩 추가 로드하며 측정한 결과, **모든 단계에서 변함없이 단일 Vue였다.**

| 로드된 앱 누적 | vue 앱 수 | vue 버전 |
|---|:---:|---|
| host + user_service | 1 | 3.5.18 |
| + advisor_app | 1 | 3.5.18 |
| + qa_app | 1 | 3.5.18 |
| + ta_app | 1 | 3.5.18 |
| + aicm_app | 1 | 3.5.18 |
| + ce_app | 1 | 3.5.18 |

**remote 6개가 모두 붙어도 Vue는 한 벌.** 7개 앱 전체가 동일 버전(3.5.18)으로 정렬돼 있다.

**콘솔 경고 확인** (새로고침하며 1,119건 수집):
`Unsatisfied version` / `shared singleton` / `duplicate` 계열 경고는 **1건도 없었다.**
→ shared 협상은 완전히 정상이다. 이 부분은 더 볼 필요가 없다.

## 11. element-plus 중복 — 🔴 확정 (1차 미해결 과제 해소)

### 11-1. 결정적 실험

깨끗한 상태에서 앱을 하나씩 붙이며 **element-plus 인스턴스 고유 네임스페이스**(`el-id-<ns>-*`)를 추적했다.

| 시점 | id 네임스페이스 | 포퍼 컨테이너 |
|---|---|---|
| host + user_service (`/admin/menu`) | `{1251: 3}` | `el-popper-container-1251` |
| **+ advisor_app** (`/advisor/consultant`) | **`{1251: 21, 9522: 11}`** | **`1251`, `9522`** |
| + qa_app (`/qa/home/qa-dashboard`) | `{1251: 13}` | `1251`, `9522` |
| + ta_app (`/ta/dashboard`) | `{1251: 13}` | `1251`, `9522` |
| **+ aicm_app** (`/aicm/dashBoard`) | **`{1251: 2, 3814: 1}`** | `1251`, `9522` |
| + ce_app (`/ce/agentDashboard`) | `{1251: 11}` | `1251`, `9522` |

**advisor_app 을 로드하는 순간 정확히 새 네임스페이스 `9522` 와 두 번째 포퍼 컨테이너가 생겼다.**
→ **element-plus 중복 확정.** 1차의 가설이 사실로 확인되었다.

### 11-2. 인스턴스 소유자

| 네임스페이스 | 소유 | 근거 |
|---|---|---|
| `1251` | **host_app** | 최초 로드부터 존재. user_service·qa·ta·ce 화면도 이 값을 사용 |
| `9522` | **advisor_app (우리)** | advisor 로드 시점에 정확히 출현 |
| `3814` | **aicm_app** | aicm 화면에서만 출현 |

**즉 element-plus 를 자기 번들에 따로 갖고 있는 앱은 `advisor_app` 과 `aicm_app` 두 개다.**
`qa_app` / `ta_app` / `ce_app` / `aicc_user_service` 는 host 인스턴스(`1251`)를 그대로 쓴다.
→ **우리 앱이 (aicm과 함께) 소수파**다.

> 다만 qa/ta/ce 는 측정 시점에 id 생성 컴포넌트를 렌더하지 않았을 가능성도 있어,
> "확실히 공유 중"이라기보다 **"중복 증거가 관측되지 않음"** 이 정확한 표현이다.

### 11-3. z-index 대역 실측

```
2001, 2002, 2003, 2004   ← base 2000 : advisor / aicm 의 자체 element-plus
                              2001 = el-overlay adv-modal-container      (우리 모달)
                              2002~2004 = el-select__popper ecp-select   (ecp-ui-kit 컴포넌트)
3001 … 3019              ← base 3000 : host 인스턴스 (host가 초기값 3000 설정)
9999                     ← 우리 하드코딩 (ChatHistoryModal / ManageWorkspace)
```

`@timbel-aicc/ecp-ui-kit` 은 element-plus 를 **peer dependency**(`>=2.4.0 <3`)로 선언한다.
따라서 UI 킷 컴포넌트(`ecp-select`)는 **우리 번들의 copy** 를 물고 들어와 2000 대역을 쓴다.

**실질 영향**: 우리 모달·셀렉트(2000대)는 **포털 UI(3000대)보다 항상 아래**다. 겹치면 포털이 이긴다.
반대로 `9999` 를 명시한 두 모달만 **모든 것 위**에 뜬다.

## 12. 🔴 새로 발견 — CSP가 report-only 상태

포털 응답 헤더:

```
Content-Security-Policy-Report-Only:
  default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data: blob:; font-src 'self' data:;
  connect-src 'self' http://124.194.32.36:62009;
  frame-ancestors 'self'; base-uri 'self'; object-src 'none'
```

콘솔에 실제로 위반이 계속 기록되고 있다.

```
Loading the script 'http://124.194.32.36:62041/remoteEntry.js?t=…' violates the following
Content Security Policy directive: "script-src 'self'".
The policy is report-only, so the violation has been logged but no further action has been taken.
```

**`script-src 'self'` 는 host 오리진(62000) 스크립트만 허용한다.**
따라서 **62020(우리)·62031·62041·62056·62010 의 remoteEntry 는 전부 위반 대상**이다.

> ⚠️ **지금은 `Report-Only` 라서 동작한다. 이 헤더를 enforce(`Content-Security-Policy`)로 바꾸는 순간
> `aicc_user_service` 를 제외한 모든 remote 앱이 로드 실패한다.** (user_service 만 host와 같은 오리진)

### 12-1. CSP 기초 (인계자용)

**CSP(Content-Security-Policy)** 는 서버가 브라우저에게 보내는 **"이 페이지는 어디서 온 리소스만 실행해라"** 는 규칙표다.
본래 목적은 **XSS 방어** — 공격자가 `<script src="http://evil.com/…">` 를 심어도 허용 목록에 없으면 브라우저가 실행을 거부한다.

**헤더 이름이 곧 동작이다.**

| 헤더 | 동작 |
|---|---|
| `Content-Security-Policy` | **차단한다** |
| `Content-Security-Policy-Report-Only` | **차단하지 않는다.** 위반을 기록만 한다 |

Report-Only 는 원래 **"본격 적용 전 관찰 단계"** 다. 며칠 돌려 위반을 수집 → 정책 보정 → enforce 전환이 표준 절차다.

> **함정: 이 정책에는 `report-uri` / `report-to` 가 없다.**
> 위반 보고서를 받을 주소가 없어 **브라우저 콘솔에만 찍히고 사라진다.**
> 즉 **"관찰 모드인데 관찰자가 없는 상태"** 이며, 아무도 위반을 집계하고 있지 않다.
> 이 상태로 시간이 지나면 "문제 없어 보이니 켜자"는 판단이 나올 위험이 있다.

### 12-2. 규칙 해석

| 지시자 | 값 | 뜻 |
|---|---|---|
| `default-src` | `'self'` | 기본은 자기 오리진(62000)만 |
| `script-src` | `'self'` | JS는 62000에서만 |
| `style-src` | `'self' 'unsafe-inline'` | CSS는 62000 + 인라인 `<style>` |
| `img-src` | `'self' data: blob:` | 이미지는 62000 + data/blob |
| `font-src` | `'self' data:` | 폰트는 62000 + data URL |
| `connect-src` | `'self' http://…:62009` | XHR/fetch/WS 는 62000 과 API 게이트웨이만 |
| `frame-ancestors` | `'self'` | 외부 iframe 금지 (클릭재킹 방어) |
| `object-src` | `'none'` | 플러그인 금지 |

정책 내용 자체는 잘 짜여 있다. **문제는 MF 구조를 반영하지 않았다는 것뿐이다.**

```
CSP의 전제 : "내 오리진 것만 믿는다"
MF의 본질  : "남의 오리진 스크립트를 런타임에 가져와 실행한다"
```

설계 철학이 정반대이므로, MF를 쓰는 한 `script-src 'self'` 는 성립할 수 없다.

### 12-3. enforce 전환 시 차단되는 것 (실측)

페이지 1회 로드에서 외부 오리진 리소스 **175건**을 분류한 결과:

| 지시자 | 차단 대상 | 영향 |
|---|---|---|
| **`script-src 'self'`** | 62020 **25**, 62010 11, 62031 8, 62041 6, 62056 3 = **스크립트 53개** | 🔴 **remote 앱 전멸** |
| **`connect-src`** | 각 remote `remoteEntry.js` fetch 5건 | 🔴 프리로드 경로 차단 |
| **`font-src 'self' data:`** | 62020 의 `Pretendard-Bold.woff2`, `Pretendard-Medium.woff2`, `MaterialIconsOutlined-Regular.woff2` | 🟡 **폰트·아이콘 깨짐** |
| **`style-src 'self'`** | `https://code.highcharts.com/highcharts.css` | 🟡 차트 스타일 깨짐 |
| `img-src` | (관측된 위반 없음) | ✅ |
| `connect-src` (62009) | API 호출 113건 → **허용** | ✅ |

**살아남는 앱은 `aicc_user_service` 하나뿐**이다. host 와 같은 오리진(`62000/mf-app`)에 있기 때문.

> ⚠️ `script-src` 만 보고 "스크립트 목록만 추가하면 되겠다"고 판단하면 **아이콘 폰트가 전부 깨진다.**
> `font-src` 도 반드시 함께 손봐야 한다.

### 12-4. 인프라 구성 (서버 실측 — 2026-08-03)

**서비스별 서버 소프트웨어**

```
62000  Server: nginx/1.27.5   + CSP-Report-Only  ← 모든 응답에 부착 (존재하지 않는 경로에도)
62010  Server: nginx/1.31.3
62031  Server: nginx/1.29.8            ACAO: *
62041  Server: nginx/1.29.8            ACAO: *
62056  Server: nginx/1.29.8            ACAO: http://124.194.32.36:62000  ← 유일하게 좁게 설정
62020  (우리) X-Powered-By: Express    ← nginx 아님. Express 정적 서빙
62009  (Server 헤더 없음)              ← API 게이트웨이
```

**같은 IP 에 nginx 버전이 3종(1.27.5 / 1.29.8 / 1.31.3)** 공존한다 → 호스트에 설치된 단일 nginx 가 아니라
**서비스마다 자기 nginx 를 품은 Docker 컨테이너** 구조다. 그래서 **호스트 파일시스템에는 `nginx.conf` 가 없다.**

**컨테이너 ↔ 서비스 매핑** (`docker ps` 기준)

| 컨테이너 | 포트 | 역할 |
|---|---|---|
| **`AICC-portal-web`** | 62000 | **포털 (CSP 발원지)** |
| `AICC-portal-mf-app` | 62000/mf-app | user_service (same-origin 프록시) |
| **`AICC-asst-web-dev`** | 62020 | **우리 앱** (Express) |
| `AICC-ce-web` | 62010 | CE |
| `ta-web` / `qa-web` | 62031 / 62041 | TA / QA |
| `AICC-aicm-web` | 62056 | AICM |
| `AICC-gateway` | 62009 | API 게이트웨이 |

**CSP 정의 위치 — 2곳에 중복**

```
AICC-portal-web:/etc/nginx/conf.d/default.conf              ← server 레벨
AICC-portal-web:/etc/nginx/inc/nginx-locations-prod.inc      ← location = /index.html 안에 한 번 더
                (nginx-locations.inc 는 위 prod 파일로의 symlink)
```

`location = /index.html` 이 자체 `add_header` 를 가지면 **server 레벨 헤더를 상속하지 않는다**(nginx 규칙).
그래서 HTML 진입점에도 CSP 가 붙도록 같은 헤더를 반복 선언해 두었다.
→ ⚠️ **CSP 를 수정하려면 반드시 두 곳 모두 고쳐야 한다.**

**설정 파일은 이미지에 구워져 있다**

```
$ docker inspect AICC-portal-web --format '{{range .Mounts}}…{{end}}'
(빈 출력 = 볼륨 마운트 없음)
```

→ 호스트에서 파일을 고칠 수 없다. **포털 저장소의 Dockerfile/설정을 수정해 재빌드·재배포**해야 한다.
즉 **비개발 담당자가 서버에서 직접 처리할 수 있는 작업이 아니다.**

### 12-5. 포털 설정에 명시된 enforce 계획 ⚠️

`default.conf` 주석 원문:

> 인라인 `<script>` 부재라 script-src 는 'self' 가능(XSS 방어 핵심). … 관찰 후 튜닝 대상:
> **크로스오리진 커스텀 리모트(remoteLoader remote_url)** · SAML IdP 폼 POST(form-action) ·
> **크로스오리진 XHR(connect-src)**. **위반 0 확인 후 헤더명을 `Content-Security-Policy` 로 전환(enforcing).**

**즉 enforce 전환은 "혹시 모를 위험"이 아니라 문서화된 로드맵이다.**

포털팀이 **크로스오리진 리모트가 튜닝 대상임을 이미 인지**하고 있다는 점은 긍정적이다(모르는 상태가 아니다).
다만 전환 조건에 논리적 모순이 있다:

```
전환 조건 : "위반 0 확인 후"
현재 상태 : 크로스오리진 remote 5개가 매 페이지 로드마다 위반 발생
          + report-uri 가 없어 위반을 수집·집계하는 곳이 없음
```

**크로스오리진 remote 가 존재하는 한 위반은 절대 0 이 되지 않는다.** 조건이 충족될 수 없으므로 방치해도 당장은 안전하지만,
**리포트를 볼 수단이 없는 상태에서 "문제 없어 보인다"고 판단해 전환하면 그 즉시 포털 전체가 정지**한다.

### 12-6. same-origin 프록시 현황 — 웹 앱은 미구현

포털 nginx 는 **same-origin reverse proxy 를 설계 방침으로 명시**하고 있다.

```
# Portal nginx 설정 (Docker installer 용 — same-origin reverse proxy, HTTP :80)
# Portal SPA(/) + portal-service API 를 단일 origin 으로 노출.
```

실제로 MF 앱 하나는 이미 그 방식으로 붙어 있다.

```nginx
location /mf-app/ { proxy_pass http://portal-mf-app/; }   # aicc_user_service
```

**이것이 `aicc_user_service` 만 CSP 위반 없이 동작하는 이유다.**

federation 라우트는 별도 파일로 분리되어 opt-in 방식이다.

```
/etc/nginx/inc/nginx-locations-aicc.inc          (5,362 bytes)
/etc/nginx/inc/nginx-locations-aicc-active.inc   (0 bytes ← 비어 있음 = OFF)
AICC_FEDERATION_ENABLED=false
```

**⚠️ 중요: 이 파일이 프록시하는 것은 "웹 앱"이 아니라 "백엔드 API"다.**

```nginx
location /aicc/asst-service/ { proxy_pass http://asst-service:3000/api/asst/v1/; }
location /aicc/ce-service/   { proxy_pass http://ce-service:8080/api/ce/v1/; }
location /aicc/ta-service/   { proxy_pass http://ta-service:3000/api/ta/v1/; }
location /aicc/qa-service/   { proxy_pass http://qa-service:3010/api/qa/v1/; }
location /aicc/aicm-service/ { proxy_pass http://aicm-service:32012/api/aicm/v1/; }
location /aicc/user-service/ { proxy_pass http://portal-service:32021/api/; }
```

`remoteEntry.js` 를 서빙하는 **프론트엔드 컨테이너(asst-web / qa-web / ta-web / aicm-web / ce-web)를 프록시하는
location 은 존재하지 않는다.** 그래서 remote 는 여전히 62020·62031·62041·62056·62010 으로 **직접(크로스오리진) 로드**되고,
이것이 CSP 위반의 원인이다.

> 현재 이 스위치는 `false` 이며, 각 앱은 게이트웨이(62009)를 직접 호출한다.
> `connect-src` 에 62009 가 명시되어 있어 **API 호출은 CSP 를 통과**한다(측정: XHR 113건 정상).

### 12-7. 대응 방법 (서버 실측 반영)

> **어느 방법이든 `AICC-portal-web` 이미지를 재빌드·재배포해야 한다** (설정이 이미지에 내장, 마운트 없음).
> 프론트엔드 코드로는 해결 불가.

| 방법 | 내용 | 실현성 | 비고 |
|---|---|:---:|---|
| **A. CSP allowlist 추가** | CSP 헤더에 remote 오리진 5개를 나열 (**2곳 모두**) | 🟢 현실적 | remote 추가·포트 변경 시 함께 수정 필요 |
| **B. 웹 앱 same-origin 프록시** | `nginx-locations-aicc.inc` 에 웹 컨테이너 location 신설 + host 의 remote URL 을 상대경로로 변경 | 🟡 중간 | 각 web 컨테이너가 `timbel_network` 에 있어야 함. CSP·CORS 문제 동시 소멸 |
| **C. `report-uri` 추가** | 위반을 실제로 수집 | 🟢 쉬움 | **enforce 전 필수.** 현재 "관찰자 없는 관찰 모드" 해소 |
| **D. 현상 유지** | Report-Only 유지 + **enforce 금지**를 명확히 공유 | 🟢 | **현재 권장** |
| ~~E. nonce 방식~~ | 요청별 난수 발급 | 🔴 | 정적 nginx 서빙과 부적합. 과함 |
| ~~F. CSP 제거~~ | — | 🔴 | 비권장. 보안 후퇴 |

**A 적용 예시** (⚠️ `default.conf` 와 `nginx-locations-prod.inc` **양쪽** 모두)

```nginx
add_header Content-Security-Policy-Report-Only "
  default-src 'self';
  script-src  'self' http://124.194.32.36:62020 http://124.194.32.36:62031
                     http://124.194.32.36:62041 http://124.194.32.36:62056
                     http://124.194.32.36:62010;
  connect-src 'self' http://124.194.32.36:62009 http://124.194.32.36:62020
                     http://124.194.32.36:62031 http://124.194.32.36:62041
                     http://124.194.32.36:62056 http://124.194.32.36:62010;
  font-src    'self' data: http://124.194.32.36:62020;
  style-src   'self' 'unsafe-inline' https://code.highcharts.com;
  img-src     'self' data: blob:;
  frame-ancestors 'self'; base-uri 'self'; object-src 'none';
" always;
```

> `font-src` 를 빠뜨리면 스크립트는 살아나도 **Pretendard·Material Icons 폰트가 깨진다.** 반드시 함께.

**B 적용 예시** (`nginx-locations-aicc.inc` 에 추가)

```nginx
# 웹 앱(remoteEntry) same-origin 프록시 — 현재 없음. 신설 대상.
location /advisor-web/ { proxy_pass http://asst-web:80/; }
location /qa-web/      { proxy_pass http://qa-web:80/; }
# … 이후 host 의 remote URL 설정을 절대 URL → 상대경로로 변경
```

**현재 권장: D (현상 유지) + C (리포트 수집 추가)**

당장 enforce 계획이 실행되지 않는다면 건드릴 이유가 없다.
**"enforce 하면 포털 전체가 정지한다"** 는 사실이 포털 담당자에게 확실히 전달되는 것이 가장 중요하다.
enforce 가 실제로 추진되면 **A 로 시작하고, 장기적으로 B** 가 구조적으로 옳다.

## 13. 기타 관측

- **remote 프리로드**: `/advisor/consultant` 로 이동했을 뿐인데 `qa_app`(62041) remoteEntry 도 로드되었다.
  → 포털이 일부 remote 를 선반영(preload)하는 것으로 보인다.
- **캐시 버스터**: 모든 remoteEntry 에 `?t=<타임스탬프>` 가 붙는다 (host 쪽 ChunkLoadError 완화책).
- **콘솔 노이즈**: 단일 페이지 로드에 **1,119건**(그중 1,074건은 브라우저가 생략). 실제 경고를 찾기 어려운 수준이다.
  MF 문제 진단 시 **콘솔을 비우고 필터를 걸어야** 한다.
- 반복 경고: `ECPIcon: Unknown color "gray"` (ecp-ui-kit), `el-link underline` deprecated(element-plus 3.0 대비).

## 14. 2차 종합

| 항목 | 판정 | 비고 |
|---|:---:|---|
| shared (vue/pinia/router) | ✅ | remote 6개 전부 붙어도 Vue 1개 / 3.5.18 단일. 협상 경고 0건 |
| 리프 라우팅 설계 | ✅ | 서버 메뉴 데이터가 진입점 1개 구조와 일치 |
| publicPath / 청크 로드 | ✅ | 각 remote 자기 오리진에서 로드 |
| element-plus 중복 | 🔴 확정 | host / advisor / aicm 3벌. 우리는 2000 대역 → 포털 UI 아래 |
| 하드코딩 9999 | ⚠️ | 측정 최대치 3019 대비 압도적. 포털 전체를 덮음 |
| **CSP report-only** | 🔴 | enforce 전환 시 **모든 remote 로드 실패**. 전사 리스크 |

**1차 결론 유지**: 프레임워크 공유는 완벽하다. 실제 리스크는 element-plus 중복(경미)과 **CSP(중대·잠재)** 두 가지다.

## 15. 후속 확인이 필요한 것

1. **CSP enforce 계획이 있는지** 포털/인프라팀에 확인 — 있다면 remote 오리진 화이트리스트 등록 필수
2. `:z-index="9999"` 두 곳이 **의도된 값인지** 확인 (`ChatHistoryModal.vue:2`, `ManageWorkspace.vue:2`)
3. qa/ta/ce 가 element-plus 를 정말 공유하는지 — 각 앱에서 셀렉트·모달을 실제로 열어 네임스페이스 재확인
4. aicm_app 도 우리와 같은 2000 대역인지 — 겹침 사고는 **advisor ↔ aicm** 사이에서 먼저 날 수 있다

---

## 부록 A. 재측정 절차

`agent01` 로 다시 재현하려면 아래 순서를 따른다. (스크립트는 세션 스크래치패드에 있었으므로 필요 시 재작성)

**① 기존 브라우저를 건드리지 않고 CDP 크롬 띄우기**

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/mf-diag-profile \
  --no-first-run --no-default-browser-check \
  "http://124.194.32.36:62000"
```

**② 로그인 후 콘솔에서 실행할 진단 스니펫**

```js
// (1) MF 컨테이너 + remoteEntry
Object.keys(window).filter(k => { try { const v = window[k];
  return v && typeof v === "object" && typeof v.get === "function" && typeof v.init === "function"; } catch { return false; } });
[...document.querySelectorAll("script[src*='remoteEntry']")].map(s => s.src);

// (2) Vue 인스턴스 수 / 버전  ← shared 협상 판정의 핵심
(() => { const s = new Set(), v = new Set();
  const w = e => { if (e.__vue_app__) { s.add(e.__vue_app__); if (e.__vue_app__.version) v.add(e.__vue_app__.version); }
                   for (const c of e.children) w(c); };
  w(document.documentElement); return { apps: s.size, versions: [...v] }; })();

// (3) z-index 실측 (element-plus 카운터 정합)
[...document.querySelectorAll("[style*='z-index']")]
  .map(e => ({ z: e.style.zIndex, cls: e.className.toString().slice(0,60) }))
  .sort((a,b) => parseInt(a.z) - parseInt(b.z));

// (4) element-plus 인스턴스 지표
(() => { const ns = {};
  [...document.querySelectorAll("[id^=el-id-]")].forEach(e => {
    const m = e.id.match(/^el-id-(\d+)-/); if (m) ns[m[1]] = (ns[m[1]] || 0) + 1; });
  return { idNamespaces: ns,
           popperContainers: [...document.querySelectorAll("[id^=el-popper-container-]")].map(e => e.id) }; })();

// (5) 다크모드 / CSS 변수
({ htmlClass: document.documentElement.className,
   primary: getComputedStyle(document.documentElement).getPropertyValue("--el-color-primary").trim(),
   bg:      getComputedStyle(document.documentElement).getPropertyValue("--el-bg-color").trim() });

// (6) 전역 el- 태그 미해석 여부 (0 이어야 정상)
[...document.querySelectorAll("el-badge, el-tooltip, el-dialog, el-icon, el-button, el-select, el-input")].map(e => e.tagName);

// (7) 리소스 오리진 분포
(() => { const o = {}; performance.getEntriesByType("resource").forEach(r => {
    try { const k = new URL(r.name).origin; o[k] = (o[k] || 0) + 1; } catch {} }); return o; })();
```

## 부록 B. 2차 측정에서 확인할 것 — ✅ 완료 (위 9~15절 참조)

> 아래는 2차 측정 전에 세운 체크리스트다. **전부 측정 완료**되었으며 결과는 9~14절에 있다.
> 3차 측정 시에도 같은 항목을 그대로 쓰면 비교가 가능하다.

1. **remote 가 몇 개 붙는가** — `window` 의 MF 컨테이너 목록, remoteEntry 스크립트 개수
   → 앱이 3개 이상이면 shared 협상 참여자가 늘어난다. 버전이 가장 높은 하나가 전체를 지배한다
2. **각 remote 의 vue 버전** — 여전히 앱 인스턴스가 1개인가. 2개 이상이면 어느 앱이 원인인가
3. **element-plus 이중 카운터의 확정** — 다른 앱 화면에서도 2000/3000 대역이 갈리는가
   → 6-3 가설(전역 태그 vs 명시적 import)이 맞는지 판정
4. **id 네임스페이스가 2개 이상 관측되는가** — 관측되면 element-plus 중복이 **확정**된다
5. **z-index 최대값** — 다른 앱이 9999 이상을 쓰는가 (우리 9999 와 충돌 여부)
6. **다른 앱의 리소스 오리진** — 배포 주소 지도 작성
7. **콘솔 경고** — `Unsatisfied version ... of shared singleton module` 류가 찍히는가
   (콘솔을 비우고 새로고침한 뒤 확인)

---

## 부록 C. 포털 담당자 전달용 안내 (비개발자용)

> 포털 서비스 담당자가 웹 보안 개념에 익숙하지 않은 상황을 전제로 작성. 그대로 전달해도 되도록 다듬은 문구다.

---

**[공유] 포털 CSP 설정 관련 — 적용 전 반드시 협의 필요**

**1. CSP 와 CORS 는 이름은 비슷하지만 정반대 방향의 규칙입니다**

- **CORS** = "**남의 서버**가 **내 데이터를 줘도 되는지**" — **주는 쪽**이 정하는 규칙
- **CSP** = "**내 페이지**가 **어디서 온 코드를 실행해도 되는지**" — **받는 쪽**이 정하는 규칙

비유하자면
- CORS = 도서관이 "이 책은 외부인도 빌릴 수 있다"고 정하는 것 (대출 정책)
- CSP = 내가 "나는 우리 도서관 책만 읽겠다"고 정하는 것 (독서 규칙)

둘은 서로를 대체하지 않으며 **각각 따로 설정**해야 합니다.

**2. 현재 포털 상황**

포털 화면은 6개의 별도 서버에서 실시간으로 가져와 조립됩니다.

```
상담 어드바이저 62020 · QA 62041 · TA 62031 · AICM 62056 · AI 62010 · 관리 (포털 내부)
```

그런데 포털에 설정된 CSP 는 **"62000 서버의 코드만 실행"** 으로 되어 있어, 위 5개 서버의 화면은 **전부 규칙 위반** 상태입니다.

**지금은 문제가 없습니다.** 헤더 이름이 `Content-Security-Policy-Report-Only` 라서
**위반을 기록만 하고 차단하지 않는 "관찰 모드"** 이기 때문입니다.

**3. 주의할 점 — 딱 하나입니다**

헤더 이름에서 **`-Report-Only` 를 떼면 즉시 차단 모드로 바뀝니다.**
그 순간 **관리 메뉴를 제외한 포털의 모든 화면이 빈 화면**이 됩니다. (스크립트 53개 차단 실측 확인)

포털 설정 파일 주석에는 *"위반 0 확인 후 enforcing 으로 전환"* 이라는 계획이 적혀 있습니다.
그러나 **현재 구조에서는 위반이 0 이 될 수 없습니다** — 화면을 외부 서버에서 가져오는 방식 자체가 위반으로 기록되기 때문입니다.
또한 위반 내역을 수집하는 주소(`report-uri`)가 없어 **관찰 모드인데 아무도 관찰하지 않는 상태**입니다.

**4. 요청 사항**

1. 보안 점검 등에서 "CSP 를 적용하라"는 지적을 받더라도 **그냥 켜지 말고 프론트엔드 팀과 먼저 협의**해 주세요.
2. 켜야 한다면 **각 화면 서버 주소를 허용 목록에 먼저 추가**해야 합니다. (스크립트뿐 아니라 **폰트 경로도 함께** — 빠뜨리면 아이콘이 전부 깨집니다)
3. 설정 파일은 `AICC-portal-web` 컨테이너 **이미지 안에 포함**되어 있어(볼륨 마운트 없음) 서버에서 직접 수정할 수 없습니다.
   → **포털 저장소 수정 후 재빌드·재배포**가 필요하며, 포털 개발 담당자의 작업입니다.
4. 수정 시 **CSP 는 두 곳에 중복 정의**되어 있으니 반드시 양쪽 모두 변경해야 합니다.
   - `/etc/nginx/conf.d/default.conf`
   - `/etc/nginx/inc/nginx-locations-prod.inc` (`location = /index.html` 내부)

---

## 관련 문서

- `docs/module-federation-개념과-구조-가이드.md` — 개념·구조·설계 (이 문서의 이론 편)
- `docs/webpack-mf-chunkload-fix-guide.md` — 청크 404 실전 대응
- `docs/darkmode-hardcoded-color-guide.md` — 다크모드 색상 정리
