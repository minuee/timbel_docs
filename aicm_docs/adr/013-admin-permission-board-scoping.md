# ADR-013: 게시판 관리 권한의 BoardPermission MANAGE 이관

- **상태**: 승인됨
- **날짜**: 2026-04-13
- **의사결정자**: 개발팀
- **관련 문서**: [FD-ACL-권한체계.md](../01-requirements/features/FD-ACL-권한체계.md), [04-permission-architecture.md](../02-architecture/04-permission-architecture.md) 부록 E

---

## 1. 컨텍스트

### 1.1 현재 설계: AdminPermission은 Global 스코프

현재 모든 AdminPermission은 **테넌트 전체(Global)** 에 대해 적용된다. `manage_boards` 권한을 가진 사용자는 테넌트 내 모든 게시판을 관리할 수 있고, `bypass_approval`을 가진 사용자는 모든 게시판에서 승인을 우회할 수 있다.

| 권한 체계 | 스코프 | 설명 |
|-----------|--------|------|
| BoardPermission | **게시판 단위** | 게시판 A의 VIEW/EDIT/APPROVE를 개별 부여 |
| AdminPermission | **Global (테넌트 전체)** | 이진 판단 — 있으면 전체, 없으면 전체 불가 |

이는 의도적인 설계였다. 현재 게시판 트리(parent_id)는 **사이드바 네비게이션 용도**로만 사용되며, 권한 계산에 영향을 주지 않는다(FD-DOC: "트리 구조는 네비게이션 용도일 뿐 권한 계산에 영향을 주지 않는다").

### 1.2 구조적 비대칭

문서 자원 접근과 관리 자원 접근 사이에 스코프 세밀도의 비대칭이 존재한다:

```
문서 자원 접근:  BoardPermission  → 게시판 단위 스코프  (세밀)
관리 자원 접근:  AdminPermission  → 테넌트 전체 Global  (뭉뚱그림)
```

"이 문서를 볼 수 있냐"는 게시판 단위로 세밀하게 제어하면서, "이 게시판을 관리할 수 있냐"는 전체 테넌트에 대해 이진 판단하고 있다.

### 1.3 언제 문제가 되는가

게시판 트리가 네비게이션 전용인 현재는 문제가 없다. 그러나 **루트게시판이 "자원의 조직적 경계"로 승격**되는 시나리오에서 문제가 발생한다:

```
루트게시판: HR 지식베이스        루트게시판: 기술지원 KB
├── 채용 매뉴얼                 ├── 제품 FAQ
├── 인사 정책                   ├── 트러블슈팅 가이드
└── 급여 규정 (민감)            └── 릴리즈 노트

HR 관리자 = `manage_boards` 보유 Role (전역)
→ 현재: 기술지원 KB 게시판도 관리 가능 (의도하지 않은 권한 누출)
→ 기대: HR 지식베이스 하위만 관리 가능
```

이 시나리오에서 **전역** `manage_boards`만으로 모든 게시판 자원에 접근 가능한 것은 **최소 권한 원칙(Principle of Least Privilege)** 에 위배된다.

---

## 2. 자원 스코프 분류: 글로벌 vs 루트게시판 하위

루트게시판이 조직적 경계가 되면, 현재 "관리 자원(Admin-scoped)"으로 통합 분류된 자원들을 **글로벌 자원**과 **루트게시판 하위 자원**으로 재분류해야 한다.

### 2.1 분류 기준

| 기준 | 글로벌 자원 | 루트게시판 하위 자원 |
|------|-----------|-------------------|
| 소속 | 테넌트 전체에 걸침 | 특정 루트게시판 트리 내에서만 의미 |
| 관리 주체 | 테넌트 전역 관리자 | 해당 도메인(루트게시판) 관리자 |
| 교차 사용 | 여러 루트게시판에서 공유 | 한 루트게시판 내에서만 사용 |

### 2.2 분류 결과

#### 글로벌 유지 — 테넌트 전체에 걸치는 자원

