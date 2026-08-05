# 백그라운드 탭 알림 (타이틀 + favicon) — 구현/이식 가이드

> 설계·기술검토 배경은 `advisor-background-notification-tab-alert.md` 참고. **이 문서는 실제 구현 결과와 다른 레포 이식 절차.**
>
> 구현 완료: `asst-web-portal` (2026-07-28)
> 신규 의존성 없음 / 백엔드 변경 없음 / **http(비 secure context)에서 동작**

---

## 1. 무엇을 해결하나

실시간 알림을 토스트로만 띄우면 **사용자가 다른 탭을 보고 있을 때 그대로 사라진다.**
탭 타이틀과 favicon을 바꿔 백그라운드에서도 인지시킨다.

| 원하는 것 | 가능 | 방법 |
|---|---|---|
| 다른 탭 활성 / 창 최소화 시 알림 | ✅ | **이 문서** — 권한·https 불필요 |
| OS 데스크톱 알림 | ⚠️ https 에서만 | Notification API — http 환경은 권한 요청 자체가 차단 |
| 소리 알림 | ✅ | `Audio.play()` — 별건 |
| **탭/브라우저를 닫았을 때** | ❌ | 소켓 연결이 사라져 원리적으로 불가. Web Push(Service Worker) 필요하고 그것도 https 전용 |

---

## 2. 확정 사양 (그대로 따를 것)

| # | 항목 | 결정 | 이유 |
|---|---|---|---|
| 1 | 알림 대상 | **hidden 인 동안 새로 도착한 건만** | 기존 미확인분은 화면 배지가 이미 담당. 자리 비운 사이 뭐가 왔는지가 알고 싶은 것 |
| 2 | 카운트 출처 | **자체 카운터** (store 미확인수 아님) | ①의 귀결. store 를 watch 하면 "기존 미확인"까지 잡히고 비동기 갱신 타이밍 문제도 생김 |
| 3 | 타이틀 | **정적 프리픽스**, 깜빡임 없음 | 백그라운드 탭은 `setInterval` 이 강하게 스로틀링돼 깜빡임이 뚝뚝 끊긴다 |
| 4 | favicon | 32x32 canvas에 **빨간 원 + 흰 숫자**, `9+` 상한 | 원본(16x16) 위 배지는 판독 불가. 두 자릿수도 안 보임 |
| 5 | 원복 | **탭 복귀(visible) 시점 하나로 충분** | hidden 중엔 읽을 수 없으므로 "미확인 0" 조건은 불필요 |

표시 형태: `🚨 코칭요청 2건 - {원래 타이틀}` + favicon 빨간 원에 `2`

---

## 3. 성능 (이식 시 반드시 유지할 원칙)

이 기능은 **있으면 좋은 부가기능**이다. 상시 비용이 있으면 안 된다.

| 항목 | 비용 |
|---|---|
| 타이머 / 폴링 / 깜빡임 | **없음** |
| Vue watcher | **없음** (store 카운트를 watch 하지 않는다) |
| 상시 이벤트 리스너 | `visibilitychange` **1개**/화면 |
| 카운터 | 일반 변수(`let`) — 렌더와 무관하므로 `ref` 금지(반응성 오버헤드 0) |
| canvas favicon 생성 | 백그라운드 수신 **그 순간에만** 1회 |
| MutationObserver | **알림 활성 중에만** 연결, clear 시 disconnect |
| 라우터 가드 추가분 | `if (!isActive) return;` 한 줄 |

→ 알림이 꺼져 있는 평상시엔 코드가 사실상 잠들어 있다.

---

## 4. 이식 절차

### 4-1. 유틸 파일 복사 (`src/utils/tabAlert.ts`)

프레임워크 비의존(순수 DOM)이라 **그대로 복사하면 된다.**

```ts
/**
 * 탭 백그라운드 알림 유틸 (탭 타이틀 + favicon)
 * - 권한/https 불필요. 백그라운드 탭 스로틀링을 피하려 깜빡임 없이 정적 표시만 한다.
 * - 원본 title/favicon 은 "최초 활성화 시 한 번만" 스냅샷 → 멱등.
 */

const FAVICON_SIZE = 32;
const DEFAULT_FAVICON_HREF = "/favicon.ico";
const ALERT_FAVICON_COLOR = "#E53935";

let isActive = false;
let currentCount = 0;
let currentLabel = "";
let baseTitle = "";
let originalFaviconHref = "";

// 우리가 직접 쓴 타이틀 값. MutationObserver 가 "외부 변경"만 골라내기 위한 가드(무한 루프 방지).
let lastAppliedTitle = "";
let titleObserver: MutationObserver | null = null;

function buildAlertFavicon(count: number): string {
  const size = FAVICON_SIZE;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;

  const ctx = canvas.getContext("2d");
  if (!ctx) return "";

  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
  ctx.fillStyle = ALERT_FAVICON_COLOR;
  ctx.fill();

  const text = count > 9 ? "9+" : String(count);
  ctx.fillStyle = "#FFFFFF";
  ctx.font = `bold ${count > 9 ? 16 : 20}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, size / 2, size / 2 + 1);

  return canvas.toDataURL("image/png");
}

