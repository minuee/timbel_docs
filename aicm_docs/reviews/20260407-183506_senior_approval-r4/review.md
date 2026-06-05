> **문서 유형**: 모듈스펙
> **종합 점수**: 85 / 100 (공용 86 × 0.6 + 전문 84 × 0.4)
> **리뷰 대상**: `docs/03-module-design/approval/` (README.md, data.md, api.md, rules.md, schedule.md)
> **페르소나**: 최민재 — 시니어 백엔드 개발자 (AI)
> **리뷰일**: 2026-04-07 18:35
> **지적사항**: P1: 1건, P2: 3건, P3: 2건
> **자동 반영 가능**: 4건 / 설계 결정 필요: 2건
> **라운드**: Round 4 (이전 Round 3: 83점 → +2)

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-MS-01 | API 설계 품질 | 87 | 30% | Round 4 에러 코드 2종 추가 + getUsersByTeam으로 계약 완성도 향상; CreateApprovalInternalDto에 type 필드 미노출이 유일한 갭 |
| RD-MS-02 | 구현 변환 용이성 | 83 | 10% | BR-APR-034 구현 가이드 추가로 개선; SQL 예시·DDL·TypeScript DTO 모두 구체적이나 batch-decide stepOrder 자동 특정 로직 구현 예시 부족 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 85 | 25% | schedule.md §4 concurrency 근거 추가로 견고해짐; events.md policyId 레거시 잔류가 유일한 불일치 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 86 | 15% | Submit=Document API, 결재행위=Approval API 분리 명확; 범위 제외 기능·Phase 2 로드맵 정리 양호 |
| RD-MS-05 | 모듈 간 계약 명확성 | 84 | 10% | 3개 ExportService 인터페이스 명확; type=DELETE 경로 내부 계약 미정의 + getUsersByTeam boardId 비대칭이 소폭 감점 |
| RD-MS-06 | 운영 고려사항 | 87 | 10% | 메트릭 p95 목표·알림 임계값·로그 레벨·설정값 카탈로그 빠짐없이 정의 |
| | **공용 소계** | **86** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-MS-SR-01 | 런타임 안정성 설계 | 86 | 50% | 재시도·DLQ·분산 락·OCC·보정 배치·Critical tx 타임아웃/롤백 전략이 실무 수준; concurrency 근거 추가로 완성도 상승 |
| EX-MS-SR-02 | 참조 무결성 | 81 | 50% | BR-031~035 전량 추가 + 에러 코드 매핑 개선 but events.md policyId 잔류·BR-033 위반 시 적용 범위 모호·type=DELETE 내부 계약 부재 |
| | **전문 소계** | **84** | 100% | |

### 종합: 85 / 100 (공용 86 × 0.6 + 전문 84 × 0.4)

---

## 차원별 상세 피드백

### 공용 차원

#### RD-MS-01. API 설계 품질 — 87/100 우수

Round 4에서 `APR_ACTIVE_APPROVAL_EXISTS`(BR-APR-035)와 `APR_DELEGATION_INVALID_SELF_AUTHOR`(BR-APR-033) 에러 코드를 추가하면서 BR↔에러 코드 매핑이 한층 촘촘해졌습니다. `AuthExportService.getUsersByTeam` 추가로 TEAM 단계 승인 대상 집계 계약도 완성되었고요.

**잘 된 점:**
- 에러 코드 테이블(api.md §에러 코드 참조)이 20종으로 확장되면서 모든 BR에 에러 코드가 1:1 매핑됨
- `BoardExportService`, `AuthExportService`, `DocumentExportService` 3개 내부 계약 인터페이스가 TypeScript 시그니처로 명확히 정의됨
- PaginatedResponse 패턴, 페이지네이션/정렬/필터 쿼리 파라미터가 일관적
- batch-decide의 partial success 패턴(건별 독립 트랜잭션 + failedItems 분리)이 실무적

