# 핸드오프 — 다크 모드 svc-web(임베드) 대응 요청

**대상:** ce-web / asst-web / ta-web / qa-web / aicm-web 각 팀
**요청:** 온프레 포털에 Module Federation 으로 임베드될 때, 자기 화면의 "덜 다크한 잔여 영역"을 다크로 채워 주세요.
**포털 측 상태:** 전파 채널 이미 완비 — svc-web 측 코드 변경만 남았습니다(포털은 외부 repo 를 수정하지 않습니다).

---

## 1. 배경 — 지금 무엇이 되고 무엇이 안 되나

온프레 포털은 다크 모드 시 `document.documentElement` 에 `.dark` 클래스를 토글하고, Element Plus 다크 CSS 변수를 전역으로 로드합니다. svc-web 은 별도 앱이 아니라 **포털과 같은 document 에 임베드**되므로, 이 신호는 이미 리모트까지 도달합니다.

라이브 실측(POC4 advisor) 결과 2계층으로 갈립니다:

| 계층 | 상태 | 근거 |
|---|---|---|
| **계층1 — Element Plus 컴포넌트** (버튼/인풋/셀렉트/테이블/다이얼로그 등) | ✅ **이미 다크** | 포털이 `html.dark` + EP 다크 css-vars 전역 로드 → 리모트 EP 도 뒤집힘. 실측: `--el-bg-color` 가 `#141414` 로 전환 |
| **계층2 — svc-web 자체 커스텀 스타일** (하드코딩 색 카드/헤더, DevExtreme·Highcharts·Vue-Flow 등 JS 위젯) | ❌ **라이트로 남음** | 이 스타일들이 임베드 경로에서 로드되지 않거나 `html.dark` 를 참조하지 않음 |

즉 사용자가 보는 "반쪽 다크(어두운 배경 위 흰 카드)"는 **계층2**에서 옵니다. 이 계층은 각 svc-web 코드에만 있으므로 **포털이 대신 고칠 수 없습니다.**

## 2. 포털이 이미 제공하는 것 (수신만 하면 됨)

- 공유 DOM 의 `html.dark` 클래스 (포털 다크 토글 시 on/off)
- Element Plus 다크 css-vars 전역 로드 (`portal bootstrap` 에서 import — 리모트 EP 가 이걸 탐)
- 공유 pinia store `ecp-global` 의 `isDark`/`primaryTheme`/`assemblySize` (ce/ta/qa/aicm 수신, **asst 는 store id 불일치로 미수신 — 아래 §4**)

**새로 만들 "신호 배선"(이벤트 수신 등)은 없습니다** — 다크 여부는 이미 공유 DOM(`html.dark`)·공유 store(`isDark`)에 들어와 있습니다. 리모트가 할 일은 (a) `html.dark` 에 걸릴 자기 CSS 를 임베드 경로에서 로드하고, (b) JS 테마 위젯은 그 `isDark` 값을 **읽어서 위젯 옵션에 적용하는 코드**를 넣는 것뿐입니다.

## 3. 공통 요청 (5개 팀 전부)

1. **임베드 경로에서 자기 다크 스타일시트 로드.** 현재 `main.ts` / `App.vue <style>` 에만 물려 있는 **자기 `element-dark.scss` / `common.scss` 의 `html.dark { }` 오버라이드 블록**을 **MF expose 컴포넌트 그래프(또는 MF 진입 모듈)에서도** import 하세요.
   - ⚠️ **Element Plus 다크 css-vars(`element-plus/theme-chalk/dark/css-vars.css`)는 재import 하지 마세요.** 호스트 포털이 이미 전역 로드합니다(계층1이 이미 다크되는 그 메커니즘). 리모트(EP 2.9.3)가 재import 하면 호스트 EP 2.13.7 다크 변수와 **버전 충돌을 되살립니다.** 지금은 리모트 EP dark css-vars 가 임베드 경로에 안 실려 안전한 상태입니다 — 그대로 두세요.
   - 근거: 포털이 이미 `html.dark` 를 켜므로, 리모트는 "그 클래스에 걸릴 자기 규칙"만 페이지에 실으면 됩니다.