/** 일부 브라우저는 href 만 바꾸면 갱신되지 않아 link 를 제거 후 새로 붙인다. */
function applyFavicon(href: string) {
  if (!href) return;
  document.querySelectorAll('link[rel~="icon"]').forEach(el => el.remove());

  const link = document.createElement("link");
  link.rel = "icon";
  link.href = href;
  document.head.appendChild(link);
}

function applyTitle(title: string) {
  lastAppliedTitle = title;
  document.title = title;
}

function buildAlertTitle(): string {
  return `🚨 ${currentLabel} ${currentCount}건 - ${baseTitle}`;
}

function startTitleObserver() {
  if (titleObserver) return;

  const titleEl = document.querySelector("title");
  if (!titleEl || typeof MutationObserver === "undefined") return;

  titleObserver = new MutationObserver(() => {
    if (!isActive) return;

    const now = document.title;
    if (now === lastAppliedTitle) return; // 우리가 쓴 값 → 무시

    baseTitle = now; // 외부가 바꾼 값이 새 base
    applyTitle(buildAlertTitle());
  });

  titleObserver.observe(titleEl, { childList: true, characterData: true, subtree: true });
}

function stopTitleObserver() {
  titleObserver?.disconnect();
  titleObserver = null;
}

export function setTabAlert(count: number, label: string): void {
  if (typeof document === "undefined") return;

  if (!count || count <= 0) {
    clearTabAlert();
    return;
  }

  if (!isActive) {
    baseTitle = document.title;
    const iconEl = document.querySelector<HTMLLinkElement>('link[rel~="icon"]');
    originalFaviconHref = iconEl?.getAttribute("href") || DEFAULT_FAVICON_HREF;
    isActive = true;
    startTitleObserver();
  }

  if (currentCount === count && currentLabel === label) return; // 같은 상태면 DOM 미접근

  currentCount = count;
  currentLabel = label;

  applyTitle(buildAlertTitle());
  applyFavicon(buildAlertFavicon(count));
}

export function clearTabAlert(): void {
  if (typeof document === "undefined" || !isActive) return;

  stopTitleObserver();
  applyTitle(baseTitle);
  applyFavicon(originalFaviconHref);

  isActive = false;
  currentCount = 0;
  currentLabel = "";
  baseTitle = "";
  originalFaviconHref = "";
  lastAppliedTitle = "";
}

/** 외부(라우터)가 document.title 을 새로 쓴 직후 호출 → base 갱신 후 접두사 재적용. 비활성이면 no-op. */
export function reapplyTabAlert(nextBaseTitle?: string): void {
  if (typeof document === "undefined" || !isActive) return;

  baseTitle = nextBaseTitle ?? document.title;
  applyTitle(buildAlertTitle());
}

export function isTabAlertActive(): boolean {
  return isActive;
}
```

### 4-2. 수신 화면에 훅 3개

**① 카운터 + 함수 2개** (화면 컴포넌트 setup 스코프)

```ts
import { setTabAlert, clearTabAlert } from "@/utils/tabAlert";

// 렌더와 무관 → ref 아님
let bgNewCount = 0;

const notifyTabAlert = () => {
  if (document.visibilityState !== "hidden") return;
  bgNewCount += 1;
  setTabAlert(bgNewCount, "코칭요청"); // 라벨은 화면별로
};

const resetTabAlert = () => {
  if (document.visibilityState !== "visible") return;
  bgNewCount = 0;
  clearTabAlert();
};
```

**② 실시간 수신 핸들러에서 호출** — 기존 토스트는 그대로 두고 한 줄만 추가

```ts
const handleRedisMessage = (data: any) => {
  // ...기존 필터/파싱/목록갱신 그대로...
  notifyTabAlert();       // ← 추가. hidden 아니면 내부에서 알아서 return
  showCustomMessage({ /* 기존 그대로 */ });
};
```

> ⚠️ **중복 수신 방어(dedupe)를 함께 적용한다면 `notifyTabAlert()` 는 반드시 dedupe 뒤에 둔다.**
> 이 카운터는 대표적인 **1회성 부수효과**라, 재연결 복원으로 같은 이벤트가 3번 오면
> 타이틀이 `🚨 코칭 3건` 이 되어 그대로 노출된다. 목록 재조회는 멱등이라 dedupe 앞에 둬도 된다.
> → `realtime-event-dedupe-guide.md` 참고.

**③ 등록/해제**

```ts
onMounted(() => document.addEventListener("visibilitychange", resetTabAlert));

