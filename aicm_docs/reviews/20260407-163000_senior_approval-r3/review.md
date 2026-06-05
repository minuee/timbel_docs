> **문서 유형**: 모듈스펙
> **종합 점수**: 83 / 100 (공용 84 × 0.6 + 전문 81 × 0.4)
> **리뷰 대상**: `docs/03-module-design/approval/` (README.md, data.md, api.md, rules.md, schedule.md, events.md)
> **페르소나**: 최민재 — 시니어 백엔드 개발자 (AI)
> **리뷰일**: 2026-04-07 16:30
> **리뷰 라운드**: Round 3 (Round 2: 79점)
> **지적사항**: P1: 1건, P2: 3건, P3: 3건
> **자동 반영 가능**: 5건 / 설계 결정 필요: 2건

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-MS-01 | API 설계 품질 | 82 | 30% | DocumentExportService·AuthExportService 계약 추가로 대폭 개선, 그러나 FD-APR BR-APR-031~035 에러 코드·규칙이 api.md/rules.md에 미반영 |
| RD-MS-02 | 구현 변환 용이성 | 82 | 10% | DTO→엔티티 매핑 명시(ApprovalStepDto→ApprovalStepResult), total_steps 불변 조건 서비스 레이어 보장 명시로 개선 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 84 | 25% | traceId 기본 필드화·cron timezone 명시·예약 배포 보정 배치 상세화가 우수. 수신 이벤트명 README↔events.md 불일치 잔존 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 87 | 15% | 책임 테이블·Phase 제외 기능·피처 게이트 7종 정의가 명확. ft:approval.delegation 누락은 의도적인지 확인 필요 |
| RD-MS-05 | 모듈 간 계약 명확성 | 85 | 10% | 3개 ExportService(Board·Auth·Document) TypeScript 인터페이스 완비. TEAM 확장 메서드는 향후 보완 명시 |
| RD-MS-06 | 운영 고려사항 | 86 | 10% | 메트릭 9종·알림 임계값 7종·로그 레벨 가이드·아카이브 Phase 1 영구 보관 명시 |
| | **공용 소계** | **84** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-MS-SR-01 | 런타임 안정성 설계 | 85 | 50% | batch-decide 건별 독립 트랜잭션·cc_list OCC·schedule.md DocumentModule 실패 폴백 상세화가 실무 수준 |
| EX-MS-SR-02 | 참조 무결성 | 77 | 50% | FD-APR BR-APR-031~035가 rules.md에 없고, APR_ACTIVE_APPROVAL_EXISTS 에러 코드 api.md 미반영, 이벤트명 불일치 |
| | **전문 소계** | **81** | 100% | |

### 종합: 83 / 100 (공용 84 × 0.6 + 전문 81 × 0.4)

---

## 차원별 상세 피드백

### 공용 차원

#### RD-MS-01. API 설계 품질 — 82/100 양호

Round 3에서 가장 체감되는 개선은 **모듈 간 계약의 명시화**다. `api.md`의 `DocumentExportService` 인터페이스가 `transitionToPublished`, `transitionToApprovedScheduled`, `transitionToDraftOnReject` 세 메서드를 TypeScript 시그니처로 정의하고, `AuthExportService`도 `hasPermission`, `getUsersByRole`을 명시한 것은 구현자가 바로 인터페이스를 뽑아 쓸 수 있는 수준이다.

`batch-decide`에 건별 독립 트랜잭션 + `failedItems` 배열 추가는 이전 리뷰의 핵심 지적을 정확히 해소했다. "50건 전체를 단일 트랜잭션으로 묶지 않는다"는 명시가 좋다.