2. **비-EP 위젯 다크 대응.** DevExtreme·Highcharts·Vue-Flow·wangEditor 등 JS 테마 위젯은 `html.dark` CSS 만으로 안 바뀝니다 → 공유 store 의 `isDark`(또는 `document.documentElement.classList.contains('dark')`)를 **읽어서** 위젯별 다크 옵션을 켜는 코드를 넣으세요. (참고: DevExtreme 은 현재 `dx.light.css` 만 로드된 상태라 `dx.dark.css` 로드도 동반돼야 합니다. 이 repo들에 isDark 로 구동하는 기존 위젯 예시는 없으니 새로 작성해야 합니다.)
3. **하드코딩 색 → 변수화.** 라이트색 하드코딩(예: `#212121`, `#fff` 배경 카드)을 `--el-text-color-*` / `--el-bg-color` 등 EP 변수 또는 자기 `html.dark` 오버라이드로 치환하세요.

## 4. 서비스별 추가

- **asst-web**: pinia store id 가 `ecp-layout` 이라 포털 `ecp-global` 의 `isDark` 를 **못 받습니다**. `ecp-global` 로 정렬하거나 임베드 시 호스트 store 를 참조하세요. (계층1 EP 는 DOM 으로 이미 다크됨. 이 항목은 JS 구동 위젯의 다크 신호 수신용.)
- **qa-web**: persist key 가 `ecp-global-v2` 라 리모트가 자체 hydrate 하지 않습니다 — 런타임 store 는 id `ecp-global` 로 공유되고 호스트가 리모트 라우트보다 먼저 store 를 생성하므로 무해하나, 혼동 방지로 문서화 권장.

## 5. 완료 정의 (팀별 체크리스트) & 우선순위

각 팀은 자기 서비스에 대해 아래를 만족하면 완료입니다:

- [ ] `element-dark.scss` / `common.scss` 의 `html.dark {}` 블록이 **임베드 경로(MF expose 그래프)에서도** 로드됨 (§3.1)
- [ ] EP dark css-vars 재import **하지 않음**(호스트 제공) — §3.1 경고 준수
- [ ] 하드코딩 라이트색이 EP 변수/`html.dark` 오버라이드로 치환됨 (§3.3)
- [ ] (JS 위젯 보유 시) 위젯이 `isDark`/`html.dark` 를 읽어 다크 옵션 적용 (§3.2)
- [ ] asst 만: store id `ecp-global` 정렬 (§4)
- [ ] 포털 다크 토글 시 자기 임베드 화면이 full-dark, 라이트 복귀 무손상 (§5 검증)

**우선순위 권고**: **asst-web(advisor) 먼저.** 운영자가 실제로 보는 화면이 advisor 관리자 페이지이고(사용자 직접 확인), asst 는 store 불일치까지 겹쳐 잔여 라이트가 가장 눈에 띕니다. 그다음 ce → ta/qa → aicm 순(임베드 노출 빈도 기준). 추적은 `docs/parity/PARITY.md` 에 M1(포털 계층1 확인)/M2(각 svc-web 계층2 반영) 로 분리 기록.

## 5b. 검증 (반영 후)

포털 다크 토글 → 임베드된 자기 화면에서:
- 계층1(EP 컴포넌트)은 이미 다크 (반영 전에도) — 회귀 없음 확인
- 계층2(자체 커스텀·JS 위젯)가 다크로 전환되는지 확인
- 라이트 복귀·테마색·글자크기 무손상

## 6. 경계 / 주의

