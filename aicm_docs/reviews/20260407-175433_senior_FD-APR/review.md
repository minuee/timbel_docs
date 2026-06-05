> **문서 유형**: FD (기능정의서)
> **종합 점수**: 65 / 100 (공용 68 × 0.6 + 전문 61 × 0.4)
> **리뷰 대상**: `docs/01-requirements/features/FD-APR-승인워크플로.md`
> **페르소나**: 최민재 — 시니어 백엔드 개발자 8년차 (NestJS/TypeScript, 금융권 SI 3건 리드) (AI)
> **리뷰일**: 2026-04-07 17:54
> **지적사항**: P1: 3건, P2: 5건, P3: 3건
> **자동 반영 가능**: 7건 / 설계 결정 필요: 4건

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-FD-01 | 비즈니스 규칙 명확성 | 72 | 30% | BR 27개의 트리거·조건·동작이 대체로 구체적이나, BR-APR-012 서술 모순과 BR-APR-027 누락이 구현 시 혼란 유발 |
| RD-FD-02 | 상태 전이 완결성 | 72 | 20% | PUBLISH 시나리오의 상태 다이어그램은 충실하나, DELETE 승인 전이와 published→draft 재편집 경로가 다이어그램에서 누락 |
| RD-FD-03 | 데이터 모델 설계 타당성 | 50 | 20% | FD 엔티티 스키마와 data.md 간 구조적 불일치 다수 — ApprovalAction/Decision 이름, CC 테이블/JSONB, is_bypass 잔존, type 필드 부재 |
| RD-FD-04 | 확장성/유연성 | 82 | 15% | 피처 게이트, Phase 분리, 게시판 상속/오버라이드, 템플릿 시스템이 확장에 충분한 여유를 제공 |
| RD-FD-05 | 규칙 간 정합성 | 58 | 10% | BR-APR-012 "항상 허용" vs pending 제한 모순, 위임+자기승인 교차, mandatory_steps+max_steps 충돌 시나리오 미정의 |
| RD-FD-06 | 비기능 요구 완전성 | 70 | 5% | API 응답시간·큐 분리·스케줄러 정밀도 정의됨. 승인 레코드 보존 기간, Rate Limiting 정책 누락 |
| | **공용 소계** | **68** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-FD-SR-01 | 비즈니스 규칙 구현 충분성 | 62 | 40% | API DTO·이벤트 계약은 충실하나, 엔티티 스키마가 data.md와 불일치하여 "어느 쪽을 구현할지" 판단 불가 |
| EX-FD-SR-02 | 규칙-기능 추적 완전성 | 65 | 30% | 대부분의 BR이 섹션 참조를 가지나, BR-APR-027(유지보수 SLA 정지)이 FD에 없고 DELETE 승인 시나리오가 전무 |
| EX-FD-SR-03 | 암묵적 복잡도 노출 | 55 | 30% | 동시 처리·COUNT 조기 반려는 잘 다루었으나, 위임↔자기승인·mandatory_steps↔max_steps·ROLE/TEAM 런타임 해석 등 교차 복잡도 미노출 |
| | **전문 소계** | **61** | 100% | |

### 종합: 65 / 100 (공용 68 × 0.6 + 전문 61 × 0.4)

---

## 차원별 상세 피드백

### 공용 차원

#### RD-FD-01. 비즈니스 규칙 명확성 — 72/100 양호

FD-APR의 비즈니스 규칙 카탈로그(§비즈니스 규칙 카탈로그)는 BR-APR-001부터 BR-APR-030까지 27개 규칙을 일목요연하게 정리하고 있으며, 대부분의 규칙에 트리거·조건·동작·참조 섹션이 명시되어 있다. 특히 BR-APR-001/002의 승인 유형별 통과/반려 판정 규칙은 ANY·ALL·COUNT 각각에 대해 구체적 조건을 서술하여, NestJS 서비스 메서드의 if-else 분기를 바로 작성할 수 있는 수준이다.

그러나 다음의 문제가 식별된다:

1. **BR-APR-012 서술 모순**: FD §5에서는 "작성자는 **상태와 무관하게** 언제든 승인 요청을 철회 가능"이라 하면서, 에러 코드에서는 `APR_ALREADY_COMPLETED`(409)로 이미 완료된 건의 철회를 차단한다. rules.md에서는 명확히 `Approval.status == pending` 조건을 걸고 있다. FD 본문의 "상태와 무관하게"는 `pending_review` 내부에서 어느 단계에 있든이라는 의미인 것 같으나, 문구 그대로 읽으면 approved/rejected 상태에서도 철회 가능하다는 오해를 야기한다.

2. **BR-APR-027(시스템 유지보수 모드 시 SLA 타이머 일시 정지) 누락**: rules.md에는 BR-APR-027이 정의되어 있고 FD §4.4에서도 "시스템 점검 기간 동안 SLA 타이머 일시 정지"를 언급하지만, 비즈니스 규칙 카탈로그 테이블에 BR-APR-027이 빠져 있다. 유지보수 모드의 SLA 정지 로직은 구현 복잡도가 높아 BR로 명시해야 한다.

3. **DELETE 승인 유형 미정의**: data.md에서 `Approval.type`이 `PUBLISH`/`DELETE` 두 종류이고, ApprovalHistory에도 `delete_submitted`, `delete_approved` 등의 액션이 정의되어 있으나, FD에서는 DELETE 승인에 대한 비즈니스 규칙이 전혀 없다. 삭제 요청 결재의 트리거·조건·후속 처리가 누락되어 있다.

#### RD-FD-02. 상태 전이 완결성 — 72/100 양호

§1의 Mermaid 상태 다이어그램은 PUBLISH 시나리오의 핵심 전이를 잘 커버한다. `draft → pending_review → published`, `pending_review → approved_scheduled → published`, 반려/철회/자동반려/긴급발행 경로가 모두 그려져 있으며, 위임 승인에 대한 노트도 포함되어 있다.

미비 사항:

1. **DELETE 승인 전이 부재**: data.md §2.2에 DELETE 승인의 상태 전이 테이블이 있다(`pending → approved` 시 `Document.deleted_at = now()`, 반려/철회 시 현상 유지). FD의 상태 다이어그램에는 이 경로가 전혀 없다.

2. **published → draft 재편집 경로 누락**: §11.2에서 "published 상태인 문서를 수정하면 수정본이 별도 draft 상태로 생성"이라 서술하나, 이것이 동일 Document의 status 변경인지, 새 Document/Version 생성인지 불명확하다. 상태 다이어그램에도 이 전이가 없다.

3. **approved_scheduled → draft 전이의 주체 불명확**: 다이어그램에 "예약 취소"로만 표시되어 있는데, 누가 취소하는지(승인권자? 관리자? 작성자?) 그리고 문서가 draft로 돌아간 후 재요청이 필요한지가 상태 다이어그램만으로는 파악 불가하다.

#### RD-FD-03. 데이터 모델 설계 타당성 — 50/100 보통

FD에 "엔티티 통합 스키마" 섹션이 있어 FD 수준의 데이터 모델을 제공한 점은 긍정적이다. 그러나 **data.md와의 구조적 불일치가 6건 이상** 식별되어, 구현 시 "어느 문서를 기준으로 삼아야 하는지" 혼란이 심각하다. 금융권 SI에서 이런 수준의 불일치는 개발-검수 단계에서 대량 재작업을 초래한다.

**구체적 불일치 목록:**

| FD 엔티티 스키마 | data.md | 불일치 내용 |
|-----------------|---------|------------|
| `ApprovalAction` (§ApprovalAction 테이블) | `ApprovalDecision` | **엔티티명 자체가 다름** |
| `ApprovalCC` (별도 테이블, 4개 필드) | `Approval.cc_list` (JSONB 배열) | **구조가 완전히 다름** — 별도 테이블 vs JSONB |
| `Approval.is_bypass` BOOLEAN 필드 존재 | status enum에 `bypassed` 포함, `is_bypass` 제거 (ADR-011 A-5) | **삭제된 필드가 FD에 잔존** |
| `Approval.current_step_order` (INTEGER) | `Approval.current_step` (SMALLINT) + `total_steps` | **필드명·타입 불일치**, total_steps 누락 |
| `Approval.type` 필드 없음 | `Approval.type` VARCHAR(20) — `PUBLISH`/`DELETE` | **FD에 type 필드 자체가 없음** |
| `ApprovalHistory` 엔티티 없음 | `ApprovalHistory` 별도 테이블 정의 | **FD에 감사 이력 엔티티 누락** |
| `Approval.scheduled_publish_at` | `Approval.scheduled_at` + `bull_job_id` | 필드명 불일치, bull_job_id 누락 |

