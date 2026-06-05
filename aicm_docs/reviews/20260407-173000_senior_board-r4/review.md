> **문서 유형**: 모듈 스펙
> **종합 점수**: 89 / 100 (공용 89 × 0.6 + 전문 90 × 0.4)
> **리뷰 대상**: `docs/03-module-design/board/` (README.md, data.md, api.md, rules.md)
> **페르소나**: 최민재 — 시니어 백엔드 개발자 (AI)
> **리뷰일**: 2026-04-07 17:30
> **리뷰 라운드**: Round 4 (이전: Round 3 = 86점)
> **지적사항**: P1: 0건, P2: 2건, P3: 3건
> **자동 반영 가능**: 3건 / 설계 결정 필요: 2건

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-MS-01 | API 설계 품질 | 90 | 30% | RESTful 관례·DTO 일관성·에러 카탈로그 견고. OCC·boardConfig deep-merge 시맨틱까지 명세 |
| RD-MS-02 | 구현 변환 용이성 | 88 | 10% | TypeScript DTO + DDL + CTE 패턴 + 상속 의사코드 — 주니어도 즉시 구현 가능 수준 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 90 | 25% | 멱등성 키·DLQ·보정 배치·Outbox Phase 2 로드맵 모두 견고. R4에서 updatedBy required·affectedBoardIds 대칭 해결 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 90 | 15% | Layer 1 독립 원칙 준수. Controller 오케스트레이션 패턴으로 Board↔Doc 경계 깔끔 |
| RD-MS-05 | 모듈 간 계약 명확성 | 88 | 10% | BoardExportService 8메서드 명확. 소비 모듈 매핑·getBoardConfig 활용처 기술됨 |
| RD-MS-06 | 운영 고려사항 | 88 | 10% | 트리 깊이·동시성·Redis 폴백·메트릭 5종·감사 로그 7종 모두 포함 |
| | **공용 소계** | **89** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-MS-SR-01 | API↔데이터 모델 구현 정합성 | 90 | 50% | DTO↔DDL 필드 매핑 일관. board_config.notice 적용 범위가 data.md·rules.md·api.md 3곳 정합 |
| EX-MS-SR-02 | 이벤트 설계 정합성 | 90 | 50% | 이벤트 페이로드↔DB 변경사항 대응 정확. R4 대칭 수정(restored.affectedBoardIds, updated.updatedBy) 완료 |
| | **전문 소계** | **90** | 100% | |

### 종합: 89 / 100 (공용 89 × 0.6 + 전문 90 × 0.4)

**Round 3(86) → Round 4(89): +3점 상승**

---

## 차원별 상세 피드백

### 공용 차원

#### RD-MS-01. API 설계 품질 — 90/100 우수

api.md의 전체 설계 품질이 높다. 11개 엔드포인트가 일관된 패턴을 따르며, 에러 코드 카탈로그가 rules.md와 양방향 참조로 연결되어 있다. 특히 `BoardResponse`가 DB 원본(`approvalRequired: boolean | null`)과 상속 해석 후 유효값(`effectiveApprovalRequired: boolean`)을 동시에 노출하면서, 목록·트리 DTO에서는 유효값만 노출하는 설계는 실무적으로 견고하다.

`UpdateBoardDto.boardConfig`의 "최상위 키 단위 deep-merge" 시맨틱이 명시되어 있고, `expectedUpdatedAt` 기반 OCC가 선택적(미전달 시 skip)으로 설계된 점도 관리자 도구의 실용성을 잘 반영했다.

`PATCH /boards/:id` 오케스트레이션 시퀀스 다이어그램이 BR-BRD-006 검증 흐름을 시각적으로 보여주어, 복잡한 Controller 조율 로직을 구현자가 파악하기 쉽다.

한 가지 아쉬운 점은, `GET /boards`의 오프셋 페이지네이션이 프로젝트 표준(커서 기반)의 의식적 예외임을 명시한 것은 좋으나, `GET /boards/tree`에는 페이지네이션 자체가 없다. 테넌트당 100개 이하 운영 가정하에 문제없지만, 규모 확장 시 트리 응답 크기에 대한 가이드라인이 있으면 더 좋겠다.

#### RD-MS-02. 구현 변환 용이성 — 88/100 우수

주니어 개발자가 이 문서만으로 코드를 짤 수 있는 수준이다. TypeScript DTO 인터페이스, 완전한 DDL, CTE 쿼리 패턴(descendants, 재귀 소프트 삭제), 상속 체인 의사코드(`isApprovalRequired`, `getMandatoryApprovalConfig`)가 모두 갖추어져 있다.

`board_config` 접근 패턴의 `getCommentConfig` 예시가 merge 동작을 코드 수준으로 보여주어, JSONB 기본값 병합 구현에 대한 혼동을 방지한다. `board_type`별 초기 설정 시드(BR-BRD-005)도 타입별 기본값이 표로 정리되어 있어 분기 로직 구현이 명확하다.

