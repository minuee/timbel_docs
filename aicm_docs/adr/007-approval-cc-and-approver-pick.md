# ADR-007: 승인 참조라인(CC) 및 승인자 선택(Approver Pick) 도입

- **상태**: 승인됨
- **날짜**: 2026-03-24
- **의사결정자**: 개발팀
- **관련 문서**: [approval-module.md](../03-module-design/approval/data.md), [02-module-architecture.md](../02-architecture/02-module-architecture.md), [03-auth-architecture.md](../02-architecture/03-auth-architecture.md), 기능정의서 1.4

> ⚠️ **역주 (용어 갱신)**: 이 ADR 본문의 **ApprovalPolicy**는 현재 **ApprovalLineTemplate**으로 전환되었다. **allow_requester_pick**은 기안자 주도 결재라인 모델로 통합되어 필드·플래그로는 제거되었다. 아래는 당시 의사결정 기록이다.

---

## 1. 컨텍스트

### 1.1 현재 설계: 정책 기반 고정형 (패턴 1)

현재 ApprovalModule은 **정책 기반 고정형**으로 설계되어 있다. 관리자가 ApprovalPolicy를 생성하고, 게시판(BoardConfig)에 연결하면, 해당 게시판의 모든 문서가 동일한 결재라인을 따른다. 승인 대상자는 정책 단계의 `approver_source`/`approver_target`과 BoardPermission(APPROVE)의 조합으로 자동 결정된다.

### 1.2 실무 KMS에서 반복되는 두 가지 요구

**요구 1 — "이 문서를 특정 팀장에게 올리고 싶다"**

정책이 `ROLE: 팀장`으로 지정되어 있으면 팀장 역할을 가진 모든 사용자가 승인 가능하다. 그러나 실무에서는 "내 직속 팀장에게만 올리고 싶다"는 요구가 빈번하다. 현재 설계에서는 불가하여 불필요한 승인 알림이 다른 팀장에게까지 전달된다.

**요구 2 — "법무팀에도 알려줘야 하는데"**

승인 흐름에 공식적으로 참여하지는 않지만, 특정 문서의 승인 과정을 열람하고 의견을 남기고 싶은 이해관계자가 있다. 현재 설계에서는 승인 건에 참조자를 추가하는 방법이 없다.

### 1.3 KMS vs 전자결재 — 범위 결정의 핵심

한국 전자결재 시스템(그룹웨어)은 기안자 완전 지정, 합의/협조라인, 전결/대결, 조건부 결재라인 등 고도로 복잡한 워크플로우를 제공한다. 그러나 KMS의 승인은 **콘텐츠 품질 통제**가 목적이므로, 전자결재 수준의 복잡도는 과설계다.

---

## 2. 결정

### 2.1 참조라인(CC) — 승인 건 단위 참조자 추가

기안자가 승인 요청 시 참조자(CC)를 0~N명 추가할 수 있다. CC 대상자는 알림을 받고, 승인 건 내용을 열람하고, 비구속적 코멘트를 남길 수 있다. 승인/반려 권한은 없다.

**새 엔티티: `ApprovalCc`**

| 필드 | 타입 | 설명 |
|------|------|------|
| id | UUID (PK) | |
| approval_id | UUID (FK → Approval) | 소속 승인 건 |
| user_id | UUID | 참조 대상자 |
| comment | TEXT (nullable) | 비구속적 의견 |
| read_at | TIMESTAMPTZ (nullable) | 열람 시각 |

- CC는 **단계별이 아닌 승인 건 전체**에 대해 걸린다
- CC 코멘트는 승인/반려 판정에 영향 없다 (비구속적)
- CC 코멘트는 UPDATE 허용 (ApprovalDecision의 Append-Only와 다름)

### 2.2 승인자 선택(Approver Pick) — 정책이 허용하면 기안자가 지정

정책 단계에 `allow_requester_pick` 플래그를 추가하여, 기안자가 해당 단계의 승인자를 자격 있는 풀 내에서 직접 선택할 수 있게 한다.

**변경 필드:**

| 엔티티 | 필드 | 설명 |
|--------|------|------|
| ApprovalPolicyStep | `allow_requester_pick BOOLEAN (default false)` | 기안자 승인자 선택 허용 여부 |
| ApprovalStepResult | `designated_approver_ids UUID[] (nullable)` | 기안자가 지정한 승인자 목록 |

