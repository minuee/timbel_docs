# Module Federation 개념과 구조 — 포털 인계 대비 가이드

> **대상**: 이 프로젝트(asst-web-portal)와 host 포털을 인계받을 프론트엔드 개발자
> **목적**: Module Federation(이하 **MF**)이 무엇이고, 왜 이 구조를 쓰며, 어디를 건드리면 어디가 깨지는지 이해한다.
> **범위**: MF 자체의 정의·동작 원리·설계 원칙이 중심. 구체적 장애 대응은 `webpack-mf-chunkload-fix-guide.md` 참고.
>
> 기준 버전: webpack `^5.99.9` / vue `3.5.18` / vue-router `^4.2.4` / pinia `^2.2.4`

---

## 0. 30초 요약

- MF = **여러 개의 독립 배포된 웹앱을, 사용자 브라우저에서 실시간으로 합쳐 하나처럼 보이게 하는 webpack 5 기능.**
- 우리 구조: **포털(host_app)** 이 **이 앱(advisor_app)** 의 컴포넌트를 런타임에 가져다 자기 화면에 끼워 넣는다.
- 포털이 아는 것은 `exposes` 에 적힌 **이름 3개뿐**. 그 아래 내부 구조는 전부 우리 몫.
- 그래서 **"우리 앱을 재배포하면 포털은 재배포 없이 최신 화면을 보게 된다"** 가 이 구조의 최대 이득이고,
  **"포털이 우리 내부를 모른다"** 가 이 구조의 최대 제약이다. 이 문서의 거의 모든 내용이 이 두 문장에서 파생된다.

---

## 1. 왜 이런 게 필요한가 (문제부터)

한 포털 화면 안에 **여러 팀이 만든 화면**이 들어간다고 하자.

### 전통적 방식 — 하나의 앱으로 합치기

```
포털 저장소 안에 상담 어드바이저 코드도 같이 둔다
→ 버튼 색 하나 바꿔도 포털 전체를 다시 빌드/배포
→ 팀마다 배포 주기가 다른데 릴리스를 서로 기다려야 함
→ 저장소 하나가 계속 비대해지고 빌드 시간이 늘어남
```

### 라이브러리(npm)로 분리하면?

```
상담 어드바이저를 npm 패키지로 만들어 포털이 install
→ 여전히 "포털이 다시 빌드/배포" 해야 반영됨 (빌드 시점에 합쳐지므로)
→ 버전 올리는 PR, 릴리스 태깅… 배포 리드타임은 그대로
```

즉 **분리는 됐지만 배포 독립성은 안 생긴다**. 이게 핵심 미해결 과제였다.

### 대안 비교

| 방식 | 배포 독립 | 화면 통합감 | 단점 |
|---|:---:|:---:|---|
| 한 저장소로 합치기 | ✕ | ◎ | 배포가 서로 묶임 |
| npm 라이브러리 | ✕ | ◎ | 빌드 타임 결합, 리드타임 그대로 |
| iframe | ◎ | ✕ | 스타일/높이/라우팅/통신 전부 단절, UX 나쁨 |
| Web Components | ○ | ○ | 프레임워크 상태·라우터 공유가 까다로움 |
| **Module Federation** | **◎** | **◎** | 설정 복잡, 버전 정합성 관리 필요 |

MF는 **"배포는 따로, 화면은 하나로"** 를 동시에 만족시키려는 답이다.
이렇게 앱을 도메인 단위로 쪼개 독립 배포하는 아키텍처를 **마이크로 프론트엔드(Micro Frontend)** 라고 부르고,
MF는 그것을 구현하는 **수단** 중 하나다. (MF = 아키텍처가 아니라 도구)

---

## 2. 정의와 핵심 개념

### 2-1. 한 문장 정의

> **Module Federation**: 서로 다른 빌드 결과물끼리, **실행 시점(런타임)에** 모듈(코드 조각)을 주고받게 해주는 webpack 5의 기능.

- **Module** = 코드 덩어리 (컴포넌트, 함수, 라우터 설정 등)
- **Federation** = 연합 (독립된 주체들이 대등하게 협력)
- 합쳐서 **"코드 연합"** 정도로 읽으면 된다.

### 2-2. 가장 중요한 한 가지 — 언제 합쳐지는가

| | npm 라이브러리 | Module Federation |
|---|---|---|
| 합쳐지는 시점 | **빌드 타임** (배포 전, 서버에서) | **런타임** (사용자 브라우저에서) |
| 상대 코드 위치 | 내 번들 안에 복사됨 | **상대 서버에 그대로 있음** |
| 상대가 수정하면 | 내가 다시 빌드·배포해야 반영 | **사용자가 새로고침하면 반영** |

MF를 이해할 때 헷갈리는 대부분은 이 표 한 줄에서 갈린다.
`import("advisor_app/X")` 는 **내 번들 안의 코드를 부르는 게 아니라, 다른 서버에 HTTP 요청을 보내는 코드**다.

### 2-3. 역할 3가지

| 용어 | 읽는 법 | 뜻 | 우리 프로젝트 |
|---|---|---|---|
| **host** | 호스트 | 남의 모듈을 **가져다 쓰는** 쪽 | **포털** (`host_app`) |
| **remote** | 리모트 | 자기 모듈을 **내주는** 쪽 | **이 앱** (`advisor_app`) |
| **shared** | 셰어드 | 양쪽이 **같이 쓰기로 약속한** 라이브러리 | vue / pinia / vue-router |

> host와 remote는 **역할 이름이지 신분이 아니다.** 한 앱이 동시에 둘 다일 수 있다.
> 실제로 우리 앱도 `remotes: { host_app: ... }` 설정이 있어 형식상 host 역할도 갖는다 (7-3절 참고).