#### RD-MS-03. 이벤트/비동기 설계 건전성 — 90/100 우수

Round 4에서 해결된 두 가지 사항이 이벤트 설계의 건전성을 한 단계 올렸다:

1. **`BoardUpdatedPayload.updatedBy` required 전환**: 감사 추적 관점에서 "누가 변경했는지"는 필수 정보이므로 optional이었던 것이 설계 결함이었다. 이번에 바로잡았다.
2. **`BoardRestoredPayload.affectedBoardIds` required 전환**: `board.deleted`와 대칭으로 맞춘 것은 소비자 입장에서 일관된 처리 로직을 보장한다. 단일 노드 복구 시에도 1건 배열로 담는다는 명시가 좋다.

`BoardEventEnvelope`의 공통 래퍼 설계(eventType, occurredAt, tenantId, boardId, idempotencyKey, schemaVersion)가 프로덕션 수준이다. 멱등성 키 형식도 이벤트 유형별로 구체적으로 제시되어 있다.

보정 배치 패턴(5분 주기, 워터마크 스캔)과 Phase 2 Outbox 로드맵이 명시되어 있어 운영 안정성 계획이 명확하다.

남은 개선점은, `board.moved`와 `board.toggled`가 감사 로그에서는 별도 action으로 존재하지만(README.md 감사 로그 대상), BullMQ 이벤트에서는 `board.updated`로 통합된다는 매핑이 api.md 이벤트 섹션에 명시되어 있지 않다는 점이다.

#### RD-MS-04. 모듈 책임 범위 적절성 — 90/100 우수

BoardModule의 Layer 1 독립 원칙이 일관되게 관철되어 있다. "BoardService는 다른 도메인 모듈에 대한 DI 의존이 없다"는 원칙이 README, api.md, rules.md 전체에서 흔들리지 않는다. pending_review 검사가 Controller 오케스트레이션으로 해결된 패턴은 모듈 경계를 깨지 않으면서도 비즈니스 요구를 충족한다.

문서 가시성 처리를 DocumentModule에 위임한 결정("게시판 소프트 삭제 시 소속 문서의 가시성 처리는 BoardModule이 관여하지 않는다")도 적절한 관심사 분리이다.

#### RD-MS-05. 모듈 간 계약 명확성 — 88/100 우수

`BoardExportService` 인터페이스 8개 메서드가 소비 모듈의 실제 사용 패턴을 잘 반영한다. `getMandatoryApprovalConfig`의 상속 체인 해석 로직이 의사코드로 명시되어 있어, approval 모듈이 이 계약을 호출할 때 null 반환의 의미를 정확히 이해할 수 있다.

`getBoardConfig` 소비 모듈 테이블(Document, Approval, Community)이 모듈별 주요 용도와 함께 나열되어 있는 것도 좋다.

다만 `findById`가 soft-deleted 게시판을 반환하는지 여부가 인터페이스 JSDoc만으로는 불명확하다. DocumentModule이 `board.deleted_at`을 확인해 필터링하려면 `findById`는 soft-deleted 게시판도 반환해야 하는데 이 동작이 명시되어 있지 않다.

#### RD-MS-06. 운영 고려사항 — 88/100 우수

운영 가이드 섹션이 충실하다. 트리 깊이(10/20), 동시성 제어(OCC, CTE 원자성, FK 자연 방어), Redis 폴백(트리 캐시·BullMQ), 이벤트 보정 배치, 감사 로그 7종, 메트릭 5종 모두 포함되어 있다.

`board.events.dlq_count > 0이면 WARN 알림` 같은 구체적 알림 임계값까지 정의한 것은 운영 첫날부터 모니터링을 설정할 수 있게 해준다.

---

### 전문 차원

#### EX-MS-SR-01. API↔데이터 모델 구현 정합성 — 90/100 우수

시니어 백엔드 개발자 관점에서 DTO↔엔티티 매핑을 대조했을 때 일관성이 높다:

- `CreateBoardDto` → `Board` 엔티티: 모든 필드가 1:1 대응되며, `boardType`(camelCase) → `board_type`(snake_case) 변환은 NestJS 표준 패턴이다.
- `BoardResponse`의 dual field 패턴(`approvalRequired` 원본 + `effectiveApprovalRequired` 유효값)이 DB 저장과 비즈니스 로직을 모두 표현한다.
- DDL 제약조건(`chk_root_approval_required`, `chk_root_versioning_enabled`)이 rules.md의 BR-BRD-005와 정합한다.

