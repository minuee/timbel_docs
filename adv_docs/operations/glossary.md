# 용어집 (Glossary)

> Advisor 프로젝트에서 자주 등장하는 약어 / 도메인 용어 / 기술 용어 정리.
> 모르는 용어가 나오면 먼저 여기서 검색하세요.

---

## 1. 도메인 / 비즈니스 용어

| 용어 | 의미 |
|------|------|
| **Advisor (상담 어시스트)** | 본 프로젝트. 콜센터 상담원을 위한 AI 보조 플랫폼. |
| **CCaaS** | Contact Center as a Service. 콜센터 플랫폼 전체 |
| **CTI** | Computer Telephony Integration. 전화 시스템과 컴퓨터 연동. `cc_cti_id` 가 상담원 식별자로 사용됨. |
| **상담원 (agent)** | 통화를 받는 사용자. `role: AGENT`. |
| **관리자 (admin)** | 상담원 모니터링 + 코칭 발송. `role: ADMIN`. |
| **viewer** | 읽기 전용 관찰자 (관리자 변형) |
| **턴 (turn)** | 한 사람의 발화 단위. `turn_idx` 로 식별. |
| **콜 / 통화 (call)** | 한 번의 전화 통화. `call_id` 로 식별. |
| **콜스탯 (callstats)** | 통화 통계 데이터. `raw_call.callstats_call` 등. `callstats_id`는 통화의 통계 단위 식별자. |
| **테넌트 (tenant)** | 본 시스템을 사용하는 고객사. 테넌트별 DB 분리. `tenant_id` 로 식별. |
| **워크스페이스 (workspace)** | CE 서비스의 단위. 봇과 그래프가 워크스페이스별로 관리됨. |

---

## 2. STT / NLP 관련

| 용어 | 의미 |
|------|------|
| **STT** | Speech-to-Text. 음성 → 텍스트 변환 |
| **NLP** | Natural Language Processing. STT 결과에서 의미 추출 (인텐트, 키워드, 엔티티) |
| **EOU** | End-of-Utterance. 발화 종료 시점 판단. EOU 오판 시 한 발화가 두 turn으로 쪼개짐. |
| **NeMo** | NVIDIA 의 STT/NLP 프레임워크. Turn EOU 이슈가 있어 [specs/](../specs/) 에 분석 기록 다수. |
| **partial** | 발화 중인 누적 텍스트. `nlp:partial` 채널. `masked_text=""`, `nlp=null`. |
| **complete** | 발화 확정. `nlp:complete` 채널. 마스킹 + NLP 분석 완료. |
| **origin_text** | 원본 발화 텍스트 (마스킹 전) |
| **masked_text** | 개인정보 마스킹 적용된 텍스트 (예: 카드번호 → ****) |
| **intent** | 발화의 의도 분류 (예: `REFUND_INQUIRY`) |
| **keyword** | NLP가 추출한 핵심 키워드 |
| **search_query** | NLP가 추출한 검색 쿼리 (RAG 입력용) |
| **speaker** | 발화자. `"customer"` 또는 `"agent"`. |

---

## 3. AI / LLM 관련

| 용어 | 의미 |
|------|------|
| **LLM** | Large Language Model. GPT, Claude, 자체 모델 등. |
| **SLLM** | Small Language Model. 경량 모델 (자체 운영). 담당: 최문용 책임님. |
| **RAG** | Retrieval-Augmented Generation. 검색 + LLM 답변. |
| **Orchestrator** | LLM Orchestrator. 프롬프트 관리 + 모델 라우팅 서비스. `LLM_ORCHESTRATOR_HOST`. |
| **promptName** | Orchestrator 측 프롬프트 이름. 예: `adv-conversations-summarize`. |
| **assist-stream** | 고객 발화 → RAG/LLM 답변을 SSE로 스트리밍하는 Advisor 엔드포인트. |
| **assist snapshot** | assist-stream 응답을 통화별로 저장하는 데이터. `callstats_assist_snapshot` 테이블. |
| **distill** | LLM 답변을 압축/요약하는 옵션 (현재 `false` 사용). |
| **conversation history** | LLM에게 컨텍스트로 제공하는 과거 N턴의 대화. |

---

## 4. 시스템 / 인프라

| 용어 | 의미 |
|------|------|
| **asst-service** | 백엔드 (NestJS). 본 프로젝트의 API 서버. |
| **asst-web** | 프론트엔드 (Vue 3). `ecs-cloud-portal` 이라는 이름으로 빌드됨. |
| **asst-web-ui** | 별도 mock 데모 (실제 서비스 아님). |
| **Langsa 게이트웨이** | API 게이트웨이. 모든 트래픽의 단일 진입점. `LANGSA_GATEWAY_URL`. |
| **ECP** | ECS Cloud Portal. asst-web을 호스트하는 상위 포털. 모듈 페더레이션. |
| **CE (Call Experience)** | CE 서비스. 어드바이저봇 / 봇 그래프 워크플로우 엔진. `CE_HOST`. |
| **KMS** | Knowledge Management System. 문서 저장 + 검색. `KNOWLEDGE_API_URL`. |
| **TA** | Text Analytics. 통화 분석 서비스. `TA_HOST` (현재 코드 주석). |
| **QA** | Quality Assurance. 통화 품질 평가. `QA_API_URL`. |
| **User Service** | 사용자/조직/테넌트 관리. `USER_HOST`. 토큰 검증도 위임. |

---

## 5. 백엔드 패턴 / 라이브러리