data.md는 ADR-011의 결정사항을 반영한 최신 상태로 보이며, FD는 이전 버전의 스키마를 그대로 유지하고 있다. **FD의 엔티티 스키마가 data.md와 동기화되지 않으면, FD를 기준으로 구현한 개발자와 data.md를 기준으로 구현한 개발자 간 충돌이 불가피하다.**

#### RD-FD-04. 확장성/유연성 — 82/100 우수

설계의 확장성은 매우 양호하다:

- **피처 게이트 전략**: `ft:approval.enabled`, `ft:approval.multi_step`, `ft:approval.bypass` 등으로 점진적 기능 활성화가 가능하다. 금융권 고객은 전체 기능을, 일반 고객은 단순 승인만 켤 수 있는 구조다.
- **Phase 1/Phase 2 분리**: §7.6 사후 검토, §12 에스컬레이션을 명확히 향후 확장으로 분리하면서도, 데이터 모델은 선설계(`post_review_deadline` 등)해둔 점이 실용적이다.
- **게시판 상속/오버라이드**: §2.7의 상속 모델은 조직 구조가 복잡한 금융권에서 유용하다. replace 방식(merge가 아닌)의 오버라이드는 예측 가능성이 높다.
- **승인/버전 독립 설정**: §2.5의 4가지 조합 매트릭스는 다양한 운영 시나리오를 커버한다.

개선 가능 사항: 게시판 계층 구조가 변경될 때(parent_id 변경) 진행 중인 승인 건의 mandatory_approval_config 참조에 어떤 영향이 있는지가 미정의되어 있다. 스냅샷 시점이 요청 시점이므로 영향 없을 것이나 명시가 필요하다.

#### RD-FD-05. 규칙 간 정합성 — 58/100 보통

**식별된 규칙 간 충돌/갭:**

1. **BR-APR-012 vs 에러 코드**: §5에서 "상태와 무관하게 언제든 철회 가능"이라 하고, 에러 코드에서는 `APR_ALREADY_COMPLETED`(409)로 완료 건 철회를 차단한다. "상태 무관"은 `pending` 상태 내의 어느 단계에서든이라는 의미겠지만, 문구가 모호하다.

2. **위임 + 자기승인 교차**: A가 B에게 위임했는데, B가 해당 문서의 작성자인 경우 `self_approve_blocked`가 적용되는지 정의가 없다. 금융권에서는 이 시나리오가 감사 이슈가 될 수 있다.

3. **mandatory_steps + max_steps 충돌**: `mandatory_steps`가 3개인데 `max_steps = 2`이면 어떻게 되는가? mandatory_steps는 max_steps에 포함되는지(count toward), 아니면 별도인지 규칙이 없다. BR-APR-029에서 "총 단계 수(필수 단계 포함)"이라 하므로 포함이겠으나, 설정 시점에서 모순 방지 검증 규칙이 필요하다.

4. **관리자 오버라이드 + 자기승인**: BR-APR-014로 관리자가 모든 단계를 승인할 수 있는데, 관리자가 동시에 문서 작성자라면 BR-APR-008의 자기승인 차단이 오버라이드되는지 불명확하다.

#### RD-FD-06. 비기능 요구 완전성 — 70/100 양호

§비기능 요구사항에서 동시 처리, 감사 로그, 큐 분리, 스케줄러 정밀도, API 응답시간(p95 < 500ms), 일괄 처리량(50건)을 잘 정의했다.

