# 07. 리스크 · 기술 부채 · 개선 우선순위

인수인계 시점(2026-08-14, `release` 브랜치)에 확인된 항목이다. 심각도 순으로 정렬했다.

---

## 🔴 P0 — 즉시 조치 권장

### 1. MUI X Pro 라이선스 키가 리포지토리에 평문 커밋됨
```
Dockerfile:
ENV REACT_APP_MUI_LICENSE_KEY=7fa2d890358b98e3ddd012724ee5fa02Tz0xMTg3MDks...
```
유료 라이선스 키가 소스에 하드코딩되어 git 히스토리에 남아 있다. 온프렘 납품 시 고객사에도 그대로 전달된다.
**조치**: 빌드 시 주입(CI 시크릿)으로 전환. 이미 노출되었으므로 키 재발급 검토.
> 참고: CRA 특성상 `REACT_APP_*`는 **어차피 번들에 포함되어 클라이언트에 노출**된다. MUI 라이선스 키는 원래 그런 성격의 키지만, 리포/이미지에 박아두는 것과는 별개 문제다.

### 2. `package-lock.json`이 깨져 있어 재현 가능한 빌드가 불가능
```
npm ci → Invalid: lock file's es-object-atoms@1.0.0 does not satisfy 1.1.2
         Missing: get-proto, math-intrinsics, dunder-proto from lock file
```
`npm ci`가 아예 실행되지 않는다. 운영 Dockerfile은 `npm install --force`를 써서 **빌드할 때마다 의존성 트리가 달라질 수 있다.** 어제 되던 빌드가 오늘 깨질 수 있는 상태다.
**조치**: lock 파일 재생성 후 커밋 + Dockerfile을 `npm ci`로 전환.

### 3. 패키지 매니저 3중 혼선
`package-lock.json`(820KB)과 `bun.lock`(473KB)이 **동시에 커밋**되어 있고, README는 npm/yarn을 안내하며, Dockerfile은 npm을 쓴다. 사람마다 다른 매니저로 설치하면 트리가 달라진다.
**조치**: 하나로 확정하고 나머지 lock 삭제.

### 4. peer dependency 충돌 방치
`echarts@6.0.0` ↔ `echarts-for-react@3.0.2`(peer `^3||^4||^5`). `--force`/`--legacy-peer-deps`로 우회 중이라 **런타임에 조용히 깨질 수 있다**(차트 API 시그니처 변경).
**조치**: `echarts`를 5.x로 내리거나 `echarts-for-react`를 echarts 6 지원 버전으로 올린다. 이용 현황 차트(9개 파일) 회귀 테스트 필요.

---

## 🟠 P1 — 계획 세워 처리

### 5. `ContentsStore.js` 1440줄 God Store
회의록의 목록·검색·홈·북마크·휴지통·캘린더·업로드·STT진행·상세편집·메모·하이라이트·공유·다운로드·이용현황이 **한 파일**에 있다. 액션 60여 개. 충돌이 잦고 영향 범위 예측이 어렵다.
**조치**: 도메인별 분리(ContentListStore / ContentDetailStore / UploadStore / SttProgressStore …). 한 번에 말고 신규 기능부터 새 스토어로.

### 6. `httpCode` 계약으로 인한 에러 처리 중복
백엔드가 HTTP 200 + body `httpCode`를 쓰기 때문에 axios interceptor를 쓸 수 없고, 스토어의 모든 액션이 `switch (res.data.httpCode)`를 반복한다(수백 줄). **분기를 빠뜨리면 실패가 조용히 성공 처리된다.**
**조치**: `requestUtil`에 응답 정규화 래퍼를 추가해 `{ ok, code, data, message }`로 변환하고, 실패는 reject로 통일. 백엔드 변경 없이 프론트에서만 흡수 가능하다. → [03-data-flow.md](./03-data-flow.md)

### 7. 스토어 반환 규약 이원화 + 실패도 `resolve`
Promise 스타일과 `(onOk, onError, onFinal)` 콜백 스타일이 섞여 있고, 일부는 둘 다 받는다. 게다가 **권한 실패를 `reject`가 아니라 `resolve({code: 401})`로 반환**하는 곳이 많아 `catch`만 단 호출부는 에러를 놓친다.
**조치**: 신규 코드는 Promise + reject로 통일. `fileUpload`(인자 10개) 같은 시그니처는 옵션 객체로 리팩터링.

### 8. ESLint 훅 규칙 전면 비활성 + lint가 항상 성공
```js
'react-hooks/exhaustive-deps': 'off',
'react-hooks/rules-of-hooks': 'off',
```
```json
"lint": "eslint . --fix || true"
```
훅 의존성 버그가 잠재해 있을 가능성이 높고, CI에서 lint 실패를 감지할 수 없다.
**조치**: `rules-of-hooks`부터 `error`로 복구(이건 위반 시 실제 버그다). `exhaustive-deps`는 `warn`으로 두고 점진 정리. `|| true` 제거.

### 9. 테스트 0건
`@testing-library/*`가 설치되어 있으나 테스트 파일이 하나도 없다. 위 리팩터링을 하려 해도 안전망이 없다.
**조치**: 최소한 `requestUtil`, `tokenStore`, `ContentsStore`의 핵심 액션부터 단위 테스트 추가.

### 10. 셀렉터 없는 스토어 통째 구독
```js
const { contents, refreshContents, applyedFilters, ... } = useContentsStore();
```
1440줄 스토어의 어느 필드가 바뀌어도 리렌더된다. STT 진행률이 초 단위로 갱신되는 화면에서 특히 비용이 크다.
**조치**: 셀렉터 + `useShallow` 적용. 목록/상세 화면부터.