| 용어 | 의미 |
|------|------|
| **BFF** | Backend-for-Frontend. asst-service가 외부 서비스를 프록시. |
| **DataSource** | TypeORM의 DB 연결 인스턴스. 테넌트마다 별도 생성. |
| **synchronize** | TypeORM 옵션. 엔티티 변경 시 자동으로 ALTER. 로컬만 `true`. |
| **DbCleanupInterceptor** | 응답 후 처리 (실제로는 no-op, 로깅만). |
| **TraceLogger** | 분산 추적용 로거. `[traceId]` prefix 자동 부착. |
| **AsyncLocalStorage** | Node.js 비동기 컨텍스트 저장소. trace ID 보존에 사용. |
| **path-to-regexp v8** | Express 5의 라우팅 라이브러리. `(.*)` 금지, `{*name}` 사용. |

---

## 6. 프론트엔드 패턴 / 라이브러리

| 용어 | 의미 |
|------|------|
| **Composable** | Vue 3 Composition API. 로직 재사용 단위 (`useXxx`). |
| **Pinia** | Vue 3 상태 관리. Vuex의 후속. |
| **persistedstate** | Pinia 플러그인. localStorage 영속화. |
| **모듈 페더레이션 (Module Federation)** | Webpack 5 기능. 여러 앱이 런타임에 모듈 공유. ECP 호스트 통합에 사용. |
| **devextreme** | DevExpress의 UI 라이브러리. 21.2.5 버전 고정 (레거시). |
| **vue-flow** | 노드/엣지 기반 다이어그램. 어드바이저봇 시각화 등에 사용. |

---

## 7. 실시간 / 메시징

| 용어 | 의미 |
|------|------|
| **Socket.IO** | WebSocket 기반 실시간 통신. 기본 path: `/socket.io`. |
| **Pub/Sub** | Publish-Subscribe. Redis 채널 모델. |
| **room** | Socket.IO의 그룹 단위. Redis 채널명 = room명으로 매핑. |
| **sticky session** | LB가 같은 사용자를 같은 pod로 라우팅. Socket.IO 필수. |
| **SSE** | Server-Sent Events. 단방향 HTTP 스트리밍. assist-stream 에 사용. |
| **redis-message** | Socket.IO 이벤트 이름. Redis pub/sub 메시지 중계용. |

---

## 8. 도메인 모듈 약어

| 디렉토리 | 풀네임 |
|---------|-------|
| `agent` | 상담원 |
| `call` | 통화 통계 |
| `coaching` | 코칭 (상담원→상담원 또는 관리자→상담원) |
| `summary` | 통화 요약 |
| `todo` | 후속조치 |
| `memo` | 개인 메모 |
| `bookmark` | 북마크 |
| `notice` | 공지 |
| `favorite` | 즐겨찾기 (5종) |
| `intent-feedback` | 인텐트 정답/오답 피드백 |
| `keyword-detect` | 금칙어/위험어 감지 |
| `group` | 상담원 그룹 |
| `config` | 테넌트 설정 |
| `document` | 문서 메타 (KMS 보조) |
| `search` | 문서 검색 (KMS 위임) |
| `assist-stream` | AI 상담 보조 |
| `shared` | 공통 유틸/DTO |

---

## 9. 환경 / 배포

| 용어 | 의미 |
|------|------|
| **NODE_ENV** | Node 런타임 환경. `local` / `development` / `production`. |
| **MODE** | Webpack 빌드 모드. `local` / `dev` / `prd` / `aws` / `ncp`. |
| **NCP** | Naver Cloud Platform. NCP 빌드 모드 (`build:ncp`). |
| **온프레미스 (on-premise)** | 클라우드 아닌 고객사 사내 서버 배포. |
| **DB_DIRECT_CON** | DB 연결 방식 토글. `1`=정적, `0`=테넌트 동적. |
| **DBA** | Database Administrator. 마이그레이션 적용 담당. |

---

## 10. 자주 헷갈리는 페어

| 용어 1 | 용어 2 | 차이 |
|--------|--------|------|
| **call_id** | **callstats_id** | call_id는 통화 식별자 (외부 시스템), callstats_id는 통계 데이터 식별자 |
| **agent_id** | **cc_cti_id** | agent_id는 일반 ID, cc_cti_id는 CTI 시스템 ID (소문자 매칭 주의) |
| **assist-stream** | **어드바이저봇** | 전자는 RAG/LLM SSE, 후자는 CE 그래프 봇 Socket.IO |
| **메인 소켓** | **어드바이저봇 소켓** | 메인=asst-service, 어드바이저봇=CE 서비스 |
| **`partial`** | **`stt:final`** | partial은 NLP 누적, stt:final은 STT 종료 (현재 빈 핸들러) |
| **`Authorization`** | **`x-auth-token`** | Bearer fallback vs 우선 헤더 |
| **`USER_HOST`** | **`TENANT_HOST`** | 둘 다 사용자/테넌트 조회. 현재 코드는 USER_HOST 사용. |
| **`LLM_ORCHESTRATOR_HOST`** | **`LLM_HOST`** | 전자가 메인, 후자는 fallback (레거시) |

---

## 11. 약어 빠른 참조

ASR · STT · NLP · NLU · LLM · SLLM · RAG · BFF · CTI · CCaaS · SSE · WS/WSS · K8s · LB · ALB · TLS · TTL · LRU · ORM · ERD · KMS · QA · TA · IAM · DTO · CRUD · CI/CD · MQ · pub/sub · CDN · ECP · NCP

각 항목의 풀네임은 위 섹션 참조.

---

## 12. 갱신 정책

- 새 용어 발견 시 즉시 추가
- 의미가 바뀌면 갱신
- 이 문서는 모든 후임자가 가장 자주 접속하는 페이지가 되도록 유지
