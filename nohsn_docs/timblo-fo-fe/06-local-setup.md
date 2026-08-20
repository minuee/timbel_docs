# 06. 로컬 구동 가이드

2026-08-14 기준 macOS(Apple Silicon)에서 **실제로 구동 확인 완료**된 절차다.

## 사전 요구사항

- **Node 22.13.1** (`.nvmrc`). Node 24에서는 검증하지 않았다.
- npm 10.9.2 (Node 22에 동봉)
- 백엔드 접근 — 기본은 DEV 서버(`https://dev.timblo.io`). 사내망/VPN 필요 여부는 환경에 따라 다름.

## 1. Node 버전 맞추기

```bash
cd <repo>
nvm install    # .nvmrc 를 읽어 22.13.1 설치
nvm use
node -v        # v22.13.1
```

## 2. 의존성 설치 ⚠️ 중요

```bash
npm install --legacy-peer-deps
```

### `npm ci`는 쓸 수 없다 (2건의 이유)

1. **peer dependency 충돌** — `echarts@6.0.0` vs `echarts-for-react@3.0.2`(peer `^3||^4||^5`)
   ```
   npm error ERESOLVE could not resolve
   Conflicting peer dependency: echarts@5.6.0
   ```
2. **`package-lock.json`이 `package.json`과 동기화가 깨져 있다**
   ```
   npm error Invalid: lock file's es-object-atoms@1.0.0 does not satisfy es-object-atoms@1.1.2
   npm error Missing: get-proto@1.0.1 from lock file
   npm error Missing: math-intrinsics@1.1.0 from lock file
   npm error Missing: dunder-proto@1.0.1 from lock file
   ```

즉 현재 저장소의 lock 파일로는 **재현 가능한 설치가 불가능**하다. 운영 `Dockerfile`이 `npm install --force`를 쓰는 것도 같은 이유로 보인다. → [07-risks-todo.md](./07-risks-todo.md)

> `npm install`을 돌리면 `package-lock.json`이 갱신된다(약 120줄). 커밋 여부는 팀에서 결정할 것.

설치 결과: 1894 패키지, 약 17초. `npm audit`에서 84건(critical 5, high 38)이 보고되나 대부분 CRA/webpack 개발 의존성 체인이다.

## 3. 환경변수 `.env` 작성

프로젝트 루트에 `.env`를 만든다 (`.gitignore`에 포함되어 커밋되지 않는다).

```bash
# ── 백엔드 도메인. 코드에서 `${REACT_APP_DOMAIN}/api/` 로 조립된다.
REACT_APP_DOMAIN=https://dev.timblo.io

# ── 로컬 개발 모드 (★ 필수)
#    /login, /join, /findPassword 라우트를 활성화한다.
#    false면 외부 /sign 페이지로 풀 리다이렉트되어 로컬에서 로그인 자체가 불가능하다.
REACT_APP_IS_DEV=true
REACT_APP_IS_LOCALHOST=true

# ── 인증 쿠키
REACT_APP_COOKIE_ALIAS=timblo_token
REACT_APP_COOKIE_EXPIRE_HOUR=24
REACT_APP_IS_SSO=false

# ── Socket.IO
REACT_APP_SOCKET_PATH=/socket.io
REACT_APP_SOCKET_PING_INTERVAL=25000
REACT_APP_SOCKET_PING_TIMEOUT=20000

# ── 챗봇 (별도 LLM 호스트)
REACT_APP_IS_CHATBOT=true
REACT_APP_SK_API_HOST=https://abiz.timblo.io

# ── MUI X Pro 라이선스 (없으면 DataGrid Pro에 워터마크 + 콘솔 경고)
REACT_APP_MUI_LICENSE_KEY=<Dockerfile 참조 또는 팀에서 수령>

# ── 개발 서버
PORT=3000
WDS_SOCKET_PORT=0
GENERATE_SOURCEMAP=true
```

### ⚠️ README의 환경변수 목록은 신뢰하지 말 것

README에는 `REACT_APP_API_URL`, `REACT_APP_SOCKET_URL`, `REACT_APP_LOGIN_URL`, `REACT_APP_BO_ADMIN_URL`이 나오지만 **코드에서 전혀 사용되지 않는다.** 실제로 코드가 참조하는 변수는 아래 11개가 전부다.

| 변수 | 사용 횟수 | 위치 |
|---|---|---|
| `REACT_APP_DOMAIN` | 25 | API base URL, 소켓, 리다이렉트 |
| `REACT_APP_COOKIE_ALIAS` | 24 | 토큰 저장 키 |
| `REACT_APP_IS_DEV` | 3 | 개발용 라우트/분기 |
| `REACT_APP_SOCKET_PATH` | 2 | Socket.IO path |
| `REACT_APP_IS_SSO` | 2 | `/sign?f=true&s=<isSSO>` |
| `REACT_APP_SOCKET_PING_INTERVAL` / `_TIMEOUT` | 각 1 | 소켓 keepalive |
| `REACT_APP_SK_API_HOST` | 1 | 챗봇 LLM 호스트 |
| `REACT_APP_MUI_LICENSE_KEY` | 1 | MUI X Pro |
| `REACT_APP_IS_LOCALHOST` | 1 | `CheckCookies.js` 분기 |
| `REACT_APP_IS_CHATBOT` | 1 | 챗봇 UI 노출 |