- 포털은 신호 emit 측만 제공(무해)하며 **외부 repo 를 수정하지 않습니다.** 위 계약을 리모트가 구현하기 전까지 계층2 다크는 안 보입니다.
- EP 버전 스큐(리모트 2.9.3 ↔ 포털 2.13.7): `--el-*` 변수·`.el-*` 클래스는 대체로 안정 → 다크 전파는 성립. 구조 변경분에서 경미한 시각 글리치 가능(다크 실패가 아니라 미세차) — 눈으로 확인.
- 온프레 포털의 `apps/portal/src/ui-kit`(자체 킷)는 미배포·이 건과 무관합니다.

**정본 설계:** `docs/parity/_design/dark-mode-remote-propagation.md`

---
---

# 📌 [asst-web 자체 분석 · 대응 현황] — 우리 팀 기록

> 위 핸드오프(포털 담당자 발신)를 **asst-web 실제 코드와 대조**한 결과와 우리 대응 방침. (작성: 2026-07-20)
> **결론: 요청사항 전부 대응 가능.** 단 문서의 위젯 목록·파일 지목이 우리 실정과 일부 달라 아래로 정정.

## A. 요청별 검증 결과 (문서 주장 vs 우리 코드)

| 문서 항목 | 문서 주장 | 우리 실제 | 판정 |
|---|---|---|---|
| §4 store id | asst store id 가 `ecp-layout` 이라 포털 `ecp-global` 의 `isDark` 미수신 | `ecp-layout` 맞음(`stores/modules/layout.ts:6`, persist key 도 `ecp-layout`). `ecp-global`/`ecp-global-v2` 는 **우리 프로젝트에 문자열조차 없음.** `isDark`/`primaryTheme`/`assemblySize` 모두 이 store state | ✅ 사실 |
| §3.3 하드코딩 색 | 라이트색 하드코딩 다수 | `.vue`/`.scss` 231개 중 50개 파일, `#fff` 계열 197회 / `background:#…` 208회. 밀집: `element.scss`(46), `NewSubMenu.vue`(36), `HeaderActionBar/index.vue`(16) | ✅ 사실(규모 큼) |
| §3.1 EP 버전 | 리모트 EP 2.9.3 | `package.json:54` = **2.9.3** 확인. EP dark css-vars 는 `main.ts:18` 에서만 import(임베드 경로엔 안 실려 현재 안전) | ✅ 사실 |
| §3.2 위젯 목록 | DevExtreme·Highcharts·Vue-Flow·wangEditor | **아래 B로 정정 필요** | ⚠️ 부분 오류 |
| §3.1 파일 지목 | "`common.scss` 의 `html.dark` 블록" | `common.scss` 엔 다크 블록 **없음**(배럴 역할). 실제 다크 규칙은 `element-dark.scss`(`html.dark`), `element.scss`(`.dark`), `devExtreme.scss`(`.dark .dx-*`)에 분산 | ⚠️ 지목 어긋남 |

## B. §3.2 JS 위젯 — 우리 실정 (문서와 다름)

| 문서 언급 | asst-web 실제 | 다크 대응 필요 |
|---|---|---|
| DevExtreme | ✅ 실사용(그리드) | ❗ **필요.** `dx.dark.css` 아예 없음(`dx.light.css` 고정, `main.ts:50`) → 다크 CSS 로드 + isDark 로 전환 코드 **신규 작성** |
| Toast UI Editor | ✅ 실사용(`EditorComponent.vue`) — **문서 누락분** | ❗ **필요(쉬움).** 다크 코드는 이미 있으나 `isDark` 가 `ref(false)` 하드코딩(`:26` "임시" 주석) → 전역 store 에 **연결만** 하면 됨 |
| Highcharts | ⚠️ 등록 코드 주석처리(`main.ts:104~`), 데모뷰만 | ➖ 현재 무영향. 스타일 기반(`useTheme.ts:21`, `highchart.scss`)은 있어 켜면 대응됨 |
| Vue-Flow | ❌ 미사용(dead import 1개, `DxDataGridWrapper.vue:78`) | ➖ 해당 없음 |
| wangEditor | ❌ 아예 없음(package.json·소스 0건) | ➖ 해당 없음 |

