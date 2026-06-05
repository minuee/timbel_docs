> **문서 유형**: 모듈 스펙
> **종합 점수**: 86 / 100 (공용 86 × 0.6 + 전문 85 × 0.4)
> **리뷰 대상**: `docs/03-module-design/board/` (README.md, data.md, api.md, rules.md)
> **페르소나**: 최민재 — 시니어 백엔드 개발자 8년차 NestJS/TypeScript (AI)
> **리뷰일**: 2026-04-07 18:21
> **지적사항**: P1: 0건, P2: 0건, P3: 3건
> **자동 반영 가능**: 2건 / 설계 결정 필요: 1건
> **라운드**: Round 3 (Round 1: 61점 → Round 2: 81점 → Round 3: 86점, +5점)

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-MS-01 | API 설계 품질 | 87 | 30% | BoardResponse에 원본/유효값 분리, board.restored 이벤트 추가, config_updated 스냅샷 확정으로 R2 P2·P3 전수 해소 |
| RD-MS-02 | 구현 변환 용이성 | 87 | 10% | DDL·CTE·상속 의사코드·effective 필드 해석 가이드까지 NestJS 구현 즉시 착수 가능 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 85 | 25% | 5종 이벤트 + DLQ + Phase 1 보정 배치 5분 주기 확정으로 감사 로그 ↔ BullMQ 갭 해소 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 86 | 15% | Layer 1 독립 원칙 일관, Board↔Document 오케스트레이션·문서 삭제 연동 방침 변함 없이 견고 |
| RD-MS-05 | 모듈 간 계약 명확성 | 86 | 10% | getBoardConfig 소비 모듈 3종(Document, Approval, Community) 명시로 계약 추적 완전성 확보 |
| RD-MS-06 | 운영 고려사항 | 85 | 10% | Phase 1 보정 배치 채택 + Outbox Phase 2 검토로 운영 전략이 명확. 감사 로그는 RDB 직접 기록으로 손실 불가 |
| | **공용 소계** | **86** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-MS-SR-01 | 런타임 안정성 설계 | 84 | 50% | 보정 배치 5분 주기·워터마크 전략·감사 로그 RDB 직접 기록으로 이벤트 손실 윈도우가 운영 허용 수준 |
| EX-MS-SR-02 | 참조 무결성 | 85 | 50% | FK·partial unique·ON DELETE 전략 정합 유지, BoardResponse 원본/유효값 분리로 상속 시맨틱 API 정합 완성 |
| | **전문 소계** | **85** | 100% | |

### 종합: 86 / 100 (공용 86 × 0.6 + 전문 85 × 0.4)

---

## 차원별 상세 피드백

### 공용 차원

#### RD-MS-01. API 설계 품질 — 87/100 우수

Round 2의 P2·P3 수정이 빠짐없이 반영되어 "우수" 구간에 진입했다. 11개 REST 엔드포인트 + 5종 BullMQ 이벤트가 RESTful 관례·이벤트 설계 모범 사례를 충실히 따른다.

**잘 된 점:**
- `BoardResponse`에 `approvalRequired: boolean | null`(DB 원본)과 `effectiveApprovalRequired: boolean`(상속 해석 후 유효값)을 분리한 설계가 탁월하다. 관리자 UI에서 "이 게시판이 자체 설정인지 상속인지" 즉시 판별 가능하고, FD-APR §2.7의 "상위 설정과 다름" 뱃지 구현에 별도 조회가 불필요하다. 목록(`BoardListItem`)·트리(`BoardTreeNode`)는 유효값만 반환하여 일반 사용자 DTO의 경량화도 유지 — 상세와 목록의 책임 분리가 깔끔하다.
- `board.restored` 이벤트가 `board.deleted`와 대칭 구조로 추가되었다. `affectedBoardIds`로 재귀 복구 시 영향 범위를 다운스트림에 전달 가능하고, 멱등성 키(`board.restored:{boardId}:{restoredAt}`)도 정의되어 있다.
- `board.config_updated` 페이로드가 `previousBoardConfig`(변경 전)·`boardConfig`(변경 후) 전체 스냅샷 + `changedKeys?`(필터링 힌트)로 확정되었다. "기본 구현: 전체 스냅샷"이 명시되고, 해시 축약은 "정책 협의 하에 예외"로 단서가 붙어 소비자 구현 혼란이 해소되었다.
- `board.updated`와 `board.config_updated` 분리 발행 규칙이 명확하다 — "board_config 제외 컬럼 변경 → board.updated", "board_config만 변경 또는 메타와 동시 변경 → board.config_updated 추가 발행". 소비자가 관심사를 깔끔하게 분리할 수 있다.