누락 사항:
- **승인 레코드 보존 기간**: 감사 로그 보관은 FD-AUD 참조로 처리했으나, Approval/ApprovalStepResult/ApprovalDecision 레코드 자체의 보존 기간은 미정의.
- **Rate Limiting**: 일괄 승인 50건 제한은 있으나, 단일 사용자의 승인 요청 빈도 제한(DoS 방지)이 없다.
- **가용성 요구**: 자동 반려 스케줄러의 "최대 지연 허용치 5분"은 있으나, 승인 API 자체의 가용성 SLA가 없다.

---

### 전문 차원

#### EX-FD-SR-01. 비즈니스 규칙 구현 충분성 — 62/100 양호

**잘 된 점:**
- §API DTO 스키마에 7개 엔드포인트의 Request/Response DTO가 필드 레벨까지 정의되어 있다. 승인 요청(Submit), 승인/반려(Decide), 철회, 긴급 발행, 일괄 처리, 위임, 예약 배포가 모두 커버된다.
- §이벤트 계약에서 10개 도메인 이벤트의 페이로드·소비 모듈·동기/비동기가 명시되어 있어, NestJS EventEmitter 기반 구현의 계약을 바로 정의할 수 있다.
- 멱등 키 패턴(`{event_name}:{approval_id}:{step_order}`)이 정의되어 있어 중복 이벤트 처리를 고려했다.

**구현 시 블로커:**

1. **엔티티 스키마 불일치** (RD-FD-03 상세 참조): FD의 엔티티 스키마를 보고 TypeORM Entity를 작성하면 data.md와 완전히 다른 코드가 나온다. 예를 들어 FD 기준으로 `ApprovalAction` 엔티티를 만들면, data.md에서는 `ApprovalDecision`이므로 API 스펙(api.md)의 `DecisionResponse`와 매핑이 안 된다.

2. **DELETE 승인 유형 부재**: data.md에서 `Approval.type = 'DELETE'`이고 api.md의 `ApprovalDetailResponse`에도 `type: 'PUBLISH' | 'DELETE'`가 있는데, FD에서는 DELETE 시나리오가 전혀 기술되지 않았다. 삭제 요청 결재의 서비스 메서드(승인 완료 시 soft delete, 반려 시 현상 유지)를 FD만으로는 구현할 수 없다.

3. **Submit 엔드포인트 소관 불일치**: FD §API DTO 스키마에서 `POST /api/approvals`로 승인 요청을 정의하나, api.md에서는 Submit이 Document API 소관(`POST /documents/:id/submit`)이며 Approval 모듈은 내부 서비스 호출만 받는다고 명시한다. FD를 보고 Approval Controller에 Submit 엔드포인트를 만들면 api.md와 충돌한다.

#### EX-FD-SR-02. 규칙-기능 추적 완전성 — 65/100 양호

대부분의 BR이 FD 본문의 특정 섹션에서 참조되고 있으며, 비즈니스 규칙 카탈로그의 "참조 섹션" 컬럼이 양방향 추적을 지원한다.

**추적 갭:**

1. **BR-APR-027 (유지보수 모드 SLA 정지)**: rules.md에 정의되어 있으나 FD 카탈로그에 없다. §4.4에서 "시스템 점검(유지보수 모드) 기간 동안 SLA 타이머 일시 정지"를 서술했으므로 BR-ID를 부여해야 한다.

2. **DELETE 승인 시나리오**: BR 카탈로그에 삭제 요청 결재 관련 규칙이 없다. data.md에는 DELETE 타입의 상태 전이·후속 처리·ApprovalHistory 액션(`delete_submitted`, `delete_approved` 등)이 상세히 정의되어 있으므로, FD에서도 최소한 "삭제 요청 시 승인 적용 여부", "삭제 승인 완료 시 소프트 딜리트"에 대한 BR이 필요하다.

3. **BR-APR-009 참조 섹션 오류**: 카탈로그에서 §3.1로 참조하나, CC(참조라인)는 §3.2에 정의되어 있다. §3.1은 "기안자 결재라인 구성"이다.

4. **에러 코드와 BR 매핑 불완전**: `APR_MANDATORY_STEPS_MISSING`(BR-APR-028), `APR_STEP_COUNT_OUT_OF_RANGE`(BR-APR-029), `APR_APPROVER_NO_PERMISSION`(BR-APR-030)이 FD의 에러 코드 카탈로그에 없다. rules.md와 api.md에는 있으나 FD에서 누락.

