> **문서 유형**: 모듈 스펙
> **종합 점수**: 61 / 100 (공용 68 × 0.6 + 전문 49 × 0.4)
> **리뷰 대상**: `docs/03-module-design/board/` (README.md, data.md, api.md, rules.md)
> **페르소나**: 최민재 — 시니어 백엔드 개발자, 8년차 NestJS/TypeScript (AI)
> **리뷰일**: 2026-04-07 15:30
> **지적사항**: P1: 2건, P2: 4건, P3: 3건
> **자동 반영 가능**: 5건 / 설계 결정 필요: 4건

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-MS-01 | API 설계 품질 | 75 | 30% | RESTful 관례·DTO·에러 코드 견고하나, BoardConfig TS 인터페이스에 notice 섹션 누락 |
| RD-MS-02 | 구현 변환 용이성 | 72 | 10% | DDL·CTE·의사코드 제공으로 구현 변환 양호하나, 이벤트 페이로드·deep-merge 상세 예제 미비 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 48 | 25% | BullMQ board.events 큐 존재하나 재시도 정책·이벤트 스키마·멱등성 키 미정의 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 85 | 15% | Layer 1 독립 원칙 준수, 문서 가시성 위임, Controller 오케스트레이션 패턴 우수 |
| RD-MS-05 | 모듈 간 계약 명확성 | 68 | 10% | BoardExportService 8개 메서드 정의, 그러나 이벤트 페이로드·약타입 반환값 한계 |
| RD-MS-06 | 운영 고려사항 | 72 | 10% | 감사 로그·메트릭·CTE 안전장치 양호, 로깅 레벨·캐시 장애 시 폴백 전략 미비 |
| | **공용 소계** | **68** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-MS-SR-01 | 런타임 안정성 설계 | 45 | 50% | OCC·CTE safeguard 존재, BullMQ 재시도·타임아웃·Redis 장애 시 폴백 미설계 |
| EX-MS-SR-02 | 참조 무결성 | 52 | 50% | data.md↔README/api/rules 간 상속 모델 P1급 불일치, BoardConfig notice 섹션 누락 |
| | **전문 소계** | **49** | 100% | |

### 종합: 61 / 100 (공용 68 × 0.6 + 전문 49 × 0.4)

---

## 차원별 상세 피드백

### 공용 차원

#### RD-MS-01. API 설계 품질 — 75/100 양호

금융 SI를 3건 리드한 경험에서 보면, Board API의 전반적 설계는 상당히 견고하다.

**잘 된 점:**

- RESTful 관례를 잘 준수한다. CRUD는 표준 HTTP 메서드를 따르고, 권한 전체 교체는 PUT(`PUT /boards/:id/permissions`), 부분 수정은 PATCH(`PATCH /boards/:id`)로 시맨틱이 명확하다.
- 에러 코드 체계가 우수하다. `BRD_*` 도메인 에러 11종이 rules.md §3에 정리되어 있고, 각 API 엔드포인트에서 발생 가능한 에러를 명시적으로 태깅하고 있다. 특히 `BRD_MODE_TRANSITION_BLOCKED`의 응답 본문에 `pendingCount`를 포함하여 관리자에게 행동 근거를 제공하는 것은 실무적으로 우수하다.
- OCC 패턴(`expectedUpdatedAt`)이 선택적으로 동작하며, 미전달 시 하위 호환을 유지하는 설계는 실무적이다.
- 소프트 삭제 시 200+body 반환(`DeleteBoardResponse`에 `deletedDescendantCount` 포함)은 관리자가 영향 범위를 즉시 파악할 수 있어 좋다.
- 게시판 목록 조회의 오프셋 페이지네이션 사용이 "프로젝트 표준(커서 기반)의 의식적 예외"로 명시되어 있고 근거(테넌트당 100개 이하)가 합리적이다.

**개선 필요:**

