# AICM 시스템 아키텍처

AICM은 AI 기반 지식 관리 시스템(KMS)으로, NestJS 기반 모듈러 모놀리스 아키텍처를 채택한다. 이 폴더는 시스템 아키텍처 설계 문서를 관리한다.

---

## 시스템 레벨 설계

| 문서 | 설명 | 상태 | 검수 | 최종 수정 |
|------|------|------|------|----------|
| [system-overview](./01-system-overview.md) | 설계 원칙, 기술 결정, C4 다이어그램(Level 1/2), 시스템 토폴로지, 배포 환경 | `complete` | `unreviewed` | 2026-03-23 |
| [module-architecture](./02-module-architecture.md) | NestJS 모듈 분류, 의존성 규칙, Provider 패턴, 디렉토리 구조 | `draft` | `reviewed` | 2026-04-13 |
| [data-architecture](./data/README.md) | 서비스별 데이터 아키텍처 (aicm/rag/parser), 멀티테넌트, 데이터 흐름 | `draft` | `reviewed` | 2026-03-19 |
| [auth-architecture](./03-auth-architecture.md) | 인증 흐름, 3계층 권한 모델, 권한 평가 로직, 검색 권한 필터 | `draft` | `unreviewed` | 2026-04-13 |
| [permission-architecture](./04-permission-architecture.md) | 자원 분류(문서/관리/개인), 유효 역할·권한 합산, AdminPermission 카탈로그, 권한 평가 흐름 | `draft` | `unreviewed` | 2026-03-27 |
| [async-event-architecture](./05-async-event-architecture.md) | BullMQ 큐, 임베딩 파이프라인, 예약 배포, 이벤트 흐름 | `draft` | `unreviewed` | 2026-04-13 |
| [external-integration](./06-external-integration/README.md) | LLM Orchestrator, parser-service, retrieval-service, Langfuse 연동 | `draft` | `unreviewed` | 2026-03-17 |
| [cross-cutting-concerns](./07-cross-cutting-concerns.md) | 감사 로그, 에러 핸들링, 로깅/모니터링, API 설계 규칙 | `draft` | `unreviewed` | 2026-03-17 |
| [cache-architecture](./08-cache-architecture.md) | Redis 캐시 정책, TTL, 무효화 트리거, 모듈별 캐시 사용처 총괄 | `draft` | `unreviewed` | 2026-04-13 |
| [resilience-strategy](./09-resilience-strategy.md) | 서비스 간 통신 복원력 전략 — 타임아웃, 재시도, 서킷 브레이커, DLQ, Fallback 패턴 총괄 | `draft` | `unreviewed` | 2026-04-08 |

## 유즈케이스 흐름

| 문서 | 설명 | 상태 | 검수 |
|------|------|------|------|
| [search-rag](../01-requirements/flows/search-rag/README.md) | 검색/RAG 파이프라인 — 파싱·청킹·임베딩·검색 엔드투엔드 흐름, 검색 튜닝 | `draft` | `unreviewed` |

---

## 참조 문서

| 문서 | 위치 | 설명 |
|------|------|------|
| 모듈별 상세 설계 | [docs/03-module-design/](../03-module-design/) | 모듈 단위 API 스펙, 비즈니스 규칙, 이벤트/큐 연동 상세 |
| AICM 기능정의서 | (레거시 — 정규 기능정의서는 [features/](../01-requirements/features/) 참조) | 기능 요구사항 정의 |
| 레거시 시스템 개요 | (아카이브 문서 제거됨) | FastAPI 기반 기존 시스템 참고 문서는 저장소 외부 아카이브에서 관리 |
| 레거시 RAG 가이드 | (아카이브 문서 제거됨) | 기존 청킹/임베딩 가이드는 저장소 외부 아카이브에서 관리 |

## 상태 정의

| 값 | 의미 |
|----|------|
| `complete` | 해당 문서 범위의 내용이 모두 작성됨 |
| `draft` | 내용이 있으나 미비 사항이 존재. 문서 상단 TODO 체크리스트 참조 |
| `미착수` | 아직 작성되지 않음. 빈 껍데기 파일만 존재 |
| `unreviewed` | 검수(리뷰)를 거치지 않음 |
| `reviewed` | 검수 완료 |
