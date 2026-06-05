> **문서 유형**: FD
> **종합 점수**: 87 / 100 (공용 87 × 0.6 + 전문 87 × 0.4)
> **리뷰 대상**: `docs/01-requirements/features/FD-APR-승인워크플로.md`
> **페르소나**: 최민재 — 시니어 백엔드 개발자 (AI)
> **리뷰일**: 2026-04-07 17:30
> **지적사항**: P1: 0건, P2: 3건, P3: 3건
> **자동 반영 가능**: 4건 / 설계 결정 필요: 2건
> **라운드**: Round 4 (이전: Round 3 — 84점)

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-FD-01 | 비즈니스 규칙 명확성 | 88 | 30% | BR-033 에러코드·BR-034 관리자 적용·BR-035 bypass 예외·409 계층 분리 모두 Round 4에서 해소되어 35개 BR의 트리거-조건-동작이 구현 판단 가능 수준 |
| RD-FD-02 | 상태 전이 완결성 | 86 | 20% | Mermaid 다이어그램이 bypass·예약·삭제 결재 경로를 커버하나, bypass 시 기존 건 `cancelled` 전이가 다이어그램에는 미반영 |
| RD-FD-03 | 데이터 모델 설계 타당성 | 86 | 20% | 엔티티 통합 스키마가 data.md SSoT 원칙을 지키며, §7.3에서 `cancelled` 도입 필요를 명시했으나 status ENUM 확정은 data.md에 위임된 상태 |
| RD-FD-04 | 확장성/유연성 | 88 | 15% | Phase 1/2 경계, 피처 게이트 7개 키, §7.6 사후검토·§12 에스컬레이션 향후 확장 분리가 명확 |
| RD-FD-05 | 규칙 간 정합성 | 85 | 10% | BR-007↔035 계층 분리가 깔끔하나, `ft:approval.delegation` 키가 FD 피처 게이트 표에 누락되어 rules.md와 gap 존재 |
| RD-FD-06 | 비기능 요구 완전성 | 87 | 5% | 가용성·처리량·응답시간·감사 보관이 표로 정리되어 있으며 큰 누락 없음 |
| | **공용 소계** | **87** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-FD-SR-01 | BR 구현 충분성 | 88 | 40% | BR-033·034·035 모두 에러코드+계층+트랜잭션 시퀀스까지 서비스 메서드로 바로 옮길 수 있는 수준 |
| EX-FD-SR-02 | 규칙-기능 추적 완전성 | 86 | 30% | 35개 BR이 카탈로그↔본문↔에러코드 3중 매핑으로 추적 가능. `ft:approval.delegation` FD 표 누락이 유일한 추적 gap |
| EX-FD-SR-03 | 암묵적 복잡도 노출 | 85 | 30% | bypass↔일반 submit 동시성 경합이 Round 4에서 크게 해소됐으나, bypass 취소 알림 동기/비동기 구분과 DELETE+재편집 교차 시나리오가 약간 미노출 |
| | **전문 소계** | **87** | 100% | |

### 종합: 87 / 100 (공용 87 × 0.6 + 전문 87 × 0.4) — Round 3 대비 +3

---

## 차원별 상세 피드백

### 공용 차원

#### RD-FD-01. 비즈니스 규칙 명확성 — 88/100 우수

Round 3에서 지적한 항목들이 모두 깔끔하게 해소됐다. 특히 에러 코드 카탈로그 상단의 "409 중복·활성 건 계층" 설명 블록이 인상적이다. `APR_ALREADY_PENDING`(Document Controller) vs `APR_ACTIVE_APPROVAL_EXISTS`(ApprovalService)의 검증 계층 분리를 한 문단으로 명확히 서술한 것은, 실제 구현 시 "어느 레이어에서 어떤 에러를 뱉는지" 핑퐁을 예방하는 데 큰 도움이 된다.