### 2-4. 용어 사전 (영어 부담 덜기용)

| 영어 | 발음 | 이 문서에서의 의미 |
|---|---|---|
| expose | 익스포즈 | 노출하다 → "외부에 내주는 모듈 목록" |
| remote entry | 리모트 엔트리 | remote의 **출입구 파일** (`remoteEntry.js`) |
| chunk | 청크 | 코드를 잘라 놓은 조각 파일 (`123.js` 등) |
| singleton | 싱글턴 | 딱 하나만 존재 → "vue는 한 벌만 로드" |
| eager | 이거 | 성급한 → "나중에 말고 처음부터 로드" |
| lazy / async | 레이지 / 어싱크 | 게으른 / 비동기 → "필요할 때 가서 받아옴" |
| bootstrap | 부트스트랩 | 시동 코드 (`main.ts` 진입 부분) |
| fallback | 폴백 | 실패 시 대신 쓰는 것 |

---

## 3. 동작 원리

### 3-1. remoteEntry.js — 자판기 비유

remote를 빌드하면 `remoteEntry.js` 라는 특별한 파일이 하나 생긴다.
이 파일은 **화면 코드가 아니라, 카탈로그 + 자판기**다.

```
remoteEntry.js 가 하는 일
├── init(shared)  : "vue/pinia는 너희 걸 쓸게" 하고 공유 라이브러리 협상
└── get("./이름") : 그 이름에 해당하는 모듈을 로드해서 돌려줌
```

우리 앱의 실제 산출물(`dist/remoteEntry.js`)에는 아래 3개가 등록돼 있다.

```
./AdvisorConsultantComponent
./AdvisorManagementUser
./AdvisorRenualComponent
```

> **파일명이 고정인 이유**: host는 이 파일 주소를 설정에 하드코딩한다.
> 그래서 `remoteEntry.js` 만은 contenthash가 붙지 않는다 (`webpack.config.js:107`).
> 반대로 나머지 청크는 해시가 붙는데, 이 비대칭이 개발 서버에서 ChunkLoadError를 만든다 → 9-1절.

### 3-2. 실제 로딩 순서

포털에서 `import("advisor_app/AdvisorRenualComponent")` 한 줄이 실행되면 브라우저에서 이런 일이 일어난다.

```
① <script src="http://<remote주소>/remoteEntry.js"> 를 동적으로 삽입
      ↓  (여기서 404면 remote 영역만 빈 화면)
② window.advisor_app 전역 객체 생성됨
      ↓
③ window.advisor_app.init(포털의 shared 목록)
      ↓  ← vue/pinia 버전 협상. 조건 안 맞으면 각자 로드(중복!) 하거나 에러
④ window.advisor_app.get("./AdvisorRenualComponent")
      ↓
⑤ 필요한 청크(js/css)를 remote 서버에서 추가로 내려받음
      ↓  ← 여기서 404면 ChunkLoadError
⑥ 반환된 Vue 컴포넌트를 포털 화면에 마운트
```

**여기서 반드시 기억할 것**
- 청크는 host가 아니라 **remote 서버**에서 받아온다 → remote 서버가 죽으면 그 영역만 죽는다.
- 그래서 `output.publicPath: "auto"` 가 필수다 (`webpack.config.js:27`).
  이 설정이 있어야 "내 청크는 내가 배포된 주소에서 받아라"가 성립한다.
  `"/"` 같은 고정값이면 host 도메인에서 청크를 찾아 404가 난다.

### 3-3. 코드 위에서 보는 양쪽 설정

**remote 쪽 (이 저장소, `webpack.config.js:105-121` — 실제 코드)**

```js
new ModuleFederationPlugin({
  name: "advisor_app",              // 전역에 window.advisor_app 으로 뜰 이름
  filename: "remoteEntry.js",       // 출입구 파일명
  remotes: {                        // 내가 가져다 쓸 상대 (7-3절 참고)
    host_app: "host_app@" + process.env.HOST_APP_URL + "/remoteEntry.js"
  },
  exposes: {                        // 내가 외부에 내주는 목록
    "./AdvisorConsultantComponent": "./src/view/advisor/consultant/index.vue",
    "./AdvisorManagementUser":      "./src/view/advisor/admin/management/user/index.vue",
    "./AdvisorRenualComponent":     "./src/view/advisor-renual/index.vue"
  },
  shared: {
    vue:          { singleton: true, eager: true },
    pinia:        { singleton: true, eager: true },
    "vue-router": { singleton: true, eager: true }
  }
})
```

**host 쪽 (포털, 별도 저장소 — 일반적인 형태)**

```js
new ModuleFederationPlugin({
  name: "host_app",
  filename: "remoteEntry.js",
  remotes: {
    // "설정이름: 상대name@상대주소/remoteEntry.js"
    advisor_app: "advisor_app@http://<advisor 배포주소>/remoteEntry.js"
  },
  exposes: { "./router": "./src/router/index.ts" },
  shared: { vue: { singleton: true }, pinia: { singleton: true }, "vue-router": { singleton: true } }
})
```

**사용하는 쪽 코드**

```js
// "advisor_app" 은 위 remotes 의 키, "/AdvisorRenualComponent" 는 상대 exposes 의 이름
const AdvisorRenual = defineAsyncComponent(() => import("advisor_app/AdvisorRenualComponent"));
```

> `remotes` 의 문자열 `"advisor_app@주소"` 에서 **@ 앞은 remote 쪽 `name` 과 반드시 일치**해야 한다.
> 불일치하면 `window.advisor_app` 을 못 찾아 "Container not found" 계열 에러가 난다.

---

## 4. shared — 가장 자주 사고 나는 지점