| 자원 | AdminPermission | 글로벌인 이유 |
|------|----------------|-------------|
| **Role**, UserRole, AdminPermission | `manage_roles` | 역할 체계는 조직 전체에 걸침. "HR 게시판 편집자" 역할이 HR 루트게시판에만 속하는 게 아니라, 조직 내 누구에게나 부여 가능 |
| **Team**, TeamMember, TeamRole | `manage_teams` | 팀/그룹은 조직 구조이지 게시판 구조가 아님. 한 팀이 여러 루트게시판의 문서를 관리할 수 있음 |
| **Tag** | `manage_tags` | "중요", "정책", "FAQ" 같은 태그는 도메인을 가로지르며, 교차 검색의 핵심 축 |
| **SharedContent** | `manage_shared_content` | 공통 컨텐츠 블록은 여러 게시판에서 재사용하는 것이 존재 목적 |
| **SystemConfig** | `manage_system` | 시스템 전역 설정 (배포 모드, AI 프로바이더 등) |
| **AuditLog** | `view_audit_logs` | 감사 로그를 스코프로 분리하면 감사 사각지대 발생. 전체 테넌트 감사가 본질 |
| **PromptSlot**, PromptVersion | `manage_prompts` | AI 프롬프트는 기능별 설정(요약, 글쓰기 개선 등)이지 게시판별 설정이 아님 |

#### 루트게시판 하위 — 특정 도메인에 종속되는 자원

| 자원 | AdminPermission | 하위인 이유 |
|------|----------------|-----------|
| **Board** (하위 게시판) | `manage_boards` | 루트게시판 아래의 자식 게시판은 해당 도메인의 구조. HR 관리자가 기술지원 하위 게시판을 생성/삭제하면 안 됨 |
| **BoardConfig** | `manage_boards` | 게시판 설정은 게시판에 종속 |
| **Approval 워크플로우** | `bypass_approval` | 승인 우회는 해당 도메인 내에서만 허용되어야 함. HR 관리자가 기술지원 문서 승인을 우회하는 것은 부적절 |

#### 미정 — 양면성이 있어 결정이 필요한 자원

| 자원 | AdminPermission | 쟁점 |
|------|----------------|------|
| **Template** | `manage_templates` | HR 전용 양식(퇴직 처리 양식)과 전사 공통 양식(회의록)이 공존. 루트게시판 스코프를 도입하면 **공통 양식의 소속**이 애매해짐. 별도 "Global 템플릿" 개념이 필요할 수 있음 |
| **ApprovalLineTemplate** | `manage_policies` | 도메인별 승인 라인(HR: 인사팀장→CHRO, 기술지원: 팀장→CTO)이 다를 수 있으나, 전사 공통 승인 라인("전결 라인")도 존재. Template과 유사한 혼합 문제 |
| **SearchConfig** | `manage_search` | 현재 테넌트당 싱글턴(ADR-009). 루트게시판별 검색 튜닝(HR은 정확도 위주, 기술지원은 재현율 위주)이 필요하면 **싱글턴 전제 자체가 깨짐** — 구조 변경 규모가 큼 |
| **EmbeddingConfig** | `manage_embedding` | SearchConfig와 동일한 쟁점. 도메인별 임베딩 전략이 다를 수 있으나, 현재 글로벌 설계 |

### 2.3 "미정" 자원의 설계 함의

미정 자원들은 공통적으로 **"전역 기본값 + 루트게시판별 오버라이드"** 패턴이 필요할 수 있다. 이는 현재 게시판 설정에서 `approval_required`가 루트게시판에서 설정되고 하위가 상속하는 패턴과 유사하다.

```
Template 예시:
  Global 템플릿: 회의록, 업무 보고서 (모든 루트게시판에서 사용 가능)
  HR 템플릿: 퇴직 처리 양식, 채용 평가서 (HR 루트게시판에서만 노출)
  기술지원 템플릿: 장애 보고서, 릴리즈 노트 (기술지원 루트게시판에서만 노출)
```

