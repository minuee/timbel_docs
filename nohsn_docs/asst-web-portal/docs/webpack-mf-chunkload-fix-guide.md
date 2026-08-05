# Module Federation 청크 로드 실패(ChunkLoadError) — webpack 설정 수정 이관 가이드

> **대상** Module Federation **remote** 로 동작하고 **webpack-dev-server 로 서빙되는 개발 서버**를 쓰는 프론트 레포
> **범위** `webpack.config.js` 만. 애플리케이션 코드는 건드리지 않는다.
> **상태** 기준 레포 적용 완료 (실기동 실측 검증, `vue-tsc` / eslint 신규 위반 0)
>
> 운영(빌드 + nginx) 경로는 **일부러 손대지 않는다.** 아래 조치는 전부 `webpack serve` 로 뜰 때만 동작하고,
> `webpack --config`(빌드)에서는 기존 동작이 그대로 유지된다.

---

## 0. 이 문서가 해당되는지 30초 판별

아래 **네 가지가 모두** 맞으면 같은 문제를 안고 있다.

| # | 조건 | 확인 방법 |
|---|---|---|
| 1 | Module Federation **remote** 다 | `webpack.config.js` 에 `ModuleFederationPlugin` + `exposes` |
| 2 | 개발 서버를 **`webpack serve`** 로 띄운다 | `docker-compose.*.yml` / `package.json` 에 `webpack serve` |
| 3 | 산출물 파일명에 **contenthash** 가 붙는다 | `output.filename` / `chunkFilename` 에 `[contenthash]` |
| 4 | 소스가 **볼륨 마운트**되어 watch 재컴파일된다 | compose 에 `- .:/app` 류 마운트 |

3번이 없으면(파일명 고정) 이 문제는 애초에 안 생긴다. 4번이 없어도 재배포 때마다 동일하게 발생한다.

---

## 1. 증상

- 포털(host)에서 **메뉴를 클릭하면 콘텐츠 영역만 빈 화면**. 공통영역(top menu, LNB)은 멀쩡하다.
  → remote 컴포넌트만 마운트에 실패한 것이라, 마치 iframe 안이 비어 보이는 모양이 된다.
- 콘솔:
  ```
  ChunkLoadError: Loading chunk src_view_..._vue-src_view_..._comp-c40e4d failed.
  (error: http://<remote-host>:<port>/src_view_..._comp-c40e4d.a08e09d….js)
      at __webpack_require__.f.j (remoteEntry.js?t=...)
  ```
- **F5 새로고침하면 풀린다.** ← 이 문서가 다루는 원인의 결정적 증거다.
- 특정 메뉴만이 아니라 그때그때 다른 메뉴에서 난다.

---

## 2. 원인 — 포털이 들고 있는 청크맵이 낡음

```
① 포털 접속   → remoteEntry.js 로드 → "청크명 → contenthash" 맵을 메모리에 고정
                                        (이 맵은 페이지를 새로고침할 때까지 갱신되지 않는다)
② remote 재빌드 → 모든 청크의 contenthash 가 새로 계산됨. 옛 파일은 사라짐(404)
③ 메뉴 클릭   → 동적 import → ①의 맵에 있는 "옛 해시" URL 을 요청
              → 404 → ChunkLoadError → remote 컴포넌트 마운트 실패 → 빈 화면
```

핵심은 **①의 맵이 페이지 로드 시점에 고정된다**는 점이다. 탭을 열어둔 채로 remote 가 재빌드되면
그 탭은 이미 존재하지 않는 파일명을 계속 가리킨다. 새로고침하면 새 `remoteEntry.js` 를 받아 맵이
갱신되므로 풀린다.

> `webpack serve` + 볼륨 마운트 환경에서는 **서버 코드가 갱신될 때마다** ②가 일어난다.
> 그래서 "가끔이 아니라 계속" 발생하는 것처럼 느껴진다.

### 2-1. 진단 (다른 레포에서 그대로 따라 하면 된다)

콘솔 에러에 찍힌 실패 URL 의 해시와, **지금 서버가 주는** 해시를 비교한다.

```bash
REMOTE=http://<remote-host>:<port>

# 1) 현재 remoteEntry 가 가진 청크맵 받기
curl -s "$REMOTE/remoteEntry.js" -o /tmp/re.js

# 2) 실패한 청크명으로 현재 해시 찾기 (청크명은 콘솔 에러에서 복사)
grep -o '"<청크명>":"[0-9a-f]*"' /tmp/re.js

# 3) 옛 해시(에러의 URL) vs 현재 해시 응답코드 비교
curl -s -o /dev/null -w "%{http_code}\n" "$REMOTE/<청크명>.<에러에_찍힌_해시>.js"   # → 404 면 확정
curl -s -o /dev/null -w "%{http_code}\n" "$REMOTE/<청크명>.<현재_해시>.js"          # → 200
```