### 4-1. 왜 공유해야 하나

host와 remote가 각각 Vue를 로드하면 **Vue 인스턴스가 2개** 생긴다. 그러면:

- `provide/inject` 가 통하지 않음
- pinia 스토어가 서로 다른 인스턴스 → 상태가 따로 놈
- vue-router가 2개 → URL은 바뀌는데 화면이 안 바뀜, 또는 뒤로가기가 이상해짐
- 번들 크기 2배

그래서 프레임워크 계열은 **반드시 한 벌만** 써야 한다.

### 4-2. 옵션 의미

| 옵션 | 뜻 | 우리 설정 |
|---|---|---|
| `singleton: true` | 버전이 달라도 **딱 하나만** 로드. 안 맞으면 경고 후 하나 선택 | vue/pinia/vue-router 전부 적용 |
| `eager: true` | 비동기로 나눠 받지 않고 **초기 번들에 포함** | 적용됨 (아래 설명) |
| `requiredVersion` | 요구 버전 범위 | 미지정 (package.json 값 사용) |
| `strictVersion` | 버전 불일치 시 경고가 아니라 **에러** | 미사용 |

**`eager: true` 를 쓴 이유와 대가**

- MF의 정석은 `bootstrap.js` 패턴이다. `main.ts` 를 얇게 만들고 실제 시동 코드를 `import("./bootstrap")` 로 비동기 분리해, shared 협상이 끝난 뒤 앱이 뜨게 한다.
- 우리는 그 분리 없이 `main.ts` 에서 바로 시동하므로(`webpack.config.js:25` entry), `eager: true` 로 shared를 초기 번들에 넣어 "협상 전에 vue를 못 찾는" 문제를 피했다.
- **대가**: eager로 넣은 라이브러리는 remote 번들에도 실물이 포함된다. host가 이미 로드했다면 낭비가 생길 수 있다.
- 단독 실행(`npm run serve`)과 임베드 실행을 한 코드베이스로 지원해야 하는 지금 구조에서는 **합리적인 타협**이다. 건드리지 말 것. 최적화하려면 bootstrap 패턴 도입이 선행돼야 한다.

### 4-3. 버전 정합성 규칙 (인계 시 필수)

> **vue / pinia / vue-router 버전을 올릴 때는 host 포털과 반드시 같이 맞춘다.**

한쪽만 major를 올리면 singleton 협상에서 한 벌만 살아남는데, 살아남은 쪽이 다른 쪽의 API를 만족 못 하면
런타임에 원인 파악이 매우 어려운 에러가 난다 (`Cannot read properties of undefined` 류가 화면 깊은 곳에서 터짐).

---

## 5. 이 프로젝트의 구조 지도

```
   포털 (host_app, 별도 저장소)                    이 앱 (advisor_app, 이 저장소)
   ─────────────────────────                      ─────────────────────────────
   remotes: advisor_app ─────── 런타임 로드 ─────→  dist/remoteEntry.js
   화면에 마운트         ←────── 컴포넌트 ────────  AdvisorRenualComponent
                                                          │
                                                  route.path 로 리프 결정
                                                          ↓
                                             chat / dashboard / todo / admin/* …
```

| 항목 | 위치 |
|---|---|
| MF 설정 (기본) | `webpack.config.js:105-121` |
| MF 설정 (5f 환경) | `webpack.config.5f.js:95` 부근 |
| remote 이름 | `advisor_app` |
| 노출 모듈 | 3개 (3-1절 목록) |
| host 주소 설정 | `.env.*` 의 `HOST_APP_URL` |
| 청크 404 대응 | `src/utils/lazyView.ts` |
| 임베드용 스타일 주입 | `src/view/advisor-renual/index.vue:49-53` |
| 리뉴얼 내부 라우팅 | `src/view/advisor-renual/index.vue:88-95` |

---

## 6. 설계 원칙 — 인계 후 판단 기준

### 6-1. 무엇을 expose 할 것인가

> **원칙: exposes는 "메뉴 = 화면" 단위로 최소화한다. 세부 컴포넌트를 내주지 않는다.**

- exposes에 올린 이름은 **host와의 공개 계약(API)** 이다. 이름을 바꾸거나 지우면 **포털이 깨진다.**
- 반대로 exposes에 없는 내부 구조는 언제든 자유롭게 리팩터링할 수 있다.
- 버튼·모달 같은 조각 컴포넌트를 expose 하면 계약면이 넓어져 배포 독립성이 사라진다. **하지 말 것.**

### 6-2. 라우팅 — remote 내부 라우팅 패턴

**문제**: 리뉴얼 화면은 리프 페이지가 17개인데(`index.vue:67-86`), 포털에 노출된 리뉴얼 컴포넌트는 `./AdvisorRenualComponent` **1개뿐**이다. 포털은 어떤 리뉴얼 메뉴를 눌러도 이 진입점 하나만 마운트한다.

**해결**: 진입점이 **자기 URL을 읽어 해당 리프를 직접 렌더**한다.

```js
// src/view/advisor-renual/index.vue:88-95
const route = useRoute();
const activeLeaf = computed(() => {
  if (!LEAF_ROUTING) return null;
  const m = route.path.match(/advisor-renual\/(.+)$/);
  if (!m) return null;
  return LEAF[m[1].replace(/\/+$/, "")] ?? null;
});
```

이것이 MF의 표준 패턴인 **remote 내부 라우팅(sub-routing)** 이다. 편법이 아니다.

| 선택지 | 결과 |
|---|---|
| exposes에 17개 다 등록 | 리프 추가할 때마다 **포털도 같이 배포** → 배포 독립성 상실 |
| **진입점 1개 + 내부 라우팅** | 리프를 아무리 늘려도 **우리만 배포**하면 됨 ✅ |

