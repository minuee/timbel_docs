# aicm-service — Redis

> BullMQ 큐, 캐시, 편집 락, 세션, 카운터 버퍼

---

## 1. BullMQ 큐

비동기 작업 큐. 상세 큐 설계는 [05-async-event-architecture.md §6.1](../../05-async-event-architecture.md) 참조.

| Key 패턴 | 설명 |
|----------|------|
| `{tenant_id}:bull:parsing:*` | 문서 파싱 (parser-service 호출) |
| `{tenant_id}:bull:embedding:*` | 임베딩 생성/재생성 (retrieval-service 호출) |
| `{tenant_id}:bull:ai-summary:*` | AI 자동 요약 |
| `{tenant_id}:bull:notification:*` | 알림 발송 |
| `{tenant_id}:bull:scheduled-publish:*` | 예약 발행 |
| `{tenant_id}:bull:es-indexing:*` | Elasticsearch 인덱싱 |
| `{tenant_id}:bull:re-embedding:*` | ~~재임베딩~~ (deprecated → `embedding` priority=3) |
| `{tenant_id}:bull:board.events:*` | 게시판 이벤트 처리 |
| `{tenant_id}:bull:acl.events:*` | 권한 변경 이벤트 처리 |
| `{tenant_id}:bull:export:*` | 데이터 내보내기 |
| `{tenant_id}:bull:search-events:*` | 검색 이벤트 처리 |

---

## 2. 캐시

모든 캐시 키는 `cache:` 접두사를 사용한다. 변경 이벤트 수신 시 해당 키를 DEL하여 무효화한다.

### 2.1 인증/권한 캐시

| Key 패턴 | TTL | 설명 |
|----------|-----|------|
| `{tenant_id}:cache:auth:effective-roles:{user_id}` | 5m | 사용자의 유효 역할 (직접 + 팀 상속 합산) |
| `{tenant_id}:cache:auth:accessible-boards:{user_id}:{action}` | 5m | `getAccessibleBoardIds` 결과 (action: VIEW/EDIT/APPROVE) |
| `{tenant_id}:cache:auth:admin-permissions:{user_id}` | 5m | 사용자의 유효 AdminPermission 키 목록 |
| `{tenant_id}:cache:auth:org-ancestors:{user_id}` | 10m | 사용자의 상위 팀 계층 (UserServiceOrgProvider) |

### 2.2 게시판/콘텐츠 캐시

| Key 패턴 | TTL | 설명 |
|----------|-----|------|
| `{tenant_id}:cache:board:tree` | 1h | 게시판 트리 구조 캐시 |
| `{tenant_id}:cache:agg:{type}` | 1h | 인기/트렌딩/최신 문서 집계 |

### 2.3 시스템 설정 캐시

| Key 패턴 | TTL | 설명 |
|----------|-----|------|
| `{tenant_id}:cache:syscfg:{config_key}` | 1h | SystemConfig 설정값 읽기 캐시 — 변경 시 단일 키 DEL |

### 2.4 검색 캐시

| Key 패턴 | TTL | 설명 |
|----------|-----|------|
| `{tenant_id}:cache:search:config` | 30m | 동의어/불용어/부스팅 설정 |
| `{tenant_id}:cache:search:autocomplete:{prefix}` | 10m | 검색어 prefix 기반 자동완성 결과 |

---

## 3. 분산 락

동시 실행 방지용. 모든 락 키는 `lock:` 접두사를 사용한다.

### 3.1 문서 편집 락

| Key 패턴 | TTL | 설명 |
|----------|-----|------|
| `{tenant_id}:lock:doc:{document_id}` | 30m | 비관적 락킹 (heartbeat 갱신) |

### 3.2 배치 작업 분산 락