**개선 권고:**
- `BoardUpdatedPayload.updatedBy`가 optional(`?`)로 정의되어 있는데, `PATCH /boards/:id`는 ADMIN 권한 필수이므로 항상 식별 가능한 actor가 존재한다. `updatedBy: string`(required)으로 변경하면 감사 추적 소비자가 null 체크 없이 행위자를 확보할 수 있다 → P3 #1.
- `board.restored` 페이로드의 `affectedBoardIds`가 optional(`?`)인 반면, `board.deleted`의 `affectedBoardIds`는 required이다. 단일 노드 복구에서도 `[boardId]` 1원소 배열로 반환하면 소비자가 deleted/restored 이벤트를 동일 패턴으로 처리할 수 있다. 대칭성을 위해 required로 통일하는 것이 좋겠다 → P3 #2.

#### RD-MS-02. 구현 변환 용이성 — 87/100 우수

NestJS 개발자가 이 문서만 보고 구현에 착수할 수 있는 수준이다. Round 2에서 이미 우수했으며, Round 3에서 effective 필드 관련 가이드가 추가되어 더 명확해졌다.

**잘 된 점:**
- `BoardResponse` 주석에 "목록·트리 DTO에는 본 필드 없이 유효값만 반환"이라는 매핑 가이드가 있어, DTO 변환 레이어(Mapper) 구현 시 어느 필드를 목록/상세에 노출할지 즉시 판단 가능하다.
- DDL(`CREATE TABLE`, 인덱스), CTE 패턴(descendants, 재귀 소프트 삭제), 상속 의사코드(`isApprovalRequired`, `isVersioningEnabled`, `getMandatoryApprovalConfig`)가 실제 SQL/TypeScript로 제공된다.
- `BoardExportService` 인터페이스 8개 메서드 시그니처와 JSDoc 주석이 NestJS DI 등록을 바로 할 수 있는 수준이다.
- `board_config` deep-merge 동작("최상위 키 단위")과 `BoardConfig` TypeScript 인터페이스가 정합하여, 프론트엔드 개발자도 부분 업데이트 시맨틱을 오해할 여지가 없다.

#### RD-MS-03. 이벤트/비동기 설계 건전성 — 85/100 우수

Round 2의 핵심 이슈(감사 로그 ↔ BullMQ 이벤트 간 갭, Outbox 미확정, config_updated 기본 구현 미확정)가 모두 해소되었다.