> **주의**: 이 방식은 **host와 remote가 같은 vue-router 인스턴스를 공유**해야 성립한다.
> `shared` 에서 `vue-router: { singleton: true }` 가 빠지면 `useRoute()` 가 포털의 실제 URL을 못 읽어 라우팅이 통째로 죽는다.

### 6-3. 스타일 격리

remote는 host 페이지 **안에서** 렌더되므로 CSS가 양방향으로 샌다.

| 방향 | 증상 | 대응 |
|---|---|---|
| host → remote | 포털 전역 CSS가 우리 컴포넌트를 망가뜨림 | 스코프 클래스로 되돌리기 (`index.vue` 의 `adv-remote-scope`) |
| remote → host | 우리 전역 CSS가 포털을 망가뜨림 | `<style scoped>` 사용, 전역 셀렉터 남발 금지 |

또 하나 — **임베드되면 우리 `main.ts` 는 실행되지 않는다.** 포털이 컴포넌트만 가져가기 때문이다.
따라서 `main.ts` 에서 하던 전역 스타일 import가 통째로 누락된다. 그래서 진입점에서 직접 넣어준다.

```js
// src/view/advisor-renual/index.vue:52-53
import "@/styles/global.scss";
import "@/styles/common.scss";
```

> **일반화**: `main.ts` 에서 하는 모든 초기화(전역 스타일, 플러그인 등록, 전역 지시자, i18n 초기화 등)는
> **임베드 경로에선 실행되지 않는다.** 새 전역 초기화를 추가할 땐 반드시 "임베드일 때도 도는가"를 확인해야 한다.
> 이건 MF의 대표적 함정이고, 단독 실행으로 테스트하면 절대 안 잡힌다.

### 6-4. host ↔ remote 통신

권장 순서:

1. **props / emit** — 가장 안전. 계약이 명시적이다.
2. **shared pinia 스토어** — singleton이 보장될 때만. 결합도가 올라간다.
3. **전역 이벤트(window.dispatchEvent)** — 느슨하지만 추적이 어렵다. 최후 수단.
4. ~~전역 변수 직접 접근~~ — 금지. 배포 시점이 다른 두 앱이 암묵적으로 결합된다.

### 6-5. 실패를 전제로 설계하기

remote 로딩은 **네트워크 요청**이다. 즉 **실패할 수 있다.**

- 404 (배포 직후 옛 청크맵) → `src/utils/lazyView.ts` 가 감지해 1회 자동 새로고침, 재실패 시 안내 UI
- remote 서버 다운 → 그 영역만 빈 화면. host 전체는 살아야 한다
- 반드시 `defineAsyncComponent` 의 `errorComponent`/`loadingComponent` 나 그에 준하는 폴백을 둘 것

> `import()` 를 감싸지 않고 그대로 쓰면 remote 장애가 **화면 전체 백지**로 번진다.

---

## 7. 자주 나오는 오해 정리

### 7-1. "MF를 쓰면 프레임워크가 달라도 된다"

기술적으로는 가능하지만(React host + Vue remote), 그때는 shared 이점이 사라지고 마운트/언마운트를 수동으로 관리해야 한다.
**우리는 양쪽 다 Vue 3 이며, 그 전제 위에서 shared singleton 설계가 성립한다.** 이 전제를 깨지 말 것.

### 7-2. "remote를 배포하면 포털도 배포해야 한다"

**아니다.** 그게 MF를 쓰는 이유다. 단 두 가지 예외가 있다.

- `exposes` 의 **이름을 바꾸거나 지울 때** (계약 변경)
- **shared 라이브러리 major 버전**을 올릴 때 (4-3절)

### 7-3. "우리 앱도 host_app 을 쓰고 있다"

설정상으론 그렇지만(`webpack.config.js:108-110`), **실제로는 쓰지 않는다.**

```js
// src/routers/index.ts:12-17 — 정의만 되어 있고 호출하는 곳이 없다
const loadHostRoutes = async () => {
  const { default: hostRouter } = await import("host_app/router");
  return hostRouter.options.routes;
};
```

그래서 `.env.*` 의 `HOST_APP_URL` 은 아무 주소나 넣어도 로컬이 정상 동작한다
(`.env.106.local:48-51` 주석 참고). 실질 관계는 **포털 → 우리 단방향**이다.

> 인계 시: 이 dead code를 지울지 말지는 "포털 라우팅 정보를 우리가 읽을 계획이 있는가"로 판단하면 된다.
> 계획이 없다면 `remotes` 설정과 함께 정리하는 게 혼란을 줄인다.

---

## 8. 디버깅 방법

브라우저 콘솔에서 바로 확인할 수 있는 것들:

```js
// ① remote 컨테이너가 로드됐는가
window.advisor_app          // undefined 면 remoteEntry.js 자체를 못 받은 것

// ② vue가 한 벌인가 (두 벌이면 상태 공유가 깨진다)
// Vue DevTools 에서 앱 인스턴스가 2개로 보이면 shared 협상 실패 신호
```

네트워크 탭에서 볼 순서:

1. `remoteEntry.js` — 200인가? 주소가 맞는가? (`HOST_APP_URL` / host의 remotes 설정)
2. 그 뒤 따라오는 청크(`*.js`) — **remote 도메인**에서 받아오는가? host 도메인이면 `publicPath` 문제
3. 404 청크가 있는가? → ChunkLoadError → `webpack-mf-chunkload-fix-guide.md`

---

## 9. 흔한 함정 체크리스트

우리 프로젝트에서 실제로 겪고 대응한 것들이다. **전부 같은 뿌리(런타임 결합)에서 나온다.**

