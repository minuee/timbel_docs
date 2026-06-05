# aicm-service — 데이터 아키텍처

> NestJS 모듈러 모놀리스 기반 메인 서비스. PostgreSQL, Elasticsearch, Redis, MinIO를 소유한다.

---

## 인프라 소유 현황

| 인프라 | 역할 | 문서 |
|--------|------|------|
| PostgreSQL | 원천 데이터, 트랜잭션, 관계 (Database-per-tenant) | [rdb.md](./rdb.md) — 전체 ERD 및 공통 설계 원칙 |
| Elasticsearch `aicm_blocks` | BM25 키워드 검색 (블록 단위, 문서 검색용) | [es.md](./es.md) |
| PostgreSQL `access_event_log` | 접근 이벤트 로그 원장 (RDB 파티셔닝 + Materialized View 집계) | [rdb.md](./rdb.md) §5 |
| Redis | BullMQ 큐, 캐시, 편집 락, 세션, 카운터 버퍼, 검색 설정 캐시 | [redis.md](./redis.md) |
| MinIO | 파일 스토리지 (이미지, 첨부파일, 내보내기, 원본 문서) | [minio.md](./minio.md) |
| BullMQ 큐 | 비동기 작업 큐 채널 목록, DLQ 매핑, 생산/소비 관계 | [05-async-event-architecture.md](../../05-async-event-architecture.md) |

## 모듈별 RDB 엔티티 상세

모듈별 엔티티 필드, DDL, 인덱스는 각 모듈 설계 폴더의 `data.md`를 참조한다.

| 모듈 | 데이터 모델 |
|------|-----------|
| DocumentModule | [document/data.md](../../../03-module-design/document/data.md) |
| ApprovalModule | [approval/data.md](../../../03-module-design/approval/data.md) |
| AuthModule | [auth/data.md](../../../03-module-design/auth/data.md) |
| BoardModule | [board/data.md](../../../03-module-design/board/data.md) |
| CommunityModule | [community/data.md](../../../03-module-design/community/data.md) |
| TemplateModule | [template/data.md](../../../03-module-design/template/data.md) |
| SharedContentModule | [shared-content/data.md](../../../03-module-design/shared-content/data.md) |
| NotificationModule | [notification/data.md](../../../03-module-design/notification/data.md) |
| AggregationModule | [aggregation/data.md](../../../03-module-design/aggregation/data.md) |
| AI AssistantModule | [ai-assistant/data.md](../../../03-module-design/ai-assistant/data.md) |
| LogEventModule | [log-event/data.md](../../../03-module-design/log-event/data.md) |
| SearchModule | [search/data.md](../../../03-module-design/search/data.md) |
| SystemConfigModule | [system-config/data.md](../../../03-module-design/system-config/data.md) |

---

**관련 문서**
- [데이터 아키텍처 전체 개요](../README.md) — 크로스 서비스 데이터 흐름, 멀티테넌트 격리
- [retrieval-service](../retriever/README.md) — Milvus/ES(aicm_chunks) 소유
- [parser-service](../parser/README.md) — Stateless, MinIO 읽기 전용
