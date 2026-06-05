> **문서 상태**
> | 항목 | 값 |
> |------|-----|
> | 상태 | `draft` |
> | 검수 | `unreviewed` |
> | 작성일 | 2026-03-20 |
> | 최종 수정 | 2026-03-20 |

# 승인 흐름 다이어그램

> 승인 요청부터 발행까지의 엔드투엔드 흐름을 시각화한다. 각 시나리오의 상세 전략·설계 근거는 [단일 승인](./01-single-approval.md), [다단계 승인](./02-multi-step-approval.md), [긴급 발행](./03-bypass-emergency.md)에서 다룬다.

---

## 1. 승인 상태 전이도

### 1.1 Approval 상태 전이 (전체)

```mermaid
stateDiagram-v2
    [*] --> pending : 승인 요청 (submitted)

    pending --> approved : 최종 단계 승인 완료
    pending --> rejected : 어느 단계에서든 반려
    pending --> withdrawn : 요청자 철회

    approved --> [*] : published 전환

    rejected --> [*] : draft 복귀
    withdrawn --> [*] : draft 복귀

    note right of pending
        다단계 승인:
        current_step 1 → 2 → ... → total_steps
        각 단계 내부에서 ANY/ALL/COUNT 판정
    end note
```

### 1.2 ApprovalStepResult 상태 전이 (단계별)

```mermaid
stateDiagram-v2
    [*] --> step_pending : 단계 시작

    step_pending --> step_approved : 승인 조건 충족
    step_pending --> step_rejected : 반려 발생

    step_approved --> [*] : 다음 단계로 진행 or 최종 완료
    step_rejected --> [*] : 전체 Approval rejected

    note right of step_pending
        ANY: 1명 approved → step_approved
        ALL: 전원 approved → step_approved
        COUNT: N명 이상 approved → step_approved
        1명이라도 rejected → step_rejected (ALL/COUNT)
    end note
```

### 1.3 Document 상태와 Approval 상태의 매핑

```mermaid
flowchart LR
    subgraph docStatus["Document.status"]
        D1["draft"]
        D2["pending_review"]
        D3["approved_scheduled"]
        D4["published"]
    end

    subgraph appStatus["Approval.status"]
        A1["pending"]
        A2["approved"]
        A3["rejected"]
        A4["withdrawn"]
    end

    D1 -->|"승인 요청"| D2
    D2 -.-> A1

    A1 -->|"최종 승인"| A2
    A2 -->|"즉시 발행"| D4
    A2 -->|"예약 발행"| D3
    D3 -->|"예약 시간 도래"| D4

    A1 -->|"반려"| A3
    A3 --> D1

    A1 -->|"철회"| A4
    A4 --> D1
```

---

## 2. 시퀀스 다이어그램

### 2.1 단일 승인 (1단계/ANY) — 승인 성공

```mermaid
sequenceDiagram
    actor Author as 작성자
    participant API as aicm-service
    participant DB as PostgreSQL
    participant EB as EventBus
    participant Notif as NotificationModule
    actor Approver as 승인권자

    Author->>API: POST /approvals (document_id, comment)
    API->>DB: Document.status = pending_review
    API->>DB: Approval 생성 (template_id, total_steps=1)
    API->>DB: ApprovalStepResult 생성 (step 1, type=ANY)
    API->>DB: DocumentVersion 생성 (submitted)
    API->>DB: ApprovalHistory (action=submitted)
    API->>EB: approval.requested 이벤트
    EB->>Notif: 승인권자에게 알림

    Approver->>API: POST /approvals/:id/decide (approved, comment)
    API->>DB: ApprovalDecision 생성 (approved)
    API->>DB: ApprovalStepResult.status = approved
    API->>DB: Approval.status = approved
    API->>DB: ApprovalHistory (action=approved)

    Note over API,DB: Critical 트랜잭션 (동일 TX)
    API->>DB: Document.status = published
    API->>DB: DocumentVersion.status = published

    API->>EB: document.published 이벤트
    API->>EB: approval.approved 이벤트
    EB->>Notif: 작성자에게 승인 완료 알림
```

### 2.2 다단계 승인 (2단계) — 승인 성공

```mermaid
sequenceDiagram
    actor Author as 작성자
    participant API as aicm-service
    participant DB as PostgreSQL
    participant EB as EventBus
    actor Approver1 as 1단계 승인권자
    actor Approver2 as 2단계 승인권자

    Author->>API: POST /approvals (document_id)
    API->>DB: Approval (template_id, total_steps=2, current_step=1)
    API->>DB: ApprovalStepResult x2 (step 1: pending, step 2: pending)
    API->>DB: ApprovalHistory (submitted)
    API->>EB: 1단계 승인권자에게 알림

    Approver1->>API: POST /approvals/:id/decide (approved)
    API->>DB: ApprovalDecision (step 1, approved)
    API->>DB: StepResult[1].status = approved
    API->>DB: Approval.current_step = 2
    API->>DB: ApprovalHistory (step_approved, step=1)
    API->>EB: 2단계 승인권자에게 알림
    API->>EB: 작성자에게 "1단계 통과" 알림

    Approver2->>API: POST /approvals/:id/decide (approved)
    API->>DB: ApprovalDecision (step 2, approved)
    API->>DB: StepResult[2].status = approved
    API->>DB: Approval.status = approved
    API->>DB: ApprovalHistory (approved)

    Note over API,DB: Critical 트랜잭션
    API->>DB: Document.status = published
    API->>EB: document.published 이벤트
```