**개선 필요:**
- `CreateApprovalInternalDto`에 `type` 필드가 없음. `Approval.type`은 `PUBLISH`/`DELETE` 두 값을 갖는데, 내부 DTO는 PUBLISH 경로(Submit)만 고려. **type=DELETE 결재 생성 시 호출자(Document API)가 type을 전달할 수단이 정의되어 있지 않음** → P1
- `getUsersByTeam(teamId)`에 `boardId` 파라미터 없음. `getUsersByRole(roleName, boardId)`는 역할+게시판 기준으로 후보를 반환하지만 TEAM은 팀원만 반환 → APPROVE 권한 필터링을 별도 `hasPermission` N회 호출로 해결해야 함. 의도적 설계라면 주석에 명시 필요 → P2

---

#### RD-MS-02. 구현 변환 용이성 — 83/100 우수

BR-APR-034에 "구현 가이드" 섹션이 추가된 것이 좋습니다. `requester_id === actor_id` 검증 선행이라는 한 줄이 주니어 개발자에게 모호한 관리자 오버라이드 × 자기승인 교차를 명확히 풀어줍니다.

**잘 된 점:**
- schedule.md의 자동 반려 배치 SQL(재귀 CTE + maintenance_pause_interval)이 복붙 수준으로 구체적
- data.md DDL이 CHECK, UNIQUE, partial index까지 완비
- api.md DTO 인터페이스가 TypeScript 타입으로 정의되어 ORM 매핑에 직결
- `ft:approval.delegation` OFF 시 404 반환·위임 매칭 비활성화 동작이 README + rules.md 양쪽에서 서술

**개선 필요:**
- batch-decide에서 "현재 활성 단계 자동 특정" 로직 — `Approval.current_step`에 대응하는 `ApprovalStepResult`를 찾는 과정이 서술적이지만, 단건 decide는 클라이언트가 `stepOrder`를 직접 지정. 이 비대칭을 구현 가이드에서 한 줄로 정리해주면 주니어 혼란 방지 → P3

---

#### RD-MS-03. 이벤트/비동기 설계 건전성 — 85/100 우수

schedule.md §4에 `scheduled-publish` 워커 **concurrency = 1** 근거가 추가된 것이 Round 4의 가장 실질적인 개선 중 하나입니다. Critical tx DB 커넥션 풀 고갈 위험, 수평 확장 시 `concurrency × 인스턴스 수 ≤ 풀 최대` 공식까지 명시한 점이 좋습니다.

**잘 된 점:**
- `scheduled-publish` 큐: 멱등성 키(jobId), 재시도(3회 지수 백오프), DLQ, 타임아웃(1분), graceful shutdown 모두 정의
- 보정 배치(schedule.md §2.4)가 BullMQ 누락·실패 + DocumentModule 장애 양쪽 안전망
- EventBus 이벤트 멱등성 패턴(events.md §4.2)이 소비자별로 정리
- 분산 락 TTL이 배치 주기와 정합(예: 자동 반려 5분 주기 / 락 TTL 5분)

**개선 필요:**
- events.md `ApprovalSubmittedEvent.policyId`가 잔류 — 현재 모델은 `ApprovalPolicy → ApprovalLineTemplate`으로 전환 완료. `templateId: string | null`로 수정 필요. 대상 문서 목록(5개)에 events.md가 빠져 있지만, api.md·schedule.md가 events.md를 참조하므로 정합성 영향 → P2

---

#### RD-MS-04. 모듈 책임 범위 적절성 — 86/100 우수

모듈 책임 테이블(README §모듈 책임)에 "삭제 요청 결재"가 명시적으로 추가되었고, BR-APR-031이 이를 뒷받침합니다. "현재 범위 제외 기능" 테이블(단계별 SLA, 에스컬레이션, 사후 검토)이 Phase 2 로드맵과 함께 정리되어 있어 기획자·개발자 모두 범위를 오해할 여지가 적습니다.

**잘 된 점:**
- Submit 진입점 = Document API, 결재 행위 = Approval API 분리가 ADR-011 A-2와 정합
- 결재라인 템플릿 CRUD 소관이 ADR-011 §E-1로 근거 있음
- `ft:approval.delegation` OFF 시 위임 API 404·위임 검색 비활성화라는 명확한 경계 설정