**잘 된 점:**
- **감사 로그 ↔ BullMQ 갭 해소**: 감사 로그 7종(created/updated/deleted/restored/moved/permissions_updated/toggled) 대비, BullMQ 5종(created/updated/config_updated/deleted/restored) + permissions_updated(cache.md)가 정렬되었다. `board.moved`와 `board.toggled`는 `board.updated`의 `changedFields`로 커버되며, 이 결정이 api.md에 "board_config 제외 컬럼이 변경되어 커밋 성공한 경우"라는 트리거 조건으로 명시되어 있다.
- **Phase 1 보정 배치 5분 주기 확정**: README.md에 "5분 주기 배치가 워터마크(updated_at, 삭제·복구 시각 등) 기준으로 스캔해, 누락된 board.* 이벤트를 재발행"이 명시되었다. api.md의 이벤트 페이로드·멱등성 키 규약과 동일하게 enqueue한다는 조건도 있다. Outbox는 Phase 2 검토로 명확히 정리되어, 구현 팀이 Phase 1에서 무엇을 만들어야 하는지 혼란이 없다.
- **감사 로그 RDB 직접 기록**: "감사 로그는 도메인 트랜잭션 내 RDB에 직접 기록하므로 enqueue 실패와 무관하게 손실 없이 남는다"는 문장이 운영 안정성에 대한 결정적 보장이다. 금융권 감사 요건에서 가장 중요한 포인트가 명확히 커버된다.
- BullMQ `board.events` 큐의 DLQ(`board.events-dlq`), 재시도(3회, 지수 백오프), `BoardEventEnvelope` 제네릭 래퍼, `schemaVersion: 1`이 이벤트 계약의 프로덕션 수준 기반을 제공한다.

#### RD-MS-04. 모듈 책임 범위 적절성 — 86/100 우수

Round 2와 동일하게 견고하다. Layer 1 독립 원칙이 4개 파일 전체에서 일관된다.

**잘 된 점:**
- BoardService는 DocumentModule 등 다른 도메인 모듈에 대한 DI 의존이 없다. BR-BRD-006의 in-flight 문서 확인은 Controller 레벨 오케스트레이션으로 처리한다 — 이 패턴이 README·api·rules 3곳에서 일관되게 기술된다.
- "문서 삭제 연동 방침"(README.md)이 Board의 독립성과 Document의 자체 필터링 책임을 깔끔하게 분리한다.
- `board_config`(JSONB) vs FK 정책 구분 기준 표(data.md)가 설계 결정의 근거를 명시한다.
- `getBoardConfig` 소비 모듈이 README.md에 명시됨으로써, 향후 새 모듈이 board_config를 조회할 때 이 표에 추가하면 되는 확장 지점이 명확하다.

#### RD-MS-05. 모듈 간 계약 명확성 — 86/100 우수

Round 2 P3 #3(getBoardConfig 소비 모듈 누락)이 해소되어 계약 추적이 완전해졌다.

**잘 된 점:**
- `getBoardConfig` 소비 모듈이 표로 명시: DocumentModule(문서 작성·목록·상세 UI, 첨부/알림 한도), ApprovalModule(승인 흐름 연계 알림·표시 옵션), CommunityModule(댓글 깊이, 익명 허용, 글쓰기 규칙). 용도 열이 구체적이어서 "왜 이 모듈이 board_config를 읽는지"가 명확하다.
- "그 외 모듈(예: 공지·배너 크로스보드 연동)이 동일 설정이 필요하면 동일 API를 재사용한다"는 확장 가이드가 있어, 향후 추가 소비자에 대한 방침도 정해져 있다.
- 의존 관계 Mermaid 다이어그램과 표가 일치하며, `Board → Doc` (Controller 오케스트레이션), `Doc → Board` (읽기), `Approval → Board` (읽기), `Com → Board` (읽기) 등 방향·유형·용도가 4열로 정리되어 있다.
- `BoardExportService` 8개 메서드 시그니처가 TypeScript 인터페이스로 명시되어, 소비 모듈 개발자가 import 후 바로 호출할 수 있다.

#### RD-MS-06. 운영 고려사항 — 85/100 우수

Round 2의 "Outbox 미확정" 이슈가 "Phase 1 보정 배치 채택 + Outbox Phase 2 검토"로 확정되어 운영 전략이 명확해졌다.