| Key 패턴 | TTL | 설명 |
|----------|-----|------|
| `{tenant_id}:lock:search:es-recon` | 10m | ES Reconciliation 배치 동시 실행 방지 (schedule.md §2.1) |
| `{tenant_id}:lock:search:log-archive` | 30m | SearchLog 아카이빙 배치 동시 실행 방지 (schedule.md §2.2) |
| `{tenant_id}:lock:ai:embedding-recon` | 5m | AI Embedding Reconciliation 동시 실행 방지 (ai-assistant/schedule.md §2.1) |
| `{tenant_id}:lock:ai:summary-recon` | 3m | AI Summary Reconciliation 동시 실행 방지 (ai-assistant/schedule.md §2.2) |
| `{tenant_id}:lock:ai:usage-archive` | 60m | AiUsageLog 아카이빙 동시 실행 방지 (ai-assistant/schedule.md §2.3) |
| `{tenant_id}:lock:ai:partial-timeout` | 2m | partial 상태 타임아웃 체크 동시 실행 방지 (ai-assistant/schedule.md §2.4) |

---

## 4. 카운터 / 버퍼

Redis 원자적 연산(INCR/DECR)으로 실시간 집계 후, 주기적으로 RDB에 flush한다.

| Key 패턴 | 자료구조 | TTL | 설명 |
|----------|---------|-----|------|
| `{tenant_id}:community:like_count:{documentId}` | String | — | 문서별 좋아요 수. DB 원천, 5분 주기 보정 |
| `{tenant_id}:community:comment_count:{documentId}` | String | — | 문서별 댓글 수. DB 원천, 5분 주기 보정 |
| `{tenant_id}:access:counts` | Hash | — | 문서별 조회수 원자적 집계. 10분 주기(@Cron)로 PG flush 후 HDEL |
| `{tenant_id}:access:dedup:{userId}:{documentId}` | String | 5m | 동일 사용자의 5분 이내 재조회 시 조회수 중복 카운트 방지 |

---

## 5. 스트림

Redis Streams를 사용한 이벤트 버퍼. Consumer Group으로 배치 소비한다.

| Key 패턴 | 자료구조 | 소비 주기 | 설명 |
|----------|---------|----------|------|
| `{tenant_id}:access:log:stream` | Stream | 5분 (@Cron) | 조회 이벤트 버퍼 → RDB `access_event_log` batch INSERT |

---

## 6. 세션

| Key 패턴 | TTL | 설명 |
|----------|-----|------|
| `session:{session_id}` | 설정값 | 사용자 세션 (온프렘 전용). 테넌트 구분은 세션 값 내부 `tenantId` 필드로 처리 |

> 유일하게 `{tenant_id}:` 프리픽스 없이 사용하는 키. 온프레미스 단일 테넌트에서도 동일 형식이며, SaaS에서는 ECP 세션을 사용하므로 이 키가 생성되지 않는다.

---

## 7. 상태 관리

서비스 운영 상태를 추적하는 키.

| Key 패턴 | TTL | 설명 |
|----------|-----|------|
| `{tenant_id}:circuit:{service_name}` | — | 외부 서비스 서킷브레이커 상태 공유 (document/events.md §3.3) |
| `{tenant_id}:stale-alert:{documentId}` | 7d | 드래프트 방치 알림 중복 방지 (document/schedule.md §2.8) |

---

## 8. 테넌트 격리 원칙

Redis는 단일 인스턴스를 공유하며 키 프리픽스(`{tenant_id}:`)로 테넌트 데이터를 격리한다. BullMQ 큐도 동일하게 키 프리픽스로 구분한다. 온프레미스 배포에서는 단일 테넌트이므로 프리픽스가 고정값이 된다.

> `session:{session_id}` 키만 예외적으로 테넌트 프리픽스 없이 사용한다 — 세션은 온프레미스 단일 테넌트에서도 동일 형식이며, 테넌트 구분은 세션 값 내부의 `tenantId` 필드로 처리한다.

---

**관련 문서**
- [전체 개요 (멀티테넌트 격리)](../README.md)
- [비동기 처리 아키텍처](../../05-async-event-architecture.md) — BullMQ 큐 설계 상세