| # | 증상 | 원인 | 대응 위치 |
|---|---|---|---|
| 9-1 | remote 재배포 후 그 영역만 빈 화면, 콘솔에 `ChunkLoadError` | host가 페이지 로드 시점의 **옛 청크맵**을 들고 있어 사라진 해시 청크를 요청 | `webpack.config.js:26-38` (dev-server 파일명 고정 + no-store) / `src/utils/lazyView.ts` / 전용 문서 참고 |
| 9-2 | 임베드하면 flex 레이아웃이 세로로 깨짐 | `main.ts` 를 안 거쳐 전역 SCSS 미주입 | `index.vue:49-53` 진입점 직접 import |
| 9-3 | 체크박스가 좌상단으로 몰림 등 이상한 스타일 | host 전역 CSS가 remote로 샘 | `adv-remote-scope` 스코프 클래스로 되돌림 |
| 9-4 | `host_app@undefined/remoteEntry.js` 404 | `HOST_APP_URL` 미설정 | `.env.*` 에 값 지정 |
| 9-5 | 상태가 따로 놀거나 라우팅이 안 먹음 | shared singleton 실패 → vue/pinia/router 2벌 | `webpack.config.js:117-121` 확인, 양쪽 버전 정합 |
| 9-6 | 리프 URL로 갔는데 원하는 화면이 아닌 허브가 뜸 | 내부 라우팅 플래그 누락 | `.env.*` 의 `VITE_RENUAL_LEAF_ROUTING` (10-2절) |

---

## 10. 인계받을 때 확인할 것

### 10-1. 구조 파악 순서 (추천)

1. `webpack.config.js:105-121` — 이 앱이 무엇을 내주고 무엇을 가져오는지
2. `dist/remoteEntry.js` 에서 노출 이름 확인 — 설정과 산출물이 일치하는지
3. 포털 저장소의 `remotes` 설정 — 주소가 어느 환경을 가리키는지
4. `src/view/advisor-renual/index.vue` — 내부 라우팅이 어떻게 도는지
5. `src/utils/lazyView.ts` — 실패 시 어떻게 복구하는지

### 10-2. 환경변수 주의

`VITE_RENUAL_LEAF_ROUTING` 은 MF 자체 설정이 **아니라**, 리뉴얼 화면을 서버별로 켜고 끄는 **롤아웃 스위치**다.

```js
// src/view/advisor-renual/index.vue:63
const LEAF_ROUTING = process.env.VITE_RENUAL_LEAF_ROUTING === "true";
```

- 코드는 모든 환경 번들에 들어간다. 플래그가 없으면 `activeLeaf` 가 항상 `null` → 기존 사이트맵 허브가 뜬다.
- **새 환경의 `.env` 를 만들 때 이 줄을 빠뜨리면 리프 진입이 조용히 안 된다** (에러가 안 나서 더 헷갈림).
- 리뉴얼이 전 환경 기본이 되면 이 플래그는 제거 대상이다.

### 10-3. 배포 시 체크

- [ ] remote 배포 주소가 host의 `remotes` 설정과 일치하는가
- [ ] `output.publicPath: "auto"` 가 유지되는가 (청크를 자기 서버에서 받게 하는 핵심)
- [ ] 운영 빌드에서 `[contenthash]` 가 유지되는가 (dev-server만 고정 파일명)
- [ ] `exposes` 의 이름을 바꾸지 않았는가 (바꿨다면 포털도 같이 배포)
- [ ] vue/pinia/vue-router 버전을 포털과 맞췄는가
- [ ] remote 서버가 host 도메인에 대해 CORS를 허용하는가

---

## 11. 호환성 점검 — host·다른 앱과 부딪히는지 확인하기

> 포털 소스가 없어도 **브라우저만으로 대부분 진단된다.** 이 장은 그 절차와 판정 기준이다.
>
> 📌 **실제 개발 서버를 측정한 결과는 `docs/module-federation-실측기록.md` 에 있다.**
> 이 장은 "어떻게 확인하는가"(방법론), 실측기록은 "확인해보니 어땠는가"(결과)를 담는다.
> 아래 내용 중 실측으로 보정된 것:
> - `__webpack_share_scopes__` 는 **window 로 접근되지 않았다** → **Vue 앱 인스턴스 수**로 판정할 것 (11-4 ① 참고)
> - element-plus 중복은 **사실로 확정**되었다 (host / advisor / aicm 3벌)
> - 추가 리스크로 **CSP report-only** 가 발견되었다 (enforce 전환 시 전 remote 로드 실패)

### 11-1. 현재 shared 설정의 위험도

```js
// webpack.config.js:117-121
shared: {
  vue:          { singleton: true, eager: true },
  pinia:        { singleton: true, eager: true },
  "vue-router": { singleton: true, eager: true }
}
```

| 항목 | 상태 | 설명 |
|---|:---:|---|
| 프레임워크 3종 singleton | ✅ | 상태·라우팅이 깨지는 최악은 막혀 있다 |
| 버전 협상 | ⚠️ | `requiredVersion`·`strictVersion` 없음 → 불일치해도 **경고만** 찍고 진행 |
| `eager: true` | ⚠️ | 동작 이상 없음. **번들 크기 손해**만 (4-2절) |
| shared 누락 라이브러리 | 🔴 | 아래 11-2 |

**버전이 갈리면 어떻게 되나**: singleton은 **버전 높은 쪽 하나**가 이긴다.
우리 `vue` 는 `3.5.18` 로 **정확히 고정**(캐럿 없음), `pinia ^2.2.4`, `vue-router ^4.2.4` 는 범위다.
host가 `vue 3.4.x` 라면 3.5.18이 채택되어 **포털이 자기가 빌드한 적 없는 Vue 위에서 돈다.**
minor 차이는 대개 무사하지만 **major가 갈리면(pinia 2→3, vue-router 4→5) 조용히 터진다.**

