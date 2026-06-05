> **문서 유형**: 모듈 스펙
> **종합 점수**: 79 / 100 (공용 80.0 × 0.6 + 전문 77.5 × 0.4)
> **리뷰 대상**: `docs/03-module-design/approval/` (README.md, data.md, api.md, rules.md, schedule.md)
> **페르소나**: 최민재 — 시니어 백엔드 개발자 8년차, NestJS/TypeScript (AI)
> **리뷰일**: 2026-04-07 18:09
> **라운드**: Round 2 (Round 1: 67점 → Round 2: 79점, +12점)
> **지적사항**: P1: 0건, P2: 4건, P3: 5건
> **자동 반영 가능**: 6건 / 설계 결정 필요: 3건

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-MS-01 | API 설계 품질 | 82 | 30% | DTO 매핑·batch-decide 자동 단계 결정 로직 추가로 구현 모호성 대폭 해소; schedule API 두 경로 선후관계만 보완 필요 |
| RD-MS-02 | 구현 변환 용이성 | 80 | 10% | TypeScript 인터페이스·DDL·배치 SQL이 구현 1:1 변환 수준; ORM 레이어 매핑 힌트 없으나 범위 외 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 78 | 25% | 11종 이벤트·DLQ·멱등 키·재시도 전략 건전; 이벤트 페이로드에 traceId·단계 상세 누락 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 82 | 15% | 12개 책임 영역과 제외 범위가 명확; Submit 오케스트레이션 경계 확정됨 |
| RD-MS-05 | 모듈 간 계약 명확성 | 76 | 10% | BoardExportService 계약 추가로 크게 개선; AuthModule 계약·Document Critical tx 시그니처 미정의 |
| RD-MS-06 | 운영 고려사항 | 80 | 10% | 메트릭 9종·알림 7종·Critical tx 타임아웃·유지보수 모드 폴백 우수; 데이터 아카이브·cron timezone 미명시 |
| | **공용 소계** | **80.0** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-MS-SR-01 | 런타임 안정성 설계 | 79 | 50% | Critical tx 롤백·유지보수 모드·배치 폴백이 추가되어 크게 개선; batch-decide 트랜잭션 경계·cc_list lock contention 미정의 |
| EX-MS-SR-02 | 참조 무결성 | 76 | 50% | DDL CHECK/UNIQUE 제약 건전; total_steps ↔ ApprovalStepResult 행 수 불변 조건·외부 사용자 참조 dangling 대응 미명시 |
| | **전문 소계** | **77.5** | 100% | |

### 종합: 79 / 100 (공용 80.0 × 0.6 + 전문 77.5 × 0.4)

---

## 차원별 상세 피드백

### 공용 차원

#### RD-MS-01. API 설계 품질 — 82/100 양호

Round 1에서 지적한 핵심 P2 두 건(ApproverDto → approver_source/approver_target 매핑, batch-decide stepOrder 자동 결정)이 모두 반영되어 **구현 시 가장 큰 모호성이 해소**되었다. 특히 api.md의 "DTO → ApprovalStepResult 매핑" 단락(line 106)에서 **"배열 DTO ≠ 복수 행"이고 `approver_source` 단일 값 + `approver_target` JSONB**로 대응된다는 설명은 실제 Service 레이어 코딩 시 판단 근거가 된다.

batch-decide 설명(line 452)의 "서버는 각 건에 대해 `Approval.status === 'pending'`이고 `ApprovalStepResult.step_order === Approval.current_step`인 현재 활성 단계를 자동으로 특정"이라는 문구도 명확해졌다.

**잔여 개선 사항**:
- `POST /approvals/:approvalId/schedule`(사후 예약 설정)과 `POST /approvals/:approvalId/steps/:stepOrder/decide`의 `scheduledPublishAt` 파라미터(승인 시점 즉시 예약) — 두 경로의 우선순위와 상호배타 관계가 명시되지 않았다. 승인 시 `scheduledPublishAt`을 넘기면 schedule API를 별도 호출할 필요가 없는 건지, 혹은 승인 후에만 schedule이 가능한 건지 한 줄 가이드가 필요하다.
- `GET /approvals/inbox`의 `slaRemainingSeconds`와 `slaDeadlineAt` 두 필드를 동시에 반환하는데, 클라이언트가 어느 것을 primary로 사용해야 하는지 안내가 없다. 타임존 차이로 인한 UI 혼란을 방지하려면 하나를 권장 필드로 명시하는 것이 좋다.