**그러나**, FD-APR에서 Round 3까지 추가된 BR-APR-031(삭제 요청 결재), BR-APR-032(필수 단계 수 vs max_steps), BR-APR-033(위임·작성자 교차 시 위임 무효), BR-APR-034(관리자 오버라이드와 자기승인 차단), BR-APR-035(문서당 활성 승인 건 유일)가 **rules.md 규칙 카탈로그에 부재**하다. 특히 BR-APR-035에 대응하는 에러 코드 `APR_ACTIVE_APPROVAL_EXISTS`가 `api.md` 에러 코드 참조 테이블에도 없다. data.md §2.2에 type=DELETE 동작은 상세히 기술되어 있지만, rules.md에 정식 규칙으로 카탈로그되지 않으면 구현자가 BR-ID 기반으로 코드를 추적할 때 누락할 수 있다.

예약 배포 두 경로 상호 배타 가이드(`api.md` schedule 엔드포인트, `schedule.md` 상단)가 두 문서에 일관되게 명시된 것은 이전에 혼동 가능성이 있던 부분을 잘 해소했다.

#### RD-MS-02. 구현 변환 용이성 — 82/100 양호

`total_steps`와 `ApprovalStepResult` 행 수 불변 조건에 대해 "서비스 레이어(`ApprovalService.createApproval` 등 승인 건 생성 유일 경로)에서 삽입 직후·커밋 전에 보장한다"고 명시한 것은 좋다. DB CHECK를 채택하지 않는 설계 결정 근거(성능·유지보수)도 기록되어 있어 구현자가 "왜 DB 레벨이 아닌지" 의문을 갖지 않는다.

DTO→엔티티 매핑 설명(`api.md`의 "DTO → ApprovalStepResult 매핑" 단락)이 "배열 DTO ≠ 복수 행"임을 명확히 한 것이 유용하다.

다만, BR-APR-033(위임·작성자 교차 시 위임 무효)의 구현 가이드가 모듈 스펙 어디에도 없다. FD-APR §8.5에는 기술되어 있으나, rules.md에 규칙이 없으면 이 엣지케이스를 구현에서 놓칠 수 있다. 금융권에서 위임받은 사용자가 본인 문서를 승인하는 시나리오는 감사 이슈로 직결된다.

#### RD-MS-03. 이벤트/비동기 설계 건전성 — 84/100 우수

Round 3의 이벤트 설계 개선이 인상적이다:

1. **traceId 기본 필드화**: `events.md`에서 `ApprovalEventBusPayloadBase`에 `traceId: string`을 필수로 포함하고, BullMQ의 `AsyncJobContext.traceId`와 동일 목적임을 명시. 분산 추적 관점에서 모범적이다.
2. **cron timezone 명시**: `schedule.md` 상단에 "본 문서의 cron 표현식은 모두 **Asia/Seoul** 기준"으로 명시하고 각 배치에도 반복 기재. 운영 환경 오해 여지를 제거했다.
3. **예약 배포 보정 상세화**: `schedule.md` §2.4의 DocumentModule 장애 시 폴백(지수 백오프 3회 재시도, 다음 주기 재처리, 한계·알림)이 실무 수준으로 기술되어 있다.

**남은 이슈**: README.md의 수신 이벤트 행에서 `board.config_updated`라 하고, events.md §2 테이블에서는 `board.policy_updated`라 한다. 동일 이벤트인데 이름이 다른 건 런타임에 리스너가 등록되지 않는 버그로 직결된다 — 이전 Round에서 지적된 이슈인지 모르겠지만, 여전히 잔존한다.

#### RD-MS-04. 모듈 책임 범위 적절성 — 87/100 우수

README.md의 책임 테이블 12행이 모듈의 경계를 명쾌하게 정의한다. "현재 범위 제외 기능" 테이블도 3건의 Phase 2 항목을 FD 참조와 함께 명시하고 있어 좋다.

피처 게이트 7종(`ft:approval.enabled` ~ `ft:approval.reject_comment_required`)이 비활성 시 동작까지 기술되어 있다. 다만 FD-APR §1에 있는 `ft:approval.delegation`이 README.md 피처 게이트 테이블에 없다. 게시판 `delegation_allowed` 설정으로 대체한 것인지, 별도 피처 게이트가 필요한지 설계 결정이 필요하다.

#### RD-MS-05. 모듈 간 계약 명확성 — 85/100 우수