BR-034의 "관리자 오버라이드를 쓰더라도 본인 작성 문서를 직접 최종 승인하는 것은 허용하지 않는다"는 경계가 명확해졌고, 에러코드 `APR_SELF_APPROVE_BLOCKED`에 "(BR-APR-034)" 태깅까지 되어 있어 추적이 깨끗하다.

BR-035의 bypass 예외 서술도 좋다. "일반 Submit만 적용"이라는 원칙과 "bypass는 기존 pending을 자동 취소하는 예외 경로"라는 구분이 §3과 §7.3 양쪽에서 교차 확인 가능하다.

#### RD-FD-02. 상태 전이 완결성 — 86/100 우수

Mermaid 다이어그램이 draft↔pending_review↔published, approved_scheduled, bypass 경로를 잘 커버하고 있다. 다단계 승인이 `pending_review` 내부에서 진행된다는 설명도 적절하다.

다만 bypass 시 기존 pending 건이 `cancelled`로 전이되는 경로가 §7.3 본문에만 서술되어 있고 다이어그램에는 없다. FD 다이어그램은 문서 상태 흐름만 표현하므로 구조적 문제는 아니지만, Approval.status 전이(pending → cancelled)가 시스템 전용이라는 점을 rules.md §1.1 다이어그램에 반영할 필요가 있다.

#### RD-FD-03. 데이터 모델 설계 타당성 — 86/100 우수

엔티티 통합 스키마에서 data.md SSoT 원칙을 잘 지키면서도, FD 맥락에서 필요한 핵심 필드를 표로 요약해 놓은 것이 좋다. ADR-011 `is_bypass` 제거 결정까지 인라인으로 언급하여 의사결정 추적이 가능하다.

§7.3에서 "ENUM에 `cancelled`가 아직 없으면 data.md CHECK 제약·마이그레이션과 함께 도입하거나"라고 써 놓은 것은 적절한 위임이지만, FD가 요구사항의 원천이므로 "`cancelled`를 도입한다"고 단언하고 data.md에 반영을 지시하는 편이 SSoT 방향과 더 맞다.

#### RD-FD-04. 확장성/유연성 — 88/100 우수

Phase 1과 향후 확장의 경계가 명확하다. §7.6 사후 검토의 "Phase 1 RDB 스키마에는 해당 컬럼이 없으며"라는 선언, §12의 단계별 리마인더/에스컬레이션 향후 확장 분리가 깔끔하다. 피처 게이트 7개 키가 rules.md §3과 동일 키라는 참조도 있어서 점진적 롤아웃 경로가 보인다.

#### RD-FD-05. 규칙 간 정합성 — 85/100 우수

BR-007과 BR-035의 관계가 Round 4에서 완전히 해소되었다. BR-007은 "일회성 원칙 + 문서 상태 pending_review에서 재시도 시 APR_ALREADY_PENDING"이고, BR-035는 "DB 레벨에서 pending Approval 1건 강제 + APR_ACTIVE_APPROVAL_EXISTS"로, 검증 시점과 계층이 명확히 분리된다.

남은 gap은 rules.md §3에 `ft:approval.delegation` 피처 게이트가 있는데 FD §1 피처 게이트 표에 누락된 점이다. rules.md에서 "비활성 시 위임 API 404, 인박스·decide에서 위임 확장 비활성화"까지 서술하고 있으므로 FD에서도 키를 명시해야 한다.

#### RD-FD-06. 비기능 요구 완전성 — 87/100 우수

비기능 요구사항이 가용성, 처리량, 동시 처리, 감사 로그, 큐 분리, 스케줄러 정밀도, API 응답시간, 일괄 처리량, 감사 로그 보관까지 9개 항목으로 표 정리되어 있어 누락이 거의 없다.

### 전문 차원

#### EX-FD-SR-01. BR 구현 충분성 — 88/100 우수

시니어 백엔드 관점에서 이 FD만 읽고 서비스 메서드를 설계할 수 있는지 시뮬레이션했다.

