# 어드바이저 백그라운드 알림 — 탭 타이틀 + favicon 비상 표시

> 목적: 코칭 / 코칭요청 알림을 어드바이저 화면이 **백그라운드일 때도** 인지할 수 있게 한다.
> 현재는 포어그라운드 토스트(`showCustomMessage`)만 있어 다른 탭을 보고 있으면 놓친다.
>
> **작업 대상 레포: `asst-web-portal` (Vue 3 / 프론트엔드 전용)**
> 백엔드(`asst-service-portal`) 변경 없음. 이 문서만 저 레포로 가져가서 작업하면 된다.
>
> 조사 기준 코드: `asst-web-portal`, `asst-service-portal` 실제 소스. 아래 파일:라인은 조사 시점 기준.

---

## 1. 배경

### 현재 흐름 (이미 동작 중)

```
관리자/상담사 행위
      │
      ▼
백엔드 CoachingSocketHandler ──emit──▶ Socket.IO room
      │                                (room 이름 = Redis 채널 문자열)
      ▼
프론트 on("redis-message") 수신
      │
      ▼
showCustomMessage(...)  ← 토스트. 포어그라운드에서만 보인다.
```

- 백엔드 채널/이벤트 정의: `asst-service-portal/src/common/constants/coaching.constants.ts`
  - room: `{env}:{tenantId}:{receiver_key}:coaching` / `...:coaching_request`
  - `message.type`: `coaching_created` / `coaching_request_created`
- 백엔드 emit: `asst-service-portal/src/common/gateways/handlers/coaching-socket.handler.ts`

### 프론트 수신 지점 — 딱 2곳

| 역할 | 파일 | 핸들러 | 토스트 호출 |
|---|---|---|---|
| 관리자 (코칭요청 받음) | `src/view/advisor/admin/index.vue` | `handleCoachingRequestRedisMessage` :436 | :453 |
| 상담사 (코칭 받음) | `src/view/advisor/agent/index.vue` | `handleCoachingRedisMessage` :562 | :579 |

토스트 유틸: `src/utils/messageUtils.ts:23` `showCustomMessage()`

**진입점이 2개뿐이라 변경 범위가 작다.**

### 문제

`showCustomMessage`는 화면을 보고 있을 때만 유효하다. 다른 탭이 활성 상태거나 창이 최소화되면 알림이 그대로 사라진다.

---

## 2. 결론 요약 (기술 검토 결과)

| 원하는 효과 | 가능? | 방법 |
|---|---|---|
| 다른 탭 활성 / 창 최소화 시 알림 | ✅ **가능** | 탭 타이틀 + favicon 교체 (**이 문서의 채택안**) |
| 같은 상황에서 OS 데스크톱 알림 | ⚠️ https 에서만 | Notification API — **106(http)에서 불가** |
| 같은 상황에서 소리 알림 | ✅ 가능 | `Audio.play()` — 이번 범위에서 제외, 향후 |
| **탭/브라우저를 완전히 닫았을 때** 알림 | ❌ **원리적으로 불가** | Web Push 필요 → 아래 4절 |

### 왜 Notification API(OS 알림)를 채택하지 않았나

Notification API는 **secure context(https 또는 localhost)에서만** 동작한다. 권한 요청 자체가 차단된다.

| 환경 | URL | OS 알림 |
|---|---|---|
| 로컬 | `http://localhost:8173` (`.env.106.local` `HOST_APP_URL`) | ✅ localhost 예외 |
| 106 | `http://106.242.165.142:32026` (`.env.106.dev` `SELF_URL`) | ❌ **불가** |
| 운영 | `https://ecp.etaas.co.kr` (`.env.prd` `LANGSA_GATEWAY_URL`) | ✅ |

106이 http 구조이므로 **OS 알림은 106에서 검증도 사용도 불가**하다.
반면 이 문서의 채택안(타이틀 + favicon)은 **권한 불필요 · https 불필요**라 106에서 그대로 동작한다.

### 왜 "탭 닫힘"은 불가능한가

탭이 닫히면 **Socket.IO 연결 자체가 사라진다.** 이벤트가 브라우저에 도착할 경로가 없으므로, 표현 방식을 아무리 바꿔도 해결되지 않는다.

