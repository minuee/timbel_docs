> **문서 유형**: 모듈 스펙
> **종합 점수**: 67 / 100 (공용 73 × 0.6 + 전문 59 × 0.4)
> **리뷰 대상**: `docs/03-module-design/approval/` (README.md, data.md, api.md, rules.md + schedule.md 참조)
> **페르소나**: 최민재 — 시니어 백엔드 개발자 8년차 NestJS/TypeScript (AI)
> **리뷰일**: 2026-04-07 17:55
> **지적사항**: P1: 1건, P2: 7건, P3: 5건
> **자동 반영 가능**: 8건 / 설계 결정 필요: 5건

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-MS-01 | API 설계 품질 | 78 | 30% | RESTful 관례·에러 코드·피처 게이트가 견실하나, 내부 DTO와 템플릿 DTO 간 approver 구조 불일치 및 batch-decide 스텝 결정 로직 미기술 |
| RD-MS-02 | 구현 변환 용이성 | 72 | 10% | DDL·JSONB 예시·TypeScript 인터페이스가 충실하나, ROLE/TEAM → 실제 사용자 목록 해석 경로와 일부 구용어 잔존 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 58 | 25% | 4개 배치 작업·DLQ·분산 락·보정 배치가 체계적이나, **자동 반려 배치 SQL이 데이터 모델과 정면 불일치** |
| RD-MS-04 | 모듈 책임 범위 적절성 | 82 | 15% | Document Controller 오케스트레이션·Feature Gate 기반 비활성화·범위 제외 명시가 우수 |
| RD-MS-05 | 모듈 간 계약 명확성 | 68 | 10% | Document↔Approval 내부 계약이 명확하나, Board config 읽기 서비스 계약·Auth 역할 해석 인터페이스 미기술 |
| RD-MS-06 | 운영 고려사항 | 85 | 10% | 메트릭 9종·알림 임계값 7종·로그 레벨 가이드·외부 설정값 카탈로그가 실무 수준 |
| | **공용 소계** | **73** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-MS-SR-01 | 런타임 안정성 설계 | 62 | 50% | optimistic locking·분산 락·보정 배치가 있으나, Critical tx 타임아웃·서킷브레이커·BullMQ 재시도 전략이 schedule.md에 미기술 |
| EX-MS-SR-02 | 참조 무결성 | 55 | 50% | BR 카탈로그↔에러 코드 상호 참조가 견실하나, **schedule.md가 존재하지 않는 approval_line_template.sla_hours를 참조**하여 런타임 정합성 깨짐 |
| | **전문 소계** | **59** | 100% | |

### 종합: 67 / 100 (공용 73 × 0.6 + 전문 59 × 0.4)

---

## 차원별 상세 피드백

### 공용 차원

#### RD-MS-01. API 설계 품질 — 78/100 양호

**잘 된 점:**

- 엔드포인트 요약 테이블(api.md 상단)이 메서드·경로·설명·권한을 일목요연하게 정리하고 있어 전체 API 지형 파악이 쉽다.
- 모든 엔드포인트에 TypeScript interface로 Request/Response DTO가 정의되어 있고, `ApprovalStatus`, `StepApprovalType` 등 공통 타입도 별도 섹션으로 관리된다.
- 에러 코드 카탈로그가 api.md §에러 코드 참조에 20개 코드와 HTTP 상태·관련 BR·적용 엔드포인트를 매핑하여, 프론트엔드 개발자가 에러 핸들링을 구현할 때 바로 참조할 수 있다.
- `CreateApprovalInternalDto`를 별도 정의하여 공개 REST(Document Submit)와 내부 서비스 경계를 명확히 분리한 점은 금융권 SI에서 레이어 간 책임 분리에 부합한다.
- Feature Gate (`ft:approval.enabled`, `ft:approval.bypass` 등)가 엔드포인트 레벨에서 명시되어, Guard 구현 시 빠짐없이 적용할 수 있다.

**개선 필요 사항:**