**잘 된 점:**
- 이벤트 발행 보정이 Phase 1(보정 배치 5분 주기)·Phase 2(Outbox 검토)로 명확히 로드맵되었다.
- "감사 로그는 도메인 트랜잭션 내 RDB에 직접 기록하므로 enqueue 실패와 무관"이라는 운영 보증이 추가되었다.
- Redis 장애 폴백(트리 캐시·무효화·BullMQ enqueue)이 구분별로 세분화되어 있다.
- 주요 메트릭 5개(`active_count`, `tree_max_depth`, `tree_avg_children`, `cache_hit_rate`, `events.dlq_count`)가 운영 대시보드 구성에 바로 사용 가능하다.
- OCC 패턴이 SQL 수준까지 구체적이고, 동시성 제어 시나리오 3건(동일 게시판 동시 수정, 재귀 삭제 중 복구, 이동과 삭제 동시 발생)이 전략별로 정리되어 있다.

---

### 전문 차원

#### EX-MS-SR-01. 런타임 안정성 설계 — 84/100 우수

Round 2에서 "Outbox 미확정"으로 80점이었던 차원이, Phase 1 보정 배치 확정으로 개선되었다.

**잘 된 점:**
- Phase 1 운영 결정이 명확하다: "5분 주기로 워터마크 기준 스캔 → 누락된 board.* 이벤트 재발행". 보정 배치의 이벤트 페이로드·멱등성 키가 api.md의 정규 이벤트와 동일하다는 조건이 명시되어 있어, 소비자가 정규 이벤트와 보정 이벤트를 구분 없이 멱등하게 처리할 수 있다.
- 감사 로그의 RDB 직접 기록은 이벤트 손실과 독립적이므로, 금융권 규제 관점에서 가장 중요한 감사 추적은 무조건 보장된다. 실무에서 BullMQ enqueue 실패가 발생해도 감사 기록은 살아 있으니, 보정 배치 5분 윈도우 동안 검색 인덱스 동기화만 지연되는 수준으로 리스크가 한정된다.
- CTE `depth < 20` safeguard, 재귀 소프트 삭제 원자성, BullMQ 지수 백오프 등 기존 안정성 설계가 유지된다.

**개선 권고:**
- 보정 배치의 구현 수준 상세가 더 있으면 좋겠다. 예를 들어: (1) 배치가 마지막 성공 실행의 타임스탬프를 어디에 저장하는지(Redis vs DB), (2) 배치 자체 장애 시 재시작 전략, (3) 서비스 재기동 시 첫 배치의 스캔 범위. 다만 이는 구현 상세이므로 모듈 스펙에서는 현재 수준이 적절하다.

#### EX-MS-SR-02. 참조 무결성 — 85/100 우수

Round 2(82점)에서 `BoardResponse` 원본/유효값 분리가 반영되어 상승했다.

**잘 된 점:**
- FK 전략이 일관적이다: `default_approval_template_id`(`ON DELETE SET NULL`), `parent_id`(`ON DELETE RESTRICT`), `board_permission.board_id`(`ON DELETE CASCADE`).
- `BoardResponse`의 `approvalRequired: boolean | null` + `effectiveApprovalRequired: boolean` 구조가 API 레벨에서 상속 시맨틱을 완전히 표현한다. 소비자는 `null`이면 "상속 중", 값이 있으면 "오버라이드 중"으로 판별할 수 있고, 실제 적용값은 `effective*` 필드로 얻는다.
- FD-APR의 `mandatory_approval_config` JSON 스키마(§2.6)와 data.md의 스키마가 필드 수준에서 정합한다.
- approval/data.md의 `ApprovalDelegation.board_id FK → Board`와 board/data.md의 Board 엔티티가 정합하며, `delegation_allowed` 제어 흐름이 양쪽 모듈에서 일관된다.
- `mandatory_approval_config` 상속이 "replace(대체), 병합 아님"으로 명확히 정의되어 있다.