### 11-2. shared에 없는데 공유가 필요한 것들 (가장 중요)

`dependencies` 중 **두 벌이 되면 실제로 문제가 생기는** 라이브러리들이다.

| 라이브러리 | 두 벌이면 생기는 일 | 심각도 |
|---|---|:---:|
| `element-plus` (2.9.3) | **z-index 카운터가 각자 따로** 돌아 팝업 겹침 순서가 깨짐 / 다크 CSS 변수 분리 / CSS 2벌 로드 | 🔴 |
| `socket.io-client` (^4.7.4) | **커넥션이 2개** 열려 실시간 이벤트 중복 수신 | 🔴 |
| `vue-i18n` (`>=11.1.6 <11.4.0`) | i18n 인스턴스 분리 → `$t` 미해석·언어 전환 불일치 | 🟡 |
| `quasar` (2.12.6) | 플러그인(Notify/Dialog) 상태 분리 | 🟡 |
| `@vueuse/core`, `dayjs` | 중복 로드(용량)만. 동작은 무해 | 🟢 |

> shared에 추가하면 해결되지만, **host도 같은 라이브러리를 shared로 선언해야 성립한다.**
> 한쪽만 선언하면 공유되지 않고 그대로 두 벌이다. 반드시 포털팀과 합의 후 양쪽 동시 반영.

### 11-3. 계약서에 없는 숨은 의존 — element-plus 전역 등록

`main.ts:25` 에서 `app.use(ElementPlus)` 로 전역 등록하는데, **임베드되면 `main.ts` 가 실행되지 않는다**(6-3절).
그런데도 `<el-button>` 같은 전역 태그가 렌더된다면, 그건 **host 포털이 element-plus를 전역 등록해줬기 때문**이다.

즉 우리 화면은 **포털의 전역 등록에 암묵적으로 의존**하고 있다. 포털이 element-plus를 걷어내면 우리가 깨진다.

현재 리뉴얼 화면은 대부분 명시적 import를 쓰고 있어 비교적 안전하다.

```js
import { ElDialog, ElIcon } from "element-plus";   // ← 이 방식이면 host 사정과 무관
```

다만 아래 3개 파일은 `<el-` 전역 태그를 쓴다. **점검 대상.**

```
src/view/advisor-renual/call-history/components/RenualCallDetailModal.vue
src/view/advisor-renual/components/RenualNotifBell.vue
src/view/advisor-renual/todo/index.vue
```

> **원칙: 리뉴얼 화면에서는 element-plus를 항상 명시적 import로 쓴다.**

### 11-4. 진단 절차 (브라우저만으로)

**① share scope 직접 확인 — 가장 강력**

포털에 임베드된 화면에서 콘솔에 입력:

```js
__webpack_share_scopes__.default
```

host와 remote가 협상한 **결과 전체**가 나온다.

```
{
  vue: { "3.5.18": { loaded: 1, from: "advisor_app", ... },
         "3.4.21": { from: "host_app", ... } },   ← 키가 2개 = 불일치 발생 중
  ...
}
```

판정 기준:

| 관찰 | 의미 |
|---|---|
| 한 라이브러리 아래 **키(버전)가 2개 이상** | 버전 불일치. major가 다르면 위험 |
| `loaded: 1` 이 붙은 항목 | **실제 채택된 것**. `from` 으로 어느 앱 것이 이겼는지 확인 |
| 목록에 `element-plus`/`socket.io-client` 가 **없음** | 공유되지 않음 = 두 벌 |

**② 중복 로드 확인**

```js
window.advisor_app                                               // remote 컨테이너 로드 여부
document.querySelectorAll("script[src*='remoteEntry']").length   // 붙은 remote 개수
```

Vue DevTools에서 **앱 인스턴스가 2개**로 보이면 그 자체가 협상 실패 신호다.

**③ 네트워크 탭**

1. `remoteEntry.js` — 200인가, 주소가 맞는가
2. 뒤따르는 청크가 **우리 도메인**에서 오는가 (host 도메인이면 `publicPath` 문제)
3. `element-plus/dist/index.css` 같은 게 **2번 로드**되는가

**④ 콘솔 경고**

MF는 버전 불일치를 **에러가 아니라 경고**로 흘린다. 놓치기 쉬우니 임베드 화면을 띄울 땐 **콘솔을 비우고 새로고침**해서 볼 것.

```
Unsatisfied version 3.4.21 from host_app of shared singleton module vue (required ^3.5.0)
No required version specified and unable to automatically determine one
```

### 11-5. 포털팀에 확인할 5가지

소스를 못 봐도 이것만 물어보면 대부분 커버된다.

1. host의 `shared` 목록과 버전 — vue/pinia/vue-router가 우리와 **major 일치**하는가
2. host가 **element-plus를 전역 등록**하는가 (11-3 의존)
3. host가 **socket.io를 쓰는가** — 쓴다면 커넥션 중복 여부
4. host의 `remotes` 주소 — 어느 환경을 가리키는가
5. host의 **vue-router 인스턴스를 우리와 공유**하는가 (6-2 리프 라우팅이 여기 의존)

---

## 12. 스타일 — 다크모드 / 전역 CSS / z-index

> **핵심: MF는 CSS를 전혀 격리하지 않는다.** JS 모듈만 나눠 받을 뿐, 스타일은 전부 **같은 document, 같은 `<head>`** 에 들어간다.
> 그래서 다크모드·전역 CSS·z-index 문제는 MF의 **직접적 부작용**이다. 우연이 아니다.

