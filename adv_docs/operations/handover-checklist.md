# 후임자 인수인계 체크리스트

> 새로 합류하는 개발자가 1~2주 안에 Advisor 시스템에 익숙해지기 위한 단계별 체크리스트.

---

## Day 1: 시스템 큰 그림

### 읽기

- [ ] [adv_docs/architecture/00-overview.md](../architecture/00-overview.md) — 전체 아키텍처
- [ ] [asst-service/CLAUDE.md](../../asst-service/CLAUDE.md) — 백엔드 컨벤션
- [ ] 루트 [CLAUDE.md](../../CLAUDE.md), [AGENTS.md](../../AGENTS.md) — 프로젝트 규칙

### 이해 확인 질문

1. asst-service와 asst-web의 관계는?
2. Langsa 게이트웨이를 거치는 이유는?
3. 외부 서비스 5개 이상 이름 댈 수 있는가? (`USER_HOST`, `LLM_ORCHESTRATOR_HOST`, `SEARCH_HOST`, `CE_HOST`, `KNOWLEDGE_API_URL`)
4. `asst-web`과 `asst-web-ui`의 차이는?

---

## Day 2~3: 멀티테넌트 DB 이해

### 읽기

- [ ] [adv_docs/architecture/01-multi-tenant-db.md](../architecture/01-multi-tenant-db.md)
- [ ] [asst-service/src/common/middleware/auth.middleware.ts](../../asst-service/src/common/middleware/auth.middleware.ts)
- [ ] [asst-service/src/common/services/dynamic-database.service.ts](../../asst-service/src/common/services/dynamic-database.service.ts)
- [ ] [asst-service/src/common/services/tenant-config.service.ts](../../asst-service/src/common/services/tenant-config.service.ts)

### 실습

- [ ] 로컬에 PostgreSQL 띄우고 `DB_DIRECT_CON=1`로 백엔드 실행
- [ ] Postman/Insomnia로 `GET /api/asst/v1/agents` 호출해서 응답 확인
- [ ] 강제로 토큰을 잘못 보내서 401 응답 받아보기
- [ ] `DynamicDatabaseService.getConnectionDetails()` 결과 확인 (디버거 또는 임시 엔드포인트)

### 이해 확인 질문

1. `DB_DIRECT_CON=0` 일 때 첫 요청 흐름은?
2. 같은 테넌트의 두 번째 요청은 캐시를 어떻게 활용하나?
3. `runSchemaMigrations` 가 매번 실행되는데 문제는 없나?
4. 엔티티 추가 시 수정해야 할 두 곳은?

---

## Day 4~5: 실시간 스트리밍 이해

### 읽기

- [ ] [adv_docs/architecture/02-realtime-streaming.md](../architecture/02-realtime-streaming.md)
- [ ] [asst-service/src/common/gateways/socket.gateway.ts](../../asst-service/src/common/gateways/socket.gateway.ts)
- [ ] [asst-service/src/common/controllers/redis-monitor.controller.ts](../../asst-service/src/common/controllers/redis-monitor.controller.ts)
- [ ] [asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts) — 800줄, 가장 복잡

### 실습

- [ ] 로컬 Redis 실행 후 `redis-cli`에서 직접 `PUBLISH` 시뮬레이션
  ```
  PUBLISH dev:tenant1:agent01:call:events '{"type":"start","call_id":"test-001"}'
  ```
- [ ] 브라우저 콘솔에서 `socket.on('redis-message', console.log)` 로 메시지 확인
- [ ] `POST /redis-monitor/subscribe/{channel}` 호출 후 채널 구독 시작 확인
- [ ] partial → complete 시뮬레이션 후 채팅 UI 반응 확인

### 이해 확인 질문

1. 백엔드는 어떤 채널을 자동 구독하나? (답: coaching만 자동, 나머지는 프론트가 요청)
2. `nlp:partial` 과 `nlp:complete` 의 데이터 형식 차이는?
3. `streamingBySpeaker` 가 필요한 이유는?
4. K8s sticky session이 깨지면 어떤 증상이 나타나는가?
5. assist-stream(SSE)과 redis-message(Socket.IO)의 차이는?

---

## Day 6~7: 프론트엔드 화면 구조

### 읽기

- [ ] [adv_docs/architecture/03-frontend.md](../architecture/03-frontend.md)
- [ ] [asst-web/src/view/advisor/consultant/index.vue](../../asst-web/src/view/advisor/consultant/index.vue) — 진입점
- [ ] [asst-web/src/view/advisor/agent/index.vue](../../asst-web/src/view/advisor/agent/index.vue) — 상담사 화면
- [ ] [asst-web/src/view/advisor/components/chat/index.vue](../../asst-web/src/view/advisor/components/chat/index.vue) — 채팅 컴포넌트
- [ ] [asst-web/src/api/socketIOPlugin.ts](../../asst-web/src/api/socketIOPlugin.ts)
- [ ] [asst-web/src/routers/index.ts](../../asst-web/src/routers/index.ts)

### 실습

- [ ] `npm run local` 로 프론트 실행
- [ ] 브라우저에서 상담원 화면 진입 → 콘솔 로그로 socket 연결 확인
- [ ] Vue DevTools에서 Pinia 스토어 상태 관찰
- [ ] `useChatMessageParser` 에 breakpoint 걸고 실제 메시지 흐름 따라가기

---