1. **`CreateApprovalInternalDto.ApprovalStepDto.approvers[]` 구조 vs 데이터 모델 불일치 (P2)**: 내부 DTO의 `ApproverDto`는 `{ type, id }` 배열로 하나의 단계에 여러 타입의 승인자를 혼합할 수 있는 구조인데, data.md의 `ApprovalStepResult`는 `approver_source`(단일 VARCHAR)와 `approver_target`(JSONB)으로 **단계당 하나의 승인자 소스 유형**만 저장할 수 있다. 템플릿 DTO(`ApprovalTemplateStepDto`)는 `approverSource` + `approverTarget`으로 데이터 모델과 일관되나, 내부 Submit DTO만 다른 구조를 사용한다.

2. **`POST /approvals/batch-decide`의 stepOrder 자동 결정 로직 미기술 (P2)**: 개별 decide 엔드포인트는 `/:approvalId/steps/:stepOrder/decide`로 명시적 stepOrder를 받지만, batch-decide는 `approvalIds[]`만 받는다. 시스템이 각 건의 `current_step`을 자동으로 결정하여 처리한다는 점이 명시되지 않았다. 주니어 개발자가 구현 시 이 로직을 누락하거나 잘못 구현할 수 있다.

3. **`DecideDto.scheduledPublishAt` vs `POST /approvals/:approvalId/schedule` 이중 경로 (P3)**: 최종 단계 승인 시 인라인으로 예약 배포를 설정할 수도 있고, 별도 schedule 엔드포인트로도 설정할 수 있다. 두 경로의 우선순위, 이미 인라인 예약된 건에 대해 schedule 엔드포인트로 변경이 가능한지 여부가 불명확하다.

4. **`ft:approval.reject_comment_required` 위반 시 에러 코드 누락 (P3)**: 반려 시 코멘트 필수 피처 게이트가 활성화된 상태에서 코멘트 없이 반려하면 어떤 에러 코드가 반환되는지 정의되지 않았다. 전역 `VALIDATION_ERROR`로 처리할 수도 있지만, 도메인 특화 코드(예: `APR_REJECT_COMMENT_REQUIRED`)가 없으면 프론트엔드에서 적절한 UX를 제공하기 어렵다.

---

#### RD-MS-02. 구현 변환 용이성 — 72/100 양호

**잘 된 점:**

- data.md가 엔티티 필드 테이블 → JSONB 구조 예시 → 제약 조건 → 설계 결정 → DDL+인덱스 순으로 구성되어, 주니어 개발자가 위에서 아래로 읽으며 Entity 클래스와 Migration을 작성할 수 있다.
- `cc_list` JSONB, `steps` JSONB의 인라인/아웃라인 결정 근거(TOAST 임계값 2KB 미만, 항상 함께 로드 등)가 명시되어 있어 "왜 별도 테이블이 아닌가?" 질문에 답할 수 있다.
- rules.md의 BR 카탈로그가 트리거 → 조건 → 동작 → 위반 시 → 근거 구조로 일관되어, NestJS Guard/Service 로직에 1:1 대응시키기 용이하다.

**개선 필요 사항:**

1. **data.md §2.2 `total_steps` 설명에 "정책에서 복사" 구용어 잔존 (P2)**: "전체 단계 수 (요청 시점에 정책에서 복사)"라고 되어 있으나, 새 모델에서는 "정책"이라는 별도 엔티티가 없다. "요청 시점에 기안자가 구성한 결재라인의 총 단계 수"로 수정해야 한다. 주니어 개발자가 이 문구를 보고 존재하지 않는 Policy 엔티티를 찾으려 할 수 있다.

2. **ROLE/TEAM `approver_target` → 실제 승인 대상자 목록 해석 로직 미기술 (P3)**: `approver_source = 'ROLE'`이고 `approver_target = 'team_leader'`일 때, "해당 역할 + 게시판 APPROVE 권한 보유자"가 승인 대상이라고 명시하지만, 이 조회 로직(AuthModule 인터페이스, Board 컨텍스트 전달 방식)이 구체적으로 기술되지 않았다. 특히 TEAM의 경우 "팀 소속 + APPROVE 권한"의 교집합을 어떻게 쿼리하는지 서비스 메서드 시그니처가 필요하다.