**개선 필요:**
- BR-APR-031 삭제 요청 결재의 트리거가 "Document API에서 삭제 시도"인데, Document API → ApprovalService 호출 시 사용할 DTO·메서드가 정의되지 않음. PUBLISH 경로의 `CreateApprovalInternalDto`/`createApproval()`과 별도인지, 동일 메서드에 type 파라미터를 추가하는지 명시 필요 → P1과 연관(P3)

---

#### RD-MS-05. 모듈 간 계약 명확성 — 84/100 우수

Round 4에서 `AuthExportService.getUsersByTeam` 추가, `board.config_updated` 이벤트명 통일로 모듈 간 계약이 개선되었습니다. Critical tx 타임아웃·롤백·보상 전략(rules.md §1.4)도 이전 라운드 대비 보강된 부분입니다.

**잘 된 점:**
- `DocumentExportService`의 3개 메서드(`transitionToPublished`, `transitionToApprovedScheduled`, `transitionToDraftOnReject`)가 식별자 중심 시그니처로 깔끔
- `BoardExportService.getMandatoryApprovalConfig`가 상속 해소를 포함한 단일 호출로 정의
- events.md 소비 이벤트 테이블에 `board.config_updated`, `user.deactivated` 수신 + 실패 시 보정 경로 명시

**개선 필요:**
- `getUsersByTeam(teamId)` vs `getUsersByRole(roleName, boardId)` 비대칭 — RD-MS-01에서 지적한 것과 동일. 계약 수준에서 통일하거나 차이를 JSDoc으로 명시 필요
- `CreateApprovalInternalDto`에 `type` 필드 없음 → type=DELETE 경로 계약 공백

---

#### RD-MS-06. 운영 고려사항 — 87/100 우수

모니터링·로깅·설정값 정의가 모범적입니다. 특히 `approval.decide_latency_ms` p95 < 500ms 목표, `bypass_count > 10/일` WARNING 같은 구체적 임계값이 운영팀과 합의하기 좋은 형태입니다.

**잘 된 점:**
- 9개 메트릭 + 7개 알림 임계값 + 7개 로그 레벨 가이드가 빠짐없이 정의
- 외부 설정값 카탈로그(README §외부 설정값 카탈로그)가 기본값·용도·참조를 포함
- 배치 연속 3회 전체 실패 시 운영자 Slack 알림(schedule.md §2.1 실패 처리)이 실무적
- `scheduled_publish.dlq_count > 0`이면 CRITICAL + PagerDuty — 적절한 심각도 분류

---

### 전문 차원

#### EX-MS-SR-01. 런타임 안정성 설계 — 86/100 우수

8년간 금융권 SI에서 겪었던 워커 장애·메시지 유실 사고를 떠올리면, 이 스펙의 비동기 안정성 설계는 상당히 견고합니다. Round 4에서 concurrency 근거가 추가된 것이 특히 반갑습니다 — "왜 1인가?"에 대한 DB 커넥션 풀·낙관적 락 충돌 근거가 코드 리뷰 때 논쟁을 줄여줄 겁니다.

**실무 시뮬레이션 관점에서 잘 된 점:**
- `scheduled-publish` Job의 멱등성 키(`scheduled-publish:{approvalId}`) + Worker 내 상태 이중 체크(`Approval.status !== approved` → 스킵, `Document.status === published` → 스킵) — 과거에 중복 발행으로 ES 인덱스가 꼬였던 경험상 이 이중 체크가 필수임
- 분산 락 TTL이 배치 주기와 정합(자동 반려: 5분/5분, 리마인더: 매일/10분, 위임 만료: 매일/5분, 보정: 30분/15분)
- Critical tx 타임아웃 30~60초 + 롤백 전체 원칙(rules.md §1.4) — 한쪽만 반영된 좀비 상태 방지
- DocumentModule 장애 시 폴백 전략(schedule.md §2.4): 지수 백오프 3회 → 다음 주기 자동 재시도 → 한계 알림

