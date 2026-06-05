# ADR-010: BoardPolicyBinding 제거 및 Board 직접 FK 전환

- **상태**: 승인됨
- **날짜**: 2026-03-26
- **의사결정자**: 개발팀
- **관련 문서**: [board-module](../03-module-design/board/data.md), [approval-module](../03-module-design/approval/data.md), [rdb](../02-architecture/data/aicm/rdb.md)

> ⚠️ **역주 (용어 갱신)**: 이 ADR이 다루던 **approval_policy_id**(Board → 정책 FK)는 현재 **mandatory_approval_config**(JSONB)와 **default_approval_template_id**로 대체되었다. 아래는 당시 BoardPolicyBinding 제거 및 직접 FK 전환에 대한 의사결정 기록이다.

---

## 1. 컨텍스트

### 1.1 기존 설계 — BoardPolicyBinding

BoardModule은 게시판에 승인 정책을 연결하기 위해 **BoardPolicyBinding** 중간 테이블을 사용했다. `action_type` 컬럼(PUBLISH, REPUBLISH, DELETE)으로 액션별 독립 승인 정책을 바인딩하는 구조였다.

```
Board ||--o{ BoardPolicyBinding : "1:N (액션별 승인 정책)"
BoardPolicyBinding }o--|| ApprovalPolicy : "N:1"
```

| action_type | 설명 |
|-------------|------|
| `PUBLISH` | 신규 문서 발행 시 승인. 바인딩 존재 여부가 관리 모드/자유 모드 결정 |
| `REPUBLISH` | 수정 후 재발행 시 승인. 바인딩 없으면 재승인 없이 즉시 재발행 |
| `DELETE` | 문서 삭제 시 승인. 바인딩 없으면 즉시 소프트 딜리트 |

### 1.2 문제

**1. 운영에서 액션별 차등 승인이 불필요하다**

실제 운영 시나리오를 검토한 결과, 승인 정책이 있는 게시판에서는 발행·재발행·삭제 **모든 액션에 동일한 정책**이 적용된다. "발행은 2단계, 삭제는 1단계"처럼 액션별로 다른 정책을 적용하는 요구사항이 없다.

**2. PUBLISH/REPUBLISH 구분이 불필요하다**

토씨 하나를 수정하든 전체를 다시 쓰든, 승인 정책이 있으면 **무조건 동일 승인**을 거쳐야 한다. 최초 발행과 재발행의 승인 강도를 차등 적용하는 것은 운영 정책에 맞지 않다.

**3. Board의 다른 정책 FK와 패턴이 불일치한다**

Board는 `default_template_id`(직접 FK → Template)와 `default_retention_policy_id`(직접 FK → RetentionPolicy)를 이미 직접 FK로 보유한다. ApprovalPolicy만 중간 테이블을 거치므로 패턴이 일관되지 않아 코드·문서 이해에 혼동을 준다.

**4. 중간 테이블의 오버헤드**

BoardPolicyBinding은 `action_type`, `enabled` 등 사용하지 않는 차원을 가지며, 승인 여부 판단 시 항상 JOIN이 필요하다.

---

## 2. 결정

### 2.1 BoardPolicyBinding 테이블 제거

BoardPolicyBinding 테이블과 관련 DDL, 인덱스를 모두 제거한다.

### 2.2 Board에 approval_policy_id 직접 FK 추가

```sql
approval_policy_id UUID REFERENCES approval_policy(id) ON DELETE SET NULL
```

- `NULL`이면 **자유 모드** — 승인 없이 직접 발행/수정/삭제, 버전 관리 없음
- 값이 있으면 **관리 모드** — 발행·재발행·삭제 모두 해당 정책으로 승인, 버전 관리 ON

### 2.3 승인=버전 동기화 규칙 유지

기존 규칙의 핵심은 유지한다. 판단 기준만 변경된다.

| 기존 | 변경 후 |
|------|--------|
| PUBLISH 바인딩 존재 여부 (`enabled = true`) | `Board.approval_policy_id IS NOT NULL` |

### 2.4 모드 판단 로직

```
function isManaged(boardId):
  return Board.find(boardId).approval_policy_id is not null

function getApprovalPolicy(boardId):
  return Board.find(boardId).approval_policy_id
```

---

## 3. 근거

### 3.1 단일 승인 정책이면 중간 테이블이 불필요하다

