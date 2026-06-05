# SystemConfig 캐시 전략

> 참조: [data/aicm/redis.md](../../02-architecture/data/aicm/redis.md) · [08-cache-architecture](../../02-architecture/08-cache-architecture.md) · [events.md](./events.md) · [rules.md](./rules.md)

---

## 1. 캐시 개요

| 캐시 대상 | 전략 | 키 패턴 | TTL | 무효화 트리거 |
|-----------|------|---------|----:|-------------|
| 설정값 읽기 캐시 | cache-aside | `{tenant_id}:cache:syscfg:{config_key}` | 1시간 | `system_config.changed` 이벤트 |

---

## 2. 캐시 상세

### 2.1 설정값 읽기 캐시

#### 기본 정보

| 항목 | 값 |
|------|---|
| 전략 | cache-aside |
| 키 패턴 | `{tenant_id}:cache:syscfg:{config_key}` |
| TTL | 1시간 (3600초) |
| 직렬화 | JSON |

> 각 모듈은 자주 참조하는 설정값을 이 캐시를 통해 읽는다. 캐시 미스 시 DB에서 조회하여 캐시에 저장한다.

#### 무효화

| 트리거 | 동작 | BR |
|--------|------|---|
| `system_config.changed` 이벤트 수신 | 해당 `config_key`의 Redis 캐시 키 DEL | BR-SYS-002 |
| TTL 만료 (1시간) | 자연 만료 — 이벤트 발행 실패 시의 fallback | BR-SYS-002 |

> 다중 인스턴스 환경에서는 이벤트 버스(Redis pub/sub)를 통해 모든 인스턴스에 무효화가 전파된다.

#### Warm-up / Fallback

| 항목 | 값 |
|------|---|
| Warm-up | lazy-load (최초 조회 시 캐시 적재) |
| Fallback | DB 직접 조회 — Redis 장애 시에도 설정 조회 가능 |

---

## 3. 키 패턴 요약

| 키 패턴 | 원천 문서 | 일치 확인 |
|---------|----------|----------|
| `{tenant_id}:cache:syscfg:{config_key}` | [redis.md §2.3](../../02-architecture/data/aicm/redis.md) | 일치 |

---

## 4. 성능 목표

| 항목 | 목표 |
|------|------|
| 설정 조회 (캐시 hit) | < 5ms |
| 설정 조회 (DB fallback) | < 50ms |
| 이벤트 전파 지연 | < 500ms (이벤트 발행 → 캐시 무효화 완료) |
