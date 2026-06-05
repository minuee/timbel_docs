# SystemConfig 이벤트 및 부수효과

> 참조: [05-async-event-architecture](../../02-architecture/05-async-event-architecture.md) · [02-module-architecture](../../02-architecture/02-module-architecture.md) · [rules.md](./rules.md)

---

## 1. 발행 이벤트

### 1.1 Best-effort 티어 — EventBus

SystemConfigModule은 BullMQ 큐를 사용하지 않으며, 모든 이벤트를 EventBus(Best-effort)로 발행한다. 전달 보장은 Best-effort이며, BR-SYS-002의 재시도·TTL 폴백으로 운영 품질을 보강한다.

#### system_config.changed

| 항목 | 값 |
|------|---|
| 티어 | Best-effort |
| 채널 | EventBus (NestJS EventEmitter) |
| 트리거 | 설정 변경 시 DB 커밋 완료 (BR-SYS-002, BR-SYS-010) |
| 전달 보장 | Best-effort — DB 트랜잭션 커밋 성공 후 동일 요청 흐름에서 EventBus 발행 시도 (원자성은 DB 커밋과 이벤트 발행 간 보장하지 않음) |

**페이로드**:

```typescript
interface SystemConfigChangedPayload {
  config_key: string;    // 변경된 설정 키
  category: string;      // 설정 카테고리
  before: unknown;       // 변경 전 값
  after: unknown;        // 변경 후 값
  changed_by: string;    // 변경한 관리자 UUID
  changed_at: string;    // 변경 일시 (ISO 8601)
}
```

**소비자**:

| 소비자 모듈 | 처리 | 비고 |
|------------|------|------|
| DocumentModule | 문서 관련 설정(`lm:document.*`) 캐시 무효화 | 해당 config_key의 Redis 캐시 DEL |
| SearchModule | 검색 관련 설정 캐시 무효화 (SystemConfig 범위에 한함) | SearchConfig 전용 설정은 별도 관리 |
| AI AssistantModule | 임베딩 파이프라인 관련 설정(`lm:embedding.*`) 캐시 무효화 | 임베딩 파이프라인 트리거 관리 담당 모듈 |
| AggregationModule | 인기/트렌딩 가중치 설정(`pm:aggregation.*`, `lm:aggregation.*`) 캐시 무효화 | — |
| LogEventModule | 감사 로그 비동기 기록 — `actor`, `action(system_config.update)`, `config_key`, `before`/`after`, `timestamp` | BR-SYS-010 |

#### 이벤트 발행 실패 시 폴백 정책

| 단계 | 동작 |
|------|------|
| 1 | 설정 변경 DB 커밋 완료 |
| 2 | EventBus로 `system_config.changed` 발행 시도 |
| 3 | 실패 시 최대 3회 재시도 (지수 백오프, 초기 지연 500ms) |
| 4 | 재시도 소진 시: 캐시는 TTL 만료(1시간)로 자연 갱신 (fallback), 운영 모니터링 지표(`sys.event_publish_failure_count`) 증가, 운영 관리자 알림 발송 |

> **실패를 어떻게 아는가**: EventBus는 인프로세스(NestJS EventEmitter)이므로, **발행 코드**에서 `emit`(또는 Nest가 제공하는 발행 API) 호출을 감쌀 때 **동기 예외**가 나면 그 시점이 곧 발행 실패다(try/catch로 포착). 비동기 리스너가 나중에 실패하는 경우는 “발행”이 아니라 **소비 측 처리 실패**로 보고, BR-SYS-002의 재시도·지표는 **발행 호출이 끝까지 성공하지 못한 경우**에 적용한다. 메트릭·알림은 그 catch/rejection 지점에서 올린다.

---

## 2. 소비 이벤트

SystemConfigModule은 다른 모듈의 이벤트를 소비하지 않는다. 독립 모듈로서 자체 이벤트만 발행한다.

| 이벤트명 | 발행 모듈 | 처리 |
|----------|----------|------|
| — | — | — |