- **BoardConfig TS 인터페이스에 `notice` 섹션이 누락되어 있다.** api.md §공통 타입의 `BoardConfig` 인터페이스에는 `comment`, `display`, `attachment`, `notification`, `posting`, `banner` 6개 그룹만 정의되어 있으나, data.md의 board_config JSON 스키마에는 `notice` 섹션이 별도로 존재하고(line 188-198), rules.md BR-BRD-017도 `notice`를 유효 최상위 키로 열거한다. 주니어 개발자가 api.md의 TS 인터페이스만 보고 구현하면 `notice` 설정을 완전히 누락하게 된다.
- `BoardResponse.approvalRequired`는 "루트에서 상속된 값"이라고 주석이 달려 있는데, 이것이 "상속 해소(resolved) 후 boolean"인지 "DB 원시값"인지 API 소비자가 혼동할 수 있다. 응답에 `approvalRequiredResolved: boolean` + `approvalRequiredRaw: boolean | null` 같은 구분이 있으면 관리자가 "이 게시판의 자체 설정인지, 상위에서 물려받은 것인지" 판단이 용이할 것이다.

---

#### RD-MS-02. 구현 변환 용이성 — 72/100 양호

**잘 된 점:**

- DDL이 인덱스까지 포함되어 제공된다. `CREATE TABLE`, `CREATE INDEX` 그대로 적용 가능한 수준이다.
- CTE 패턴(하위 게시판 조회, 재귀 소프트 삭제)이 실제 SQL로 제공되어 주니어가 바로 활용할 수 있다.
- 상속 로직의 의사코드(`isApprovalRequired`, `isVersioningEnabled`, `getMandatoryApprovalConfig`)가 제공된다.
- 상태 전이 다이어그램(rules.md §1)과 시퀀스 다이어그램(api.md — 오케스트레이션, 권한 캐시 무효화)이 복잡한 흐름을 시각적으로 설명한다.
- `board_config` 접근 패턴(`getCommentConfig` 함수)이 기본값 병합 로직을 보여준다.

**개선 필요:**

- `board_config`의 PATCH deep-merge가 "최상위 키 단위"라고 기술되어 있으나, 구체적 예시가 부족하다. 예를 들어, `{ comment: { enabled: false } }`를 전달했을 때 기존 `comment.anonymous_allowed`와 `comment.max_depth`가 유지되는지, 아니면 `comment` 전체가 교체되는지 정확한 동작을 보여주는 before/after 예제가 필요하다. "deep-merge"라고 했으므로 하위 키가 유지되는 것으로 추정되지만, 구현자 입장에서 확인이 필요한 지점이다.
- `board.permissions_updated` 이벤트의 페이로드 구조가 어디에도 정의되어 있지 않다. BullMQ 큐에 어떤 데이터를 enqueue하는지 — `boardId`, 영향받는 `roleId` 목록 등 — 소비자(AuthModule)가 필요로 하는 최소 정보가 명시되어야 한다.
- `BoardConfig`의 `notice` 섹션 기본값(data.md에 정의)이 api.md TS 인터페이스에 반영되지 않아, 구현 시 참조 문서가 나뉘게 된다.

---

#### RD-MS-03. 이벤트/비동기 설계 건전성 — 48/100 보통

Board 모듈의 비동기 표면이 작다는 것은 이해하지만, 존재하는 비동기 설계의 완성도가 부족하다.

**잘 된 점:**

- BullMQ `board.events` 큐를 통한 `board.permissions_updated` 이벤트 전달 패턴은 Board의 Layer 1 독립성을 유지하면서 AuthModule 캐시 무효화를 수행하는 좋은 아키텍처다.
- DLQ 메트릭(`board.events.dlq_count`)이 정의되어 있고, `> 0`이면 WARN 알림을 발생시키는 모니터링 기준이 명시되어 있다.
- 트리 캐시(`cache:board:tree`, TTL 1h)가 명시되어 있다.

**개선 필요:**