**아쉬운 점:**
- schedule.md §2.1 자동 반려 배치의 `maintenance_pause_interval` 함수가 "DB 함수 또는 애플리케이션 계산"으로 열려 있는데, 두 경로의 성능 특성이 다름(DB 함수: 쿼리 내 계산 가능 but 함수 관리 부담 / 앱: N+1 but 단순). 권장 경로를 하나로 제시하면 좋겠음
- 서킷 브레이커 패턴에 대한 언급 없음 — 모놀리스 내부 호출이므로 필수는 아니나, DocumentModule의 `transitionToPublished`가 ES enqueue 등 외부 의존을 포함할 수 있으므로 배치 호출 경로에서 고려 여지 있음

---

#### EX-MS-SR-02. 참조 무결성 — 81/100 우수

Round 4에서 BR-APR-031~035 전량 추가 + 에러 코드 2종 추가로 "정의는 있는데 참조가 없는" 유령 규칙/에러 코드가 대폭 줄었습니다. board.config_updated 통일도 좋습니다. 다만 아직 3건의 참조 불일치가 남아 있습니다.

**개선된 점(Round 3 대비):**
- BR-APR-035 `APR_ACTIVE_APPROVAL_EXISTS` — 기존 BR-APR-007(이미 pending이면 차단)과 짝을 이루며, api.md 에러 코드 테이블에도 적용 엔드포인트까지 명시
- BR-APR-033 `APR_DELEGATION_INVALID_SELF_AUTHOR` — 위임×자기승인 교차 규칙이 신설되어 직무 분리 빈틈 보완
- BR-APR-034 관리자 오버라이드 + self_approve_blocked 교차 — 구현 가이드(`requester_id === actor_id`)까지 명시
- events.md 소비 이벤트 `board.config_updated` 통일 (기존 `board.policy_updated`에서 변경)

**남은 불일치:**
1. **events.md `ApprovalSubmittedEvent.policyId`** — `ApprovalPolicy` → `ApprovalLineTemplate` 모델 전환이 완료된 상태에서 레거시 필드가 잔류. `templateId`로 수정 필요 → P2
2. **BR-APR-033 "위반 시" 적용 범위 모호** — 트리거는 "위임이 활성인 승인 건에서 승인 대상자 판별"(decide 시점)인데, 위반 시에 "위임 생성 시 작성자를 위임 대상으로 지정"을 언급. 위임은 게시판 단위(`board_id`)이므로 생성 시점에 특정 문서 작성자 검증 불가. api.md 에러 코드 테이블에서도 `delegation 생성`이 적용 엔드포인트로 나열됨 → P2
3. **`CreateApprovalInternalDto`에 `type` 필드 부재** — Approval.type이 PUBLISH/DELETE 두 값을 갖고 BR-APR-031이 DELETE 워크플로를 정의하지만, 내부 DTO가 type을 전달하지 못함 → P1

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P1 | EX-MS-SR-02 | `CreateApprovalInternalDto`에 `type` 필드 없음 — type=DELETE 결재 생성 계약 부재 | `api.md §CreateApprovalInternalDto` | add | BR-APR-031 삭제 결재 구현 시 Document→Approval 호출 불가. 모델(data.md)과 규칙(rules.md)은 DELETE를 정의했으나 내부 API 계약에 전달 수단 없음 | `CreateApprovalInternalDto`에 `type?: 'PUBLISH' \| 'DELETE'` 필드 추가 (기본값 PUBLISH). 또는 `CreateDeleteApprovalInternalDto`를 별도 정의 |
| P2 | EX-MS-SR-02 | `ApprovalSubmittedEvent.policyId` 레거시 잔류 | `events.md §approval.submitted` | fix | ApprovalPolicy→ApprovalLineTemplate 전환 완료 상태에서 이벤트 소비자가 policyId를 참조하면 항상 null. 감사 로그 추적에 빈 값 | `policyId` → `templateId: string \| null`로 변경 |
| P2 | EX-MS-SR-02 | BR-APR-033 "위반 시" 적용 범위 모호 — 위임 생성 시점에 문서 작성자 검증 불가 | `rules.md §BR-APR-033`, `api.md §에러 코드` | fix | 위임은 게시판 단위이므로 생성 시 특정 문서 작성자와 대조 불가. 구현 시 "어느 시점에서 어떻게 검증?"이 불명확 | 위반 시 설명을 decide 경로 한정으로 수정. api.md 에러 코드 적용 엔드포인트에서 "delegation 생성" 제거, "decide(위임 경로)" 한정으로 변경 |
| P2 | RD-MS-01 | `getUsersByTeam(teamId)`에 boardId 파라미터 없음 — getUsersByRole과 비대칭 | `api.md §AuthExportService` | decision | TEAM 단계에서 APPROVE 권한 필터링 위해 별도 hasPermission N회 호출 필요. getUsersByRole은 boardId로 한 번에 필터링. N+1 우려 | (A) boardId 파라미터 추가하여 대칭 맞추기 또는 (B) 의도적 차이라면 JSDoc에 "APPROVE 필터링은 호출측에서 hasPermission으로 수행" 명시 |
| P3 | RD-MS-02 | batch-decide vs 단건 decide의 stepOrder 처리 비대칭에 대한 구현 가이드 부재 | `api.md §batch-decide` | add | 단건 decide는 클라이언트가 stepOrder 지정, batch-decide는 서버가 자동 특정. 주니어 구현 시 혼란 가능 | batch-decide 설명에 "단건 decide와의 차이점" 1줄 구현 가이드 추가 |
| P3 | RD-MS-04 | type=DELETE 결재의 Document→Approval 호출 경로 상세 미정의 | `api.md §연동 계약`, `rules.md §BR-APR-031` | add | P1과 연관. PUBLISH 경로는 Submit→createApproval으로 정의됐으나, DELETE 경로의 트리거 엔드포인트·내부 호출 흐름 미기술 | "호출 흐름" 섹션에 DELETE 경로 추가: `DELETE /documents/:id` → `ApprovalService.createApproval({...type: 'DELETE'})` 또는 동등 |