### 2.3 다단계 승인 — 2단계에서 반려

```mermaid
sequenceDiagram
    actor Author as 작성자
    participant API as aicm-service
    participant DB as PostgreSQL
    participant EB as EventBus
    actor Approver1 as 1단계 승인권자
    actor Approver2 as 2단계 승인권자

    Note over Author,API: 1단계 통과까지 동일 (2.2 참조)
    Approver1->>API: POST /approvals/:id/decide (approved)
    API->>DB: StepResult[1].status = approved, current_step=2

    Approver2->>API: POST /approvals/:id/decide (rejected, "최신 규정 미반영")
    API->>DB: ApprovalDecision (step 2, rejected)
    API->>DB: StepResult[2].status = rejected
    API->>DB: Approval.status = rejected
    API->>DB: ApprovalHistory (step_rejected, step=2)
    API->>DB: ApprovalHistory (rejected)
    API->>DB: Document.status = draft
    API->>EB: 작성자에게 반려 알림 (사유 포함)

    Note over Author: 수정 후 재요청 시 1단계부터 다시 시작
```

### 2.4 긴급 발행 (Bypass)

```mermaid
sequenceDiagram
    actor Bypasser as BYPASS 권한자
    participant API as aicm-service
    participant DB as PostgreSQL
    participant EB as EventBus
    participant Audit as LogEventModule
    participant Notif as NotificationModule

    Bypasser->>API: POST /approvals/bypass (document_id, bypass_reason)

    API->>API: BYPASS_APPROVAL 권한 확인

    API->>DB: Approval 생성 (is_bypass=true, bypass_reason, status=approved)
    API->>DB: ApprovalHistory (action=bypassed)

    Note over API,DB: Critical 트랜잭션
    API->>DB: Document.status = published
    API->>DB: DocumentVersion 생성 (published)

    API->>EB: approval.bypassed 이벤트
    EB->>Audit: 감사 로그 기록 (approval.bypassed)
    EB->>Notif: 관리자 전원에게 긴급 발행 알림
    API->>EB: document.published 이벤트
```

### 2.5 승인 요청 철회

```mermaid
sequenceDiagram
    actor Author as 작성자
    participant API as aicm-service
    participant DB as PostgreSQL
    participant EB as EventBus

    Note over Author: 다단계 승인 진행 중 (step 1 통과, step 2 대기)

    Author->>API: POST /approvals/:id/withdraw

    API->>DB: Approval.status = withdrawn
    API->>DB: ApprovalHistory (action=withdrawn)
    Note over DB: StepResult, Decision 기록은 보존 (감사 추적)
    API->>DB: Document.status = draft
    API->>EB: 현재 단계 승인권자에게 철회 알림
    API->>EB: 작성자에게 철회 확인 알림

    Note over Author: 수정 후 재요청 시 새 Approval 생성 (1단계부터)
```

---

## 3. 승인 유형별 판정 로직 다이어그램

### 3.1 ANY (1명 승인 → 통과)

```mermaid
flowchart TD
    A["승인자 A가 판단"] --> B{"decision?"}
    B -->|"approved"| C["StepResult = approved<br/>(즉시 통과)"]
    B -->|"rejected"| D["StepResult = rejected<br/>(즉시 반려)"]
```

### 3.2 ALL (전원 승인 → 통과)

```mermaid
flowchart TD
    A["승인자 A가 판단"] --> B{"decision?"}
    B -->|"rejected"| REJECT["StepResult = rejected<br/>(1명이라도 반려 → 즉시 반려)"]
    B -->|"approved"| C{"전원 승인 완료?"}
    C -->|"아직 미처리자 있음"| WAIT["대기 (pending 유지)"]
    C -->|"전원 완료"| PASS["StepResult = approved"]
```

### 3.3 COUNT (정족수 N명 → 통과)

```mermaid
flowchart TD
    A["승인자 A가 판단"] --> B{"decision?"}
    B -->|"approved"| C{"approved 수 >= required_count?"}
    C -->|"미달"| WAIT["대기 (pending 유지)"]
    C -->|"충족"| PASS["StepResult = approved"]
    B -->|"rejected"| D{"남은 인원으로<br/>required_count 달성 가능?"}
    D -->|"가능"| WAIT
    D -->|"불가능"| REJECT["StepResult = rejected"]
```

---

## 관련 문서

- [README](./README.md) — 문서군 개요
- [단일 승인 시나리오](./01-single-approval.md)
- [다단계 승인 시나리오](./02-multi-step-approval.md)
- [긴급 발행 시나리오](./03-bypass-emergency.md)
- [승인 권한 평가](./04-permission-evaluation.md)
