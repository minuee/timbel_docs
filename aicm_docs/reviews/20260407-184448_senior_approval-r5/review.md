> **문서 유형**: 모듈스펙
> **종합 점수**: 86 / 100 (공용 87 × 0.6 + 전문 85 × 0.4)
> **리뷰 대상**: `docs/03-module-design/approval/` (README.md, data.md, api.md, rules.md, schedule.md, events.md)
> **페르소나**: 시니어 백엔드 개발자 — 최민재 (AI)
> **리뷰일**: 2026-04-07 18:44
> **Round**: 5 (이전 Round 4 = 85점)
> **지적사항**: P1: 1건, P2: 2건
> **자동 반영 가능**: 2건 / 설계 결정 필요: 1건

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-MS-01 | API 설계 품질 | 86 | 30% | CreateApprovalInternalDto `type` 추가·bypass cancelled 흐름 보강으로 개선. 단, `cancelled`가 data.md DDL에 미반영 |
| RD-MS-02 | 구현 변환 용이성 | 88 | 10% | DDL·JSONB·DTO 매핑·DELETE 호출 흐름이 명확하여 주니어도 구현 착수 가능 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 83 | 25% | `templateId` 수정 반영, BullMQ 설계 견고. `approval.cancelled` 이벤트 미정의가 감점 요인 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 91 | 15% | 승인 엔진 책임이 명확하고 Document Submit 오케스트레이션 위임이 잘 분리됨 |
| RD-MS-05 | 모듈 간 계약 명확성 | 90 | 10% | `getUsersByTeam(teamId, boardId)` 시그니처 보강, 3개 Export 계약 일관됨 |
| RD-MS-06 | 운영 고려사항 | 92 | 10% | 메트릭 9종, 알림 임계값 7건, 로그 레벨 가이드, 외부 설정값 카탈로그 완비 |
| | **공용 소계** | **87** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-MS-SR-01 | 런타임 안정성 설계 | 90 | 50% | BullMQ 재시도·DLQ·멱등성·분산 락·Graceful Shutdown 모두 실무 수준 |
| EX-MS-SR-02 | 참조 무결성 | 80 | 50% | `cancelled` 상태가 api.md/rules.md에만 존재, data.md DDL·events.md·History action에 누락 |
| | **전문 소계** | **85** | 100% | |

### 종합: 86 / 100 (공용 87 × 0.6 + 전문 85 × 0.4)

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P1 | EX-MS-SR-02 | `cancelled` 상태가 data.md Approval.status CHECK/DDL에 누락 | data.md §2.2 CHECK, §3.2 DDL | fix | api.md·rules.md에서 `cancelled`를 정의했으나 DDL `CHECK (status IN (...))` 에 없어 **INSERT 시 DB 에러 발생** | CHECK 제약에 `'cancelled'` 추가, §2.2 status 필드 설명·전이 규칙 표에 cancelled 행 추가 |
| P2 | RD-MS-03 | bypass 시 기존 pending 건 `cancelled` 전환에 대한 이벤트·감사 경로 미정의 | events.md §1.2 | add | api.md bypass 설명에 "감사·이력·알림" 언급하나 events.md에 `approval.cancelled` 이벤트 부재 → 알림/감사 누락 위험 | `approval.cancelled` 이벤트 + 페이로드(cancelledApprovalId, replacedByApprovalId, reason) 추가 |
| P2 | EX-MS-SR-02 | ApprovalHistory action CHECK에 `cancelled` 관련 액션 미포함 | data.md §2.5, §3.5 | fix | bypass 시 시스템 취소 이력을 History에 기록하려면 action enum에 값이 필요 | action CHECK에 `'cancelled'` (또는 `'system_cancelled'`) 추가 |

---

## Round 4→5 수정 반영 확인

| 수정 항목 | 반영 여부 | 확인 위치 |
|-----------|:---------:|-----------|
| CreateApprovalInternalDto `type` 필드 | ✅ | api.md §CreateApprovalInternalDto — `type?: 'PUBLISH' \| 'DELETE'` |
| events.md `policyId`→`templateId` | ✅ | events.md §1.2 `ApprovalSubmittedEvent.templateId` |
| BR-033 decide 경로 한정 | ✅ | rules.md BR-APR-033 — "**`decide`(승인/반려) 경로**에서만" 명시 |
| `getUsersByTeam(teamId, boardId)` | ✅ | api.md §Auth 모듈 내부 계약 — 두 파라미터 시그니처 |
| DELETE 호출 흐름 | ✅ | api.md §연동 계약 — DELETE 경로 별도 기술 |
| bypass 자동 cancelled | ✅ | api.md bypass 설명, rules.md §1.1 상태 전이 |
| `cancelled` 상태 추가 | ⚠️ 부분 | api.md `ApprovalStatus` 타입·rules.md 전이도에 반영, **data.md DDL 미반영** |