- **BullMQ `board.events` 큐의 재시도 정책이 정의되어 있지 않다.** 비동기 처리 아키텍처 문서에 일반 정책이 있을 수 있으나, Board 모듈 스펙 자체에 "재시도 N회, 지수 백오프, 최종 실패 시 DLQ 이동" 같은 명시가 필요하다. 금융권에서 권한 캐시 무효화 실패는 "승인 권한 없는 사용자가 승인을 수행"하는 보안 사고로 이어질 수 있다.
- **이벤트 페이로드 스키마가 미정의다.** `board.permissions_updated` 이벤트에 어떤 필드가 포함되는지(boardId, changedRoleIds, timestamp, schemaVersion 등) 명시가 없다. 참조 문서인 approval/api.md의 이벤트 계약 섹션은 `schemaVersion`, `traceId`, 멱등 키까지 정의하고 있어 대조적이다.
- **멱등성 키가 미정의다.** 같은 `board.permissions_updated` 이벤트가 중복 전달될 때 AuthModule이 멱등하게 처리할 수 있는 키(`{boardId}:{timestamp}` 등)가 없다. 권한 캐시를 무조건 무효화하면 멱등하긴 하지만, 이러한 판단이 문서에 명시되어야 한다.
- **Redis(트리 캐시) 장애 시 폴백 전략이 없다.** 캐시 미스 시 DB 직접 조회로 폴백하는 것은 당연하지만, Redis 자체가 불가용한 경우 트리 조회 API가 어떻게 동작하는지(에러? DB 폴백?) 명시가 필요하다.

---

#### RD-MS-04. 모듈 책임 범위 적절성 — 85/100 우수

Board 모듈의 책임 경계 설정은 이 문서의 가장 큰 강점이다.

**잘 된 점:**

- "문서 삭제 연동 방침" (README.md) — 게시판 소프트 삭제 시 소속 문서의 가시성은 DocumentModule이 `board.deleted_at`을 확인하여 자체 필터링한다는 원칙이 명시적이다. 이는 Board→Document 역방향 의존을 차단하여 Layer 1 독립성을 지키는 핵심이다.
- Controller 레벨 오케스트레이션 패턴(api.md `PATCH /boards/:id` 시퀀스 다이어그램) — BoardService는 DocumentModule을 모르고, Controller가 두 서비스를 조율한다. 금융권 SI에서 서비스 간 순환 참조로 고생한 경험이 있는데, 이 패턴은 그 문제를 깔끔하게 해결한다.
- 게시판 타입(`board_type`)은 에디터 프로파일에만 영향을 주며, 승인·버전은 독립 설정이라는 분리가 명확하다. `board_type`에 따른 에디터 프로파일 표는 "프론트엔드 참조용"으로 명시되어 백엔드 스펙과 혼선을 방지한다.
- `board_config`(JSONB)와 FK 정책의 구분 기준(data.md — 변경 빈도, 참조 무결성, 공유 여부)이 표로 정리되어 있어 설계 근거가 명확하다.

**개선 필요:**

- `BoardExportService.getBoardConfig`가 "앱 레벨 기본값 병합 후 반환"한다고 되어 있는데, 이 기본값의 원천(하드코딩? 환경변수? SystemConfig?)이 명시되어 있지 않다. 기본값 변경 시 Board 모듈 코드 수정이 필요한지, 외부 설정으로 제어 가능한지 명확해야 한다.

---

#### RD-MS-05. 모듈 간 계약 명확성 — 68/100 양호

**잘 된 점:**

- `BoardExportService` 인터페이스가 8개 메서드로 명확히 정의되어 있고, 각 메서드의 역할이 주석으로 설명된다.
- 의존 관계 표(README.md)가 방향·대상·유형·용도를 명시한다.
- Mermaid 의존 관계 다이어그램이 시각적으로 제공된다.
- FK 관계가 DDL 레벨에서 `ON DELETE SET NULL`/`ON DELETE CASCADE`/`ON DELETE RESTRICT`로 명시되어 있다.

**개선 필요:**