`REACT_APP_COOKIE_EXPIRE_HOUR`는 Dockerfile/README에 있으나 코드에서 쓰이지 않는다(만료는 JWT `exp`로 계산).

## 4. 실행

```bash
npm start          # craco start → http://localhost:3000
```

정상 기동 시 출력:
```
Compiled with warnings.
webpack compiled with 24 warnings
```
**warnings만 있으면 정상이다.** 에러가 아니다.

## 5. CORS — DEV 백엔드는 localhost를 허용한다

확인 결과 `https://dev.timblo.io`가 `http://localhost:3000` origin을 명시적으로 허용한다.

```
access-control-allow-origin: http://localhost:3000
access-control-allow-methods: POST,GET,PUT,OPTIONS,DELETE,PATCH
access-control-allow-headers: authorization, content-type
access-control-allow-credentials: true
```

따라서 **프록시 설정 없이** 로컬에서 DEV API를 그대로 호출할 수 있다.

## 6. 로그인

`REACT_APP_IS_DEV=true`이므로 `http://localhost:3000/login`에서 이메일/비밀번호로 로그인한다. DEV 서버 계정이 필요하니 팀에서 발급받을 것.

로그인 성공 시 흐름:
```
POST /api/auth/login → 토큰 → 쿠키(timblo_token) 저장
→ auth/user/me + auth/workspace/me 조회
→ CheckUser 통과 → Main 렌더 → Socket.IO 연결
```

## 기동 시 나오는 정상 경고 (무시해도 됨)

| 경고 | 설명 |
|---|---|
| `Failed to parse source map from .../react-datepicker/src/*.tsx` (20여 건) | `react-datepicker`가 소스맵에 원본 TS 경로를 참조하는데 배포 패키지에 `src/`가 없음. `GENERATE_SOURCEMAP=false`로 끄면 사라진다 |
| `babel-preset-react-app is importing @babel/plugin-proposal-private-property-in-object without declaring it` | CRA 미유지보수로 인한 알려진 경고 |
| `onAfterSetupMiddleware / onBeforeSetupMiddleware is deprecated` | webpack-dev-server 4 경고 |
| `Browserslist: caniuse-lite is 11 months old` | `npx update-browserslist-db@latest`로 해소 가능 |
| `The legacy JS API is deprecated ... Dart Sass 2.0.0` | `sass` 버전 관련. `.scss` 2개 파일에서 발생 |
| eslint `no-unused-vars` / `array-callback-return` 등 24건 | 기존 코드의 누적 경고. 빌드는 통과 |

## 트러블슈팅

| 증상 | 조치 |
|---|---|
| `npm ci` 실패 | 정상이다. `npm install --legacy-peer-deps`를 쓸 것 (위 2번) |
| 포트 3000 사용 중 | `.env`의 `PORT` 변경. **단, DEV 백엔드 CORS는 `localhost:3000`만 허용**할 수 있으니 변경 시 API 실패 가능 |
| 흰 화면 / 계속 `/sign`으로 튕김 | `REACT_APP_IS_DEV=true` 확인. `.env` 변경 후 **dev 서버 재시작 필수**(CRA는 env를 빌드 타임에 주입) |
| API 전부 401 | 쿠키가 `secure: true; sameSite: none`으로 저장됨. Chrome은 `http://localhost`를 보안 컨텍스트로 취급하므로 보통 동작하나, 다른 브라우저에서는 실패할 수 있다 |
| `heap out of memory` (빌드 시) | `NODE_OPTIONS="--max-old-space-size=8192" npm run build` (운영 `scripts/start.sh`와 동일) |
| MUI DataGrid에 워터마크 | `REACT_APP_MUI_LICENSE_KEY` 미설정 |
| 실시간 갱신 안 됨 | 콘솔에 `connect ::`가 찍히는지 확인 → [05-realtime-socket.md](./05-realtime-socket.md) |

## 프로덕션 빌드 확인

```bash
NODE_OPTIONS="--max-old-space-size=8192" npm run build
npx serve -s build -l 3000
```
운영 컨테이너(`scripts/start.sh`)와 동일한 방식이다.

## Docker로 띄우기

```bash
docker compose build            # VERSION 환경변수 필요
docker compose up
# → localhost:9000 (컨테이너 내부 3000)
```
컨테이너는 **기동 시점에 빌드**하므로 첫 실행이 매우 느리다(수 분 + 메모리 8GB 옵션). 개발 중에는 `npm start`를 쓸 것.