## Day 8~9: 도메인 모듈

### 읽기

- [ ] [adv_docs/specs/domains-overview.md](../specs/domains-overview.md)
- [ ] [adv_docs/flows/call-lifecycle.md](../flows/call-lifecycle.md) — 통화 1건 전체 흐름
- [ ] 핵심 도메인 5개 코드:
  - [ ] [asst-service/src/advisor/call/](../../asst-service/src/advisor/call/)
  - [ ] [asst-service/src/advisor/summary/](../../asst-service/src/advisor/summary/)
  - [ ] [asst-service/src/advisor/coaching/](../../asst-service/src/advisor/coaching/)
  - [ ] [asst-service/src/advisor/assist-stream/](../../asst-service/src/advisor/assist-stream/)
  - [ ] [asst-service/src/advisor/search/](../../asst-service/src/advisor/search/)

### 실습

- [ ] Swagger UI(`/api/asst/v1/doc`) 에서 5개 도메인 엔드포인트 직접 호출
- [ ] `POST /summary` 호출 → LLM 응답까지 따라가보기

---

## Day 10: 운영 / 환경

### 읽기

- [ ] [adv_docs/operations/env-variables.md](env-variables.md)
- [ ] [adv_docs/api/conventions.md](../api/conventions.md)
- [ ] `.env.development` (있다면)
- [ ] `migrations/` 모든 SQL 파일

### 실습

- [ ] dev 환경 접속 (가능하다면)
- [ ] 운영 K8s 매니페스트 확인 (Deployment, ConfigMap, Secret)
- [ ] 로그 시스템(Kibana/Loki 등) 접근 + 트레이스 ID로 요청 추적

---

## Week 2: 첫 실제 작업

### 추천 시작 작업 (난이도 순)

1. **README/문서 오타 수정** — 작은 PR로 git 워크플로우 익히기
2. **간단한 GET 엔드포인트 추가** — Controller→Service→Entity 패턴 학습
3. **기존 도메인에 필드 추가** — 마이그레이션 + 엔티티 + DTO 수정 경험
4. **버그 수정** — `TODO-REFACTOR.md` 에서 작은 것 골라보기
5. **테스트 작성** — 기존 코드에 누락된 단위 테스트 추가

---

## 알아두면 좋은 운영 노하우

> 자주 발생하는 장애 시나리오별 대응은 [incident-runbook.md](incident-runbook.md) 를 참조하세요.
> 시스템의 미해결 과제·민감 이슈는 문서로 남기지 않고 인수인계 세션에서 구두로 전달합니다.

### 디버깅 시 자주 사용하는 도구

| 도구 | 용도 |
|------|------|
| `GET /redis-monitor/status` | Redis 구독 상태 |
| `GET /redis-monitor/debug/rooms` | Socket.IO room 상태 |
| Swagger UI `/api/asst/v1/doc` | API 직접 호출 |
| Vue DevTools (브라우저 확장) | Pinia 스토어 + 컴포넌트 트리 |
| `redis-cli` `MONITOR` | 모든 Redis 명령 실시간 관찰 |
| OpenTelemetry 트레이스 | 분산 추적 (요청 흐름 시각화) |

### 로깅 / 추적

- **Trace ID**: 모든 요청에 `x-trace-id` 헤더 부착. 로그에 포함되어 분산 추적 가능.
- **로깅 라이브러리**: `nest-winston` + `winston-daily-rotate-file`. 로그 회전 자동.
- **민감 정보**: 현재 `auth.middleware.ts` 가 토큰 일부를 콘솔에 출력 — **운영에서는 줄여야 함**.

---

## 추가 학습 리소스

| 주제 | 자료 |
|------|------|
| NestJS 11 | [공식 문서](https://docs.nestjs.com) |
| TypeORM 0.3 | [공식 문서](https://typeorm.io/) |
| Socket.IO | [공식 문서](https://socket.io/docs/v4/) |
| Vue 3 Composition API | [공식 문서](https://vuejs.org/guide/extras/composition-api-faq.html) |
| Pinia | [공식 문서](https://pinia.vuejs.org/) |
| RFP / 요구사항 | [RFP_요구사항_통합목록.docx](../../RFP_요구사항_통합목록.docx) |
| 27건 구현현황 점검 | [상담어시스트_27건_구현현황_점검.docx](../../상담어시스트_27건_구현현황_점검.docx) |
| 미구현/부분구현 | [RFP_미구현_부분구현_정리.docx](../../RFP_미구현_부분구현_정리.docx) |
| 작업 단위 정리 | [advisor_작업단위_정리_v2.docx](../../advisor_작업단위_정리_v2.docx) |

---

## 인수인계 종료 체크

- [ ] 모든 환경(로컬/dev/prod)에 접근 가능
- [ ] Swagger UI / 로그 시스템 / 모니터링 계정 발급 완료
- [ ] GitHub 권한 + PR 머지 권한
- [ ] K8s 클러스터 / 컨테이너 레지스트리 접근
- [ ] 운영팀 슬랙 / 이슈 트래커 합류
- [ ] 외부 서비스(USER, LLM, SEARCH, CE) 담당자 연락처
- [ ] 첫 PR 머지 경험 완료
- [ ] 인수인계 세션에서 구두 전달받은 미해결 과제 숙지
- [ ] 통화 라이프사이클 한 사이클 직접 따라가본 경험