**구현 직행 가능한 부분**: BR-033의 "위임받은 사용자가 해당 건의 문서 작성자이면 해당 단계에서 위임 무효 → `APR_DELEGATION_INVALID_SELF_AUTHOR`"는 `decide()` 메서드에서 `if (delegate.userId === approval.requesterId && step.isDelegated) throw` 한 줄로 변환된다. BR-034의 `requester_id === actor_id` 체크도 마찬가지.

**bypass 트랜잭션 시퀀스**: §7.3의 "먼저 해당 pending 건을 cancelled → 감사·이력 기록 → 알림 이벤트 → bypassed 생성 → 동일 트랜잭션에서 published 전환"이 순서가 명확해서 `BypassService.execute()`의 트랜잭션 경계를 잡는 데 문제 없다.

BR-035의 두 에러코드 계층 분리로 "Document Controller에서 먼저 문서 상태 체크 → Approval Service에서 DB 유니크 체크"라는 방어 심층(defense in depth)이 자연스럽게 설계된다.

#### EX-FD-SR-02. 규칙-기능 추적 완전성 — 86/100 우수

35개 BR이 카탈로그 → 본문 참조 섹션 → 에러 코드 카탈로그의 3중 매핑으로 추적 가능하다. 유령 규칙이나 고아 규칙이 보이지 않는다.

유일한 추적 gap은 `ft:approval.delegation`이다. rules.md §3에서 이 키의 비활성 시 동작까지 상세히 기술하고 있는데, FD §1 피처 게이트 표에 행이 없다. 위임은 §8 전체를 차지하는 주요 기능이므로 피처 게이트 표에 포함되어야 한다.

#### EX-FD-SR-03. 암묵적 복잡도 노출 — 85/100 우수

Round 4에서 가장 크게 개선된 차원이다. bypass↔일반 submit의 동시성 경합 시나리오가 BR-035 예외 + `cancelled` 상태 도입으로 명확해졌다.

남은 암묵적 복잡도:

1. **bypass 취소 알림의 동기/비동기**: §7.3에서 "관련 승인권자에게 알림을 발송한 뒤 새 긴급 발행 건을 bypassed로 생성한다"라고 서술하는데, 이벤트 계약에서 모든 알림은 비동기(`NTF 이벤트 → notification 큐`)이므로 본문은 "발송한 뒤"가 아니라 "이벤트를 발행한 뒤"가 정확하다.

