> **문서 유형**: 모듈 스펙
> **종합 점수**: 81 / 100 (공용 81 × 0.6 + 전문 81 × 0.4)
> **리뷰 대상**: `docs/03-module-design/board/` (README.md, data.md, api.md, rules.md)
> **페르소나**: 최민재 — 시니어 백엔드 개발자 8년차 NestJS/TypeScript (AI)
> **리뷰일**: 2026-04-07 18:09
> **지적사항**: P1: 0건, P2: 2건, P3: 3건
> **자동 반영 가능**: 4건 / 설계 결정 필요: 1건
> **라운드**: Round 2 (Round 1: 61점 → Round 2: 81점, +20점)

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-MS-01 | API 설계 품질 | 82 | 30% | 11개 엔드포인트 RESTful 설계, DTO 타입 완비, BullMQ 이벤트 스키마 상세 추가로 대폭 개선 |
| RD-MS-02 | 구현 변환 용이성 | 85 | 10% | TypeScript DTO·DDL·CTE 패턴·상속 의사코드로 NestJS 구현 즉시 착수 가능 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 75 | 25% | 이벤트 래퍼·멱등성·DLQ·폴백이 추가되었으나, 감사 로그 대비 BullMQ 이벤트 종류 누락 존재 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 85 | 15% | Layer 1 독립 원칙 일관 유지, Board↔Document 오케스트레이션 패턴 명확 |
| RD-MS-05 | 모듈 간 계약 명확성 | 80 | 10% | BoardExportService 8개 메서드 시그니처 정의, 의존 방향 표 명확 |
| RD-MS-06 | 운영 고려사항 | 82 | 10% | Redis 폴백·이벤트 보정·OCC·DLQ 메트릭이 추가되어 운영 커버리지 대폭 향상 |
| | **공용 소계** | **81** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-MS-SR-01 | 런타임 안정성 설계 | 80 | 50% | OCC·CTE safeguard·Redis 폴백·Outbox 권장이 체계적이나, Outbox 채택 여부가 미확정 |
| EX-MS-SR-02 | 참조 무결성 | 82 | 50% | FK·partial unique·ON DELETE 전략 정합, BR-BRD-016 불완전 상태 인지, 상속 의사코드 완비 |
| | **전문 소계** | **81** | 100% | |

### 종합: 81 / 100 (공용 81 × 0.6 + 전문 81 × 0.4)

---

## 차원별 상세 피드백

### 공용 차원

#### RD-MS-01. API 설계 품질 — 82/100 양호

Round 1 대비 가장 큰 개선이 이루어진 차원이다. 11개 REST 엔드포인트가 RESTful 관례를 잘 준수하고, 모든 요청/응답에 TypeScript 인터페이스가 정의되어 있다.

**잘 된 점:**
- `BoardConfig` 타입에 `notice` 섹션이 추가되어 FD-NTC와의 정합이 해소됨. `defaultPopup`, `defaultConfirmationRequired`, `maxPinnedCount`, `reminderDaysBefore` 등 공지 운영에 필요한 설정이 구체적으로 정의되었다.
- BullMQ 이벤트 스키마가 `BoardEventEnvelope<T, P>` 제네릭 래퍼로 타입 안전하게 정의됨. `board.created`, `board.updated`, `board.config_updated`, `board.deleted` 4종의 페이로드·멱등성 키·트리거 조건이 명확하다.
- `board.updated`와 `board.config_updated` 분리가 합리적 — config 변경만으로 전체 메타데이터 이벤트를 발행하지 않아 소비자가 관심사를 분리할 수 있다.
- `BoardResponse`에서 `approvalRequired`, `versioningEnabled`를 "유효값(상속 해석 후)"으로 반환하는 설계가 API 소비자 관점에서 직관적이다.
- `UpdateBoardDto.boardConfig`의 "최상위 키 단위 deep-merge" 동작이 명시되어 있어 부분 업데이트 시맨틱이 명확하다.