3. **batch-decide가 건별 stepOrder를 어떻게 결정하는지 구현 가이드 없음**: RD-MS-01과 연관되나, 구현 관점에서 "각 approvalId에 대해 `Approval.current_step`을 읽어 해당 step에서 decide를 수행한다"는 한 줄이면 충분한데 누락되어 있다.

---

#### RD-MS-03. 이벤트/비동기 설계 건전성 — 58/100 보통

**잘 된 점:**

- schedule.md가 4개 배치 작업을 cron 주기·SQL·트랜잭션 범위·분산 락(Redis)·실패 처리까지 체계적으로 기술하고 있다. 특히 자동 반려 배치의 "부분 실패 허용 → 실패 건은 다음 주기에 재대상" 패턴은 금융권 배치에서 검증된 접근이다.
- 예약 배포 보정 배치(§2.4)가 BullMQ delayed job의 누락·DLQ 시나리오를 보완하는 Reconciliation 패턴을 적용한 점이 우수하다.
- README.md의 EventBus 발행 이벤트 11종이 명확히 열거되어 있고, 수신 이벤트(`board.config_updated`, `user.deactivated`)도 용도와 함께 기술되어 있다.
- 분산 락 TTL이 배치 주기와 정합 (자동 반려: 5분 락 + 5분 주기, 보정: 15분 락 + 30분 주기).

**개선 필요 사항:**

1. **[P1 치명적] schedule.md §2.1 자동 반려 SQL이 `approval_line_template.sla_hours`를 참조하지만, 해당 컬럼이 데이터 모델에 존재하지 않는다.** data.md의 `ApprovalLineTemplate` 엔티티에는 `id, name, description, steps, is_active, created_by, created_at, updated_at`만 있다. `sla_hours`와 `auto_reject_grace_hours`는 `Board.mandatory_approval_config` JSONB 내부 필드이다. 즉, 자동 반려 배치의 핵심 SQL 쿼리가 **실행 불가능**하다. 올바른 경로는 `Approval → Document → Board → mandatory_approval_config->>sla_hours`이며, Board 설정 상속(null이면 parent 추적)까지 고려해야 한다.

2. **schedule.md 자동 반려 배치에서 `approval.template_id`가 nullable인 점 미고려 (P2)**: 기안자가 템플릿 없이 직접 결재라인을 구성한 경우 `template_id = null`이므로, `JOIN approval_line_template t ON a.template_id = t.id`에서 해당 건이 누락된다. 템플릿 사용 여부와 무관하게 SLA는 Board 설정이므로 모든 pending 건이 대상이어야 한다.

3. **유지보수 모드 시 예약 배포(scheduled-publish) delayed job 도래 처리 미기술 (P2)**: BR-APR-027은 자동 반려의 SLA 일시 정지만 다루는데, 유지보수 모드 중 예약 배포 시점이 도래하면 어떻게 처리하는지(즉시 발행? 유지보수 종료 후 발행?) 정의되지 않았다.

4. **BullMQ scheduled-publish 큐의 재시도 전략이 schedule.md에 미기술 (P3)**: FD-APR §11.3에 "재시도(최대 3회) + 최종 실패 시 관리자 알림"이 명시되어 있으나, schedule.md에서 이를 BullMQ job 설정(attempts, backoff)으로 구체화하지 않았다.

---

#### RD-MS-04. 모듈 책임 범위 적절성 — 82/100 우수

**잘 된 점:**

- "승인 요청 생성의 HTTP 진입점은 Document Submit 한 곳" 원칙이 README.md, api.md 모두에서 명확히 선언되어 있어, 승인 모듈이 오케스트레이션 책임을 갖지 않는다는 점이 분명하다.
- "현재 범위 제외 기능" 테이블(README.md §범위 제외)이 FD 참조·제외 사유·향후 계획을 포함하여, Phase 1 범위가 명확히 절제되어 있다.
- Feature Gate 7종이 모듈 전체(`ft:approval.enabled`)부터 세부 기능(`ft:approval.multi_step.count_type`)까지 계층적으로 설계되어, 점진적 기능 활성화가 가능하다.

