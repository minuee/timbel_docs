# AIGA Advisor Front-End (asst-web) — 소프트웨어 / 라이브러리 구성

> `package.json` · `webpack.config.js` · `tsconfig.json` 기준 실측 정리 (DevOps.pptx slide 5 형식)

## 구성표

| 구분 | 내용 | 비고 |
|---|---|---|
| **개발언어** | Vue.js 3.5.18 (with TypeScript ~5.1.6) | Composition API / SFC |
| **Module & WAS** | Node ( v20 ) | `@types/node` v20.11 기준 (빌드 산출물은 정적 파일 → Nginx 서빙) |
| **지원 OS** | Windows, macOS, iOS, AOS 등 브라우저 환경 | |
| **지원 Browser** | Chrome, Edge, Firefox, Safari(macOS/iOS) 최신 계열 | `browserslist`: last 1 chrome/firefox/safari, (배포) `>1%, not dead` · IE 미지원 |
| **Framework / Build** | Vue 3 + Module Federation (Micro-Frontend) / Webpack 5 | 앱 이름 `advisor_app`, `remoteEntry.js` 노출 (host 앱에 임베드) |
| **Design** | 기본 SCSS(Sass) + UI-Component(Element Plus 2.9.3, 자체킷 @timbel-aicc/ecp-ui-kit) | 보조: Quasar 2.12.6, DevExtreme 21.2.5 |
| **Networking** | Axios (with Socket.IO / WebStomp / SockJS 실시간) | REST + WebSocket/STOMP 병행 |
| **State Management** | Pinia ( with pinia-plugin-persistedstate → Local Storage ) | |
| **Navigation** | Vue Router 4 | |
| **필수 Library** | vue, vue-router, pinia, axios, element-plus, typescript, @timbel-aicc/ecp-ui-kit 등 | |
| **etc Library** | dayjs, vue-i18n, highcharts, exceljs/vue3-xlsx, tiptap, @vue-flow, gojs/drawflow, devextreme, marked, pdfjs-dist, crypto-js 등 | 차트 · 에디터 · 플로우 · 문서변환 등 |

## 참고 — AIGA Admin(slide 5)과의 핵심 차이

| 구분 | AIGA Admin (React) | AIGA Advisor (asst-web / Vue) |
|---|---|---|
| 언어/프레임워크 | React 19 + Next 15 | Vue 3 + Webpack Module Federation |
| 상태관리 | zustand + Context-API | Pinia (+ persistedstate) |
| 디자인 | Chakra-UI / Styled-Component | SCSS + Element Plus (+ 자체 ecp-ui-kit) |
| 네트워킹 | axios (+ react-query) | axios (+ Socket.IO / STOMP 실시간) |
| 라우팅 | Next-router / react-router-dom | Vue Router 4 |