Round 2에서 "외부 모듈 계약이 추상적"이란 지적이 있었다면, Round 3에서 해소 수준이 높다:

- **BoardExportService**: `getMandatoryApprovalConfig(boardId)` — 상속 포함 유효 설정 반환
- **AuthExportService**: `hasPermission(userId, boardId, action)`, `getUsersByRole(roleName, boardId)` — 승인자 풀 확인과 권한 검증의 두 축
- **DocumentExportService**: 3개 상태 전이 메서드 — 명확한 `documentId + approvalId` 기반 계약

다만, `AuthExportService.getUsersByRole`은 ROLE 기반만 커버하고 TEAM 기반 승인자 해소 메서드가 없다. api.md에 "TEAM 확장·위임 반영 등 세부 집계는 본 계약을 확장하거나 별도 메서드로 보완할 수 있다"고 언급하지만, `getUsersByTeam(teamId, boardId)`같은 메서드가 없으면 구현자가 Auth 모듈에 임의 쿼리를 날릴 수 있다. P3 수준이지만 계약 완결성 관점에서 언급한다.

#### RD-MS-06. 운영 고려사항 — 86/100 우수

메트릭 9종이 목표값과 함께 정의되어 있고(`approval.decide_latency_ms` p95 < 500ms 등), 모니터링 알림 임계값 7종에 심각도(WARNING/CRITICAL)와 채널(Slack/PagerDuty)이 명시되어 있다.

데이터 아카이브 전략이 "Phase 1에서 영구 보관한다(감사·이력 요구). 데이터량 증가에 따라 향후 파티셔닝·아카이빙을 검토한다"로 명시된 것은 Round 2 지적을 해소했다.

로그 레벨 가이드가 7가지 시나리오에 대해 WARN/ERROR/INFO를 구분한 것도 운영 관점에서 유용하다.

---

### 전문 차원

#### EX-MS-SR-01. 런타임 안정성 설계 — 85/100 우수

8년간 금융권 SI를 하면서 "문서에 재시도 정책이 없어서 Worker 장애 시 메시지 유실" 사고를 겪은 입장에서, 이 모듈 스펙은 충분히 실무적이다.

**잘 된 점**:
- `batch-decide` 건별 독립 트랜잭션: "1건 실패 시 나머지 일괄 롤백 방지"를 명시하고 `failedItems`로 실패 건 빠른 식별. 50건 일괄 처리에서 1건 FK 위반으로 전체 롤백되는 사고를 예방한다.
- `cc_list` OCC 설계 결정: "Approval 레코드 레벨 OCC(`updated_at` 비교)"로 동시 갱신 충돌을 처리한다는 결정이 기록됨. 변경 빈도가 낮다는 가정하에 합리적이다.
- `schedule.md` §2.4 DocumentModule 장애 폴백: 지수 백오프 3회 재시도 → 다음 주기 재처리 → ERROR 로그·메트릭 → Slack 알림. "Approval을 임의로 approved로 되돌리지 않고, 동일 건 재시도 가능 상태를 유지한다"가 핵심 — 보상 트랜잭션 없이 멱등 재시도로 수렴하는 패턴이 좋다.
- Critical 트랜잭션 타임아웃 30~60초 + 롤백 정책(`rules.md` §1.4)이 명확하다.

**개선 여지**:
- `scheduled-publish` 큐의 동시 처리수가 1인데, 예약 배포가 특정 시간대에 집중되면(예: 금융권 시행일) 큐 지연이 발생할 수 있다. 순서 보장이 필수인지, 아니면 동시 처리수를 높여도 되는지에 대한 근거가 있으면 좋겠다.

#### EX-MS-SR-02. 참조 무결성 — 77/100 양호

모든 문서를 나란히 놓고 대조했을 때, Round 3에서 많은 불일치가 해소되었지만 아직 잔여 갭이 있다.