#### RD-MS-02. 구현 변환 용이성 — 80/100 양호

TypeScript 인터페이스로 모든 Request/Response DTO가 정의되어 있어 NestJS 프로젝트에서 `class-validator` 데코레이터를 씌우는 수준으로 바로 구현 가능하다. DDL이 CREATE TABLE + INDEX + CHECK 완전체로 제공되며, schedule.md의 배치 SQL도 복사 후 파라미터만 바인딩하면 되는 수준이다.

total_steps 설명이 "기안자가 구성한 결재라인의 단계 수"로 수정(Round 1 P2 반영)되면서, 구현자가 혼동 없이 `steps.length`를 세팅할 수 있게 되었다.

#### RD-MS-03. 이벤트/비동기 설계 건전성 — 78/100 양호

FD-APR의 이벤트 계약 테이블(11종)과 README의 EventBus 항목, schedule.md의 이벤트 발행 시점이 정합한다. `schemaVersion: 1` 포함, 멱등 키 `{event_name}:{approval_id}:{step_order}` 패턴, BullMQ 재시도(5s→10s→20s, 3회 후 DLQ) 등 비동기 신뢰성 설계가 건전하다.

**잔여 개선 사항**:
- FD-APR 이벤트 계약에서 "모든 이벤트 페이로드에 `traceId`(OpenTelemetry) 포함"이라고 기술하는데, 실제 이벤트 인터페이스 정의에 `traceId` 필드가 빠져 있다. 구현자가 누락할 수 있으므로 공통 base 인터페이스에 명시하거나, 이벤트 목록 테이블에 공통 필드를 주석으로 한 번 적어두면 좋다.
- `approval.step.approved` 이벤트 페이로드에 `approval_type`이나 승인 인원 수 같은 단계 상세가 없다. 소비자(NTF 등)가 "3명 중 2명 승인으로 통과"라는 알림을 구성하려면 추가 조회가 필요하다. Phase 1에서는 범위 외일 수 있으나, 향후 확장 시 이벤트 보강이 필요할 지점이다.

#### RD-MS-04. 모듈 책임 범위 적절성 — 82/100 양호

12개 책임 영역이 명확하고, 제외 범위 3건(단계별 SLA, 에스컬레이션, 사후 검토)이 Phase 2 계획과 함께 기술되어 있어 범위 관리가 우수하다. Submit 진입점이 Document Controller에 있다는 ADR-011 A-2 결정이 README, api.md, FD-APR에서 일관되게 참조되고 있다.

BoardExportService 계약을 통해 "Approval이 Board 테이블을 직접 조인하지 않는다"는 모듈 경계 원칙이 확립된 것도 좋다.

#### RD-MS-05. 모듈 간 계약 명확성 — 76/100 양호

Board 모듈 내부 계약(`getMandatoryApprovalConfig`)이 TypeScript 인터페이스로 추가된 것은 Round 1 대비 큰 개선이다. CreateApprovalInternalDto/Result도 경계가 명확하다.

**잔여 개선 사항**:
- **AuthModule 계약 미정의**: Approval에서 AUTH를 "읽기"로 의존하는데(README 의존 관계), 구체적으로 어떤 메서드를 호출하는지 인터페이스가 없다. `USER` source일 때 특정 사용자의 APPROVE 권한 검증, `ROLE`/`TEAM` source일 때 해당 역할/팀의 승인 가능자 풀 조회 등 — 최소한 시그니처 수준의 계약이 필요하다.
- **DocumentModule Critical tx 시그니처**: `transitionToPublished()`, `transitionToDraftOnReject()`의 파라미터(documentId만? + approvalId? + transactionManager?)가 명시되지 않았다. 동일 트랜잭션 호출이라면 `EntityManager`/`PrismaClient` 인스턴스를 인자로 넘기는 패턴일 텐데, 이 계약 수준의 힌트가 있으면 구현 경계가 더 명확해진다.