- **`getMandatoryApprovalConfig`의 반환 타입이 `Record<string, unknown> | null`로 약타입이다.** data.md에 JSONB 스키마가 상세히 정의되어 있으므로, `MandatoryApprovalConfig` 같은 명시적 타입을 반환해야 소비 모듈(DocumentModule, ApprovalModule)이 안전하게 사용할 수 있다. `Record<string, unknown>`은 런타임 타입 가드 부담을 소비자에게 전가한다.
- **`board.permissions_updated` 이벤트의 소비 계약이 불명확하다.** 이벤트 이름과 큐명은 있지만, 페이로드 TS 타입이 없다. approval 모듈의 이벤트 계약(FD-APR §이벤트 계약)은 페이로드·소비 모듈·동기/비동기를 표로 정리하고 있어 참고할 만하다.
- Board가 **소비하는 이벤트가 없다는 점**이 명시적으로 기술되어 있지 않다. "소비 이벤트: 없음"이라고 한 줄 적어주면 구현자가 이벤트 핸들러를 만들지 않아도 된다는 것을 확인할 수 있다.

---

#### RD-MS-06. 운영 고려사항 — 72/100 양호

**잘 된 점:**

- 감사 로그 대상이 7가지 작업에 대해 정의되어 있고, 각 이벤트명까지 명시되어 있다.
- 메트릭 5종(`board.active_count`, `board.tree_max_depth`, `board.tree_avg_children`, `board.cache_hit_rate`, `board.events.dlq_count`)이 용도와 함께 정의되어 있다.
- 트리 깊이 제한(운영 10, CTE safeguard 20)의 근거가 합리적이다. "하드코딩"이라는 결정도 "게시판 100개 이하 규모에서 외부화 불필요"라는 근거로 뒷받침된다.
- 배포 프로파일 피처 게이트 3종(`ft:board.community_type`, `ft:board.export_control`, `ft:notice.cross_board_banner`)이 참조되어 있다.

**개선 필요:**

- **로깅 레벨 가이드가 없다.** 어떤 작업이 INFO로 찍히고, 어떤 예외가 WARN/ERROR인지 기준이 없으면 운영 중 로그 노이즈 제어가 어렵다. 예: `BRD_CONCURRENT_MODIFICATION`은 INFO(정상 동작), `board.events` DLQ 적재는 WARN, CTE safeguard 도달은 ERROR.
- **Redis 장애 시 운영 가이드가 없다.** 트리 캐시가 불가용하면 모든 트리 조회가 DB CTE를 직접 수행하게 되는데, 이 상황의 성능 영향과 대응 방안(Redis 복구 절차, 일시적 캐시 비활성화 등)이 없다.
- 아키텍처 정합 이력 섹션(README.md §아키텍처 정합 이력)은 좋은 관행이나, 마지막 갱신 일자가 없어 최신성을 판단할 수 없다.

---

### 전문 차원

#### EX-MS-SR-01. 런타임 안정성 설계 — 45/100 보통

8년간 금융권 백엔드를 다루면서 "설계 문서에 장애 시나리오가 빠져 있으면 운영에서 반드시 터진다"는 것을 체감했다. Board 모듈은 기본기는 갖추고 있으나, 실무 수준의 안정성 설계에는 미흡하다.

**잘 된 점:**

- OCC(`updated_at` 기반 낙관적 동시성 제어) — 관리자 간 충돌 빈도를 고려하면 적절하다.
- CTE safeguard(`depth < 20`) — 데이터 오염 시에도 무한 루프를 방지한다.
- Redis 트리 캐시 TTL(1h) — 캐시 갱신이 실패해도 1시간 내에 자동 만료된다.
- 동시성 시나리오별 전략 표(README.md §동시성 제어)가 체계적이다.

**개선 필요:**