#### EX-FD-SR-03. 암묵적 복잡도 노출 — 55/100 보통

**잘 노출된 복잡도:**
- §6.3 동시 처리 규칙: optimistic locking 기반 first-wins 전략이 명확하다.
- §4.1 COUNT 유형 조기 반려: "남은 미처리 인원을 모두 합산해도 필요 정족수에 미달하면 즉시 반려"는 구현 시 핵심 로직이며 잘 서술되어 있다.
- §4.4 자동 반려 타이머: 건 전체 SLA vs 단계별 SLA를 명확히 구분하고, Phase 1/2로 분리했다.

**미노출된 복잡도:**

1. **위임 ↔ 자기승인 교차**: 위임받은 사용자가 문서 작성자인 경우 `self_approve_blocked` 적용 여부가 미정의. 실제 금융권 프로젝트에서 부재 위임 시 흔히 발생하는 시나리오다.

2. **mandatory_steps ↔ max_steps 설정 모순**: 관리자가 mandatory_steps를 3개 설정하고 max_steps를 2로 설정하면 모순이 생긴다. 설정 시점 검증 규칙이 없다.

3. **ROLE/TEAM 승인 대상자 런타임 해석**: `approver_source = 'ROLE'`인 단계에서 실제 승인 가능자는 "해당 역할 + 게시판 APPROVE 권한의 교집합"이라 했는데, 이 교집합이 승인 요청 시점에 스냅샷되는지 아니면 승인 처리 시점에 동적으로 계산되는지 명시가 없다. 요청 후 권한이 변경되면 결과가 달라진다.

4. **일괄 승인 + 개별 승인 동시 발생**: 한 건에 대해 batch-decide와 individual decide가 동시에 호출되면 어떻게 되는지. BR-APR-015의 optimistic locking이 적용된다고 추론할 수 있으나 명시가 없다.