#### RD-MS-06. 운영 고려사항 — 80/100 양호

Round 1 P2로 추가된 항목들(Critical tx 타임아웃 30~60초, 유지보수 모드 체크, DocumentModule 장애 폴백)이 모두 적절하게 반영되었다. 특히 schedule.md §2.4의 "DocumentModule 장애 시 폴백" 섹션에서 지수 백오프 재시도(5s→30s→2m), 배치 주기 내 재후보 유지, ERROR 로그·메트릭 연계까지 실무적이다.

메트릭 9종과 알림 7종도 운영에 필요한 핵심 지표를 잘 커버하고 있다.

**잔여 개선 사항**:
- 배치 cron이 UTC 기준인지 서버 로컬 타임존인지 명시되지 않았다. 특히 위임 만료(`0 0 * * *`)와 리마인더(`0 9 * * *`)는 KST/UTC 차이에 따라 사용자 체감이 달라진다.
- Approval/ApprovalHistory 테이블의 데이터 보관 주기·아카이브 전략이 없다. 금융권 5년 보관 요건(FD-APR 비기능 요구사항)이 있으므로, 테이블 파티셔닝이나 cold storage 이관 시점을 최소한 언급할 필요가 있다.

---

### 전문 차원

#### EX-MS-SR-01. 런타임 안정성 설계 — 79/100 양호

Round 1에서 가장 큰 약점이었던 **Critical tx 원자성 보장**과 **유지보수 모드 대응**이 대폭 보강되었다.

- rules.md §1.4의 타임아웃(30~60초)·롤백·비동기 단계 실패 보상 지침이 NestJS `@Transaction()` 데코레이터 또는 `queryRunner.startTransaction()` 패턴으로 바로 변환 가능한 수준이다.
- schedule.md §2.1의 유지보수 모드 전역 일시 정지 + `effective_elapsed` 계산 로직은 BR-APR-027과 정합한다.
- §2.4의 DocumentModule 장애 폴백(재시도 3회 + 다음 주기 재대상)도 실무적이다.

**잔여 개선 사항**:
- **batch-decide 트랜잭션 경계**: 50건 순차 처리 시 **건별 독립 트랜잭션**인지, **전체 단일 트랜잭션**인지 명시되지 않았다. "부분 실패 분리 보고"라는 설명으로 건별 트랜잭션으로 추정되나, 명시적 가이드가 필요하다. 단일 트랜잭션이면 1건 실패에 49건이 롤백되는 치명적 상황이 발생한다.
- **cc_list JSONB의 `read_at` 갱신 경합**: CC 대상자가 승인 건을 열람하면 `Approval.cc_list` JSONB 내부의 `read_at`이 UPDATE된다. 이때 Approval 행 전체에 row-level lock이 걸리므로, 승인 처리(`decide`)와 CC 열람이 동시에 발생하면 lock contention이 생길 수 있다. 승인 건당 CC가 0~5명으로 저빈도라 실질적 영향은 낮지만, 금융권 분기 약관 개정 같은 대량 승인 시나리오에서는 주의가 필요하다.
- 자동 반려 배치 SQL의 WITH RECURSIVE + `maintenance_pause_interval` 합성이 복잡한데, `approval` 테이블의 `created_at` 인덱스와 `board` 테이블의 `parent_id` 인덱스가 CTE를 효과적으로 지원하는지 실행 계획 검증 힌트가 없다. EXPLAIN ANALYZE 결과까지는 불필요하나, "트리 깊이 ≤ 10, 배치 상한 100건이므로 N+1 허용" 같은 성능 가정을 명시하면 코드 리뷰 시 도움이 된다 (schedule.md에 서비스 레이어 대안 단락에서 일부 언급하고 있으나, SQL 경로에 대한 힌트는 없다).

#### EX-MS-SR-02. 참조 무결성 — 76/100 양호