이 패턴을 도입하면 Template, ApprovalLineTemplate 등에 `scope_board_id: UUID | NULL` (NULL이면 글로벌) 컬럼이 필요하며, AdminPermission 스코프와는 별개의 데이터 모델 변경이 수반된다.

---

## 3. 영향받는 권한 목록

`04-permission-architecture.md` 부록 E의 스코프 후보 컬럼에 이미 식별되어 있다:

| 권한 키 | 현재 스코프 | 스코프 후보 | 스코프가 필요한 이유 |
|---------|-----------|-----------|-------------------|
| `manage_boards` | Global | **Board** | HR 관리자가 기술지원 게시판까지 관리하면 안 됨 |
| `bypass_approval` | Global | **Board** | HR 관리자가 기술지원 문서 승인을 우회하면 안 됨 |
| `manage_teams` | Global | **Team** | 조직 단위 관리자 분리 가능성 |
| 나머지 11개 | Global | Global | 테넌트 전체 적용이 적절 |

---

## 4. 스코프 도입 시 파급 범위

단순한 테이블 컬럼 추가가 아닌, 여러 계층에 걸친 변경이다:

### 4.1 AdminPermission 스키마 확장

```typescript
// 현재
AdminPermission { role_id, permission_key }

// 스코프 추가 시
AdminPermission { role_id, permission_key, scope_type, scope_id }
// scope_type: 'GLOBAL' | 'BOARD'
// scope_id:   null (GLOBAL) | root_board_id (BOARD 스코프)
```

### 4.2 메타정보 VIEW 바이패스 범위 변경

현재 BR-ACL-023(유효 역할에 AdminPermission이 있으면 메타정보 수준 VIEW 바이패스)에 스코프 조건이 추가되어야 한다:

- `manage_boards(scope: HR KB)` → HR KB 하위만 메타정보 바이패스
- 기술지원 KB는 그 외 사용자와 동일하게 BoardPermission 필요

### 4.3 권한 평가 흐름 변경

```
현재:   AdminPermission 보유? → 허용(글로벌)
스코프: AdminPermission 보유? → 대상이 스코프 내인가? → 허용
```

### 4.4 캐시 무효화 전략 변경

스코프가 추가되면 유효 역할 캐시의 키에 board 차원이 추가되어야 할 수 있다.

### 4.5 감사 로그

스코프 바이패스와 퍼미션 기반 접근을 구분해야 하므로 감사 로그 포맷에도 영향.

---

## 5. 검토 대안

### 대안 A: AdminPermission에 scope_type/scope_id 추가 — 기각

AdminPermission 테이블에 `scope_type`, `scope_id` 컬럼을 추가한다. 기존 Global 권한은 `scope_type = 'GLOBAL'`, `scope_id = NULL`로 마이그레이션.

- 장점: 기존 모델의 자연스러운 확장, UNIQUE 제약 변경만으로 스키마 호환
- **기각 사유**: 권한 평가 시 "이 게시판의 루트게시판이 뭔가"를 매번 계산해야 함. 이미 게시판 단위 스코프 인프라(BoardPermission)가 존재하는데 AdminPermission에 중복으로 스코프를 구축하는 셈

### 대안 B: Board-scoped Admin Role 도입 — 기각

AdminPermission을 건드리지 않고, Role 자체에 `admin_board_scope: UUID[]`를 추가하여 해당 Role의 관리 범위를 제한한다.

- 장점: AdminPermission 평가 로직 변경 없음
- **기각 사유**: Role과 AdminPermission의 스코프가 다른 계층에서 결정되어 직관적이지 않음. 권한의 범위가 권한 테이블이 아닌 역할 테이블에서 정해지므로 디버깅 복잡도 상승

### 대안 C: 루트게시판을 Workspace로 승격 — 기각

루트게시판을 별도 엔티티(Workspace)로 분리하고, Workspace 단위로 관리자를 할당한다. 사실상 테넌트 내 서브-테넌시.

- 장점: 가장 깔끔한 경계 분리
- **기각 사유**: 가장 큰 구조 변경. Board-Workspace 관계 신규 도입, 기존 Board 트리 모델과 충돌