5. **approved_scheduled + 긴급 발행 교차**: 예약 배포 대기 상태(`approved_scheduled`)인 문서에 긴급 발행이 발생하면? 이미 승인이 완료된 상태이므로 bypass가 필요 없어 보이지만, 예약을 앞당기는 시나리오에 대한 처리가 없다.

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P1 | RD-FD-03 | FD 엔티티 스키마가 data.md와 6건 이상 구조적 불일치 (ApprovalAction/Decision, CC 테이블/JSONB, is_bypass 잔존 등) | FD-APR §엔티티 통합 스키마 | align | 구현 시 어느 문서 기준인지 판단 불가, 개발자 간 충돌 불가피 | FD 엔티티 스키마를 data.md 기준으로 동기화하거나, "상세 DDL은 data.md 참조"로 FD 스키마를 경량화 |
| P1 | EX-FD-SR-02 | DELETE 승인 유형이 FD에 전무하나 data.md·api.md에는 정의됨 | FD-APR 전체 | add | 삭제 요청 결재 워크플로의 BR·상태 전이·시나리오가 없으면 구현 불가 | FD에 "삭제 요청 결재" 섹션 추가 — 트리거(approval_required 게시판에서 삭제 시), 상태 전이, 승인 완료 시 soft delete 후속 처리 |
| P1 | EX-FD-SR-01 | Submit 엔드포인트 소관이 FD(`POST /api/approvals`)와 api.md(Document API 소관) 간 상충 | FD-APR §API DTO 스키마, api.md §연동 계약 | align | 개발자가 FD 기준으로 ApprovalController에 Submit을 만들면 api.md 아키텍처와 충돌 | FD의 API DTO 스키마에서 Submit 엔드포인트를 "Document API 소관(POST /documents/:id/submit)이며, Approval 모듈은 내부 서비스 호출만 수신"으로 수정 |
| P2 | RD-FD-01 | BR-APR-027(시스템 유지보수 모드 SLA 정지)이 FD 카탈로그에 누락 | FD-APR §비즈니스 규칙 카탈로그 | add | rules.md에만 존재하여 FD↔rules.md 추적이 끊김. 구현 복잡도가 높은 규칙 | 카탈로그에 BR-APR-027 행 추가, §4.4에 BR-ID 태깅 |
| P2 | RD-FD-05 | BR-APR-012 "상태와 무관하게 철회 가능" 서술이 실제 pending 제한과 모순 | FD-APR §5 | fix | 문구 그대로 읽으면 approved/rejected 상태에서도 철회 가능으로 오해 | "pending 상태의 승인 건에 대해 어느 단계에서든 철회 가능"으로 수정 |
| P2 | EX-FD-SR-03 | 위임받은 사용자가 문서 작성자인 경우 self_approve_blocked 적용 여부 미정의 | FD-APR §8, §3.3 | decision | 금융권 감사 이슈 — 부재 위임 시 자기 승인이 우회되면 내부통제 위반 | §8.4 제약사항에 "위임 대상자가 해당 문서의 작성자인 경우 self_approve_blocked 동일 적용" 규칙 추가 |
| P2 | EX-FD-SR-03 | mandatory_steps 수 > max_steps 설정 시 모순 방지 검증 부재 | FD-APR §2.6, rules.md | add | 관리자 설정 오류 시 기안자가 결재라인을 구성할 수 없는 교착 상태 발생 | mandatory_steps 수 ≤ max_steps 검증 규칙(BR) 추가, 게시판 설정 저장 시 사전 검증 |
| P2 | EX-FD-SR-02 | BR-APR-028~030의 에러 코드 3건이 FD 에러 코드 카탈로그에 누락 | FD-APR §에러 코드 카탈로그 | add | rules.md·api.md에는 있으나 FD에 없어 추적 불완전 | `APR_MANDATORY_STEPS_MISSING`, `APR_STEP_COUNT_OUT_OF_RANGE`, `APR_APPROVER_NO_PERMISSION` 추가 |
| P3 | RD-FD-02 | published → draft 재편집 경로가 상태 다이어그램에 없음 | FD-APR §1, §11.2 | add | §11.2에 서술은 있으나 다이어그램에서 누락되어 전체 상태 흐름 파악 불완전 | Mermaid 다이어그램에 `published --> draft : 수정 시작 (사본 생성)` 전이 추가 |
| P3 | EX-FD-SR-03 | ROLE/TEAM 승인 대상자의 해석 시점(요청 시 스냅샷 vs 처리 시 동적)이 미정의 | FD-APR §2.4 | decision | 요청 후 권한 변경 시 승인 가능자 목록이 달라지는 엣지 케이스 | §2.4에 "ROLE/TEAM 지정 시 승인 처리 시점에 동적으로 대상자 산출" 또는 "요청 시점 스냅샷" 명시 |
| P3 | RD-FD-01 | BR-APR-009 참조 섹션이 §3.1(기안자 결재라인)로 잘못 기재 — 실제 CC는 §3.2 | FD-APR §비즈니스 규칙 카탈로그 | fix | 참조 추적 오류 | §3.2로 수정 |

---

## 설계 질문

| ID | 질문 | 블로킹 항목 |
|----|------|-------------|
| DQ-1 | DELETE 승인 유형(삭제 요청 결재)은 Phase 1 범위인가? data.md·api.md에는 정의되어 있으나 FD에서 의도적으로 제외한 것인지, 누락인지 확인이 필요하다. | P1 #2 |
| DQ-2 | FD 엔티티 스키마와 data.md 중 구현 기준 문서는 어느 쪽인가? FD 스키마를 data.md에 맞춰 갱신할 것인지, 아니면 FD를 "개요"로 유지하고 data.md를 단일 원천으로 삼을 것인지 결정이 필요하다. | P1 #1 |
| DQ-3 | 위임받은 사용자가 문서 작성자인 경우 자기승인 차단 정책을 어떻게 적용할 것인가? (a) 위임과 무관하게 작성자이면 차단, (b) 위임이면 허용, (c) 게시판 설정에 옵션 추가 | P2 #3 |
| DQ-4 | ROLE/TEAM 승인자의 대상자 해석은 요청 시점 스냅샷인가, 처리 시점 동적 계산인가? 스냅샷이면 ApprovalStepResult에 실제 사용자 UUID 목록을 저장해야 하고, 동적이면 처리 시마다 권한 조회가 필요하다. | P3 #2 |