**개선 권고:**
- Round 2 DQ-1(`board_config.notice` 설정의 non-notice 게시판 적용 범위)이 미결 상태로 남아 있다. BR-BRD-017은 `notice` 키를 모든 board_type에서 허용하지만, 실제 동작 의미(notice 설정이 community 게시판에서 유효한지)가 문서에 없다. 이는 구현 단계에서 결정해도 되지만, 모듈 스펙에 한 줄이라도 방침이 있으면 프론트엔드와의 핑퐁을 방지할 수 있다 → P3 #3.

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P3 | RD-MS-01 | `BoardUpdatedPayload.updatedBy`가 optional — ADMIN 전용 API이므로 항상 식별 가능 | api.md §board.updated | fix | 감사 추적 소비자가 null 체크 필요, 실무상 undefined가 올 수 없는 필드 | `updatedBy?: string` → `updatedBy: string`(required)으로 변경 |
| P3 | RD-MS-01, RD-MS-03 | `board.restored`의 `affectedBoardIds`가 optional — `board.deleted`는 required | api.md §board.restored | fix | deleted/restored 이벤트 소비 패턴 비대칭. 단일 복구에도 `[boardId]` 배열로 통일하면 소비자가 동일 로직으로 처리 가능 | `affectedBoardIds?: string[]` → `affectedBoardIds: string[]`(required), 단일 복구 시 `[boardId]` 반환 |
| P3 | EX-MS-SR-02 | `board_config.notice` 설정의 non-notice 게시판 적용 범위 미명시 (R2 DQ-1 미결) | data.md §board_config 또는 rules.md §BR-BRD-017 | decision | 프론트엔드가 non-notice 게시판에서 notice 설정 UI를 노출할지 판단 불가. 구현 시 핑퐁 발생 가능 | data.md board_config 설명에 "notice/banner 키는 모든 board_type에서 저장 가능하며, board_type ≠ notice인 게시판에서는 해당 설정이 무시된다" 또는 "범용 적용된다" 방침을 1줄 추가 |

---

## Round 2 → Round 3 개선 요약

| Round 2 지적 | 우선순위 | 반영 상태 | 점수 영향 |
|--------------|----------|-----------|-----------|
| `board.restored` BullMQ 이벤트 누락 | P2 #1 | ✅ 완전 반영 — `board.deleted` 대칭 구조, affectedBoardIds·멱등성 키·트리거 조건 완비 | RD-MS-01 +5, RD-MS-03 +10 |
| Outbox vs 보정 배치 채택 미확정 | P2 #2 | ✅ 완전 반영 — Phase 1 보정 배치 5분 주기 확정, Outbox Phase 2 검토, 감사 로그 RDB 직접 기록 보증 | RD-MS-06 +3, EX-MS-SR-01 +4 |
| BoardResponse에 원본값(null=상속) 구분 없음 | P3 #1 | ✅ 완전 반영 — `approvalRequired`/`versioningEnabled` 원본 + `effective*` 유효값 분리, 목록·트리는 유효값만 | RD-MS-01 +5, EX-MS-SR-02 +3 |
| `board.config_updated` 기본 구현 미확정 | P3 #2 | ✅ 완전 반영 — 전/후 전체 스냅샷이 기본, changedKeys 힌트 추가, 해시 축약은 예외로 명시 | RD-MS-01 +3, RD-MS-03 +5 |
| `getBoardConfig` 소비 모듈 누락 | P3 #3 | ✅ 완전 반영 — Document, Approval, Community 3개 모듈 용도별 표 + 확장 가이드 | RD-MS-05 +6 |

**총평**: Round 2의 P2 2건·P3 3건이 모두 성실하게 반영되었다. 특히 `BoardResponse`의 원본/유효값 분리는 상속 모델의 API 표현을 완성시킨 결정적 개선이다. `board.restored` 이벤트 추가로 감사 로그 ↔ BullMQ 이벤트 간 갭이 해소되었고, Phase 1 보정 배치 5분 주기 확정으로 운영 전략의 모호함이 사라졌다. 81점 → 86점(+5)으로 "우수" 구간에 안정적으로 진입했으며, 남은 P3 3건은 모두 경미한 개선사항으로 코드 구현 단계에서 반영 가능하다. **P1·P2 수준의 구조적 문제는 더 이상 없으며, 이 모듈 스펙으로 구현 착수가 가능하다.**