---

## 🟡 P2 — 정리하면 좋음

### 11. 중복 의존성
- **날짜 7종**: `moment` + `dayjs` + `react-datepicker` + `react-datetime` + `@iftek/react-datetime` + `react-multi-date-picker` + `@mui/x-date-pickers-pro`
  (`ContentsStore.js`는 한 파일에서 dayjs와 moment를 동시에 import한다)
- **그리드 2종**: ag-grid + MUI DataGrid Pro
- **프로그레스바 3종**, **스타일링 3종**(MUI/styled-components/plain CSS)

번들 크기와 학습 비용에 직접 영향을 준다. dayjs + MUI DatePicker로 수렴 권장.

### 12. `package.json`에 없는데 코드가 쓰는 패키지
- `qs` — `src/Utils/requestUtil.js:1`
- `@mui/x-license` — `src/App.js:33`

전이 의존성 hoisting에 우연히 기대고 있다. 상위 패키지가 바뀌면 **모든 API 호출이 죽는다**(qs). 명시적 의존성으로 승격 필요.

### 13. 죽은 코드 / 문서 드리프트
- `server.js`(express) — 어디에서도 참조되지 않음. 실제 서빙은 `serve`
- `webpack.config.js` — CRACO 사용 중이라 적용되지 않음(`node-polyfill-webpack-plugin`이 실제로 먹는지 확인 필요)
- README의 `REACT_APP_API_URL` / `SOCKET_URL` / `LOGIN_URL` / `BO_ADMIN_URL` — **코드에서 미사용**
- README의 폴더 구조에 `Pages/Mobile`, `Pages/Usage`, `Components/app` 누락
- README의 브랜치 목록(main/dev/stg/poc/demo/azure)과 실제 운영 브랜치(`release`, `release-dev`, GitLab CI 기준)가 불일치
- `Themes/BasicTheme.js` — 현재 `OldTheme.js`만 사용

### 14. Socket.IO `disconnect()`가 잘못된 API 호출
```js
// NotifyManager.js:181
const disconnect = () => { if (socket) socket.destroy(); };
```
`destroy()`는 socket.io-client v4 공개 API가 아니다(v2 잔재). 재연결 시 이전 커넥션이 정리되지 않아 **메시지 중복 수신**이 발생할 수 있다.
**조치**: `socket.disconnect()` 또는 `socket.close()` + `socket.off()`로 교체.

### 15. 모바일 라우트에 실시간 기능 없음
모바일은 `Main` 레이아웃을 거치지 않아 소켓이 초기화되지 않는다(STT 진행률·알림·중복 세션 처리 모두 미동작). 의도된 것인지 확인 필요.

### 16. `InboxStore`와 `MessageStore.refreshInbox` 기능 중복
동일한 `/api/inbox`를 각각 다른 방식(axios 직접 / requestUtil)으로 호출한다. `InboxStore`는 accessToken을 인자로 받는 구식 시그니처.
**조치**: `MessageStore`로 통합하고 `InboxStore` 제거.

### 17. `console.*` 전역 하이재킹의 인자 유실
`Libs/overrideConsole.js`가 `console.info/warn/error`를 덮어쓰는데, **인자가 정확히 2개의 문자열일 때만** 그룹 처리하고 그 외에는 `args[0]`만 출력한다. `console.error('실패', errorObject)`에서 **에러 객체가 사라진다.**
**조치**: 나머지 인자도 함께 출력하도록 수정. 디버깅 중에는 원본이 유지되는 `console.log` 사용.

### 18. 코드 스플리팅 없음
`App.js`가 모든 페이지를 정적 import한다. dev 번들이 24MB(비압축)다. `React.lazy` + `Suspense`로 라우트 단위 분할 시 초기 로딩이 크게 개선된다.

### 19. `.js` / `.jsx` 확장자 규칙 부재
같은 성격의 파일이 제각각이다(`ContentList.js` vs `ContentDetail.jsx`). 컨벤션 확정 권장.

### 20. `npm audit` 84건 (critical 5 / high 38)
대부분 CRA·webpack 개발 의존성 체인이라 런타임 영향은 제한적이지만, 온프렘 납품 시 보안 검토에서 지적될 수 있다. CRA 자체가 유지보수 중단 상태라 근본 해결은 **Vite 마이그레이션**이다.

---

## 참고: CRA 유지보수 중단

`react-scripts`(create-react-app)는 공식적으로 유지보수가 중단되었다. 기동 시 다음 경고가 나온다.
> `babel-preset-react-app is part of the create-react-app project, which is not maintianed anymore.`

이미 CRACO로 webpack을 확장하고 있으므로 **Vite 전환 비용이 크지 않다.** 얻는 것: 빌드/HMR 속도, 코드 스플리팅 기본 제공, audit 이슈 대폭 감소, `NODE_OPTIONS=8GB` 같은 우회 제거. 잃는 것: `process.env.REACT_APP_*` → `import.meta.env` 치환 작업(11개 변수, 60여 곳).

---

## 권장 착수 순서

1. **P0 4건** — lock 파일 정상화 + 라이선스 키 분리 (하루)
2. **`requestUtil` 응답 정규화 래퍼** — 이후 모든 리팩터링의 기반 (6번)
3. **`rules-of-hooks` 복구 + lint 실패가 CI를 막도록** (8번)
4. **핵심 경로 테스트 추가** (9번)
5. **`ContentsStore` 분리 시작** — 신규 기능부터 (5번)
6. 중장기: Vite 전환 검토