onUnmounted(() => {
  document.removeEventListener("visibilitychange", resetTabAlert);
  bgNewCount = 0;
  clearTabAlert();
});
```

### 4-3. 라우터 가드 (SPA 필수)

라우터가 `document.title` 을 덮어쓰면 알림 접두사가 지워진다. **title 설정 직후** 한 줄:

```ts
router.beforeEach((to, from, next) => {
  document.title = to.meta.title ? `${to.meta.title} - ${APP_TITLE}` : APP_TITLE;
  reapplyTabAlert(document.title);   // ← 추가 (알림 꺼져 있으면 no-op)
  // ...
});
```

---

## 5. 이식 전 확인 목록

| # | 확인 | 안 맞으면 |
|---|---|---|
| 1 | **iframe 렌더인가?** `window.self !== window.top` | iframe이면 자기 문서의 title/favicon만 바뀌고 **브라우저 탭엔 안 보인다** → 이 방식 자체가 성립 안 함. Module Federation(remote)은 같은 document라 **문제 없음** |
| 2 | `document.title` 을 쓰는 곳이 라우터 말고 또 있나 | MutationObserver 폴백이 흡수하지만, 호스트 앱이 관리한다면 그쪽 확인 |
| 3 | `<link rel="icon">` 이 런타임에 존재하나 | 없으면 원복 시 `/favicon.ico` 폴백. 빌드 도구가 주입하는 경우가 많음(HtmlWebpackPlugin `favicon` 옵션) |
| 4 | **같은 컴포넌트가 다른 역할로 임베드되나** | 아래 6-2 참고. 중복 알림의 주원인 |
| 5 | 화면이 여러 개 열릴 수 있나(다중 탭) | 탭별로 독립 동작 — 문제 없고 오히려 자연스럽다 |

---

## 6. 함정 (실제로 밟은 것)

### 6-1. store 미확인 카운트를 watch 하면 안 된다
처음엔 미확인수 watch 로 구현했는데 두 가지가 깨진다.
- 목록 갱신 API가 **비동기**라 수신 핸들러 시점의 카운트는 **직전 값**이다.
- "기존에 안 읽은 게 있는 상태에서 탭만 벗어나도" 알림이 켜진다 → 의도와 다름.

→ **수신 이벤트를 트리거로, 자체 카운터를 쓴다.** 부수적으로 watcher가 사라져 상시 비용도 0이 된다.

### 6-2. 같은 컴포넌트가 다른 역할로 임베드되면 알림이 겹친다
`asst-web-portal` 은 관리자 화면이 상담사 컴포넌트를 `isAdmin=true` 로 임베드한다.
그대로 두면 한 탭에서 "코칭요청 1건"과 "코칭 N건"이 **서로 타이틀을 덮어쓴다.**

→ 리스너 등록을 **실제 그 역할로 동작할 때만 도는 초기화 함수 안**에 넣는다(우리는 소켓 구독 설정 함수). 정리 시 clear 도 역할 가드.

### 6-3. favicon 은 href 교체가 아니라 link 재생성
일부 브라우저는 기존 `<link>` 의 href만 바꾸면 갱신하지 않는다. remove → create → append.

### 6-4. 원래 타이틀을 하드코딩하지 말 것
`"ECS CLOUD PORTAL"` 같은 상수를 박으면 라우트별 타이틀(`{메뉴} - {앱}`)로 복원하지 못한다. **런타임 스냅샷 필수.**

### 6-5. MutationObserver 무한 루프
타이틀 변경 감지 → 재적용 → 그게 또 감지… 로 돈다. `lastAppliedTitle` 과 비교해 **자기 변경은 무시**한다. (동기 플래그는 소용없다 — observer 콜백은 마이크로태스크라 이미 플래그가 풀린 뒤 실행된다.)

---

## 7. 검증 절차

권한 팝업이 없어 http 환경에서도 그대로 검증된다.

1. 수신자 계정으로 진입 → **다른 탭으로 전환**
2. 발신 → 타이틀 `🚨 {라벨} 1건 - …` + favicon 빨간 원에 `1`
3. 한 번 더 발신 → `2건`, favicon 도 `2`
4. 탭 복귀 → 타이틀·favicon **원복**
5. 알림 켜진 상태로 **다른 메뉴 라우팅** → `🚨 {라벨} 2건 - {새 메뉴} - {앱}` 으로 base 만 교체되는지
6. 반대 방향(다른 역할) 반복 → 라벨이 맞는지, **한 탭에서 두 알림이 겹치지 않는지**
7. **포어그라운드 수신** → 탭 알림 안 뜨고 토스트만 (회귀)

> 로컬 dev server 는 favicon link 가 없을 수 있어 원복 시 기본 아이콘으로 보일 수 있다(로컬 한정). 원복 판정은 **타이틀 기준**으로 볼 것. 크롬 favicon 캐시가 완고해 갱신이 한 박자 늦는 경우도 있다.

---

## 8. 실제 변경 파일 (asst-web-portal 기준)

| 파일 | 변경 |
|---|---|
| `src/utils/tabAlert.ts` | 신규 |
| `src/view/advisor/admin/index.vue` | 카운터+함수 2개, 수신 핸들러 1줄, onMounted/onUnmounted |
| `src/view/advisor/agent/index.vue` | 동일 (+ `isAdmin/isViewer` 임베드 가드) |
| `src/routers/index.ts` | title 설정 직후 `reapplyTabAlert()` |

**기능을 걷어내려면**: import 2줄 + 호출 3곳만 지우면 원상복구된다.
