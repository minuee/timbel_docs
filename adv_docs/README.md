# Advisor 인수인계 문서

> 상담 어드바이저 (Call Center AI Assistant) 프로젝트의 후임자 인수인계용 문서 저장소입니다.
> 모든 문서는 **현재 코드 기준**이며, 변경사항이 있으면 즉시 갱신해주세요.

---

## 빠른 시작

처음 합류한 개발자는 다음 순서로 읽으세요:

1. **[architecture/00-overview.md](architecture/00-overview.md)** — 전체 시스템 개요
2. **[operations/handover-checklist.md](operations/handover-checklist.md)** — Day-by-day 학습 체크리스트

---

## 디렉토리 구조

```
adv_docs/
├── README.md                      # 이 파일 (인덱스)
│
├── architecture/                  # 시스템 아키텍처
│   ├── 00-overview.md                전체 그림 + 외부 서비스 맵
│   ├── aicc-system-context.md        AICC 전체 시스템 컨텍스트 (drawio 가이드)
│   ├── 01-multi-tenant-db.md         테넌트별 동적 DB 연결
│   ├── 02-realtime-streaming.md      Redis pub/sub + Socket.IO + SSE
│   ├── 03-frontend.md                Vue 3 + Pinia + 핵심 컴포저블
│   ├── 04-data-model.md              ERD 요약 (advisor + raw_call 스키마)
│   ├── 05-backend.md                 NestJS 모듈 구조 + BFF 선택 배경
│   ├── diagrams/                     drawio 원본 보관
│   │   └── aicc-architecture.drawio    AICC 전체 (17페이지 C4 모델)
│   └── README.md
│
├── specs/                         # 도메인/외부 시스템 스펙
│   ├── domains-overview.md           17개 도메인 요약 + 핵심 5개 상세
│   ├── llm-integration.md            LLM Orchestrator 호출 패턴
│   ├── proxy-controllers.md          BFF 프록시 6종 (KMS/CE/Audio/QA/User)
│   ├── advisorbot.md                 어드바이저봇 (CE 그래프 봇)
│   ├── stt-nlp-contract.md           외부 STT/NLP 엔진 Redis 메시지 contract
│   ├── socket-events.md              메인 Socket.IO 이벤트 전체 카탈로그
│   └── (기타 NeMo 등 외부 시스템 스펙)
│
├── api/                           # API 규약
│   ├── conventions.md                인증/페이지네이션/에러 형식 + 엔드포인트 인덱스
│   └── README.md
│
├── flows/                         # 업무 플로우
│   ├── call-lifecycle.md             통화 한 건의 전체 라이프사이클
│   ├── admin-monitoring.md           관리자 모니터링 + 실시간 코칭 발송
│   └── README.md
│
├── operations/                    # 운영
│   ├── env-variables.md              환경변수 전체 + 환경별 권장 조합
│   ├── local-setup.md                로컬 개발 환경 셋업 (PG/Redis 도커 포함)
│   ├── error-logging.md              TraceLogger / OpenTelemetry / 에러 매핑
│   ├── contacts.md                   영역별 메인 담당자 + 장애 1차 문의처
│   ├── glossary.md                   용어집 (STT/NLP/RAG/KMS/BFF/CCaaS 등)
│   ├── incident-runbook.md           장애 대응 런북 (장애별 1차 대응 절차)
│   ├── permissions.md                role(AGENT/ADMIN/VIEWER) + 동적 라우터
│   └── handover-checklist.md         후임자 Day-by-day 체크리스트
│
├── plans/                         # 진행 중/완료 계획서
│   ├── (active)                      현재 작업 중인 계획서
│   └── done/                         완료된 계획서 (이력 보존)
│
└── asst-web-ui/                   # 별도 mock 데모 (실제 서비스 아님)
    └── PROJECT.md
```

---

## 문서별 한 줄 요약

### 아키텍처