- **BullMQ `board.events` 큐의 재시도 정책이 전혀 없다.** `board.permissions_updated` 이벤트가 실패하면 AuthModule의 권한 캐시가 갱신되지 않는다. 이는 "승인 권한이 삭제되었는데 캐시에 남아 있어 승인이 진행되는" 보안 사고로 이어질 수 있다. 재시도 횟수, 백오프 전략, DLQ 이동 후 수동 개입 절차가 필요하다.
- **타임아웃 설정이 없다.** 재귀 CTE가 대용량 트리(깊이 20, 수백 노드)에서 실행될 때의 쿼리 타임아웃이 미정의다. PostgreSQL `statement_timeout`을 Board 모듈 레벨에서 설정하는 가이드가 필요하다.
- **Redis 장애 시 폴백이 미설계다.** 트리 캐시(`cache:board:tree`)가 불가용하면 모든 `/boards/tree` 호출이 DB CTE를 직접 실행한다. 테넌트당 게시판 100개 이하라 당장은 문제없겠지만, 동시 요청이 집중되면 DB 부하가 급증할 수 있다. "캐시 미스 시 DB 조회 + 결과 캐시 재적재" vs "Redis 불가용 시 에러 반환" vs "Redis 불가용 시 무조건 DB 폴백"의 전략이 명시되어야 한다.
- **`board.permissions_updated` 이벤트 발행과 DB 커밋의 원자성이 불명확하다.** 시퀀스 다이어그램을 보면 DB COMMIT 후 BullMQ enqueue가 별도로 실행된다. enqueue가 실패하면 DB는 변경되었지만 캐시 무효화가 누락된다. Transactional Outbox 패턴 또는 "enqueue 실패 시 동기 캐시 무효화 폴백" 같은 보정이 필요하다.

---

#### EX-MS-SR-02. 참조 무결성 — 52/100 보통

문서 간 교차 참조를 꼼꼼히 대조한 결과, 치명적인 불일치가 발견되었다.

**잘 된 점:**

- FK 참조가 DDL 레벨에서 정확하다. `default_approval_template_id`는 approval/data.md의 `approval_line_template` 테이블을 정확히 참조한다.
- BR-BRD-016(결재라인 템플릿 삭제 시 ON DELETE SET NULL)과 approval/api.md의 `APR_TEMPLATE_IN_USE`(삭제 차단) 에러가 상호 보완적인 방어 체계를 형성한다.
- rules.md §4 규칙 요약 매트릭스가 17개 규칙을 트리거·에러 코드와 함께 정리하고 있어, 누락 검증이 용이하다.
- API 에러 코드가 rules.md의 BR-BRD-* 규칙과 정확히 매핑된다.

**개선 필요:**

- **[P1] 승인/버전 설정 상속 모델이 문서 간 불일치한다.** 이것은 이 리뷰에서 발견한 가장 심각한 문제다:
  - **data.md §설계 결정(line 83-84)**: "모든 게시판(루트·하위)에서 `approval_required`, `versioning_enabled`, `mandatory_approval_config`를 개별 설정할 수 있다. 명시적으로 값을 설정하면 상위 설정을 오버라이드한다." + 상속 의사코드 제공
  - **data.md §필드 정의(line 35)**: "하위 게시판은 null(상속) 또는 명시값(오버라이드)"
  - **FD-APR §2.7**: "하위 게시판 관리자가 자체 설정을 명시적으로 변경 가능"
  - **README.md(line 23)**: "루트 게시판에서만 설정, 하위 게시판은 루트 값 강제 상속"
  - **api.md UpdateBoardDto(line 242-243)**: "루트 게시판에서만 변경 가능. 하위 게시판에서 전달 시 400 에러"
  - **rules.md BR-BRD-006(line 174)**: "루트 게시판에서만 변경 가능. 하위 게시판은 루트 값 강제 상속"
  - DB 스키마(CHECK 제약)는 하위 게시판의 nullable 필드를 허용하여 오버라이드를 지원하는 구조이고, FD-APR도 오버라이드를 요구하는데, API/rules/README는 이를 차단한다. 주니어 개발자가 이 문서들을 보면 "DB는 가능하게 만들어놨는데 API에서 막는 건가? 의도적인 건가 실수인가?" 혼란에 빠진다.

