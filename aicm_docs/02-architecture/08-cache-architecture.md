> **문서 상태**
> | 항목 | 값 |
> |------|-----|
> | 상태 | `draft` |
> | 검수 | `unreviewed` |
> | 작성일 | 2026-04-13 |
> | 최종 수정 | 2026-04-13 |
>
> **미비 사항**
> - [ ] 모듈별 `cache.md`와 키/TTL 완전 동기화 (우선순위: auth, aggregation, search)

# 캐시 아키텍처

> Redis 캐시 정책, 무효화 트리거, 모듈별 사용처를 총괄하는 기준 문서

---

## 1. 범위와 목적

이 문서는 AICM의 캐시 설계를 모듈 단위로 분산된 문서에서 통합해, 아래 항목을 단일 기준으로 제공한다.

- 어떤 데이터를 캐시하는지 (원천 데이터/읽기 경로)
- 얼마나 유지하는지 (TTL)
- 언제 무효화하는지 (이벤트/수동/배치)
- 장애 시 어떻게 동작하는지 (stale 허용 여부, fallback)

> 상세 키 패턴은 [data/aicm/redis.md](./data/aicm/redis.md), 비동기 전달 채널은 [05-async-event-architecture.md](./05-async-event-architecture.md), 모듈 책임은 [02-module-architecture.md](./02-module-architecture.md)를 원천으로 한다.

---

## 2. 공통 설계 원칙

| 원칙 | 설명 |
|---|---|
| 원천 우선 | 캐시는 정답 저장소가 아니라 성능 계층이다. 정합성 기준은 항상 RDB/원천 서비스다. |
| 이벤트 우선 무효화 | TTL 만료만 기다리지 않고, 상태 변경 이벤트 수신 시 즉시 무효화한다. |
| 테넌트 격리 | Redis는 `{tenant_id}:` 프리픽스로 격리한다. |
| 짧은 TTL + 명시적 무효화 | 권한/피드 등 변동성이 큰 데이터는 짧은 TTL(5~60분)과 이벤트 무효화를 병행한다. |
| 장애 시 기능 축소 | 캐시 장애는 전체 서비스 중단이 아니라 기능 축소/지연으로 흡수한다. |

---

## 3. 캐시 계층 분류

| 분류 | 예시 키 | 기본 TTL | 특성 |
|---|---|---:|---|
| 권한 평가 캐시 | `cache:auth:effective-roles:*` | 5분 | 변경 빈도 높음, 즉시 무효화 필요 |
| 조직 계층 캐시 | `cache:auth:org-ancestors:*` | 10분 | 외부/계층 조회 비용 완화 |
| 집계/피드 캐시 | `cache:agg:*` | 1시간 | 배치 재계산 + 이벤트 무효화 |
| 설정 읽기 캐시 | `cache:syscfg:*`, `cache:search:config` | 30분~1시간 | 설정 변경 이벤트로 즉시 삭제 |
| 검색 보조 캐시 | `cache:search:autocomplete:*` | 10분 | 읽기 집중, 사용자 체감 응답 개선 |
| 편집/운영 제어 키 | `lock:*`, `stale-alert:*` | 2분~30분 | 분산 락/중복 방지 용도 |

---

## 4. 모듈별 캐시 사용처

| 모듈 | 주요 캐시 키 | TTL | 무효화 트리거 |
|---|---|---:|---|
| AuthModule | `cache:auth:effective-roles:{user_id}`, `cache:auth:accessible-boards:{user_id}:{action}` | 5분 | `acl.events` 계열 이벤트, 역할/팀/멤버 변경 |
| AuthModule (OrgProvider) | `cache:auth:org-ancestors:{user_id}` | 10분 | 팀 계층 변경, 팀 멤버 변경 |
| BoardModule | `cache:board:tree` | 1시간 | 게시판 트리 변경, `board.permissions_updated` |
| AggregationModule | `cache:agg:{type}` | 1시간 | `document.*`, `system_config.changed`, 관리자 수동 새로고침 |
| SearchModule | `cache:search:config`, `cache:search:autocomplete:{prefix}` | 30분 / 10분 | 검색 설정 변경, 인덱스 재구성 이벤트 |
| SystemConfigModule | `cache:syscfg:{config_key}` | 1시간 | `system_config.changed` |
| Document/LogEvent | `access:dedup:*`, `access:counts`, `access:log:stream` | 5분 / 없음 / 없음 | 주기 배치 flush(`@Cron`), Stream 소비 |

> `access:*` 계열은 조회수/접근 로그 버퍼를 포함하므로 순수 캐시뿐 아니라 "쓰기 완충 버퍼" 역할도 수행한다.

---

## 5. 표준 무효화 이벤트 카탈로그

캐시 무효화에 직접 영향을 주는 주요 이벤트를 아래로 정렬한다.

| 채널 | 이벤트 | 주 용도 |
|---|---|---|
| `acl.events` | `acl.role.permissions_updated`, `acl.role.status_changed`, `acl.team.members_updated`, `acl.team.status_changed`, `acl.user_role.updated`, `acl.board_permission.updated`, `acl.restriction.updated` | 권한/조직 캐시 무효화, 검색 가시성 재평가 |
| `board.events` | `board.permissions_updated` | 게시판 트리/접근 캐시 무효화 |
| EventBus | `document.published`, `document.deleted`, `document.expired` | 집계 캐시 무효화 |
| EventBus | `system_config.changed` | 설정 캐시 무효화, 설정 의존 캐시 재계산 트리거 |

---

## 6. 큐와 캐시의 경계

- `embedding` 큐는 문서 최초 임베딩과 재임베딩을 함께 처리한다.
- 과거의 `re-embedding` 별도 큐는 폐기하고, `embedding` 큐 내부 우선순위로 통합한다.
- 캐시 무효화 이벤트(`acl.events`, `board.events`)는 BullMQ 큐로 전달되어 대량 변경 시에도 서비스 응답 경로를 차단하지 않는다.

---

## 7. 장애 대응 원칙

| 장애 유형 | 대응 |
|---|---|
| Redis 부분 장애 | 캐시 미스 허용 + 원천 조회 fallback |
| 집계 캐시 조회 실패 | stale 캐시 반환 또는 빈 응답 + `AGG_CACHE_UNAVAILABLE` |
| 대량 무효화 지연 | 즉시 응답 후 백그라운드 일괄 무효화 및 재계산 |
| 이벤트 소비 실패 | DLQ 적재 후 운영자 재처리 (`*-dlq`) |

---

## 8. 운영 지표

| 지표 | 임계값(기본) | 목적 |
|---|---:|---|
| 캐시 히트율 | 모듈별 목표 관리 | DB 부하 저감 |
| `acl.events` 대기 건수 | 100건 초과 경보 | 권한 반영 지연 감지 |
| DLQ 적재 건수 | 10건 초과 경보 | 무효화 누락/지연 조기 탐지 |
| 캐시 무효화 후 반영 지연 | p95 모니터링 | 권한/피드 일관성 보장 |

---

## 관련 문서

- [모듈 아키텍처](./02-module-architecture.md)
- [인증/인가 아키텍처](./03-auth-architecture.md)
- [비동기 처리 아키텍처](./05-async-event-architecture.md)
- [횡단 관심사](./07-cross-cutting-concerns.md)
- [aicm-service Redis](./data/aicm/redis.md)