기준 레포 실측 결과:

| 요청 | 결과 |
|---|---|
| 에러가 요청한 `…a08e09d….js` | **404** |
| 현재 remoteEntry 가 가리키는 `…7f1a3176b8b03a62c763.js` | **200** |

---

## 3. 조치 — dev-server 에서만 파일명 고정 + 캐시 금지

**두 가지는 반드시 한 쌍으로 적용한다.** 하나만 적용하면 오히려 상태가 나빠질 수 있다(4-2 참고).

### 3-1. config 를 함수형으로 바꾸고 serve 여부로 분기

`export default {…}` (객체) → `export default (cliEnv = {}) => ({…})` (함수)로 바꾼다.
webpack 은 config 를 함수로 내보내는 것을 표준 지원하며, `webpack serve` 로 실행하면
`@webpack-cli/serve` 가 첫 인자에 `WEBPACK_SERVE: true` 를 넣어준다.

```js
/**
 * webpack-cli 가 `serve` 로 띄웠는지 판별 (@webpack-cli/serve 가 env.WEBPACK_SERVE=true 를 주입).
 * 빌드(`webpack --config`)에서는 둘 다 미설정 → false 로 떨어져 운영 빌드는 항상 contenthash 유지.
 */
const isDevServer = webpackEnv => Boolean(webpackEnv?.WEBPACK_SERVE) || process.env.WEBPACK_SERVE === "true";

export default (cliEnv = {}) => ({
  mode: "development",
  entry: /* … 기존 그대로 … */,
  output: {
    publicPath: "auto",
    // ⚠️ dev-server 에서는 해시를 빼고 고정 파일명을 쓴다.
    //   watch 재컴파일마다 contenthash 가 전부 바뀌는데, 포털(host)은 페이지 로드 시점의
    //   remoteEntry.js 청크맵을 메모리에 들고 있으므로 재빌드 후 메뉴를 누르면 옛 해시 청크를
    //   요청 → 404 → ChunkLoadError → remote 영역만 빈 화면이 된다.
    //   고정 파일명이면 URL 이 안 변해 낡은 청크맵으로도 최신 청크를 받는다.
    //   단, dev-server 는 캐시 검증 헤더를 전혀 안 보내므로(실측: Cache-Control/ETag/Last-Modified 없음)
    //   고정 파일명만으로는 브라우저 휴리스틱 캐싱에 걸린다 → 아래 devServer.headers 의 no-store 와 한 쌍.
    filename:      isDevServer(cliEnv) ? "[name].js" : "[name].[contenthash].js",
    chunkFilename: isDevServer(cliEnv) ? "[name].js" : "[name].[contenthash].js",
    path: /* … 기존 그대로 … */,
    clean: true
  },
  /* … 나머지 전부 기존 그대로 … */
});
```

**파일 맨 끝의 닫는 괄호를 `};` → `});` 로 바꾸는 것을 잊지 말 것.** (객체 → 함수 반환으로 바뀌었으므로)

> ### ⚠️ 함정: `MODE` 로 분기하면 안 된다
> `process.env.MODE` 값(`dev`, `106.dev`, `prd` …)으로 판별하고 싶어지지만, 많은 레포에서
> **`MODE=dev` 는 dev-server 가 아니라 "개발서버용 nginx 배포 빌드"** 에도 쓰인다
> (예: `"build:dev": "cross-env MODE=dev webpack --config webpack.config.js"`).
> `MODE.includes("dev")` 로 분기하면 이 빌드 산출물까지 해시가 빠져서
> **nginx 의 `\.[0-9a-f]{8,}\.js$` 1년 immutable 캐시 규칙에 안 걸리게 되고**, 배포해도 갱신이 안 되는
> 훨씬 나쁜 문제가 생긴다.
>
> `WEBPACK_SERVE` 는 **빌드에서는 아예 설정되지 않으므로**, 판별에 실패하면 항상
> "해시 유지"라는 안전한 쪽으로 떨어진다. 이 점 때문에 `MODE` 가 아니라 이 값을 쓴다.

### 3-2. devServer 에 `Cache-Control: no-store` 추가

```js
  devServer: {
    headers: {
      /* … 기존 CORS 헤더 등 그대로 … */
      // dev-server 는 ETag/Last-Modified/Cache-Control 을 전혀 안 보낸다(실측).
      // 위 output 설정으로 serve 시 파일명이 [name].js(해시 없음)로 고정되므로,
      // 캐시 지시가 없으면 브라우저가 휴리스틱 캐싱으로 옛 청크를 붙들 수 있다.
      // → no-store 로 항상 최신을 받게 한다. (dev 전용. 빌드+nginx 경로는 이 블록을 안 읽음)
      "Cache-Control": "no-store"
    },
    /* … 나머지 기존 그대로 … */
  }
```