**해소된 불일치** (Round 2→3):
- DocumentExportService 3개 메서드 시그니처 — api.md ↔ events.md §3.1 간 정합
- AuthExportService 계약 — api.md에 신규 추가
- 예약 배포 두 경로 상호 배타 — api.md, schedule.md 양쪽에 명시
- total_steps 불변 조건 — data.md에 서비스 레이어 보장 명시

**잔존 불일치**:

1. **FD-APR BR-APR-031~035 → rules.md 미반영**: FD의 비즈니스 규칙 카탈로그에 정식 등재된 5개 규칙이 모듈 스펙 rules.md에 없다. data.md/api.md에 기능은 기술되어 있으나, rules.md의 BR-ID 카탈로그에 없으면 "규칙 기반 구현 → 테스트" 추적 체인이 끊긴다.

2. **APR_ACTIVE_APPROVAL_EXISTS 에러 코드**: FD-APR 에러 코드 카탈로그에 있으나 api.md에 없다. 기존 `APR_ALREADY_PENDING`(BR-APR-007)과 의미가 겹치는지, 별도인지 정리가 필요하다.

3. **수신 이벤트명 불일치**: README.md에 `board.config_updated`, events.md §2에 `board.policy_updated`. 동일 이벤트에 대한 두 가지 이름.

4. **`ft:approval.delegation` 피처 게이트**: FD-APR §1에 정의되어 있으나 README.md 피처 게이트 테이블에 없다.

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P1 | EX-MS-SR-02 | FD-APR BR-APR-031~035가 rules.md 규칙 카탈로그에 미반영. 특히 BR-APR-033(위임·작성자 교차 위임 무효), BR-APR-035(문서당 활성 승인 건 유일)는 금융권 감사·정합성 직결 | rules.md 전체, api.md §에러 코드 | add | 구현자가 BR-ID 기반 추적 체인을 쓰면 5개 규칙이 누락됨. BR-APR-033 미구현 시 위임받은 사용자가 본인 문서 승인하는 감사 이슈 발생 | rules.md에 BR-APR-031~035 정식 카탈로그. api.md에 `APR_ACTIVE_APPROVAL_EXISTS` 에러 코드 추가. `APR_ALREADY_PENDING`과 역할 분담 정리 |
| P2 | RD-MS-03 | README.md 수신 이벤트 `board.config_updated` ↔ events.md §2 `board.policy_updated` 이름 불일치 | README.md §인프라, events.md §2 | align | EventBus 리스너 등록 시 이름 불일치로 수신 실패 가능. 캐시 무효화 미동작 → 오래된 게시판 설정으로 승인 검증 수행 | 하나로 통일. Board 모듈의 실제 이벤트명 확인 후 양쪽 동기화 |
| P2 | RD-MS-01 | FD-APR에 있는 `APR_ACTIVE_APPROVAL_EXISTS` 에러 코드가 api.md 에러 코드 카탈로그에 누락 | api.md §에러 코드 참조 | add | 프론트엔드가 이 에러 코드를 처리할 수 없음. 기존 `APR_ALREADY_PENDING`과의 관계도 불명확 | P1 조치와 함께 api.md 에러 코드 테이블에 추가. `APR_ALREADY_PENDING`을 흡수할지 별도로 둘지 결정 |
| P2 | RD-MS-04 | FD-APR §1의 `ft:approval.delegation` 피처 게이트가 README.md 피처 게이트 테이블에 없음 | README.md §피처 게이트 | decision | 게시판 `delegation_allowed`로 대체했다면 명시적 결정 기록 필요. 미결이면 위임 전체를 피처 게이트로 제어 불가 | `ft:approval.delegation`을 README 테이블에 추가하거나, 게시판 설정으로 대체한 이유를 설계 결정으로 기록 |
| P3 | RD-MS-05 | AuthExportService에 TEAM 기반 승인자 해소 메서드 부재 — `getUsersByRole`만 있고 `getUsersByTeam` 없음 | api.md §Auth 모듈 내부 계약 | add | TEAM 단계 승인 시 Auth 모듈에 임의 쿼리를 날리게 되어 계약 경계 이탈 가능 | `getUsersByTeam(teamId, boardId): Promise<string[]>` 추가 또는 확장 계획 명시 |
| P3 | RD-MS-03 | `scheduled-publish` 큐 동시 처리수 1의 근거 미기술 — 특정 시간대 집중 시 큐 지연 가능 | events.md §4, schedule.md §2.4 | add | 금융권 시행일에 예약 배포 수십 건 집중 시 순차 처리로 지연 발생 가능 | 순서 보장 필요 여부 검토 후 근거 기술. 불필요하면 동시 처리수 상향 고려 |
| P3 | RD-MS-02 | BR-APR-034(관리자 오버라이드+자기승인 차단 교차)의 구현 가이드가 모듈 스펙에 없음 | rules.md | add | FD-APR §6.1에 기술되어 있으나 rules.md에 정식 규칙이 없으면 구현 시 놓칠 수 있음 | P1 조치(BR-APR-031~035 추가)에 포함하여 반영 |