| 문서 | 내용 |
|------|------|
| [00-overview.md](architecture/00-overview.md) | Langsa 게이트웨이 + asst-service + asst-web 관계도, 외부 서비스 5종, 모노레포 구조 |
| [aicc-system-context.md](architecture/aicc-system-context.md) | **AICC 전체 시스템 컨텍스트** (drawio 다이어그램 17페이지 가이드) |
| [01-multi-tenant-db.md](architecture/01-multi-tenant-db.md) | `AuthMiddleware → TenantConfigService → DynamicDatabaseService` 흐름, `DB_DIRECT_CON` 토글, 자동 마이그레이션 주의사항 |
| [02-realtime-streaming.md](architecture/02-realtime-streaming.md) | Redis Pub/Sub → Socket.IO 중계, 4개 채널 규약, STT partial/complete 처리, Assist Stream SSE |
| [03-frontend.md](architecture/03-frontend.md) | Vue 3 구조, Pinia 30+ 스토어, Chat 컴포저블 7종, 모듈 페더레이션 |
| [04-data-model.md](architecture/04-data-model.md) | ERD 요약 (advisor + raw_call 스키마), 핵심 join 패턴, 테이블 ↔ 엔티티 매핑 |
| [05-backend.md](architecture/05-backend.md) | NestJS 3모듈 구조, 요청 파이프라인, **BFF 패턴 선택 이유/트레이드오프**, 새 기능 추가 절차 |

### 도메인 / 외부 통합

| 문서 | 내용 |
|------|------|
| [domains-overview.md](specs/domains-overview.md) | 17개 도메인 모듈 한 줄 요약 + 핵심 5개(call/summary/coaching/assist-stream/search) 상세 |
| [llm-integration.md](specs/llm-integration.md) | LLM Orchestrator 호출 패턴 (`complete()` vs `customComplete()`), 헤더 컨벤션, 에러 매핑 |
| [proxy-controllers.md](specs/proxy-controllers.md) | BFF 프록시 6종 (CE/Knowledge/User/Audio/QA/TA) — KMS 위임 정책 포함 |
| [advisorbot.md](specs/advisorbot.md) | 어드바이저봇 (CE 그래프 봇) — Assist Stream과의 차이, 메인 소켓과 분리 |
| [stt-nlp-contract.md](specs/stt-nlp-contract.md) | 외부 STT/NLP 엔진과의 Redis 메시지 contract (필드, 예시, 순서) |
| [socket-events.md](specs/socket-events.md) | 메인 Socket.IO 이벤트 전체 카탈로그 (room 컨벤션, 이벤트 매트릭스) |

### API

| 문서 | 내용 |
|------|------|
| [conventions.md](api/conventions.md) | base path, `x-auth-token` 인증, 페이지네이션, 에러 형식, 도메인별 엔드포인트 인덱스 |

### 플로우

| 문서 | 내용 |
|------|------|
| [call-lifecycle.md](flows/call-lifecycle.md) | 로그인 → 통화 시작 → STT 발화 → 종료 → LLM 요약 전체 시퀀스 |
| [admin-monitoring.md](flows/admin-monitoring.md) | 관리자가 상담원 실시간 모니터링 + 코칭 발송 / 공지 broadcast 플로우 |

### 운영

| 문서 | 내용 |
|------|------|
| [env-variables.md](operations/env-variables.md) | 백엔드/프론트엔드 모든 환경변수 + 환경별 권장 조합 |
| [local-setup.md](operations/local-setup.md) | 로컬 개발 환경 셋업 (PG/Redis 도커, 첫 실행 체크리스트) |
| [error-logging.md](operations/error-logging.md) | TraceLogger, OpenTelemetry, 표준 에러 매핑 (502/503/500) |
| [contacts.md](operations/contacts.md) | 영역별 메인 담당자 + 코드 영역 매핑 + 장애 1차 문의처 |
| [glossary.md](operations/glossary.md) | 용어집 (STT/NLP/EOU/RAG/KMS/BFF/CCaaS/SLLM 등) |
| [incident-runbook.md](operations/incident-runbook.md) | 장애 대응 런북 (장애 시나리오별 1차 대응 절차) |
| [permissions.md](operations/permissions.md) | role(AGENT/ADMIN/VIEWER) 분기, 동적 라우터, **백엔드 권한 미완성 이슈** |
| [handover-checklist.md](operations/handover-checklist.md) | Day-by-day 학습 체크리스트 + 디버깅 도구 + 인수인계 종료 체크 |