### 12-1. 왜 MF에서 CSS가 특히 꼬이나

| 원인 | 결과 |
|---|---|
| 스타일 격리 기능이 **아예 없음** | host CSS ↔ remote CSS가 양방향으로 샌다 |
| CSS 주입 **순서가 런타임에 결정됨** | 같은 상세도(specificity)면 **나중에 들어온 쪽이 이긴다**. remote는 늦게 로드되므로 순서가 빌드마다·경로마다 달라질 수 있다 |
| `<html>`, `<body>` 는 **host 소유** | remote가 전역 상태(다크 클래스 등)를 마음대로 못 바꾼다 |
| `main.ts` 미실행 (6-3절) | 전역 스타일 import가 통째로 누락된다 |

**세 번째와 네 번째가 다크모드 문제의 뿌리다.**

### 12-2. 다크모드

우리 다크모드는 `<html>` 에 클래스를 붙이는 방식이다.

```js
// src/hooks/useTheme.ts:20-24
const html = document.documentElement as HTMLElement;
if (isDark.value) {
  html.setAttribute("class", "highcharts-dark dark");
} else html.setAttribute("class", "highcharts-light");
```

여기서 MF 관점의 문제가 둘이다.

**문제 ① `useTheme` 는 임베드에서 실행되지 않는다**

호출처는 `App.vue:23` 인데, 임베드되면 `App.vue` 를 거치지 않는다.
→ **임베드 환경의 다크모드는 전적으로 host 포털이 제어한다.** 우리는 그 결과를 *따라갈* 뿐이다.

**문제 ② 만약 실행된다면 오히려 더 위험하다**

`setAttribute("class", ...)` 는 **class 속성을 통째로 덮어쓴다.**
임베드 상태에서 이게 돌면 **포털이 `<html>` 에 걸어둔 클래스가 전부 날아간다.**

> 즉 "임베드에선 안 도는 것"이 우연히 안전판 역할을 하고 있다.
> **임베드 경로에서 `<html>`/`<body>` 전역 상태를 건드리는 코드를 새로 추가하지 말 것.**
> 꼭 필요하면 `setAttribute` 대신 `classList.add/remove` 로 **범위를 좁혀** 쓴다.

**문제 ③ element-plus 다크 변수 미로드**

```js
// src/main.ts:18 — 임베드에선 실행되지 않는다
import "element-plus/theme-chalk/dark/css-vars.css";
```

임베드에서 el- 컴포넌트가 다크에서 어색하면 **host가 이 CSS를 로드했는지** 먼저 의심할 것.

**대응 원칙**

- 리뉴얼 화면의 색은 **하드코딩 대신 CSS 변수**로 쓴다 → host가 다크로 바꾸면 자동으로 따라간다
  (관련: `docs/darkmode-hardcoded-color-guide.md`)
- `useTheme` 계열은 **단독 실행 전용 경로**로 이해한다
- 폰트 스케일이 이 원칙의 좋은 선례다. `useTheme.ts:32-38` 주석대로, 임베드에선 JS가 안 돌지만
  `global.scss` 의 `--fs-scale` 이 포털의 `--font-size-body1-dynamic` 에서 자동 유도되어 **CSS만으로 동작**한다.
  → **JS로 반응시키지 말고 CSS 변수로 유도되게 설계하라**는 게 정답 패턴이다.

### 12-3. 전역 CSS

두 방향 모두 실제로 겪은 문제다.

| 방향 | 사례 | 대응 |
|---|---|---|
| host → remote | 포털 전역 CSS가 우리 체크박스를 좌상단으로 몰아버림 | `adv-remote-scope` 스코프 클래스로 remote 하위에서만 되돌림 (`index.vue:18-20`) |
| remote → host | 우리 전역 셀렉터가 포털을 오염 | `<style scoped>` 사용, 전역 셀렉터 남발 금지 |
| 누락 | 임베드 시 `.flex` 등이 안 먹어 레이아웃이 세로로 깨짐 | 진입점에서 직접 import (`index.vue:52-53`) |

**주의: `src/styles/reset.scss` 는 `main.ts:13` 에서만 import된다.** 임베드에선 로드되지 않는다.
이건 사고가 아니라 **의도된 것**이다 — reset은 전역을 건드리므로 포털에 주입하면 포털을 깨뜨린다.
리뉴얼 화면이 reset에 의존하지 않게 만드는 것이 맞다.

### 12-4. z-index

**MF에서 z-index가 깨지는 진짜 이유는 "라이브러리가 두 벌"이기 때문이다.**

element-plus는 팝업이 뜰 때마다 **전역 카운터를 하나씩 올려서** z-index를 부여한다(기본 시작값 2000).
그런데 host와 remote가 element-plus를 **각자 로드하면 카운터도 각자 돈다.**

```
host   element-plus 카운터 : 2000 → 2001 → 2002 ...
remote element-plus 카운터 : 2000 → 2001 → 2002 ...   ← 같은 값이 재발급됨
```

→ 나중에 연 remote 다이얼로그가 host 드롭다운 **아래**로 깔리는 현상이 생긴다.
**해결책은 z-index를 올리는 게 아니라 element-plus를 shared로 공유하는 것**이다 (11-2).

또 하나, 우리 코드에는 하드코딩 z-index가 꽤 있다.

```
z-index: 9999   (10곳)
z-index: 10000  (3곳)
z-index: 2000   (3곳)
z-index: 2102   (2곳)
```

단독 실행에선 문제없지만, 임베드되면 **포털의 헤더·모달과 같은 평면에서 경쟁**한다.
`9999` 같은 값은 "포털의 어떤 것보다도 위"라고 선언하는 셈이라, 포털 모달을 덮어버릴 수 있다.