이를 뚫는 유일한 수단은 Web Push(Service Worker + VAPID)인데:
- 우리 서버가 브라우저로 직접 못 보낸다. **반드시 브라우저 벤더 푸시 서비스를 경유**한다 (Chrome=`fcm.googleapis.com`, Firefox=Mozilla autopush).
- 서버와 상담사 PC 양쪽이 외부 인터넷으로 나가야 한다.
- Service Worker 등록도 secure context 필요 → **106(http)에서 애초에 등록 불가.**

→ **Web Push는 이번 범위에서 제외.** 관리자의 "탭 닫음"은 기술이 아니라 운영으로 다룬다 (6절).

---

## 3. 채택안 — 탭 타이틀 + favicon

백그라운드일 때 브라우저 탭 자체를 알림 매체로 쓴다.

```
[코칭요청 수신]
      │
      ├─ document.visibilityState === 'visible'  → showCustomMessage (지금 그대로)
      │
      └─ document.visibilityState === 'hidden'   → setTabAlert(count)
                                                    ├─ document.title = "🚨 코칭요청 1건 - {원래 타이틀}"
                                                    └─ favicon → 비상 아이콘 교체
[탭 복귀 or 미확인 0]
      │
      └─ clearTabAlert()  → 타이틀·favicon 원복
```

### 3-1. 재사용할 기존 자산 — 카운트

`src/stores/modules/coaching.ts` 에 **이미 도메인별로 분리된 미확인 카운트가 있다.** 새 상태를 만들지 말고 이걸 쓴다.

| 필드 | 대상 | 갱신 |
|---|---|---|
| `unReadRequestCount` | 관리자 — 받은 **코칭요청** 미확인 | `:108` 전용 unread-count API |
| `unReadCoachingCount` | 상담사 — 받은 **코칭** 미확인 | `:93` 전용 unread-count API |

> `coaching.ts:25-27` 주석대로 두 카운트는 의도적으로 분리되어 있다(같은 필드면 호출 순서에 따라 값이 튄다). 배지 숫자로 쓸 때도 역할별로 올바른 필드를 골라야 한다.

수신 핸들러가 이미 `refreshCoachings()`를 호출하므로(admin `:451`, agent `:577`) 카운트는 자동으로 최신화된다.

### 3-2. favicon 현재 상태

- `index.html` 에는 **`<link rel="icon">` 태그가 없다.** (`index.html:6` 에 `<title>ECS CLOUD PORTAL</title>` 만 있음)
- 실제 favicon은 빌드 시 주입된다: `webpack.config.js:99` → `src/assets/images/favicon.ico` (**16x16**)
- 즉 **런타임에는 HtmlWebpackPlugin이 삽입한 link 태그가 존재**하므로, 그 href를 교체하면 된다. 단 없을 수도 있다고 보고 방어적으로 처리한다.

### 3-3. favicon 방식 — 통째로 교체 (권장)

| 안 | 내용 | 판단 |
|---|---|---|
| A | 원본 아이콘 위에 빨간 배지 얹기 | **비추.** 원본이 16x16이라 배지가 거의 안 보인다 |
| **B** | **32x32 canvas에 비상 아이콘을 그려 favicon 자체를 교체** | **채택.** 평소/비상 두 상태만 구분하면 되므로 이게 명확하고 눈에 띈다 |

> 이모지(🚨)를 `fillText`로 그리는 방법도 되지만 OS 폰트 렌더에 의존한다. **도형을 직접 그리는 쪽이 결과가 확실**하다.

---

## 4. 구현 상세

### 4-1. 신규 파일 `src/utils/tabAlert.ts`

공개 API 2개. 모듈 내부에 원본 상태를 보관한다.

```ts
export function setTabAlert(count: number, label: string): void
export function clearTabAlert(): void
```

- `label`: `"코칭요청"` (관리자) / `"코칭"` (상담사)
- 타이틀 형식: `🚨 ${label} ${count}건 - ${baseTitle}`
- `count <= 0` 이면 `clearTabAlert()`와 동일하게 동작시킨다 (호출부 분기 감소)
- **멱등**해야 한다. 같은 count로 여러 번 불려도 원본이 오염되지 않도록, `baseTitle` / 원본 favicon href는 **최초 활성화 시 한 번만** 스냅샷한다.