> 배포·마이그레이션·테스트·보안정책 관련 운영 지식은 별도 문서로 두지 않고 인수인계 세션에서 구두 전달 + 담당자([contacts.md](operations/contacts.md)) 연결로 다룹니다.

---

## 핵심 사실 5가지

후임자가 가장 먼저 이해해야 할 것:

1. **모든 트래픽은 Langsa 게이트웨이를 거친다** — 브라우저가 asst-service에 직접 붙는 일은 없음 (개발 환경 제외)
2. **DB는 테넌트별로 물리 분리** — `AuthMiddleware`가 토큰으로 어느 DB에 붙을지 매 요청마다 결정
3. **STT 발화는 Redis Pub/Sub 경유** — STT/NLP 엔진은 외부 시스템. asst-service는 Redis 메시지를 Socket.IO로 중계
4. **3가지 실시간 메커니즘이 공존** — Redis→Socket(STT), Socket 직접 emit(코칭), HTTP SSE(assist-stream)
5. **`asst-web-ui`는 mock 데모** — 실제 서비스 코드가 아니므로 혼동 주의

---

## 변경 이력

이 문서는 **현재 코드 기준**입니다. 다음과 같은 변경이 있을 때 즉시 갱신:

- 새 도메인 모듈 추가
- 환경변수 추가/변경
- 외부 서비스 의존성 변경
- 인증 흐름 변경
- DB 연결 패턴 변경
- 실시간 채널 규약 변경

---

## 추가 참고 자료

### 프로젝트 루트 문서

- [CLAUDE.md](../CLAUDE.md) — Claude Code용 프로젝트 컨텍스트
- [AGENTS.md](../AGENTS.md) — AI 에이전트 워크플로우
- [TODO-REFACTOR.md](../TODO-REFACTOR.md) — 남은 리팩토링 항목

### 모듈별 컨텍스트

- [asst-service/CLAUDE.md](../asst-service/CLAUDE.md) — 백엔드 컨벤션
- [asst-web/CLAUDE.md](../asst-web/CLAUDE.md) (있다면) — 프론트엔드 컨벤션

### Archived 문서 (구 인수인계)

다음 문서들은 2026-01-30 이전 작성된 구 인수인계 자료입니다. 정보가 다르면 adv_docs/가 신뢰원입니다.

| 문서 | 대체 위치 |
|------|----------|
| [asst-service/HANDOVER.md](../asst-service/HANDOVER.md) | [adv_docs/architecture/00-overview.md](architecture/00-overview.md) + 전체 adv_docs |
| [asst-service/CORS_SETUP.md](../asst-service/CORS_SETUP.md) | [operations/env-variables.md](operations/env-variables.md) |
| [asst-service/DYNAMIC_DB_SETUP.md](../asst-service/DYNAMIC_DB_SETUP.md) | [architecture/01-multi-tenant-db.md](architecture/01-multi-tenant-db.md) |
| [asst-service/setup-database.md](../asst-service/setup-database.md) | [operations/local-setup.md](operations/local-setup.md) (마이그레이션 SQL 원본: `asst-service/migrations/`) |
| [asst-service/advisorbot-integration-guide.md](../asst-service/advisorbot-integration-guide.md) | [specs/advisorbot.md](specs/advisorbot.md) |

### RFP / 요구사항 / 구 기획

> ⚠️ 아래 자료는 **초기 기획 시점** 기준입니다. 현재 구현과 다를 수 있으며, 코드/`adv_docs/`가 신뢰원입니다. 의도·배경 참고용으로만 사용하세요.