BoardPolicyBinding의 존재 이유는 `action_type`이라는 차원이 있기 때문이었다. 모든 액션에 동일 정책을 적용하면 이 차원이 사라지고, 관계가 Board:ApprovalPolicy = N:0..1로 단순화된다. N:0..1은 직접 FK로 표현하는 것이 정석이다.

### 3.2 Board 내 정책 FK 패턴 일관성

| FK | 대상 | 패턴 |
|----|------|------|
| `default_template_id` | Template | Board 직접 FK |
| `default_retention_policy_id` | RetentionPolicy | Board 직접 FK |
| `approval_policy_id` | ApprovalPolicy | **Board 직접 FK** (변경 후) |

세 정책/설정이 모두 동일한 패턴을 따르므로, 새로운 개발자가 구조를 이해하는 데 드는 인지 비용이 줄어든다.

### 3.3 DB 참조 무결성

직접 FK는 DB 레벨에서 참조 무결성을 보장한다. polymorphic 연결 테이블(하나의 `policy_id` 컬럼이 여러 테이블을 가리킴)은 DB FK 제약을 걸 수 없어 앱 레벨 검증에 의존해야 한다.

### 3.4 쿼리·코드 단순화

- 승인 정책 조회: `Board.approval_policy_id`로 즉시 접근 (JOIN 불필요)
- 관리 모드 판단: `approval_policy_id IS NOT NULL` (WHERE 절 하나)
- NestJS 엔티티: Board에 `@ManyToOne` 직접 관계 (중간 엔티티 제거)

---

## 4. 검토한 대안

| 대안 | 채택 여부 | 사유 |
|------|----------|------|
| 기존 유지 (PUBLISH/REPUBLISH/DELETE 분리) | 기각 | 모든 액션에 동일 승인 적용 → action_type 차원 불필요. enabled 플래그도 사용처 없음 |
| REPUBLISH만 제거 (PUBLISH/DELETE 유지) | 기각 | 남은 2개도 동일 정책 → 바인딩 테이블 존재 이유가 약함. 최소 2개 이상의 차원이 있어야 중간 테이블이 정당화됨 |
| polymorphic 연결 테이블 (`board_policy`) | 기각 | `policy_type` + `policy_id`로 다양한 정책을 하나의 테이블에 바인딩하는 방식. DB FK 무결성 상실(policy_id가 어떤 테이블인지 DB가 모름), 고아 레코드 위험. 현재 정책 종류 3개로 확장 빈도가 낮아 직접 FK의 안전성이 우선 |
| BoardConfig 1:1 테이블 부활 | 기각 | Board에서 분리할 BoardConfig 필드가 `approval_policy_id`, `default_template_id`, `default_retention_policy_id` 3개뿐. 항상 함께 조회되므로 분리 시 불필요한 JOIN만 추가 |

---

## 5. 영향

### 5.1 제거되는 테이블

| 테이블 | 사유 |
|--------|------|
| `board_policy_binding` | Board.approval_policy_id 직접 FK로 대체 |

### 5.2 변경되는 엔티티

| 엔티티 | 변경 내용 |
|--------|----------|
| Board | `approval_policy_id UUID FK → ApprovalPolicy (nullable)` 추가 |

### 5.3 문서 갱신

| 문서 | 변경 내용 |
|------|----------|
| board-module.md | ERD, Board 필드, 설계 결정, DDL 전면 개편. BoardPolicyBinding 섹션 삭제 |
| rdb.md | 전체 조감도 ERD 갱신, 모듈별 엔티티 목록 변경, 테이블 수 51 → 50 |
| approval-module.md | 관련 문서 링크 수정 |
| document-module.md | BoardPolicyBinding 참조 제거 |
| 00-overview.md | BoardPolicyBinding 참조 수정 |
| FD-APR, FD-DOC, FD-COM, overview | BoardPolicyBinding → Board.approval_policy_id 용어 치환 |
| document-lifecycle, approval-permission 흐름도 | 승인 플로우 설명 수정 |

### 5.4 코드 영향

| 영역 | 변경 내용 |
|------|----------|
| BoardModule 엔티티 | BoardPolicyBinding 엔티티 삭제, Board에 `approval_policy_id` 관계 추가 |
| BoardService | 승인 정책 바인딩 CRUD → Board 필드 업데이트로 단순화 |
| ApprovalService | `BoardPolicyBinding.find()` → `Board.approval_policy_id` 직접 참조 |
| DB 마이그레이션 | `board_policy_binding` 테이블 DROP, `board` 테이블에 `approval_policy_id` 컬럼 ADD |
