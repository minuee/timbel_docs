# 로컬 단독 실행 — 메뉴 이동 시 빈 화면 (transition mode="out-in") 수정 가이드

> **대상** `asst-web` 프론트 (Vue 3.5 + vue-router, MF remote `advisor_app`)
> **범위** **로컬 단독 실행 경로 전용**. 106/포털 임베드(MF remote) 경로는 이 코드를 타지 않는다.
> **상태** 기준 레포 적용 완료 (`src/layouts/components/Main/index.vue`)
> **파일** 고친 건 딱 한 곳 — `Main/index.vue` 의 `<transition>` 제거

---

## 1. 증상

- 로컬(`npm run local5f` 등 `webpack serve`)로 띄운 뒤 **상단 가로 GNB 메뉴를 클릭**하면 콘텐츠 영역이 빈 화면.
- 좌측 GNB·상단 GNB·탭은 정상 표시. **콘텐츠만** 안 나온다.
- **특정 메뉴가 아니라 모든 메뉴**에서 동일하게 재현.
- **콘솔에 에러도 경고도 전혀 없다.** (이게 진단을 가장 오래 끌었던 지점)
- **F5 새로고침하면 정상으로 뜬다.** 그 뒤 다시 메뉴를 누르면 또 빈 화면.
- **106 서버에서는 재현되지 않는다.**

## 2. 원인

`src/layouts/components/Main/index.vue` 의 라우터 아웃렛이 이렇게 3중 중첩돼 있었다.

```vue
<router-view v-slot="{ Component, route }">
  <transition appear name="fade-transform" mode="out-in">   <!-- ← 원인 -->
    <keep-alive :include="keepAliveName">
      <component :is="Component" v-if="isRouterShow" :key="route.fullPath" />
    </keep-alive>
  </transition>
</router-view>
```

`mode="out-in"` 은 **"이전 컴포넌트의 leave 가 끝났다는 신호를 받은 뒤에" 새 컴포넌트를 넣는다**는 의미다.
그런데 `transition → keep-alive → component(v-if + :key)` 로 겹친 이 구조에서는
leave 완료 → enter 인수인계가 끊긴다. 결과는:

| | 결과 |
|---|---|
| 이전 화면 | 정상적으로 사라짐 |
| 새 화면 | "leave 끝나길 기다리는 중" 상태로 **영구 대기** |
| DOM | `<!---->` (Vue 의 빈 placeholder) 만 남음 |
| 콘솔 | **아무 로그도 없음** — 예외가 아니라 "대기"이기 때문 |

### 왜 F5 는 정상인가

새로고침하면 **이전 컴포넌트가 존재하지 않는다** → leave 를 기다릴 대상이 없다 → 곧바로 enter.
그래서 "새로고침하면 되는데 메뉴로 이동하면 안 되는" 헷갈리는 증상이 된다.

### 왜 106 에서는 재현되지 않는가

이 레이아웃으로 올라가는 경로가 하나뿐이다.

```
staticRouter.ts:16   /layout  →  @/layouts/index.vue
                                    └ LayoutVertical / LayoutTransverse
                                        └ layouts/components/Main/index.vue   ← 문제 파일
```

즉 **앱이 자체 라우터로 단독 실행될 때만** 렌더된다.
106 은 host 포털이 MF `exposes` 3종(`AdvisorConsultantComponent` / `AdvisorManagementUser` /
`AdvisorRenualComponent`)만 마운트하고 레이아웃·GNB·`Main` 은 포털 자기 것을 쓴다
→ 이 트랜지션 코드를 아예 타지 않는다.

> ⚠️ 그래서 **"106 은 멀쩡한데 로컬만 이상하다"** 는 이 문제의 증상이지 환경 설정 탓이 아니다.
> chunkload(청크 404) 이슈와도 무관하다 — 청크는 요청조차 되지 않았다.

## 3. 조치

`<transition>` 을 제거한다. `keep-alive` 와 `:key` 는 그대로 둔다.