- `allow_requester_pick = true`인 단계에서만 기안자 선택 UI 노출
- 선택 풀 = `approver_target` 역할 + 해당 게시판 APPROVE 권한 보유자
- `designated_approver_ids`가 설정되면 해당 목록에 포함된 사용자만 승인/반려 가능
- null이면 기존 동작(자격 있는 전원이 승인 가능)

---

## 3. 검토한 대안

### 대안 A: 전자결재 수준 기안자 완전 지정

기안자가 조직도에서 승인자를 자유롭게 선택하여 결재라인을 직접 구성하는 방식.

**기각 이유:**
- KMS는 콘텐츠 품질 통제가 목적 — 일관성 > 유연성
- 정책 기반 품질 관리 체계가 무력화됨 (기안자가 쉬운 승인자를 골라 올릴 수 있음)
- 관리자의 승인 정책 통제력 상실
- 전자결재 수준의 UI/UX 복잡도 발생

### 대안 B: 정책 고정형 유지 (현 상태 유지)

아무 변경 없이 현재 설계를 유지하는 방식.

**기각 이유:**
- "특정 승인자에게 올리기" 요구를 해결할 수 없음 — 불필요한 승인 알림이 다수에게 전달됨
- "참조자 추가" 요구를 해결할 수 없음 — 이해관계자가 승인 과정에서 배제됨
- 실무에서 가장 빈번한 두 가지 불만을 방치하게 됨

### 대안 C (채택): 정책 뼈대 유지 + 제한된 오버라이드

정책이 결재라인의 구조(단계 수, 승인 유형, 역할)를 결정하되, 정책이 허용하는 범위 내에서만 기안자가 부분적으로 커스터마이징할 수 있는 방식.

**채택 이유:**
- 정책 기반 일관성 유지 — 관리자가 승인 구조를 통제
- 실무 요구 대응 — 참조라인과 승인자 선택으로 가장 빈번한 불만 해소
- 최소 변경 — 기존 엔티티에 필드 1~2개 추가 + 테이블 1개 신설
- 하위 호환 — `allow_requester_pick = false`(기본값)이면 기존 동작 유지

---

## 4. 결과

### 4.1 변경된 문서

- [approval-module.md](../03-module-design/approval/data.md) — ERD, ApprovalCc 엔티티 추가, ApprovalPolicyStep/ApprovalStepResult 필드 추가, DDL
- [02-module-architecture.md](../02-architecture/02-module-architecture.md) — ApprovalModule 책임/핵심 엔티티 설명 수정
- 기능정의서 1.4 — 1.4.1(정책 엔진), 1.4.2(승인 요청), 알림, 의사결정 테이블

### 4.2 변경하지 않은 것

- `BoardConfig`, `BoardPermission` — 기존 정책 연결 구조 유지
- `03-auth-architecture.md` — 권한 모델 변경 없음 (CC는 별도 권한 불필요)
- `ApprovalHistory` action 목록 — CC 코멘트는 승인 흐름이 아니므로 이력 추적 불필요

### 4.3 향후 확장 여지

| 단계 | 기능 | 현재 상태 |
|------|------|----------|
| v2 | 전결/대결 (Proxy Approval) | `timeout_hours` 필드로 데이터 모델 선설계 완료 |
| v3 | 조건 분기 (Rule-based Dynamic) | 미설계 — 문서 속성별 정책 자동 선택 |

---

## 5. 리스크

| 리스크 | 대응 |
|--------|------|
| CC 대상자가 과도하게 많으면 알림 피로도 증가 | 앱 레벨에서 CC 인원 수 상한을 설정 가능 (예: 최대 10명) |
| 기안자가 `allow_requester_pick`을 악용하여 특정 승인자만 골라 올릴 수 있음 | 관리자가 정책 단계별로 플래그를 제어 — 민감한 단계는 `false`로 강제 |
| designated_approver_ids에 지정된 전원이 부재/퇴사하면 승인 진행 불가 | 관리자 오버라이드(기존 기능)로 비상 수단 확보, 향후 timeout 에스컬레이션으로 자동 대응 |
