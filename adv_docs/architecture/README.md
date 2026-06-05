# Architecture

상담 어드바이저 시스템/컴포넌트 아키텍처 문서입니다.

## 핵심 문서

| 문서 | 주제 |
|------|------|
| [00-overview.md](00-overview.md) | Advisor 전체 아키텍처 + 외부 서비스 맵 + 모노레포 구조 |
| [aicc-system-context.md](aicc-system-context.md) | **AICC 전체 시스템 컨텍스트** (drawio 다이어그램 17페이지 가이드) |
| [01-multi-tenant-db.md](01-multi-tenant-db.md) | 테넌트별 동적 DB 연결 (`AuthMiddleware`/`DynamicDatabaseService`) |
| [02-realtime-streaming.md](02-realtime-streaming.md) | Redis Pub/Sub → Socket.IO + HTTP SSE 3종 스트리밍 |
| [03-frontend.md](03-frontend.md) | Vue 3 + Pinia + 모듈 페더레이션 + 핵심 컴포저블 |
| [04-data-model.md](04-data-model.md) | ERD 요약 (advisor + raw_call 스키마), 테이블 ↔ 엔티티 매핑 |
| [05-backend.md](05-backend.md) | NestJS 모듈 구조, 요청 파이프라인, **BFF 선택 배경/트레이드오프** |

## 다이어그램

| 위치 | 내용 |
|------|------|
| [diagrams/](diagrams/) | 다이어그램 원본 보관 (drawio + SVG) |
| [diagrams/aicc-architecture.drawio](diagrams/aicc-architecture.drawio) | AICC 전체 시스템 (Tenant, Call Gateway, Advisor, QA, TA, KMS, LLM Orchestrator 등 C4 모델) |
| [diagrams/advisor-4service-architecture.svg](diagrams/advisor-4service-architecture.svg) | Advisor ↔ auth/user/tenant-mgmt 4서비스 구조 (→ [01-multi-tenant-db.md](01-multi-tenant-db.md) 에 임베드) |
| [diagrams/advisor-runtime-sequence.svg](diagrams/advisor-runtime-sequence.svg) | 런타임 요청 시퀀스 (asst→user→auth, 캐시 최적화) |

처음 합류한 분은 **00-overview.md → aicc-system-context.md** 순서로 읽으세요.