**개선 필요:**
- 감사 로그에 `board.restored`, `board.moved`, `board.toggled`가 정의되어 있으나, BullMQ `board.events` 큐에는 대응 이벤트가 없다. 특히 **`board.restored`는 소속 문서의 가시성이 복원되는 중요 상태 전이**이므로 다운스트림(검색 인덱스 등)에 통지가 필요할 수 있다. `board.moved`와 `board.toggled`는 `board.updated`의 `changedFields`로 커버 가능하지만, `board.restored`는 `DELETE /boards/:id`의 역연산으로 별도 이벤트가 타당하다 → P2 #1.
- `BoardResponse`에 DB 원본값(`approvalRequired: boolean | null`)과 유효값(`effectiveApprovalRequired: boolean`)을 모두 반환하면, 관리자가 "이 게시판이 자체 설정인지 상속인지" 즉시 파악할 수 있다. 현재는 유효값만 반환하므로 관리자 UI에서 "상위 설정과 다름" 뱃지(FD-APR §2.7)를 표시하려면 별도 조회가 필요하다 → P3 #1.

#### RD-MS-02. 구현 변환 용이성 — 85/100 우수

NestJS 개발자가 이 문서만 보고 구현에 착수할 수 있는 수준이다.

**잘 된 점:**
- DDL이 실제 `CREATE TABLE` 문으로 제공되어 마이그레이션 파일로 거의 그대로 사용 가능하다.
- `isApprovalRequired`, `isVersioningEnabled`, `getMandatoryApprovalConfig` 의사코드가 있어 재귀 상속 로직을 바로 구현할 수 있다.
- CTE 쿼리 패턴(`descendants`, 재귀 소프트 삭제)이 실제 SQL로 제공된다.
- `BoardExportService` 인터페이스가 TypeScript 시그니처로 정의되어 있어 모듈 간 계약 구현이 직관적이다.
- 에러 코드 카탈로그(rules.md §3)가 HTTP 상태 코드·발생 규칙·메시지 템플릿을 완비하고 있어, NestJS Exception Filter 매핑이 바로 가능하다.

**개선 필요:**
- `board_config` JSON 스키마 검증을 위한 `class-validator` 데코레이터 힌트나 JSON Schema $ref가 있으면 더 좋겠지만, 모듈 스펙 수준에서는 현재 기술이 충분하다.

#### RD-MS-03. 이벤트/비동기 설계 건전성 — 75/100 양호

Round 1의 핵심 지적사항(이벤트 스키마 부재, Redis 장애 폴백 부재)이 모두 해소되었다. 그러나 이벤트 커버리지에 아직 갭이 있다.

**잘 된 점:**
- `BoardEventEnvelope<T, P>` 공통 래퍼에 `eventType`, `occurredAt`, `tenantId`, `boardId`, `idempotencyKey`, `schemaVersion` 필드가 포함되어 이벤트 계약이 견고하다.
- 멱등성 키 권장 형식(`${eventType}:${boardId}:${correlationId}`)이 명시되어 소비자 구현 가이드라인이 있다.
- DLQ(`board.events-dlq`)와 재시도 전략(지수 백오프, 3회)이 cache.md와 일관되게 정의되었다.
- Redis 장애 시 트리 캐시 폴백(DB CTE 직접 구축)과 BullMQ enqueue 실패 시 보정 패턴(Outbox/보정 배치)이 체계적이다.
- `board.events.dlq_count` 메트릭과 `> 0이면 WARN 알림` 조건이 운영 가시성을 확보한다.

**개선 필요:**
- **감사 로그 ↔ BullMQ 이벤트 간 갭**: 감사 로그에는 7가지 작업(`board.created/updated/deleted/restored/moved/permissions_updated/toggled`)이 정의되어 있는데, BullMQ에는 4종(`board.created/updated/config_updated/deleted`) + `board.permissions_updated`(cache.md)만 있다. `board.restored`는 문서 가시성 복원이라는 사이드 이펙트가 있어 별도 이벤트로 발행해야 다운스트림이 반응할 수 있다 → P2 #1 (RD-MS-01과 동일).
- `board.config_updated` 페이로드에 `boardConfig` 전체 스냅샷을 권장하면서 "민감도에 따라 해시만 전달 가능"이라는 대안을 제시하는데, **어느 쪽이 기본 구현인지** 확정하면 소비자 구현이 편해진다 → P3 #2.