DDL의 CHECK/UNIQUE/FK 제약이 비즈니스 규칙과 1:1로 대응하며, 특히 `uq_delegation_active WHERE is_active = true` partial unique index는 PostgreSQL 특성을 잘 활용한 설계다. ApproverDto → ApprovalStepResult 매핑 규칙이 추가되면서 DTO-DB 간 형변환 규칙이 명확해졌다.

**잔여 개선 사항**:
- **total_steps ↔ ApprovalStepResult 행 수 불변 조건**: `Approval.total_steps`는 "기안자가 구성한 결재라인의 단계 수"인데, 이 값이 실제 `ApprovalStepResult` 행 수와 항상 일치해야 한다. DB CHECK 제약으로는 보장이 어렵지만, 앱 레벨에서 이 불변 조건을 어떻게 보장하는지(예: 승인 건 생성 트랜잭션에서 `steps.length` 검증) 언급이 없다.
- **외부 사용자 참조 dangling 대응**: `requester_id`, `approver_id`, `delegator_id`, `delegate_id` 등이 외부 UserService를 참조하지만 FK가 없다(마이크로서비스 패턴). `user.deactivated` 이벤트를 수신하여 위임 자동 해제(BR-APR-021)하는 것은 있지만, 사용자가 삭제/비활성화된 후 Approval 건의 `requester_id`나 `approver_id`가 dangling 참조가 되었을 때의 표시/조회 전략(예: "탈퇴한 사용자" placeholder)이 명시되지 않았다.
- `ApprovalStepResult.approver_target` JSONB 내 UUID 배열(USER 유형)의 유효성은 앱 레벨에서만 보장된다. BR-APR-030에서 승인 요청 시 APPROVE 권한을 검증하므로 생성 시점에는 문제없으나, 승인 대기 중에 사용자가 비활성화되면 해당 단계의 승인 가능자 풀이 줄어드는 상황의 대응이 BR-APR-008의 "승인 가능자 없음" 분기에서 처리되는지 확인이 필요하다.

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P2 | EX-MS-SR-01 | batch-decide 50건 처리의 트랜잭션 경계(건별 vs 전체)가 미명시 | api.md §batch-decide, rules.md §BR-APR-016 | add | 건별 트랜잭션이 아니면 1건 실패에 전체 롤백 위험 | "각 건을 독립 트랜잭션으로 처리" 명시 + 실패 건 스킵 후 계속 진행 확인 |
| P2 | RD-MS-05 | AuthModule 계약(승인자 풀 조회·APPROVE 권한 검증) 인터페이스 미정의 | api.md §연동 계약, README.md §의존 관계 | add | USER/ROLE/TEAM별 승인 가능자 해석이 구현자에게 위임됨 | BoardExportService와 동일 수준으로 AuthExportService 시그니처 추가 |
| P2 | RD-MS-05 | DocumentModule Critical tx 메서드 시그니처(파라미터 목록) 미정의 | api.md §연동 계약 | add | transactionManager 전달 패턴이 불명확하여 구현 시 모듈 경계 혼선 | `transitionToPublished(documentId, txManager?)` 수준의 시그니처 추가 |
| P2 | EX-MS-SR-02 | total_steps ↔ ApprovalStepResult 행 수 불변 조건 보장 방법 미명시 | data.md §2.2, rules.md | add | 불일치 시 current_step > total_steps 판정 오류로 영구 pending 가능 | 승인 건 생성 트랜잭션에서 `total_steps === steps.length` 앱 레벨 검증 명시 |
| P3 | RD-MS-01 | decide의 scheduledPublishAt과 schedule API의 선후관계·상호배타 미명시 | api.md §decide, §schedule | add | 두 경로가 동시에 존재하여 구현 시 중복 설정 가능성 | "decide에서 scheduledPublishAt 지정 시 별도 schedule 호출 불필요" 등 한 줄 가이드 추가 |
| P3 | RD-MS-03 | 이벤트 페이로드에 traceId 공통 필드가 인터페이스에 누락 | FD-APR §이벤트 계약 | add | 구현자가 누락할 수 있음 | 이벤트 공통 base 타입에 `traceId: string` 명시 |
| P3 | RD-MS-06 | 배치 cron의 timezone 기준(UTC vs KST) 미명시 | schedule.md §1, README.md §외부 설정값 | add | 위임 만료(00:00)·리마인더(09:00)가 timezone에 따라 사용자 체감 달라짐 | "모든 cron은 UTC 기준, 사용자 facing 배치는 tenant timezone 변환" 등 명시 |
| P3 | RD-MS-06 | Approval/ApprovalHistory 데이터 보관 주기·아카이브 전략 없음 | data.md §3, README.md | add | 금융권 5년 보관 요건 대비 장기 데이터 증가 대응 부재 | 테이블 파티셔닝(created_at 월별) 또는 cold storage 이관 시점 최소 언급 |
| P3 | EX-MS-SR-01 | cc_list JSONB read_at 갱신 시 Approval 행 전체 lock → 승인 처리 경합 가능성 | data.md §2.2 | decision | 대량 승인 시나리오에서 CC 열람과 decide가 동시 발생하면 contention | JSONB 부분 UPDATE 패턴 또는 CC 열람을 별도 비동기 UPDATE로 분리 검토 |