- [RFP_요구사항_통합목록.docx](../RFP_요구사항_통합목록.docx)
- [RFP_미구현_부분구현_정리.docx](../RFP_미구현_부분구현_정리.docx)
- [RFP_진행현황_보고서.docx](../RFP_진행현황_보고서.docx)
- [상담어시스트_27건_구현현황_점검.docx](../상담어시스트_27건_구현현황_점검.docx)
- [상담어시스트_기능요건_명세서_v1.0 (1).docx](../상담어시스트_기능요건_명세서_v1.0%20%281%29.docx)
- [advisor_작업단위_정리_v2.docx](../advisor_작업단위_정리_v2.docx)
- **상담 어드바이저 Figma (구 기획/디자인 시안)** — [\[AICC CCasS\] 상담어드바이저](https://www.figma.com/design/AaxtqK1yEx0aMSajYagBvm/-AICC-CCasS--%EC%83%81%EB%8B%B4%EC%96%B4%EB%93%9C%EB%B0%94%EC%9D%B4%EC%A0%80?node-id=2-2) — 초기 화면 기획/디자인. 현재 구현과 차이 있을 수 있음 (접근 권한 필요)

### 진행 중 / 완료 계획서

- [plans/](plans/) — 활성 계획서
- [plans/done/](plans/done/) — 완료된 계획서 (설계 결정 배경)

핵심 done 계획서:

| 주제 | 문서 |
|------|------|
| BFF 전환 | [2026-04-16-bff-transition-plan.md](plans/done/2026-04-16-bff-transition-plan.md) |
| 문서 검색 | [2026-04-16-document-search-design.md](plans/done/2026-04-16-document-search-design.md) |
| 통화 분류 LLM | [2026-04-17-counseling-type-llm-plan.md](plans/done/2026-04-17-counseling-type-llm-plan.md) |
| Assist Stream SSE | [2026-04-18-assist-stream-sse-design.md](plans/done/2026-04-18-assist-stream-sse-design.md) |
| Assist Snapshot | [2026-04-20-assist-snapshot-design.md](plans/done/2026-04-20-assist-snapshot-design.md) |
| 지식 패널 리디자인 | [2026-04-20-knowledge-panel-redesign-design.md](plans/done/2026-04-20-knowledge-panel-redesign-design.md) |
| STT Completeness Gate | [2026-04-20-stt-completeness-gate-design.md](plans/done/2026-04-20-stt-completeness-gate-design.md) |
| 백엔드 Phase 1 리팩토링 | [2026-04-21-backend-phase1-refactor-plan.md](plans/done/2026-04-21-backend-phase1-refactor-plan.md) |
| 전체 리팩토링 | [2026-04-22-full-refactor-plan.md](plans/done/2026-04-22-full-refactor-plan.md) |
| Chat 컴포넌트 리팩토링 | [2026-04-27-chat-index-refactor-plan.md](plans/done/2026-04-27-chat-index-refactor-plan.md) |
| 가상 스크롤 | [2026-05-08-virtual-scroll.md](plans/done/2026-05-08-virtual-scroll.md) |

---

## 문서 갱신 규칙

1. **현재 코드 상태가 신뢰원** — 코드와 문서가 다르면 코드를 따르고 문서를 수정
2. **소스 라인 참조 유지** — `[파일.ts:42](경로#L42)` 링크가 깨지지 않도록 코드 이동 시 함께 업데이트
3. **계획서 vs 인수인계 문서** — 계획서는 시점별 의사결정 기록, 인수인계 문서는 현재 상태 설명
4. **새 도메인/기능 추가 시** — `specs/domains-overview.md` 와 `api/conventions.md` 에 항목 추가

---

**문서 작성일**: 2026-05-15
**작성 기준 코드**: `main` 브랜치 현재 상태
**다음 갱신 권장 시점**: 백엔드 Phase 2 리팩토링 또는 KMS 외부 클라이언트 전환 완료 시