#### RD-MS-04. 모듈 책임 범위 적절성 — 85/100 우수

**잘 된 점:**
- Layer 1 독립 원칙이 4개 파일 전체에서 일관되게 유지된다. BoardService는 DI 의존이 없고, Controller 레벨 오케스트레이션으로 Document·Approval과 연동한다.
- "문서 삭제 연동 방침"(README.md)이 Board의 독립성과 Document의 자체 필터링 책임을 깔끔하게 분리한다.
- `board_config`(JSONB) vs FK 정책 구분 기준 표(data.md)가 있어 "왜 이 설정은 FK이고 저 설정은 JSONB인지" 근거가 명확하다.
- `approval_required`·`versioning_enabled`·`mandatory_approval_config`의 상속/오버라이드 모델이 README·data·api·rules 4파일에서 일관되게 "오버라이드 허용"으로 통일됨 — Round 1 P1 수정이 완전히 반영되었다.

**개선 필요:**
- 없음. 모듈 책임 범위는 적절하다.

#### RD-MS-05. 모듈 간 계약 명확성 — 80/100 양호

**잘 된 점:**
- `BoardExportService` 8개 메서드가 TypeScript 시그니처로 명시되어 소비 모듈이 어떤 메서드를 호출할 수 있는지 한눈에 보인다.
- 의존 관계 표(README.md)가 방향·대상·유형·용도를 4열로 정리하여 모듈 간 의존을 추적하기 쉽다.
- BR-BRD-006 오케스트레이션 시퀀스 다이어그램(api.md)이 Board Controller → DocumentService → BoardService 흐름을 시각화한다.
- 아키텍처 정합 이력(README.md 하단)에 module-architecture.md 표A·표C 등록 완료가 체크되어 있어 문서 간 정합 추적이 가능하다.

**개선 필요:**
- `BoardExportService.getBoardConfig`의 소비 모듈이 명시되지 않음 — 어느 모듈이 이 메서드를 사용하는지 의존 관계 표에 없다. README.md의 의존 관계 표에 "config 조회" 용도를 추가하면 계약이 완전해진다 → P3 #3.

#### RD-MS-06. 운영 고려사항 — 82/100 우수

**잘 된 점:**
- Redis 장애 폴백이 구분별(트리 캐시 읽기·무효화·BullMQ enqueue) 동작으로 세분화되었다 — Round 1 P2 수정.
- 이벤트 발행 보정이 Outbox(권장)·보정 배치·권한 전용(TTL 수렴) 3가지 패턴으로 제시됨 — Round 1 P2 수정.
- OCC 패턴이 `UPDATE ... WHERE updated_at = :expectedUpdatedAt` SQL까지 구체적이다.
- 주요 메트릭 5개(`active_count`, `tree_max_depth`, `tree_avg_children`, `cache_hit_rate`, `events.dlq_count`)가 운영 대시보드 구성에 바로 사용 가능하다.

**개선 필요:**
- Outbox 패턴이 "권장"으로만 표시되어 있고 Phase 1에서 채택 여부가 미확정. 보정 배치의 실행 주기·워터마크 전략도 구체적이지 않음 → P2 #2.

---

### 전문 차원

#### EX-MS-SR-01. 런타임 안정성 설계 — 80/100 양호

8년간 NestJS 프로덕션을 운영해 본 관점에서, 이 모듈 스펙은 대부분의 런타임 위험을 커버한다.