**개선 필요 사항:**

- 전반적으로 모듈 책임이 잘 정의되어 있다. 경미한 관찰 사항으로, `ApprovalLineTemplate` CRUD가 Approval 모듈에 있는데 Board의 `default_approval_template_id`로 연결되는 만큼 Board 관리 UI와의 워크플로 관계가 README.md에 한 줄 언급되면 좋겠다.

---

#### RD-MS-05. 모듈 간 계약 명확성 — 68/100 양호

**잘 된 점:**

- `CreateApprovalInternalDto` / `CreateApprovalInternalResult`가 TypeScript 인터페이스로 명확히 정의되어, Document Controller → ApprovalService 호출 계약이 구체적이다.
- 의존 관계 Mermaid 다이어그램(README.md)이 방향·유형(Critical tx, 읽기, EventBus)을 구분하여 시각화하고 있다.
- Critical 트랜잭션 경계(`transitionToPublished()`, `transitionToDraftOnReject()`)가 README.md 의존 관계 테이블에 명시되어 있다.

**개선 필요 사항:**

1. **Board 설정 읽기 서비스 인터페이스 미정의 (P2)**: ApprovalModule이 Board의 `approval_required`, `mandatory_approval_config`를 읽는다고 README.md에 명시되어 있지만, 실제 서비스 메서드 시그니처(예: `BoardService.getMandatoryApprovalConfig(boardId): MandatoryApprovalConfig`)가 없다. 특히 Board 설정 상속(null이면 parent 재귀 탐색) 로직의 책임이 BoardModule에 있는지 ApprovalModule에 있는지 불명확하다.

2. **AuthModule 역할/팀 해석 인터페이스 미정의 (P3)**: `approver_source = 'ROLE'`일 때 "해당 역할 + 게시판 APPROVE 권한 보유자" 목록을 어떻게 조회하는지, AuthModule의 서비스 메서드 시그니처가 approval 스펙 어디에도 없다. README.md 의존 관계에 "역할/팀/권한 조회"라고만 기술되어 있다.

---

#### RD-MS-06. 운영 고려사항 — 85/100 우수

**잘 된 점:**

- 메트릭 9종(README.md §주요 메트릭)이 수집 방식(API 미들웨어, 배치 카운터, BullMQ Dashboard)과 함께 정의되어 있고, `approval.decide_latency_ms` p95 < 500ms 등 목표치가 명시되어 있다.
- 모니터링 알림 임계값 7종(README.md §모니터링 알림 임계값)이 조건·심각도·채널로 구조화되어, Terraform/Pulumi로 알림 규칙을 자동화하기 용이하다. 특히 `scheduled_publish.failure_rate > 20%`에 PagerDuty 연동까지 명시한 점이 금융권 운영에 적합하다.
- 로그 레벨 가이드(README.md)가 작업별로 WARN/ERROR/INFO를 구분하여, 금융 감사에서 요구하는 "승인 우회 행위는 WARN 이상" 정책이 반영되어 있다.
- 외부 설정값 카탈로그 7종(README.md §외부 설정값 카탈로그)이 키·기본값·용도·참조를 포함하여, 배포 시 환경별 설정 차이를 한눈에 파악할 수 있다.

**개선 필요 사항:**

- 볼륨 예측이나 용량 계획(예: 일일 예상 승인 건수, ApprovalHistory 증가율, 인덱스 크기 예측)이 없어 인프라 사이징 시 별도 추정이 필요하다 (P3).

---

### 전문 차원

#### EX-MS-SR-01. 런타임 안정성 설계 — 62/100 양호

금융권 SI 3건을 리드하면서 "배치에서 장애가 발생하면 전체 업무가 멈춘다"는 경험을 여러 번 했다. 그 관점에서 이 설계를 보면:

**잘 된 점:**

- Optimistic locking(BR-APR-015)으로 동시 승인/반려 충돌을 처리하는 방식은 금융권에서 검증된 패턴이다. 불필요한 비관적 락 대기 없이 정합성을 보장한다.
- 4개 배치 작업 모두 분산 락(Redis)을 사용하고, TTL이 배치 주기보다 같거나 짧아 데드락을 방지한다.
- "부분 실패 허용 → 실패 건은 다음 주기에 재대상"은 배치 안정성의 기본이며, 모든 배치에 일관 적용되어 있다.
- 예약 배포 보정 배치(Reconciliation)가 BullMQ의 SPOF를 보완하는 점은 실무에서 매우 중요하다.

**개선 필요 사항:**

1. **Critical 트랜잭션 `transitionToPublished()` 호출의 타임아웃 미정의 (P2)**: 최종 승인 시 동일 트랜잭션에서 DocumentModule.transitionToPublished()를 호출하는데, 이 호출이 ES 인덱싱까지 포함하면 타임아웃이 발생할 수 있다. 트랜잭션 타임아웃 설정값과, 타임아웃 발생 시 롤백 후 재시도 전략이 명시되어야 한다. 금융권에서 "승인은 됐는데 발행이 안 된" 상태가 가장 위험하다.

2. **DocumentModule 장애 시 배치 작업 폴백 미정의 (P2)**: 자동 반려 배치가 `DocumentModule.transitionToDraftOnReject()`를 호출하는데, DocumentModule이 일시 장애일 때의 처리 방식(Circuit Breaker, 백오프 재시도, 건별 스킵 후 재큐잉)이 기술되지 않았다.

3. **BullMQ scheduled-publish job의 구체적 retry 설정 미기술 (P3)**: FD-APR에 "최대 3회 재시도"가 명시되어 있으나, schedule.md에서 BullMQ job 옵션(`attempts: 3, backoff: { type: 'exponential', delay: 5000 }` 등)으로 구체화하지 않았다.

---

#### EX-MS-SR-02. 참조 무결성 — 55/100 보통

8년간 금융 SI를 하면서 "문서 A에 쓰인 필드가 실제 테이블에 없다"는 이슈가 가장 시간을 많이 잡아먹었다. 이 관점에서 심각한 불일치가 하나 발견된다:

**잘 된 점:**

- rules.md의 BR-APR-001~030 카탈로그와 api.md의 에러 코드 카탈로그가 `관련 BR` 컬럼으로 양방향 참조되어 있다. 예를 들어 `APR_ALREADY_PENDING → BR-APR-007`, `BR-APR-007 → APR_ALREADY_PENDING(409)`이 교차 검증 가능하다.
- data.md의 DDL CHECK 제약 조건과 엔티티 필드 설명의 허용 값이 일치한다 (예: `CHECK (status IN ('pending', 'approved', ...))` vs 필드 설명 "6종 status").
- README.md의 핵심 엔티티 테이블이 data.md의 상세 정의와 1:1 대응된다.

**개선 필요 사항:**

1. **[P1 치명적] schedule.md §2.1 SQL이 `approval_line_template.sla_hours`를 참조하지만, data.md ApprovalLineTemplate에 해당 컬럼이 없다.** data.md §2.1 설계 결정에 "sla_hours 등 정책 옵션은 게시판의 mandatory_approval_config JSONB로 이동"이라고 명시적으로 기술했음에도, schedule.md SQL이 구 모델 기준으로 작성되어 있다. 이는 단순 오타가 아니라 **조인 경로 자체가 다른** 구조적 불일치이다.

2. **data.md §2.2 total_steps 설명 "정책에서 복사" — 존재하지 않는 "정책" 엔티티 참조 (P2)**: 앞서 RD-MS-02에서도 언급했지만, 참조 무결성 관점에서도 data.md 내부의 자기 모순이다. §2.1에서 "정책 → Board 이동"을 명확히 기술했으면서 §2.2에서 "정책에서 복사"라고 쓴 것은 리팩토링 누락이다.

