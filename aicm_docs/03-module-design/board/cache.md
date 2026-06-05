# Board 캐시 전략

> 참조: [08-cache-architecture](../../02-architecture/08-cache-architecture.md) · [data/aicm/redis.md](../../02-architecture/data/aicm/redis.md) · [events.md](./events.md) · [rules.md](./rules.md)

---

## 1. 캐시 개요

| # | 캐시 대상 | 전략 | TTL | 무효화 |
|---|----------|------|-----|--------|
| 1 | 게시판 트리 구조 | cache-aside | 1시간 | 게시판 CRUD 시 직접 삭제 + TTL 자연 만료 |

> 게시판 트리는 사이드바 네비게이션에서 반복 조회되므로 캐시를 적용한다. 권한 필터링(BR-BRD-001)은 캐시된 트리에 대해 애플리케이션 레벨에서 수행하는 것이 아니라, 사용자별 권한 평가 후 필터링된 결과를 반환하는 방식이다. 트리 캐시 자체는 전체 활성 게시판의 계층 구조를 저장한다.

---

## 2. 캐시 상세

### 2.1 게시판 트리 구조 캐시

#### 기본 정보

| 항목 | 값 |
|------|---|
| 전략 | cache-aside |
| 키 패턴 | `{tenant_id}:cache:board:tree` |
| TTL | 3600초 (1시간) |
| 직렬화 | JSON (Board 트리 배열 — id, name, slug, parent_id, board_type, is_active, sort_order, depth) |

> `GET /boards/tree` 요청 시 Redis에서 캐시를 조회한다. 캐시 미스이면 DB에서 `is_active = true`이고 `deleted_at IS NULL`인 게시판 전체를 조회하여 트리 구조로 조립한 뒤 캐시에 저장한다.

#### 무효화

| 트리거 | BR | 동작 |
|--------|---|------|
| 게시판 생성 (`POST /admin/boards`) | BR-BRD-003, BR-BRD-004, BR-BRD-005 | 서비스 레이어에서 캐시 키 DEL |
| 게시판 수정 (`PUT /admin/boards/:id`) | BR-BRD-006, BR-BRD-013 | 서비스 레이어에서 캐시 키 DEL |
| 게시판 이동 (`PATCH /admin/boards/:id/move`) | BR-BRD-004, BR-BRD-009 | 서비스 레이어에서 캐시 키 DEL |
| 게시판 삭제 (`DELETE /admin/boards/:id`) | BR-BRD-007, BR-BRD-008 | 서비스 레이어에서 캐시 키 DEL |
| TTL 만료 (1시간) | — | 자연 만료 — 이벤트 무효화 누락 시 fallback |

> 게시판 트리 캐시의 무효화는 BoardModule 자체의 CRUD 작업에서 서비스 레이어가 직접 수행한다. 외부 이벤트에 의한 캐시 무효화는 없다 ([events.md §2](./events.md) 참조).

> `board.permissions_updated` 이벤트는 AuthModule의 `cache:auth:accessible-boards` 캐시를 무효화하는 용도이며, 게시판 트리 캐시와는 무관하다. 권한 변경은 트리 구조 자체를 변경하지 않기 때문이다.

#### Warm-up / Fallback

| 항목 | 값 |
|------|---|
| Warm-up | lazy-load (최초 `GET /boards/tree` 요청 시 DB 조회 후 캐싱) |
| Fallback | DB 직접 조회 — Redis 장애 시 캐시를 스킵하고 DB에서 트리 조회 |

---

## 3. 키 패턴 요약

| 키 패턴 | 원천 문서 | 일치 확인 |
|---------|----------|----------|
| `{tenant_id}:cache:board:tree` | [redis.md §2.2](../../02-architecture/data/aicm/redis.md) | 일치 |

### 캐시 미적용 구간

| 구간 | 사유 |
|------|------|
| 사용자별 권한 필터링 결과 | 사용자별 접근 가능 게시판 ID는 AuthModule의 `cache:auth:accessible-boards:{user_id}:{action}` 캐시가 담당 (auth/cache.md 참조) |
| 게시판 상세 (단건 조회) | 관리자 전용 API이며 호출 빈도가 낮아 캐시 이점 미미 |