---

## 설계 질문

| ID | 질문 | 블로킹 항목 |
|----|------|-------------|
| DQ-1 | `APR_ACTIVE_APPROVAL_EXISTS`(BR-APR-035)와 기존 `APR_ALREADY_PENDING`(BR-APR-007)의 역할 분담이 무엇인지? BR-APR-007은 "이미 pending 건 존재 시 재요청 차단"이고, BR-APR-035는 "유형 불문 pending 1건 유일"인데, 에러 코드를 하나로 통합할지 별도로 둘지? | P1, P2 #2 |
| DQ-2 | `ft:approval.delegation` 피처 게이트를 의도적으로 제거한 것인지? 게시판 `delegation_allowed`는 게시판 단위 제어이고, 피처 게이트는 시스템 전체 ON/OFF인데, 두 레벨 모두 필요한 건 아닌지? | P2 #3 |

---

## Round 2→3 개선 반영 평가

| 수정 사항 | 반영 상태 | 점수 영향 |
|-----------|-----------|-----------|
| batch-decide 건별 독립 트랜잭션 + failedItems | ✅ 완전 반영 — api.md, rules.md 양쪽 일관 | RD-MS-01 +3, EX-MS-SR-01 +4 |
| AuthExportService 계약 (hasPermission, getUsersByRole) | ✅ 반영 — TypeScript 인터페이스 명시 | RD-MS-05 +5 |
| DocumentExportService 계약 (3개 메서드) | ✅ 반영 — 식별자 기반 공개 계약 + 구현 오버로드 설명 | RD-MS-05 +5, RD-MS-01 +2 |
| total_steps ↔ ApprovalStepResult 행 수 불변 조건 | ✅ 반영 — 서비스 레이어 보장 + DB CHECK 미채택 근거 | RD-MS-02 +3 |
| 예약 배포 두 경로 상호 배타 가이드 | ✅ 반영 — api.md, schedule.md 양쪽 명시 | RD-MS-01 +2 |
| traceId 이벤트 기본 필드 | ✅ 반영 — ApprovalEventBusPayloadBase 도입 | RD-MS-03 +3 |
| cron timezone Asia/Seoul 명시 | ✅ 반영 — schedule.md 상단 + 각 배치 반복 기재 | RD-MS-06 +2 |
| 데이터 아카이브 Phase 1 영구 보관 | ✅ 반영 — data.md 상단에 명시 | RD-MS-06 +2 |
| cc_list OCC 설계 결정 | ✅ 반영 — data.md §2.2에 Approval 레코드 레벨 OCC 기록 | EX-MS-SR-01 +2 |

**총평**: 9개 수정 사항 모두 성실하게 반영되었다. Round 2의 핵심 지적(ExportService 계약 부재, batch 트랜잭션 전략, 이벤트 추적 필드)이 모두 해소되어 79→83으로 4점 상승. 잔여 P1은 FD↔모듈 스펙 간 규칙 동기화 이슈로, 기능 자체의 설계 결함이 아니라 카탈로그 정비 작업이다. 이것만 해소하면 85점대 진입이 가능하다.