**잘 된 점:**
- CTE `depth < 20` safeguard가 순환 참조 데이터 오염에 대한 방어선을 제공한다. `WITH RECURSIVE`가 무한 루프에 빠지면 DB 커넥션이 잠기므로, 이 safeguard는 프로덕션에서 생명줄이다.
- 재귀 소프트 삭제가 단일 CTE `UPDATE`로 원자성을 보장하여, 삭제 도중 복구 요청이 들어와도 중간 상태가 발생하지 않는다.
- `board_config` deep-merge 동작이 "최상위 키 단위"로 명확히 정의되어, `{ comment: { enabled: false } }`를 보내면 comment 그룹만 병합되고 나머지는 유지된다 — 프론트엔드와의 계약이 명확하다.
- BullMQ 재시도가 지수 백오프(1s → 2s → 4s, 상한 30s)로 구성되어 thundering herd를 방지한다.

**개선 필요:**
- Outbox 패턴을 "권장"으로만 두고 Phase 1 채택 여부를 열어둠. 실무에서 보정 배치만으로는 이벤트 손실 윈도우가 배치 주기만큼 벌어진다. BullMQ enqueue 실패 빈도와 소비자의 허용 지연을 기준으로 Outbox vs 보정 배치 중 하나를 확정해야 한다 → P2 #2.
- 트리 캐시 콜드스타트(서비스 재시작, Redis flush 직후) 시 첫 요청이 DB CTE를 타는데, 게시판 100개 이하 규모라면 문제없지만, 캐시 웜업 전략(서비스 부팅 시 사전 로드)이 있으면 더 안정적이다 — 이건 cache.md 소관이므로 여기서는 참고 의견으로만 남긴다.

#### EX-MS-SR-02. 참조 무결성 — 82/100 우수

**잘 된 점:**
- FK 전략이 일관적이다: `default_approval_template_id`는 `ON DELETE SET NULL`(삭제해도 게시판 유지), `parent_id`는 `ON DELETE RESTRICT`(하위 존재 시 물리 삭제 차단), `board_permission.board_id`는 `ON DELETE CASCADE`(게시판 삭제 시 권한도 제거).
- BR-BRD-016이 "기본 결재라인 템플릿 삭제 → approval_required=true + default_approval_template_id=NULL = 불완전 상태"를 인지하고, 관리자 조치(다른 템플릿 지정 또는 mandatory_approval_config 보완)를 안내한다.
- `mandatory_approval_config` 상속이 "replace(대체), 병합 아님"으로 명확히 정의되어, 상위·하위 설정이 섞이는 혼란이 없다.
- `UNIQUE(slug) WHERE deleted_at IS NULL` partial unique index가 소프트 삭제된 게시판의 slug 재사용을 허용하면서 활성 게시판 간 충돌을 방지한다.
- FD-APR의 `mandatory_approval_config` JSON 스키마(§2.6)와 data.md의 스키마가 필드 수준에서 정합한다: `mandatory_steps`, `self_approve_blocked`, `delegation_allowed`, `sla_hours`, `auto_reject_grace_hours`, `min_steps`, `max_steps`.
- approval/data.md의 `ApprovalDelegation.board_id FK → Board`와 board/data.md의 Board 엔티티가 정합하며, `delegation_allowed` 제어 흐름(Board.mandatory_approval_config → ApprovalDelegation 생성 검증)이 양쪽 모듈에서 일관된다.