3. **FD-APR 이벤트 계약의 `policy_snapshot` 페이로드 필드 (P3)**: FD-APR 이벤트 계약 테이블에서 `approval.submitted` 이벤트의 페이로드에 `policy_snapshot`이 있다. 모듈 스펙에서는 "정책"이 Board config로 이동했으므로, 이 필드명도 `board_approval_config_snapshot` 등으로 정합을 맞추거나, events.md에서 FD와의 차이를 명시해야 한다 (단, events.md는 이번 리뷰 직접 대상이 아님).

4. **자동 반려 배치 SQL에서 `Approval.type` 필터 누락 (P3)**: DELETE 타입 승인 건도 SLA 자동 반려 대상인지 여부가 규칙(rules.md)과 배치(schedule.md) 어디에도 명시되지 않았다.

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P1 | EX-MS-SR-02, RD-MS-03 | schedule.md §2.1 SQL이 `approval_line_template.sla_hours`를 참조하나, data.md에 해당 컬럼 없음. SLA는 `Board.mandatory_approval_config`에 위치 | `schedule.md §2.1`, `data.md §2.1` | fix | 자동 반려 배치가 실행 불가 — 런타임 장애 직결. template_id nullable이므로 JOIN 자체도 전수 누락 가능 | SQL을 `Approval → Document → Board` 경로로 재작성. Board 설정 상속(parent 재귀)은 앱 레이어 함수로 분리. `BoardService.getEffectiveMandatoryConfig(boardId)` 계약 추가 |
| P2 | RD-MS-01 | `CreateApprovalInternalDto.ApproverDto`가 `{type, id}` 배열로 혼합 타입 허용 가능하나, `ApprovalStepResult.approver_source`는 단일 값 | `api.md §연동 계약` | fix | DTO가 데이터 모델보다 넓은 구조 허용 → 구현 시 매핑 오류 또는 런타임 검증 누락 가능 | (A) DTO를 `approverSource` + `approverTarget`으로 통일하거나, (B) 혼합 타입 허용 시 data.md 설계 변경 필요 |
| P2 | RD-MS-01 | batch-decide가 stepOrder 없이 동작하는 로직(current_step 자동 사용) 미기술 | `api.md §batch-decide` | add | 구현자가 step 결정 로직을 누락하거나 전체 step iterate할 수 있음 | "각 approvalId에 대해 Approval.current_step을 읽어 해당 단계에서 decide 수행" 한 줄 추가 |
| P2 | EX-MS-SR-02 | data.md §2.2 total_steps 설명 "정책에서 복사" — 새 모델에 "정책" 엔티티 없음 | `data.md §2.2` | fix | 구현자가 존재하지 않는 Policy 엔티티를 찾으려 할 수 있음 | "요청 시점에 기안자가 구성한 결재라인의 총 단계 수"로 수정 |
| P2 | RD-MS-05 | Board `mandatory_approval_config` 읽기 서비스 계약(상속 포함) 미정의 | `README.md §의존 관계`, `api.md` | add | Approval이 Board 설정을 읽는 경로가 암묵적 → 구현자마다 다른 방식으로 접근할 수 있음 | `BoardService.getEffectiveMandatoryConfig(boardId)` 서비스 메서드 시그니처와 반환 타입을 api.md 연동 계약 섹션에 추가 |
| P2 | EX-MS-SR-01 | Critical tx `transitionToPublished()` 타임아웃·서킷브레이커 미정의 | `README.md §의존 관계`, `schedule.md` | add | 최종 승인 시 DocumentModule 장애로 "승인됐지만 미발행" 상태 발생 가능 — 금융권에서 가장 위험한 시나리오 | 트랜잭션 타임아웃 5s, 실패 시 Approval.status를 롤백하고 재시도 큐에 등록하는 보상 로직 명시 |
| P2 | RD-MS-03 | 유지보수 모드 시 예약 배포(scheduled-publish) job 도래 처리 미정의 | `schedule.md §2.4`, `rules.md` | decision | 점검 중 예약 시점 도래 시 즉시 발행할지 점검 후 발행할지 결정 필요 | BR-APR-027 확장 또는 별도 BR 추가. 추천: 유지보수 종료 후 보정 배치에서 처리 |
| P3 | RD-MS-01 | `DecideDto.scheduledPublishAt` vs `POST /schedule` 이중 경로 관계 불명확 | `api.md §decide, §schedule` | add | 예약 설정·변경의 우선순위 및 변경 가능 여부 혼란 | api.md §schedule에 "이미 인라인 예약된 건의 변경은 이 엔드포인트 사용" 등 관계 명시 |
| P3 | RD-MS-01 | `ft:approval.reject_comment_required` 위반 시 전용 에러 코드 없음 | `api.md §에러 코드`, `rules.md §4` | add | 프론트엔드가 구체적 에러 핸들링 불가 | `APR_REJECT_COMMENT_REQUIRED` (422) 추가 |
| P3 | RD-MS-05 | AuthModule 역할/팀→사용자 목록 해석 서비스 인터페이스 미정의 | `README.md §의존 관계` | add | ROLE/TEAM approver 해석 시 구현자마다 다른 쿼리 전략 가능 | `AuthService.getApproversByRole(role, boardId)`, `AuthService.getApproversByTeam(teamId, boardId)` 시그니처 추가 |
| P3 | RD-MS-06 | 볼륨 예측·용량 계획 없음 | `README.md` | add | 인프라 사이징 시 별도 추정 필요 | 일일 예상 승인 건수, ApprovalHistory 증가율, 인덱스 크기 예측 섹션 추가 |
| P3 | EX-MS-SR-02 | 자동 반려 배치에서 `Approval.type = 'DELETE'` 건의 SLA 적용 여부 미명시 | `schedule.md §2.1`, `rules.md BR-APR-022` | decision | DELETE 타입도 SLA 자동 반려 대상인지 설계 결정 필요 | rules.md BR-APR-022 조건에 type 필터 추가, schedule.md SQL WHERE절에 반영 |