#### 비상 favicon 생성 (canvas)

```ts
function buildAlertFavicon(count: number): string {
  const size = 32;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d")!;

  // 빨간 원
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
  ctx.fillStyle = "#E53935";
  ctx.fill();

  // 흰 텍스트 (숫자 or 느낌표 — 6절 미결정 항목)
  const text = count > 9 ? "9+" : String(count);
  ctx.fillStyle = "#FFFFFF";
  ctx.font = `bold ${count > 9 ? 16 : 20}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, size / 2, size / 2 + 1);

  return c.toDataURL("image/png");
}
```

#### favicon 교체 시 주의

일부 브라우저는 기존 `<link>`의 href만 바꾸면 갱신이 안 된다.
**기존 link를 제거하고 새 link를 만들어 붙이는 방식**이 안전하다.

```ts
function applyFavicon(href: string) {
  document.querySelectorAll('link[rel~="icon"]').forEach(el => el.remove());
  const link = document.createElement("link");
  link.rel = "icon";
  link.href = href;
  document.head.appendChild(link);
}
```

원복을 위해 최초 스냅샷 시 기존 href를 저장한다. 없으면 빌드 산출물 경로(`/favicon.ico`)를 기본값으로 둔다.

### 4-2. 훅 지점 — 수신 핸들러 2곳

기존 `showCustomMessage` 호출을 **유지**하고, 그 옆에 백그라운드 분기만 추가한다.

**관리자** — `src/view/advisor/admin/index.vue`, `handleCoachingRequestRedisMessage` 내부 `:453` 근처:

```ts
if (document.visibilityState === "hidden") {
  setTabAlert(useCoachingStore().unReadRequestCount, "코칭요청");
}
showCustomMessage({ /* 기존 그대로 */ });
```

**상담사** — `src/view/advisor/agent/index.vue`, `handleCoachingRedisMessage` 내부 `:579` 근처:

```ts
if (document.visibilityState === "hidden") {
  setTabAlert(useCoachingStore().unReadCoachingCount, "코칭");
}
showCustomMessage({ /* 기존 그대로 */ });
```

> `refreshCoachings()`는 비동기다. 위 코드는 **직전 카운트**를 읽을 수 있다.
> 카운트 정확도를 맞추려면 `refreshCoachings()` await 후 호출하거나, 아래 4-3의 카운트 watch에 맡기고 여기서는 트리거만 한다. **watch 방식을 권장** — 카운트 갱신과 표시를 한 곳에서 관리하게 된다.

### 4-3. 원복 조건 — 둘 다 필요

하나라도 빠지면 "이미 읽었는데 비상 아이콘이 남아 있는" 상태가 된다.

1. **탭 복귀** — `visibilitychange` 에서 `visible` 이면 `clearTabAlert()`
2. **미확인 0** — 해당 카운트를 `watch` 해서 `0`이면 `clearTabAlert()`, `> 0` 이고 탭이 hidden이면 `setTabAlert()`

리스너는 컴포넌트 `onMounted`에서 등록하고 **`onUnmounted`에서 반드시 해제**한다.
(기존 코드가 `off()` 후 `on()` 하는 패턴으로 중복 등록을 막고 있으므로 같은 규율을 따른다: admin `:488-489`, agent `:615-616`)

---

## 5. 주의점 — 설계에 반드시 반영

### 5-1. ⚠️ 백그라운드 탭 타이머 스로틀링 — 가장 중요

Chrome은 hidden 탭의 `setInterval`을 강하게 제한한다(초당 1회 → 장시간 hidden이면 더 느려짐).
**따라서 "타이틀 깜빡임"은 의도한 리듬대로 돌지 않고 뚝뚝 끊길 수 있다.**

→ **정적 표시를 기본으로 한다.** `"🚨 코칭요청 1건 - ECS CLOUD PORTAL"` 만으로도 다른 탭에서 충분히 인지되고, 스로틀링 영향을 전혀 받지 않는다.
깜빡임은 넣지 않거나 옵션으로만 둔다 (6절 미결정).

### 5-2. ⚠️ 라우터가 `document.title`을 덮어쓴다

`src/routers/index.ts:58`:

```ts
document.title = to.meta.title ? `${to.meta.title} - ${title}` : title;
```

라우팅이 일어나면 우리가 설정한 알림 타이틀이 지워진다. 두 가지를 처리해야 한다.

- **원래 타이틀을 하드코딩하지 말 것.** `"ECS CLOUD PORTAL"`을 상수로 박으면 라우트별 타이틀(`{meta.title} - ECS CLOUD PORTAL`)로 복원하지 못한다. 반드시 런타임 스냅샷.
- **알림 활성 중 라우팅 시 base title 재적용.** 권장: 라우터 가드에서 title 설정 직후 `reapplyTabAlert(newBaseTitle)`을 호출해 base를 갱신하고 알림 접두사를 다시 붙인다.

**추가 변수 — 호스트 앱 라우터**: 아래 5-3처럼 이 포털은 `host_app`의 remote로도 로드된다. 그 경우 **타이틀을 관리하는 주체가 host 앱의 라우터**일 수 있고, host 레포는 이번 작업 범위가 아니다.
→ 라우터 가드에 훅을 걸 수 없는 경우의 대비책으로 **`<title>` 에 `MutationObserver`를 걸어 외부 변경을 감지 → base 갱신 후 재적용** 방식을 폴백으로 준비한다. (자기 자신의 변경으로 무한 루프가 나지 않도록 재적용 중 플래그로 가드할 것)

### 5-3. ✅ Module Federation이지만 iframe이 아니다 — 통과

`webpack.config.js:111` `exposes` 로 어드바이저가 remote로 노출된다(`AdvisorConsultantComponent`, `AdvisorRenualComponent`, `AdvisorManagementUser`), `remotes.host_app` 은 `HOST_APP_URL`.

Module Federation은 iframe이 아니라 **같은 document에 JS 모듈을 로드**하는 방식이다. 조사 결과 `asst-web-portal` / `asst-web` 양쪽 `.vue` 에 `<iframe>` 사용 흔적이 없다.

→ **`document.title` / favicon 변경이 실제 브라우저 탭에 그대로 반영된다.**
(iframe 렌더였다면 자기 문서의 title/favicon만 바뀌어 탭에 안 보이고, 이 아이디어 자체가 성립하지 않았다.)

> 단, 라우트에 `?mode=iframe` 쿼리를 쓰는 흔적이 있다(`routers/index.ts:68`). 이는 경로 매칭용 접미사 제거 로직이고 iframe 렌더의 증거는 아니다. 다만 **호스트 앱이 특정 메뉴를 iframe으로 감싸는지는 런타임에서 한 번 확인**하는 것이 안전하다 (`window.self !== window.top` 로 판별 가능. iframe이면 `window.top.document` 접근은 동일 출처일 때만 가능).

### 5-4. 기타

- **다중 탭**: 관리자가 어드바이저를 2탭 열면 양쪽 탭 모두 비상 표시된다. 타이틀/favicon은 탭별이므로 중복 알림 문제는 없고, 오히려 자연스럽다.
- **카운트 표기 상한**: 두 자릿수는 16~32px 아이콘에서 판독이 어렵다. `9+` 로 자른다.
- **접근성/취향**: 항상 비상 아이콘이 뜨는 게 부담이면 설정 토글을 둘 수 있다. `AdminSetting.vue` / `stores/modules/settings.ts` 에 붙일 자리가 있다. (이번 범위에서는 제외 권장 — 먼저 동작을 보고 판단)

---

## 6. 미결정 사항 (작업 전 확정 필요)

| # | 항목 | 선택지 | 권장 |
|---|---|---|---|
| 1 | 타이틀 깜빡임 여부 | 정적 프리픽스 / 깜빡임 추가 | **정적만** — 5-1 스로틀링 때문 |
| 2 | favicon 텍스트 | 미확인 건수 숫자 (`1`,`2`,`9+`) / 느낌표 고정 (`!`) | **숫자** — 정보량이 더 크고 구현 비용 동일 |
| 3 | 적용 대상 | 관리자만 / 관리자+상담사 | **둘 다** — 진입점이 이미 2곳이고 비용 차이가 없다 |

> 3번 관련: 최초 논의는 관리자 케이스에서 출발했지만, 상담사도 "다른 탭 보는 중"에는 동일하게 놓친다. 코드 대칭성도 있어 함께 적용하는 편이 낫다.

---

## 7. 검증 방법

106(http)에서 그대로 검증 가능하다. 권한 팝업이 없으므로 절차가 단순하다.

1. 관리자 계정으로 어드바이저 진입 → **다른 탭으로 전환**
2. 상담사 계정에서 코칭요청 전송
3. 확인: 탭 타이틀이 `🚨 코칭요청 N건 - …` 으로 바뀌고 favicon이 빨간 아이콘으로 교체되는가
4. 탭 복귀 → 타이틀·favicon이 **원래대로** 돌아오는가
5. 코칭요청을 읽어 미확인 0 → 원복되는가
6. 알림 활성 중 **다른 메뉴로 라우팅** → 타이틀이 깨지지 않는가 (5-2 검증)
7. 상담사 방향(코칭 수신)도 1~6 반복
8. 호스트 앱(`HOST_APP_URL`)을 통해 remote로 로드된 경로에서도 탭에 반영되는가 (5-3 검증)

---

## 8. 향후 (이번 범위 밖)

| 항목 | 조건 | 비고 |
|---|---|---|
| **소리 알림** | 지금도 가능 (http OK) | `Audio.play()`. 사용자가 이미 페이지와 상호작용한 상태라 autoplay 정책 통과. 다른 창을 보고 있어도 들리므로 **인지율은 OS 알림 이상일 수 있다.** 볼륨/on-off 설정과 함께 별건으로 진행 |
| **OS 데스크톱 알림** | 운영(https)에서만 | Notification API. 권한 거부 시 되돌릴 수 없으므로 설정 토글에서 요청해야 한다. 이 문서의 타이틀/favicon을 **권한 없는 환경의 폴백**으로 두고 계층 구성하면 자연스럽다 |
| **탭 닫힘 대응 (Web Push)** | 사내망 외부 통신 정책 + https 확보 시 | 2절 참고. 현재 조건에서는 불가 |
| **완전한 탭 닫힘 대응 (대안)** | 별도 프로젝트 | Electron/Tauri 래퍼 또는 트레이 에이전트. 상담사 PC 배포가 필요해 규모가 다르다 |

### 관리자 "탭 닫음"에 대한 운영적 처리

기술로 뚫을 수 없는 부분이며, 운영 정책이 더 저렴한 해결책이다.

- 코칭요청 수신 담당자가 어드바이저를 닫아두는 것 자체가 비정상 상태다. **"관리자는 근무 중 어드바이저 상시 유지"** 를 전제로 둔다.
- 상시 유지가 부담되지 않도록 백그라운드 인지율을 올린다 → **이 문서의 작업.**
- 놓친 건은 **미확인 카운트 배지로 복구**된다. `refreshCoachings()` + `unReadRequestCount` 구조가 이미 있어, 탭을 다시 열면 놓친 요청이 보인다. **이 경로는 현재도 동작한다.**

---

## 9. 변경 파일 요약

| 파일 | 변경 |
|---|---|
| `src/utils/tabAlert.ts` | **신규** — `setTabAlert` / `clearTabAlert` (+ `reapplyTabAlert`) |
| `src/view/advisor/admin/index.vue` | `:453` 근처 백그라운드 분기 추가, 원복 리스너/watch 등록·해제 |
| `src/view/advisor/agent/index.vue` | `:579` 근처 동일 |
| `src/routers/index.ts` | `:58` 직후 `reapplyTabAlert()` 호출 (5-2) |
| `src/stores/modules/coaching.ts` | **변경 없음** — 카운트 읽기만 |

- 신규 의존성: **없음**
- 백엔드 변경: **없음**
- 서버/인프라 조건: **없음** (http에서 동작)