Round 4에서 추가된 `board_config.notice` 적용 범위 정책이 세 문서에 걸쳐 정합적으로 반영된 것을 확인했다:
- **data.md**: `board_config.notice`는 `board_type = 'notice'`인 게시판에서만 동작에 반영되며, 다른 타입에서는 저장 허용·런타임 무시 (line 208)
- **rules.md**: BR-BRD-017 동작 5항에 동일 정책 기술 (line 308)
- **api.md**: `BoardConfig.notice` JSDoc에 "board_type notice 등"으로 스코프 기술 (line 579)

`mandatory_approval_config` JSONB 스키마가 approval/data.md의 `MandatoryApprovalConfig` 계약과 필드 수준에서 정합하는 것도 확인했다(`self_approve_blocked`, `delegation_allowed`, `sla_hours`, `auto_reject_grace_hours`, `min_steps`, `max_steps`).

#### EX-MS-SR-02. 이벤트 설계 정합성 — 90/100 우수

이벤트 페이로드가 DB 상태 변경과 정확히 대응한다:

- `board.created`: `parentId`, `boardType`, `slug`, `createdBy` — Board 생성 시 핵심 필드
- `board.updated`: `changedFields` 힌트 + `updatedBy`(R4 required 전환 완료) — 소비자 재조회 패턴
- `board.config_updated`: 전후 전체 스냅샷(`previousBoardConfig`, `boardConfig`) — diff 계산 없이 동기화 가능한 설계
- `board.deleted`: `affectedBoardIds` 배열 — CTE 재귀 삭제와 1:1 대응
- `board.restored`: `affectedBoardIds` 배열(R4 required 전환 완료) — `board.deleted`와 대칭

`board.config_updated`가 `board.updated`와 병행 발행될 수 있다는 점이 명시되어 있어, 소비자가 두 이벤트를 독립적으로 처리해도 정합성이 깨지지 않는다. 이는 config 변경과 메타데이터 변경이 같은 PATCH 요청에서 동시에 일어날 때의 엣지케이스를 잘 처리한 것이다.

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P2 | RD-MS-03 | 감사 로그 action(board.moved, board.toggled)과 BullMQ 이벤트(board.updated) 간 매핑이 api.md에 미기술 | api.md §BullMQ board.updated | add | 구현자가 이동/토글 시 별도 이벤트를 만들어야 하는지 혼동 가능 | `board.updated` 트리거 설명에 "이동(parent_id 변경), 활성/비활성 전환(is_active 변경) 포함" 명시 |
| P2 | RD-MS-05 | `BoardExportService.findById`가 soft-deleted 게시판을 반환하는지 미명시 | README.md §내부 서비스 인터페이스 | add | DocumentModule이 `board.deleted_at`을 확인해 필터링하려면 soft-deleted 포함 반환이 필요한데 계약에 누락 | JSDoc에 "soft-deleted 포함, 물리 삭제된 경우만 null" 또는 `includeSoftDeleted` 파라미터 추가 |
| P3 | EX-MS-SR-02 | `board.config_updated.changedKeys`가 optional — 대부분의 소비자가 활용할 수 있는 힌트 | api.md §board.config_updated | decision | 필터링·재색인 최적화용이라면 required가 소비자 편의에 유리 | required로 전환하거나, optional 유지 시 "구현이 changedKeys를 생략할 수 있는 조건" 명시 |
| P3 | RD-MS-01 | `GET /boards/tree` 응답 크기에 대한 가이드라인 없음 | api.md §GET /boards/tree | add | 테넌트당 100개 이하 가정이지만, 트리 응답이 대형화될 경우 대비 없음 | maxDepth 클램핑 외에 예상 최대 응답 크기·노드 수 가이드라인 추가 |
| P3 | RD-MS-02 | `board_type`별 에디터 프로파일 테이블(data.md)이 프론트엔드 참조용이나 백엔드 문서에 포함 | data.md §에디터 프로파일 | decision | 프론트엔드 구현 변경 시 백엔드 문서 수정 필요 — 관리 부담 | 프론트엔드 전용 문서로 분리하거나, 현 위치 유지 시 "프론트엔드 참조용" 경계를 더 명확히 |

---

## Round 3 → Round 4 개선 공정 확인

| 수정사항 | 반영 확인 | 정합성 | 비고 |
|----------|:---------:|:------:|------|
| `BoardUpdatedPayload.updatedBy` optional → required | ✅ | api.md line 654 `updatedBy: string` (non-optional) | 감사 추적 필수 정보 확보 |
| `board.restored.affectedBoardIds` optional → required | ✅ | api.md line 698 `affectedBoardIds: string[]` (non-optional) | board.deleted와 대칭. 단일 노드도 1건 배열 명시 |
| `board_config.notice` 적용 범위 정책 추가 | ✅ | data.md §208, rules.md BR-BRD-017 동작 5항, api.md §579 | 3곳 정합 확인. "저장 허용·런타임 무시" 방침 일관 |
