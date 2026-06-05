# Board 이벤트 및 부수효과

> 참조: [05-async-event-architecture](../../02-architecture/05-async-event-architecture.md) · [02-module-architecture](../../02-architecture/02-module-architecture.md) · [rules.md](./rules.md)

---

## 1. 발행 이벤트

### 1.1 Important 티어 — BullMQ

게시판 권한 변경은 사용자의 접근 가능 게시판 캐시에 직접 영향을 주므로 BullMQ로 at-least-once 전달을 보장한다.

**큐 이름**: `board.events`

| 이벤트명 | 트리거 | BR | 소비자 |
|----------|--------|---|--------|
| `board.permissions_updated` | `PUT /admin/boards/:id/permissions` 처리 완료 시 — 기존 권한과 비교하여 실제 변경이 발생한 경우 | BR-BRD-012 | AuthModule (Redis 권한 캐시 무효화) |

#### 페이로드

```typescript
interface BoardPermissionsUpdatedPayload {
  schemaVersion: 1;
  boardId: string;
  changedRoles: {
    roleId: string;
    added: ('VIEW' | 'EDIT' | 'APPROVE')[];
    removed: ('VIEW' | 'EDIT' | 'APPROVE')[];
  }[];
  updatedBy: string;   // 변경한 관리자 UUID
  updatedAt: string;    // 변경 일시 (ISO 8601)
  traceId: string;
}
```

#### 재시도 정책

| 항목 | 값 |
|------|---|
| 최대 재시도 | 3회 |
| 백오프 | 지수 (5s → 10s → 20s) |
| DLQ | `board.events-dlq` |
| 멱등 키 | `board.permissions_updated:{boardId}` |
| 타임아웃 | 30초 |
| 동시 처리 수 | 설정값 (기본 3) |

> 멱등성 참고: 소비자(AuthModule)는 해당 Role 보유 사용자의 `cache:auth:accessible-boards:{user_id}:*` 캐시를 DEL하는 무효화 처리를 수행한다. 동일 이벤트가 중복 전달되어도 캐시 삭제는 멱등하다.

#### 보정 배치

이벤트 발행 실패(BullMQ enqueue 실패) 또는 재시도 소진 시 아래 보정이 적용된다.

| 단계 | 동작 |
|------|------|
| 1 | BullMQ 재시도 정책(최대 3회, 지수 백오프) 적용 |
| 2 | 재시도 소진 시 `board.events-dlq`로 이동, 운영 모니터링 지표(`board.events.dlq_count`) 증가 |
| 3 | 캐시 자연 갱신으로 최종 보정 — `cache:auth:accessible-boards` TTL 5분 만료 시 DB에서 재조회 |
| 4 | 관리자가 DLQ 관리 API(`GET /admin/dlq/board.events`)로 확인 후 `POST /admin/dlq/board.events/:jobId/retry`로 수동 재시도 |

### 1.2 Normal 티어 — EventBus

해당 없음.

> BoardModule은 EventBus를 사용하지 않는다. 게시판 권한 변경은 Important 티어로 분류되어 BullMQ를 통해 전달한다.

---

## 2. 소비 이벤트

BoardModule은 다른 모듈의 이벤트를 소비하지 않는다.

| 이벤트명 | 발행 모듈 | 처리 |
|----------|----------|------|
| -- | -- | -- |

> 게시판 트리 캐시(`cache:board:tree`)의 무효화는 BoardModule 자체의 CRUD 작업(생성/수정/삭제/이동) 시 서비스 레이어에서 직접 수행한다. 외부 이벤트에 의한 캐시 무효화는 없다.