### 대안 D: BoardPermission에 MANAGE action 추가 — **채택**

AdminPermission에서 게시판 종속 권한(`manage_boards`, `bypass_approval`)을 분리하여 BoardPermission의 새 action으로 이관한다. AdminPermission은 진짜 전역 운영 자원만 담당한다.

```
변경 전:
  BoardPermission  → VIEW, EDIT, APPROVE           (게시판 단위)
  AdminPermission  → 12개 키 전부 Global             (테넌트 전체)

변경 후:
  BoardPermission  → VIEW, EDIT, APPROVE, MANAGE    (게시판 단위)
  AdminPermission  → 10개 키, 진짜 전역 자원만         (테넌트 전체)
```

- **장점**:
  - 이미 존재하는 BoardPermission 인프라(게시판 단위 스코프, Role 연계, 캐시 전략)를 그대로 활용 — action enum에 MANAGE 하나 추가하는 수준
  - AdminPermission에 scope 개념을 추가할 필요 없음 — 전역/게시판 경계가 테이블 수준에서 명확히 분리
  - 특정 게시판의 관리 권한만 위임 가능 — IdP의 admin 라벨 없이도 BoardPermission(MANAGE)로 "HR 게시판 관리자" 구성 가능
  - 최소 권한 원칙(PoLP) 자연스럽게 달성
- **단점**:
  - MANAGE가 커버하는 범위(하위 게시판 CRUD + BoardConfig + Restriction + Report + 승인 우회)가 넓어 세밀도 부족 가능. 필요 시 MANAGE와 BYPASS를 분리하여 action 5개로 확장 가능

---

## 6. 결정: 자원별 스코프 분류

### 6.1 BoardPermission MANAGE로 이관하는 권한 (게시판 종속)

| 기존 AdminPermission 키 | BoardPermission action | 커버 범위 | 이관 근거 |
|---|---|---|---|
| `manage_boards` | **MANAGE** | 하위 게시판 CRUD, BoardConfig, Restriction, Report 처리 | 게시판 트리 안의 관리 행위 — HR 관리자가 기술지원 게시판을 관리하면 안 됨 |
| `bypass_approval` | **MANAGE** (통합) | 해당 게시판 내 문서의 승인 우회 | 승인 우회는 해당 도메인 내에서만 허용되어야 함 |

> **참고**: `bypass_approval`을 MANAGE와 분리하여 별도 action(`BYPASS`)으로 둘지는 구현 시 결정한다. 게시판 구조 관리자 ≠ 승인 우회자인 시나리오가 실제 발생하면 분리한다.

### 6.2 AdminPermission에 남는 권한 (전역)

| 권한 키 | 대상 | 전역인 근거 |
|---|---|---|
| `manage_roles` | Role, UserRole, BoardPermission, AdminPermission | 역할은 조직 전체에 걸침 — "HR 편집자" 역할이 HR 게시판에만 속하지 않고 조직 내 누구에게나 부여 가능 |
| `manage_teams` | Team, TeamMember, TeamRole | 팀은 조직 구조이지 콘텐츠 구조가 아님 — 한 팀이 여러 게시판의 문서를 관리할 수 있음 |
| `manage_tags` | Tag | 태그는 게시판을 가로지르는 횡단 분류 축 — 게시판별로 분리하면 교차 검색 가치 상실 |
| `manage_shared_content` | SharedContent | 공통 컨텐츠 블록의 존재 목적이 여러 게시판에서 재사용하는 것 |
| `manage_templates` | Template | 공통 템플릿(회의록, 업무보고서)은 전사 사용. 도메인 전용 템플릿(퇴직처리양식)의 노출 범위는 **템플릿 데이터 모델**(`scope_board_id`)로 제어 — 관리 권한 자체는 전역 |
| `manage_policies` | ApprovalLineTemplate | 승인 라인 템플릿은 조직 구조를 반영. 어떤 게시판이 어떤 템플릿을 쓸지는 BoardConfig에서 선택 — 템플릿 정의는 전역 |
| `manage_search` | SearchConfig, Synonym, StopWord, BoostRule | 테넌트당 싱글턴 설계(ADR-009) — 게시판별 분리 시 싱글턴 전제 붕괴 |
| `manage_prompts` | PromptSlot, PromptVersion | AI 프롬프트는 기능별 설정(요약, 글쓰기 개선)이지 게시판별 설정이 아님 |
| `manage_system` | SystemConfig | 시스템 전역 설정 |
| `view_audit_logs` | AuditLog | 감사 로그를 스코프로 분리하면 감사 사각지대 발생 — 전체 테넌트 감사가 본질 |