→ **우리가 실제로 손댈 JS 위젯 = DevExtreme(작업 큼) + Toast UI Editor(연결만).** wangEditor/Vue-Flow/Highcharts 는 무시.

## C. §4 store 정렬 — 우리는 이미 postMessage 로 수신 중

- 문서는 "`ecp-global` 로 정렬하라"지만, 우리는 이미 **postMessage 로 부모 포털과 isDark 동기화** 중: 수신 `App.vue:45`(`setGlobalState("isDark", …)`), 송신 `utils/postMessage.ts:39`.
- → **store id 를 바꾸는 게 정말 필요한지는 수정하면서 확인.** 이미 신호를 받고 있으면 §4 정렬 불필요할 수 있고, 무리하게 바꾸면 기존 로직이 깨질 위험. 문서 제안 맹종 금지.

## D. 담당자에게 회신한 요지 (2026-07-20)

> 전체 대응 가능. 어드바이저 기준: wangEditor·Vue-Flow·Highcharts 는 미사용이고 **DevExtreme(dx.dark.css)** 와 **Toast UI Editor** 는 신규 작업 필요. 이미 postMessage 로 isDark 를 받고 있어 `ecp-global` 정렬 필요 여부는 수정하면서 확인. 나머지(다크 스타일 임베드 로드, 하드코딩 색 치환)는 예정대로 진행하고 EP dark css-vars 재import 금지도 준수.

## E. ⭐ 연결 이슈 — flex 레이아웃 깨짐 (§3.1 과 같은 뿌리)

- **증상:** 우리 단독 실행은 정상인데 **포털 임베드 시 flex 레이아웃 깨짐**(한 줄에 나와야 할 게 세로 개행).
- **원인(동일 뿌리):** flex 유틸 CSS 가 임베드 경로에 **안 실림.**
  - `.flex`/`.flex-col`/`.flex-1`/`.justify-*` → `global.scss:297~` (`!important` 있음, **`main.ts:133` 에서만** import)
  - `.flx-center`/`.flx-align-center`/`.flx-justify-between` → `common.scss:97~` (`!important` 없음, **`App.vue <style>` 에서만** `@use`)
  - MF expose 진입점 3개(consultant/management-user/advisor-renual)는 `main.ts`·`App.vue` 를 안 거침 + `vue-style-loader` 는 "import 될 때만 주입" → `display:flex` 자체가 안 걸려 **block 흐름으로 세로 개행.** (advisor-renual 트리 12개 파일이 이 유틸에 의존)
  - 클래스명 충돌(`.flex` 등 흔한 이름)은 부차 요인.
- **방침(사용자 확정 2026-07-20): 1번 = 진입점에서 `global.scss`/`common.scss` 명시 import 추가.** 빠르게 증상부터 잡고, 역방향 오염(우리 `!important` flex 가 포털에 샘)이 실제 관찰되면 그때 루트 스코핑으로 좁힘.
  - ⚠️ 이 import 추가는 §3.1 다크 스타일 로드까지 **같이 해결**됨(`common.scss` 가 `element-dark.scss` 등을 배럴로 끌어오므로).

## F. 우선순위 (우리 내부)

1. **flex 임베드 로드(E)** — 포털 임베드 화면이 실제로 깨져 보이므로 최우선. §3.1 다크 로드도 동반 해결.
2. **Toast UI Editor isDark 연결(B)** — 쉬움.
3. **DevExtreme 다크(B)** — 작업 큼.
4. **하드코딩 색 치환(§3.3)** — 양 많음. advisor 관리자 화면 우선 여부는 별도 결정.
5. **§4 store 정렬** — 수정하면서 필요 여부 확인(현재 postMessage 로 수신 중).