**개선 필요:**
- `board_config.notice` 설정이 `board_type !== 'notice'`인 게시판에서도 저장 가능한지 명시적이지 않음. BR-BRD-017은 허용 최상위 키에 `notice`를 포함하므로 어떤 board_type에서든 저장은 가능하지만, 실제 동작(notice 설정이 community 게시판에서 의미가 있는지)에 대한 설계 의도가 불분명 → DQ-1.

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P2 | RD-MS-01, RD-MS-03 | `board.restored` BullMQ 이벤트 누락 — 감사 로그에는 있으나 다운스트림 통지 없음 | api.md §BullMQ 이벤트 | add | 복구 시 소속 문서 가시성이 복원되므로, 검색·필터링 다운스트림이 반응할 수 없음 | `board.restored` 이벤트 추가 (페이로드: `restoredAt`, `affectedBoardIds` — board.deleted 대칭) |
| P2 | EX-MS-SR-01, RD-MS-06 | Outbox vs 보정 배치 채택이 미확정 — Phase 1 기본 전략이 불명확 | README.md §이벤트 발행 보정 | decision | 보정 배치만으로는 배치 주기만큼 이벤트 손실 윈도우 발생. 엄격한 소비자(감사·검색)는 Outbox 필요 | Phase 1 기본 전략을 확정: (a) Outbox 채택 시 outbox 테이블 선설계, (b) 보정 배치만 사용 시 허용 지연·실행 주기 명시 |
| P3 | RD-MS-01 | `BoardResponse`에 DB 원본값(null=상속)과 유효값(boolean) 구분 없음 | api.md §BoardResponse | add | FD-APR §2.7 "상위 설정과 다름" 뱃지를 위해 원본값 필요 — 현재는 별도 조회 필요 | `rawApprovalRequired: boolean \| null` 등 원본 필드를 응답에 추가하거나, `isInherited` 플래그를 도입 |
| P3 | RD-MS-03 | `board.config_updated` 페이로드 기본 구현(스냅샷 vs 해시)이 미확정 | api.md §board.config_updated | fix | "권장" / "가능"이 병렬로 제시되어 소비자 구현 시 혼란 | 기본을 "전체 스냅샷"으로 확정하고, 해시 대안은 주석으로 남기기 |
| P3 | RD-MS-05 | `getBoardConfig` export 메서드의 소비 모듈이 의존 관계 표에 누락 | README.md §의존 관계 | add | 계약 추적 불완전 — 어느 모듈이 게시판별 설정을 조회하는지 불명확 | 의존 관계 표에 소비 모듈(예: NotificationModule, DocumentModule 등) 행 추가 |

## 설계 질문

| ID | 질문 | 블로킹 항목 |
|----|------|-------------|
| DQ-1 | `board_config.notice` 설정은 `board_type = 'notice'`인 게시판에서만 유의미한가, 아니면 모든 board_type에서 공지 문서를 다룰 수 있어 범용 적용인가? api.md에서 "공지 게시판·공지 문서 UX (board_type notice **등**)"이라고 표기했는데, 이 "등"의 범위가 무엇인지 명확히 하면 BR-BRD-017 검증 로직(notice 키를 non-notice 게시판에서 거부할지 허용할지)이 결정된다. | P3 #1 (BoardResponse 원본값)과 간접 관련 — notice 설정의 상속 시맨틱에 영향 |

---

## Round 1 → Round 2 개선 요약

| Round 1 지적 | 우선순위 | 반영 상태 | 점수 영향 |
|--------------|----------|-----------|-----------|
| 상속 모델 불일치 (README vs api vs rules) | P1 | ✅ 완전 반영 — 4파일 모두 "오버라이드 허용"으로 통일 | RD-MS-01 +15, RD-MS-04 +10 |
| api.md BoardConfig에 notice 섹션 누락 | P1 | ✅ 완전 반영 — 9개 필드의 상세 스키마 추가 | RD-MS-01 +8, EX-MS-SR-02 +5 |
| BullMQ 이벤트 스키마 부재 | P2 | ✅ 완전 반영 — 4종 이벤트 + 공통 래퍼 + 멱등성 키 | RD-MS-03 +20 |
| Redis 장애 폴백·이벤트 보정 패턴 부재 | P2 | ✅ 완전 반영 — 3가지 폴백 시나리오 + Outbox/보정 배치 | RD-MS-06 +15, EX-MS-SR-01 +12 |

**총평**: Round 1의 P1·P2 수정이 모두 성실하게 반영되었다. 상속 모델 통일은 4개 파일 전체에서 일관성을 확보했고, 이벤트 설계는 `BoardEventEnvelope` 제네릭 래퍼와 멱등성 키 규약으로 프로덕션 레벨에 근접했다. 61점 → 81점(+20)으로 "양호~우수" 구간에 진입했으며, 남은 P2 2건(board.restored 이벤트, Outbox 채택 확정)을 해소하면 85점 이상도 가능하다. P3은 코드 구현 단계에서 점진적으로 반영해도 무방하다.