### 6.3 변경 후 권한 모델 요약

```
BoardPermission (게시판 단위, action 4개):
  VIEW     — 문서 열람
  EDIT     — 문서 작성/수정
  APPROVE  — 문서 승인/반려
  MANAGE   — 게시판 관리 (하위 게시판 CRUD, BoardConfig, Restriction, Report, 승인 우회)

AdminPermission (전역, 10개):
  manage_roles, manage_teams, manage_tags,
  manage_shared_content, manage_templates, manage_policies,
  manage_search, manage_prompts, manage_system, view_audit_logs
```

```
역할 구성 예시:

Role "HR 게시판 관리자"
  ├─ BoardPermission: HR KB(VIEW/EDIT/APPROVE/MANAGE)
  └─ AdminPermission: (없음) ← 전역 AdminPermission 없이도 가능

Role "전체 운영 관리자"
  ├─ BoardPermission: 전체 게시판(VIEW/EDIT/APPROVE/MANAGE)
  └─ AdminPermission: manage_roles, manage_teams, manage_tags, ...

Role "검색 관리자"
  ├─ BoardPermission: (필요한 만큼)
  └─ AdminPermission: manage_search
```

---

## 7. 영향

### 7.1 문서 갱신

| 문서 | 변경 내용 |
|------|----------|
| FD-ACL-권한체계.md | BoardPermission action에 MANAGE 추가, §6 AdminPermission에서 `manage_boards`·`bypass_approval` 제거, 권한 평가 흐름 갱신 |
| 04-permission-architecture.md | 부록 E 스코프 후보 → 확정 반영, MANAGE action 평가 흐름 추가 |
| FD-ADM-관리자.md | 게시판 관리 섹션이 BoardPermission(MANAGE) 기반으로 변경 |
| rdb.md | BoardPermission action ENUM에 `'MANAGE'` 추가 |

### 7.2 코드 영향

| 영역 | 영향 |
|------|------|
| BoardPermission action ENUM | `'MANAGE'` 추가 |
| AdminPermission 키 | `manage_boards`, `bypass_approval` 제거 (12개 → 10개) |
| PermissionService | MANAGE action 평가 로직 추가, 기존 AdminPermission 기반 게시판 관리 검사를 BoardPermission 기반으로 전환 |
| 메타정보 VIEW 바이패스 | MANAGE 보유자도 해당 게시판에 대해 메타정보 바이패스 적용 검토 |
| 프리셋 Role | "콘텐츠 관리자" 등 프리셋에 BoardPermission(MANAGE) 반영 |
| 마이그레이션 | 기존 `manage_boards` AdminPermission 보유 Role → 전체 게시판 BoardPermission(MANAGE) 일괄 부여 |

### 7.3 전역 vs 게시판 스코프 정리

게시판 관리가 BoardPermission으로 이동하면서 **전역 `AdminPermission`과 게시판 단위 권한의 경계**가 명확해진다:

| | 변경 전 | 변경 후 |
|---|---|---|
| 전역 관리 권한 | 게시판 관리 + 전역 관리 혼재 가능 | **전역 운영 자원**은 `AdminPermission`만 |
| 게시판 관리자 | 외부 "관리자" 역할 전제 문서 흔함 | 외부 사용자 유형과 무관하게 BoardPermission(MANAGE) 부여로 가능 |
| 최소 권한 원칙 | `manage_boards` Global로 과잉 권한 위험 | 필요한 게시판만 MANAGE 부여 |