2. **DELETE 결재 + 재편집 교차**: BR-035로 동시 pending이 차단되지만, DELETE 결재가 pending인 상태에서 다른 사용자가 해당 published 문서를 재편집하려는 시나리오는 FD-APR에서 다뤄지지 않는다.

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P2 | RD-FD-05, EX-FD-SR-02 | FD §1 피처 게이트 표에 `ft:approval.delegation` 키 누락 — rules.md §3에는 상세 동작까지 있음 | FD-APR §1 피처 게이트 표 | add | 위임은 §8 전체를 차지하는 핵심 기능인데 피처 게이트 표에서 빠지면 프론트엔드가 게이트 키를 놓칠 수 있음 | FD 피처 게이트 표에 `ft:approval.delegation` 행 추가 + 비활성 시 API 404 · 위임 확장 비활성 동작 1줄 서술 |
| P2 | RD-FD-03 | `cancelled` 상태를 FD에서 요구하면서도 "도입하거나 동등한 상태로 맞추라"로 위임 — FD가 SSoT 원천이므로 단언이 적절 | FD-APR §7.3, 엔티티 통합 스키마 | fix | data.md 담당자가 "도입 여부"를 재논의할 여지가 남아 구현 착수가 지연될 수 있음 | §7.3에서 "`cancelled` 상태를 Approval.status ENUM에 추가한다"로 단언하고, 엔티티 통합 스키마의 status 열거에도 `cancelled` 포함 |
| P2 | RD-FD-05 | api.md §bypass 에러코드에 `APR_ALREADY_PENDING`이 남아 있어 FD §7.3(bypass는 기존 pending 자동 취소) 의도와 불일치 | FD-APR §7.3 마지막 문장, api.md §bypass 에러코드 | align | FD에서 "갱신 대상"이라고 명시했지만 api.md 미수정 상태가 지속되면 구현자가 bypass에서 409를 뱉는 코드를 그대로 작성할 리스크 | FD §7.3의 "갱신한다" 지시를 api.md에 실제 반영. bypass 에러코드에서 `APR_ALREADY_PENDING` 제거하고 기존 pending 자동 취소 트랜잭션 서술 추가 |
| P3 | EX-FD-SR-03 | bypass 시 기존 pending 건 취소 알림이 §7.3에서 동기 시퀀스처럼 읽힘 — 실제로는 이벤트 발행(비동기) | FD-APR §7.3 | fix | 구현자가 트랜잭션 내 동기 알림 발송을 시도할 수 있음 | "알림을 발송한 뒤" → "관련 승인권자에게 취소 알림 이벤트를 발행한 뒤" 또는 "(이벤트 기반 비동기)" 주석 추가 |
| P3 | RD-FD-02 | DELETE 결재 pending 중 해당 문서 재편집 가능 여부가 FD-APR·FD-DOC 어디에도 명시되지 않음 | FD-APR §11.4 또는 FD-DOC | decision | DELETE pending 중 문서 수정이 허용되면 삭제 대상 문서가 변경되는 모순, 차단하면 잠금 정책 필요 | §11.4에 "DELETE pending 중 문서는 published 유지 + 수정 잠금(BR-APR-005 준용 또는 별도 정책)" 1줄 추가하거나 FD-DOC에 위임 |
| P3 | RD-FD-02 | Approval.status 전이에 `pending → cancelled`(시스템 전용, bypass 경로) 경로가 rules.md §1.1 다이어그램에 미반영 | rules.md §1.1 | add | cancelled가 시스템 전용 종료 상태임이 전이 다이어그램에 없으면 상태 머신 구현 시 누락 가능 | rules.md §1.1 다이어그램에 `pending → cancelled : 긴급 발행에 의한 시스템 취소 [BR-APR-035]` 전이 추가 |

---

## Round 3 → 4 개선 공정 반영

| 수정사항 | 반영 확인 | 점수 영향 |
|----------|-----------|-----------|
| Bypass 시 기존 pending 건 자동 cancelled → bypassed 생성 | §7.3에 상세 서술, BR-035에 예외 경로 명시 | RD-FD-01 +3, EX-FD-SR-03 +3 |
| APR_ALREADY_PENDING vs APR_ACTIVE_APPROVAL_EXISTS 계층 분리 | 에러 코드 카탈로그 상단 설명 블록 추가, 각 에러코드에 계층 명시 | RD-FD-01 +2, EX-FD-SR-01 +2 |
| BR-033 에러코드 APR_DELEGATION_INVALID_SELF_AUTHOR 추가 | §8.5 + 에러 코드 카탈로그에 반영 | EX-FD-SR-01 +1 |
| BR-034 "관리자도 적용" 명시 | §6.1 + BR 카탈로그에 반영 | RD-FD-01 +1 |
| 피처 게이트 키 정합 | rules.md §3과 7개 키 일치 (단, delegation 누락) | RD-FD-05 +2 (gap 잔존으로 +2 한정) |
| 오타 수정, BR 카탈로그 정합 보강 | 전반적 가독성 향상 | RD-FD-02 +1 |

Round 3(84) → Round 4(87): 핵심 P1 이슈 해소와 계층 분리 명확화로 3점 상승. 남은 P2 3건은 피처 게이트 표 보완·cancelled 단언·api.md 동기화 수준이라 반영 난이도가 낮다.