**원칙**

- 새 z-index를 하드코딩하지 말 것. 기존 값을 참고해 **좁은 범위**에서 쓴다
- 팝업/모달은 가급적 **element-plus 컴포넌트를 그대로 사용**해 카운터 관리를 맡긴다
- 겹침 문제가 나면 값을 올리기 전에 **element-plus가 두 벌인지부터 확인**한다 (11-4 ①)

#### 해결 방식 비교 (참고)

| 방식 | 포털팀 합의 | 결합도 | 효과 |
|---|:---:|:---:|---|
| element-plus를 `shared` 에 추가 | **필요** (양쪽 동시 선언해야 성립) | 높음 — 버전이 lock-step으로 묶임 | 카운터 통일. 단 CSS 중복·다크 변수 누락은 그대로 |
| z-index 대역(band) 규약 | **필요** (숫자 범위 합의) | 낮음 | 앱 간 순서 보장 + 앱 내부는 독립. `<el-config-provider :z-index="...">` 로 시작값 이동 |
| 현행 유지 (하드코딩) | 불필요 | 없음 | 예쁘지 않지만 **현재 동작함** |

> z-index는 **하나의 문서에 하나뿐인 전역 좌표계**다. 같은 화면을 공유하는 이상
> "각 앱이 완전히 독립적으로 관리"는 성립할 수 없고, 어떤 방식이든 조율이 필요하다.
> 완전한 독립은 iframe뿐이며, 그건 통합감을 전부 포기하는 선택이다.

#### 현재 방침 (2026-08-03 결정) — 조치하지 않음

**결정: 아무것도 하지 않는다. 증상이 실제로 관측될 때까지 현행 하드코딩을 유지한다.**

판단 근거:

1. **문제가 관측되지 않았다.** 포털이 element-plus를 실제로 따로 로드하는지 미확인이며(포털 소스 접근 불가),
   팝업 겹침 사고도 보고된 바 없다. `z-index: 9999` 가 10곳 있다는 건 지금까지 그것으로 버텨왔다는 뜻이다.
2. **두 해법 모두 포털팀과의 합의가 전제**인데, 현재 팀 간 코드 정합조차 맞지 않는 상황이라
   CSS 규약 합의는 현실적으로 비용이 회수되지 않는다.
3. 문제 없는 것을 고치는 것이 가장 비싼 리팩터링이다.

**나중에 증상이 나타나면 이 순서로 볼 것**

```
① __webpack_share_scopes__.default 에 element-plus 가 있나 / 버전 키가 몇 개인가  (11-4 ①)
② 네트워크 탭에서 element-plus CSS 가 2번 로드되나
③ 실제로 겹침이 재현되나 (RenualCallDetailModal 등을 포털 헤더 위에서 열어보기)
   → ①~③ 확인 후에야 위 비교표에서 방식을 고른다
```

**합의 없이 우리끼리 할 수 있는 선행 조치** (필요해지면 이것부터. 조율이 아니라 **의존을 끊는** 방향이라 단독 가능)

| 조치 | 효과 |
|---|---|
| `<el-` 전역 태그 3개 → 명시적 import (11-3) | 포털이 element-plus를 걷어내도 우리가 안 깨짐 |
| 색상 하드코딩 → CSS 변수 (12-2) | 포털 다크 전환을 자동으로 따라감 |
| `<el-config-provider :z-index="...">` 로 시작값 지정 | 우리 팝업만 특정 대역으로 이동. 합의 없이 단독 적용 가능 |

### 12-5. 스타일 문제 진단 순서

```
① 단독 실행(npm run local106)에서도 재현되나?
   └ 재현됨  → MF 무관. 평범한 CSS 문제
   └ 임베드에서만 → 아래로

② main.ts 에서만 import 하는 스타일에 의존하고 있지 않나?  (6-3, 12-2③)
      ↓ 아님
③ DevTools 로 어느 쪽 CSS가 이겼는지 확인 (상세도 동률이면 나중 로드가 승리)
      ↓ 순서 문제 아님
④ 라이브러리가 두 벌인가? __webpack_share_scopes__.default 확인  (11-4)
      ↓ 아님
⑤ <html>/<body> 전역 상태를 누가 바꾸고 있나 (다크 클래스 등)
```

---

## 13. 더 알아볼 거리

| 주제 | 왜 알아둘 만한가 |
|---|---|
| bootstrap 패턴 (`main.ts` → `import("./bootstrap")`) | `eager: true` 를 걷어내고 shared를 정석대로 쓰는 방법 (4-2절) |
| Module Federation 2.0 | 타입 공유, 런타임 플러그인, 상세 에러 등 개선판 |
| `@module-federation/vite` | webpack 없이 Vite에서 MF 쓰기 (마이그레이션 검토 시) |
| 마이크로 프론트엔드 일반론 | MF는 수단일 뿐. 경계 나누기·팀 구조 문제가 본질 |

### 검색 키워드 (문제 만났을 때 이 단어로 찾으면 나온다)

```
module federation shared singleton
module federation ChunkLoadError
webpack module federation publicPath auto
module federation eager consumption
micro frontend routing between host and remote
```

---

## 14. 관련 문서

- `docs/webpack-mf-chunkload-fix-guide.md` — 청크 404/ChunkLoadError 실전 대응
- `docs/darkmode-hardcoded-color-guide.md` — 다크모드 하드코딩 색상 정리 (12-2와 직결)
- `docs/advisor_frontend_stack.md` — 프론트엔드 스택 전반
- `docs/local-blank-page-transition-fix-guide.md` — 빈 화면 전환 이슈
- `CLAUDE.md` — 프로젝트 작업 규약