---

## 설계 질문

| ID | 질문 | 블로킹 항목 |
|----|------|-------------|
| DQ-1 | `getUsersByTeam`에 boardId를 추가하여 getUsersByRole과 대칭을 맞출 것인지, 아니면 의도적으로 팀 멤버 목록만 반환하고 권한 필터링은 호출측 책임으로 둘 것인지? | P2 #4 |
| DQ-2 | type=DELETE 결재 생성은 기존 `createApproval(dto)` 메서드에 type 파라미터를 추가하여 통합할 것인지, 별도 `createDeleteApproval(dto)` 메서드로 분리할 것인지? | P1 #1, P3 #6 |

---

## Round 3 → Round 4 개선 공정 반영

| 수정사항 | 반영 확인 | 점수 영향 |
|----------|:---------:|-----------|
| BR-APR-031~035 전량 추가 | ✅ rules.md §2에 5개 규칙 완비, 에러 코드 테이블 정합 | EX-MS-SR-02 +3 |
| APR_ACTIVE_APPROVAL_EXISTS + APR_DELEGATION_INVALID_SELF_AUTHOR 추가 | ✅ rules.md §4 + api.md §에러 코드 양쪽 반영 | RD-MS-01 +2 |
| board.policy_updated → board.config_updated 통일 | ✅ events.md §2 소비 이벤트 | EX-MS-SR-02 +1 |
| ft:approval.delegation OFF 시 동작 명시 | ✅ README §피처 게이트 + rules.md §3 양쪽 서술 | RD-MS-02 +1 |
| AuthExportService.getUsersByTeam 추가 | ✅ api.md §Auth 모듈 내부 계약 | RD-MS-05 +2 |
| schedule.md 동시 처리수 근거 추가 | ✅ schedule.md §4 신설, 3개 고려사항 + 표 | RD-MS-03 +2, EX-MS-SR-01 +2 |
| BR-APR-034 구현 가이드 추가 | ✅ rules.md §BR-APR-034 "구현 가이드" 항목 | RD-MS-02 +1 |

Round 3의 주요 지적사항 7건 중 **7건 모두 반영**. 종합 점수 83 → 85 (+2). 새로 발견된 P1 1건(type 필드)이 상승폭을 제한했으나, 전반적으로 꾸준한 개선 궤도에 있습니다.