- **[P1] `BoardConfig` TypeScript 인터페이스에 `notice` 섹션이 누락되어 있다.** data.md의 board_config JSON 스키마와 rules.md BR-BRD-017은 `notice`를 유효 최상위 키로 정의하는데, api.md의 TS 인터페이스에는 빠져 있다. 프론트엔드 개발자와 백엔드 구현자가 api.md의 인터페이스를 기준으로 코딩하면 공지 게시판의 전용 설정(팝업, 읽음 확인, 고정 문서 등)을 아예 처리하지 못한다.

- 구용어(`board_mode`, `BoardMode`, `approval_policy_id`) 잔존은 없다 — 이것은 확인 완료.

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P1 | EX-MS-SR-02 | 승인/버전 설정 상속 모델이 data.md(오버라이드 허용) vs README/api/rules(루트 전용)로 불일치. FD-APR §2.7도 오버라이드를 명시 | `data.md §설계결정`, `README.md §모듈책임`, `api.md §UpdateBoardDto`, `rules.md §BR-BRD-006` | decision | 구현자가 상속 모델을 확정할 수 없어 코딩 착수 자체가 차단됨. DB 스키마는 이미 오버라이드를 지원하는 구조 | "루트 전용"이면 data.md의 설계 결정과 의사코드를 수정. "오버라이드 허용"이면 README/api/rules를 수정하고 FD-APR과 정합. 어느 쪽이든 4개 파일이 동일한 한 가지 모델만 기술해야 함 |
| P1 | EX-MS-SR-02 | `BoardConfig` TS 인터페이스에 `notice` 섹션 누락 — data.md JSONB 스키마와 rules.md BR-BRD-017이 정의한 notice 그룹이 api.md에 없음 | `api.md §공통타입 BoardConfig` | add | 공지 게시판 전용 설정(팝업, 읽음 확인, 고정 문서 등)이 API 계약에서 빠져 프론트/백 모두 누락 위험 | `BoardConfig` 인터페이스에 `notice?: { defaultPopup?: boolean; defaultPopupFrequency?: 'once' \| 'every_login' \| 'daily'; ... }` 추가. data.md JSONB 스키마와 1:1 대응 |
| P2 | EX-MS-SR-01 | BullMQ `board.events` 큐의 재시도 정책·이벤트 스키마·멱등성 키 미정의 | `README.md §인프라사용요약`, `api.md §권한교체흐름` | add | 권한 캐시 무효화 실패 시 보안 사고(삭제된 권한이 캐시에 잔존) 가능성. 금융권에서 치명적 | README.md 또는 별도 events.md에 이벤트 계약 섹션 추가: 페이로드 TS 타입, 재시도 정책(지수 백오프 3회), 멱등 키 포맷, DLQ 처리 절차 |
| P2 | RD-MS-01 | `BoardResponse`에서 resolved 값과 raw 값 구분 불가 — 하위 게시판의 `approvalRequired`가 자체 설정인지 상속인지 판별 불가능 | `api.md §BoardResponse` | decision | 관리자 UI에서 "이 게시판의 자체 설정" vs "상위에서 상속"을 표시하려면 API가 양쪽을 모두 반환해야 함. 상속 모델 결정(P1)과 연동 | 상속 모델이 "오버라이드 허용"이면 `approvalRequiredRaw: boolean \| null` + `approvalRequiredResolved: boolean` 이중 반환 고려. "루트 전용"이면 현행 유지 가능 |
| P2 | RD-MS-05 | `BoardExportService.getMandatoryApprovalConfig` 반환 타입이 `Record<string, unknown>` 약타입 | `README.md §내부서비스인터페이스` | fix | 소비 모듈이 런타임 타입 가드를 작성해야 하며, 타입 안전성 없음 | `MandatoryApprovalConfig` 인터페이스를 정의하고 반환 타입을 `MandatoryApprovalConfig \| null`로 변경 |
| P2 | EX-MS-SR-01 | 이벤트 발행(BullMQ enqueue)과 DB 커밋의 원자성이 불명확 — enqueue 실패 시 캐시 무효화 누락 가능 | `api.md §권한교체흐름` | add | DB는 권한이 변경되었지만 캐시에 이전 권한이 남아 있는 불일치 윈도우 발생 가능 | (1) Transactional Outbox 패턴 적용, 또는 (2) enqueue 실패 시 동기 캐시 무효화 폴백, 또는 (3) 캐시 TTL을 짧게 설정하여 자연 만료 보정 — 선택한 전략을 명시 |
| P3 | RD-MS-02 | `board_config` PATCH deep-merge 동작의 구체적 before/after 예제 부재 | `api.md §UpdateBoardDto`, `rules.md §BR-BRD-017` | add | 최상위 키 단위 deep-merge의 정확한 동작이 불확실 — 하위 키 병합인지 그룹 전체 교체인지 구현자가 판단 불가 | BR-BRD-017 또는 api.md에 구체적 예제 추가: "기존 `{ comment: { enabled: true, max_depth: 3 } }`에 `{ comment: { enabled: false } }` 전달 시 → `{ comment: { enabled: false, max_depth: 3 } }`" |
| P3 | RD-MS-06 | 로깅 레벨 가이드 부재 — 어떤 에러가 INFO/WARN/ERROR인지 기준 없음 | `README.md §운영가이드` | add | 운영 중 로그 노이즈 제어 어려움. 알림 설정 기준 불명확 | 운영 가이드에 로깅 매트릭스 추가: OCC 충돌 → INFO, DLQ 적재 → WARN, CTE safeguard 도달 → ERROR 등 |
| P3 | RD-MS-06 | Redis 장애 시 폴백 전략 미비 — 트리 캐시 불가용 시 API 동작 미정의 | `README.md §운영가이드` | add | Redis 장애 시 DB 직접 조회 폴백의 성능 영향과 대응 방안이 없음 | 운영 가이드에 캐시 장애 시나리오 추가: "Redis 불가용 → DB CTE 폴백, 동시 요청 집중 시 connection pool 주의" 또는 서킷브레이커 적용 고려 |