---

## 설계 질문

| ID | 질문 | 블로킹 항목 |
|----|------|-------------|
| DQ-1 | `CreateApprovalInternalDto`의 `ApproverDto`가 한 단계에 `USER`와 `ROLE`을 혼합하여 전달하는 것을 허용하려는 의도인가, 아니면 단계당 단일 소스 타입만 허용하려는 것인가? 허용한다면 data.md의 `approver_source` 단일 컬럼 구조와 어떻게 매핑하는가? | P2 #2 |
| DQ-2 | 유지보수 모드 중 예약 배포(scheduled-publish) 시점이 도래하면 (A) 즉시 발행, (B) 유지보수 종료 후 보정 배치에서 발행, (C) 큐에 대기 후 유지보수 종료 시 자동 처리 중 어떤 전략을 취하는가? | P2 #7 |
| DQ-3 | `Approval.type = 'DELETE'`인 건도 SLA 자동 반려 대상인가? 삭제 요청은 게시판 SLA와 동일 정책을 따르는가, 별도 SLA를 갖는가? | P3 #5 |
| DQ-4 | 최종 승인 시 `DocumentModule.transitionToPublished()` 호출이 실패하면(타임아웃, 커넥션 풀 고갈 등), Approval.status는 롤백되어 `pending`으로 유지되는가, 아니면 `approved`로 커밋되고 발행만 재시도하는가? 전자라면 승인자가 다시 승인해야 하는 UX 문제가 있고, 후자라면 "승인됐지만 미발행" 상태의 보상 트랜잭션이 필요하다. | P2 #6 |
| DQ-5 | `DecideDto.scheduledPublishAt`로 인라인 예약한 건에 대해, 이후 `POST /approvals/:approvalId/schedule`로 예약 시간을 변경할 수 있는가? 가능하다면 기존 BullMQ job을 삭제하고 재등록하는 흐름인가? | P3 #1 |