```vue
<router-view v-slot="{ Component, route }">
  <keep-alive :include="keepAliveName">
    <component :is="Component" v-if="isRouterShow" :key="route.fullPath" />
  </keep-alive>
</router-view>
```

잃는 것은 페이지 전환 페이드 애니메이션(0.2s)뿐이다.
`src/styles/common.scss` 의 `.fade-transform-*` 규칙은 다른 곳에서 쓸 수 있으니 남겨둔다.

> 트랜지션을 꼭 살려야 한다면 `mode="out-in"` 만 빼고(동시 전환) 검증할 것.
> 단 두 컴포넌트가 잠시 겹쳐 레이아웃이 흔들릴 수 있어, 기준 레포는 **제거**를 택했다.

## 4. 진단 절차 (다른 레포에서 재현·확인용)

에러 로그가 없어서 일반적인 방법으로는 안 잡힌다. `Main/index.vue` 에 임시 로그를 넣어 단계를 가른다.

```ts
// 1단계 — 라우트 매칭/컴포넌트 매핑 확인
const __diagRoute = useRoute();
watch(() => __diagRoute.fullPath, p => {
  console.log("[진단]", p, __diagRoute.matched.length, isRouterShow.value,
    __diagRoute.matched.map(r => ({ path: r.path, hasComponent: !!r.components?.default })));
}, { immediate: true });
```

```ts
// 2단계 — DOM 실제 상태 (트랜지션 0.2s 이후를 봐야 한다)
watch(() => __diagRoute.fullPath, async () => {
  await nextTick();
  setTimeout(() => {
    const holder = document.querySelector(".el-main")?.firstElementChild;
    console.log("[진단2]", {
      holderHTML길이: holder?.innerHTML.length ?? 0,
      compTag: holder?.firstElementChild?.tagName ?? "(없음)"
    });
  }, 400);
}, { immediate: true });
```

판별표:

| 로그 결과 | 원인 |
|---|---|
| `matched=0` | 라우트 매칭 실패 (path 불일치) |
| `matched≥1` 인데 `hasComponent:false` | 컴포넌트 매핑 실패 (`dynamicRouter` 의 `modules[...]` miss) |
| `hasComponent:true` + `holderHTML길이:7` (`<!---->`) + `compTag:"(없음)"` | **이 문서의 케이스** — 트랜지션이 새 컴포넌트를 안 넣음 |
| `compTag` 있는데 높이 0 / opacity 0 | 레이아웃 붕괴 또는 leave 상태 고착 |

확정 방법은 단순하다. **`<transition>` 만 잠시 제거해서 정상이면 확정.**

## 5. 같이 확인된 별건 (이 문서 범위 밖, 미조치)

`src/layouts/components/Tabs/index.vue:68`

```ts
route.meta.isKeepAlive && keepAliveStore.addKeepAliveName(route.meta.code as string);
```

`<keep-alive :include>` 는 **컴포넌트 name** 과 매칭하는데, 여기 넣는 값은 메뉴 코드
(`RENUAL_CHAT`, `ADVISOR_CONSULTANT` …)다. 라우트 컴포넌트는 `<script setup>` 이라 name 이
파일명 기반이므로 **어떤 것도 매칭되지 않는다** → 현재 keep-alive 는 아무것도 캐시하지 못한다.

동작 자체는 정상(캐시만 안 될 뿐)이라 급하지 않지만, 페이지 전환 시 상태 보존이 필요해지면
`include` 를 컴포넌트 name 기준으로 맞추거나 `route.name` 규칙을 재정의해야 한다.

## 6. 체크리스트

- [ ] `Main/index.vue` 에서 `<transition ... mode="out-in">` 제거 (keep-alive·`:key` 는 유지)
- [ ] 로컬 단독 실행으로 띄워 **상단 GNB 로 여러 메뉴 연속 이동** — 전부 정상 표시되는지
- [ ] 같은 메뉴를 F5 로도 진입해 동일하게 뜨는지
- [ ] 포털 임베드(MF) 환경은 이 파일을 타지 않으므로 **회귀 테스트 불필요** (영향 범위 0)