---

## 설계 질문

| ID | 질문 | 블로킹 항목 |
|----|------|-------------|
| DQ-1 | batch-decide에서 각 건을 독립 트랜잭션으로 처리한다는 의도가 맞는지? 아니면 전체를 하나의 트랜잭션으로 묶는 의도인지? | P2 #1 |
| DQ-2 | decide API의 `scheduledPublishAt` 파라미터와 별도 schedule API — 전자는 "승인과 동시에 예약", 후자는 "승인 완료 후 사후 예약 설정"으로 이해하면 되는지? 두 경로가 동시에 적용되면 어느 것이 우선인지? | P3 #5 |
| DQ-3 | cc_list의 read_at 갱신이 Approval 행 lock을 유발하는 문제 — Phase 1에서는 CC 0~5명·저빈도이므로 무시하고, 향후 트래픽 증가 시 별도 테이블 분리를 검토하는 방향이 맞는지? | P3 #9 |

---

## Round 1 대비 개선 요약

| 수정 항목 | Round 1 지적 | 반영 상태 | 점수 영향 |
|-----------|-------------|-----------|-----------|
| 자동 반려 SQL → Board.mandatory_approval_config WITH RECURSIVE | P1 — 정책 테이블 참조 오류 | ✅ 완전 반영 (schedule.md §2.1) | RD-MS-01/EX-MS-SR-01 대폭 개선 |
| ApproverDto → approver_source/approver_target 매핑 | P2 — 구현 모호성 | ✅ 완전 반영 (api.md line 106) | RD-MS-01 +5점 이상 |
| batch-decide stepOrder 자동 결정 | P2 — 구현 모호성 | ✅ 완전 반영 (api.md line 452) | RD-MS-01 개선 |
| total_steps 설명 정정 | P2 — 용어 혼란 | ✅ 완전 반영 (data.md §2.2) | RD-MS-02/EX-MS-SR-02 개선 |
| BoardExportService 계약 추가 | P2 — 모듈 계약 부재 | ✅ 완전 반영 (api.md + README.md) | RD-MS-05 +8점 이상 |
| Critical tx 타임아웃·보상 | P2 — 런타임 안정성 | ✅ 완전 반영 (rules.md §1.4) | EX-MS-SR-01 +10점 이상 |
| 유지보수 모드 + DocModule 폴백 | P2 — 운영 고려 | ✅ 완전 반영 (schedule.md §2.1, §2.4) | RD-MS-06/EX-MS-SR-01 개선 |

**총평**: Round 1의 P1 1건, P2 6건이 모두 충실하게 반영되어 종합 67점 → 79점으로 12점 상승했다. 특히 자동 반려 SQL의 WITH RECURSIVE 전환과 Critical tx 타임아웃/보상 지침 추가가 런타임 안정성 차원에서 가장 큰 기여를 했다. 현재 잔여 P2는 모듈 간 계약 완성도(AuthModule, DocumentModule 시그니처)와 데이터 불변 조건 보장에 집중되어 있으며, P1(치명) 수준의 이슈는 없다. **양호(80점대 진입 직전)** 수준으로, P2 4건 반영 시 80점 이상 달성이 가능하다.