## 설계 질문

| ID | 질문 | 블로킹 항목 |
|----|------|-------------|
| DQ-1 | **승인/버전 설정의 상속 모델**: data.md와 FD-APR §2.7은 "하위 게시판도 개별 오버라이드 가능"으로 기술하고, DB 스키마도 이를 지원하는 구조(nullable 필드)인데, README/api/rules는 "루트 전용"으로 차단한다. 의도된 설계가 어느 쪽인지? Phase 1에서는 루트 전용이고 향후 오버라이드를 열 계획이라면, 그 로드맵이 문서에 명시되어야 한다. | P1 #1, P2 #4 |
| DQ-2 | **`board.permissions_updated` 이벤트 발행 실패 시 보정 전략**: DB 커밋은 성공했으나 BullMQ enqueue가 실패한 경우, 어떤 전략을 사용할 것인지? Transactional Outbox? 동기 폴백? 캐시 TTL 의존? 이 결정이 없으면 권한 캐시 무효화의 신뢰성을 보장할 수 없다. | P2 #6 |
| DQ-3 | **`BoardConfig` 기본값의 관리 원천**: `getBoardConfig`가 "앱 레벨 기본값 병합 후 반환"한다고 되어 있는데, 이 기본값은 어디에 정의되는가? 코드 내 하드코딩? 환경변수? SystemConfig DB 테이블? 기본값 변경 시 재배포가 필요한지, 런타임 변경이 가능한지에 따라 설계가 달라진다. | — |
| DQ-4 | **`approval_required = true`이나 `default_approval_template_id = NULL`이고 `mandatory_approval_config = NULL`인 "불완전 승인 설정" 상태**: BR-BRD-016이 이 상태를 인지하고 있으나, 실제로 문서 제출(submit) 시 어떤 에러가 반환되는지의 책임이 Board인지 Document/Approval인지 불명확하다. 이 교차 모듈 검증의 오너십을 확정해야 한다. | — |