**왜 필요한가.** webpack-dev-server 응답에는 캐시 검증 헤더가 하나도 없다(아래 실측). 지금까지는
파일명에 해시가 붙어 URL 이 매번 달라졌기 때문에 문제가 안 됐을 뿐이다. 3-1 로 파일명을 고정하는 순간
브라우저가 검증자 없는 응답을 **휴리스틱하게 캐싱**해 옛 청크를 계속 쓸 수 있다.

```
$ curl -s -D - -o /dev/null "$REMOTE/remoteEntry.js"
HTTP/1.1 200 OK
X-Powered-By: Express
Access-Control-Allow-Origin: *
Content-Type: text/javascript; charset=utf-8
Content-Length: 890896
Vary: Accept-Encoding
Date: ...
Connection: keep-alive
                     ← Cache-Control / ETag / Last-Modified 없음
```

---

## 4. 검증

### 4-1. 적용 후 확인 절차

```bash
# ① 빌드 경로는 해시가 유지되는가 (가장 중요 — 운영 캐시 정책 보호)
node -e "
import('./webpack.config.js').then(m => {
  console.log('build:', m.default({}).output.chunkFilename);
  console.log('serve:', m.default({ WEBPACK_SERVE: true }).output.chunkFilename);
});
"
# 기대: build: [name].[contenthash].js  /  serve: [name].js

# ② 실제로 dev-server 를 띄워서 청크 URL 생성 코드 확인
npx cross-env MODE=<개발모드> npx webpack serve --config webpack.config.js --host 127.0.0.1 --port 31999 --no-open
curl -s http://127.0.0.1:31999/remoteEntry.js | grep -A3 "__webpack_require__.u ="
# 기대: return "" + chunkId + ".js"   ← 해시 없음

# ③ 캐시 헤더 확인
curl -s -D - -o /dev/null "http://127.0.0.1:31999/<아무_청크명>.js" | grep -i "cache-control"
# 기대: Cache-Control: no-store
```

기준 레포 실측 결과:

| 항목 | 결과 |
|---|---|
| `webpack serve` 기동 후 `__webpack_require__.u` | `"" + chunkId + ".js"` — 해시 없음 ✅ |
| 청크 실제 응답 | `200` + `Cache-Control: no-store` ✅ |
| `node -e` config 로드 (build 경로) | `[name].[contenthash].js` 유지 ✅ |

### 4-2. 반쪽만 적용하면 생기는 일

| 적용 | 결과 |
|---|---|
| 3-1 + 3-2 (권장) | 재빌드해도 청크 URL 불변 + 항상 최신 수신 → 문제 해소 |
| **3-1 만** | 파일명은 고정됐는데 캐시 지시가 없어 **브라우저가 옛 청크를 붙들 수 있음** (증상이 더 헷갈려짐) |
| **3-2 만** | 해시가 그대로라 청크맵 불일치는 그대로 → 아무 효과 없음 |

---

## 5. 적용 시 주의

- **컨테이너 재시작 필요.** `webpack.config.js` 는 watch 대상이 아니다. 소스 변경처럼 자동 반영되지 않으므로
  개발 서버 컨테이너를 재생성해야 적용된다.
  ```
  docker compose -f <개발용 compose 파일> up -d --force-recreate
  ```
- **운영(빌드+nginx) 무손상 확인.** 적용 후 반드시 4-1 ①로 build 경로에 `[contenthash]` 가 남아 있는지 본다.
  nginx 쪽에 `\.[0-9a-f]{8,}\.(js|css|…)$` 같은 장기 캐시 규칙이 있다면 이 규칙과 짝이므로 특히 중요하다.
- **dev-server 가 매번 전체를 다시 내려준다.** `no-store` 특성상 개발 서버 접속이 약간 느려질 수 있다.
  다만 원래도 캐시 검증 헤더가 없어 재요청하던 상황이라 체감 차이는 크지 않다.

---

## 6. 이 설정으로 해결되지 않는 범위 (참고)

이 문서의 조치는 **개발 서버(webpack serve)의 재빌드로 인한 청크맵 불일치**를 없앤다.
반면 **운영 배포(빌드 + nginx) 직후, 이미 탭을 열어두고 있던 사용자**는 같은 원리로 여전히
ChunkLoadError 를 만날 수 있다. 운영은 contenthash 를 유지해야 하므로 파일명 고정으로 풀 수 없다.

이 잔여 케이스는 **런타임 안전망**(동적 import 실패를 감지해 1회 자동 새로고침, 실패 지속 시 안내 UI)으로
따로 처리한다. 기준 레포에서는 `src/utils/lazyView.ts` + `src/components/ErrorMessage/ChunkErrorView.vue` 로
구현되어 있으며, 이 문서의 webpack 조치와 **독립적으로** 적용/이관할 수 있다.
