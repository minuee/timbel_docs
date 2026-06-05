# ADR-001: 자원 분류 체계 재정의 및 SYSTEM 역할 위상

- **상태**: 승인됨
- **날짜**: 2026-03-23
- **의사결정자**: 개발팀
- **관련 문서**: [resource-classification.md](../02-architecture/resource-classification.md), [permissions.md](../02-architecture/permissions.md)

> **현행 정렬(2026-04, 2026-04 갱신)**: AICM API 인가는 **AICM Role**에 매핑된 `BoardPermission`·`AdminPermission`만 사용한다. 본 ADR 본문의 NORMAL/ADMIN/SYSTEM **행렬·시드 서술**은 역사적 기록이다. 외부 `system`/`admin`/`normal` 계층이나 "관리자 등급"을 인가에 쓰지 않으며, `AdminPermission`은 **해당 키가 유효 역할에 있으면** 누구에게나 적용된다. SSoT는 [FD-ACL §2](../01-requirements/features/FD-ACL-권한체계.md)이다.

---

## 1. 컨텍스트

AICM의 자원 분류 체계 초안에서 모든 자원을 **문서 자원 / 시스템 자원 / 개인 자원** 3종으로 구분했다. 그러나 "시스템 자원"이라는 분류에 성격이 크게 다른 것들이 혼재되어 있었다.

### 1.1 기존 "시스템 자원"에 포함된 것들

| 실제 성격 | 예시 | "시스템 자원"이 적절한가? |
|-----------|------|------------------------|
| 콘텐츠 인프라 | Board, Template, Tag, SharedContent | 어색함 — 문서를 담는 그릇이지 시스템이 아님 |
| 조직 구조 | Team, TeamMember, Role | 어색함 — 사람과 조직이지 시스템이 아님 |
| 워크플로우 | ApprovalLineTemplate | 어색함 — 비즈니스 프로세스 정의 |
| 검색 튜닝 | SearchConfig, ParsingConfig, Synonym, BoostRule | 어중간 — 설정값에 가까움 |
| 운영 설정 | SystemConfig (파일 제한, 알림 기본값) | 어중간 — 자원이라기보단 설정 |
| 인프라/배포 | 배포 모드, DB 연결, feature flag | 유일하게 "시스템"에 가까움 — 하지만 자원이 아니라 설정 |

### 1.2 문제

- "시스템 자원이 아닌 것들"이 시스템 자원에 포함됨 (Board, Template 등)
- "진짜 시스템 수준"인 것들은 "자원"이 아니라 "설정값"임 (환경변수·구축 시 구성)
- 권한 체계에서 SYSTEM 역할이 런타임 UI에서 수행하는 역할이 사실상 없음

---

## 2. 결정

### 2.1 자원 분류: 3종 자원 + 시스템 설정(별도)

**런타임 권한 평가 대상인 자원**을 3종으로 분류한다:

| 자원 유형 | 영문 | 핵심 질문 | 예시 |
|-----------|------|----------|------|
| **문서 자원** | Document (Board-scoped) | "어떤 게시판의 콘텐츠인가?" | Document, Block, Comment, Like, Approval |
| **관리 자원** | Managed (Admin-scoped) | "서비스 운영을 위해 누가 관리하는가?" | Board, Template, Tag, SharedContent, Team, Role, ApprovalLineTemplate, SearchConfig, ParsingConfig, AuditLog |
| **개인 자원** | Personal (User-scoped) | "내 것인가?" | Bookmark, Notification, Subscription |

**시스템 설정**은 자원이 아니며, 런타임 권한 평가 대상이 아니다. 별도 참고 섹션으로 분리한다.

### 2.2 네이밍: "시스템 자원" → "관리 자원"

기존 "시스템 자원"을 **"관리 자원(Managed Resource)"**으로 변경한다.

| 후보 | 채택 여부 | 사유 |
|------|----------|------|
| **관리 자원** (Managed Resource) | **채택** | "ADMIN이 AdminPermission으로 관리한다"는 접근 주체가 명확. 코드의 `AdminPermission`과 이름이 일관됨 |
| 운영 자원 (Operational Resource) | 기각 | "운영"과 "시스템 운영" 혼동 가능 |
| 서비스 자원 (Service Resource) | 기각 | "시스템"과 구분이 모호 |
| 플랫폼 자원 (Platform Resource) | 기각 | 과하게 거창 |

### 2.3 권한 매핑

```
역할           개인 자원       문서 자원              관리 자원              시스템 설정
─────────────────────────────────────────────────────────────────────────────────
NORMAL         본인만         BoardPermission       접근 불가              접근 불가
                             (VIEW/EDIT/APPROVE)

ADMIN          VIEW 바이패스   VIEW 바이패스 +         AdminPermission      접근 불가
                             BoardPermission        (manage_* 키)

SYSTEM         전체 바이패스    전체 바이패스            전체 바이패스           전체 바이패스
                                                                        (배포/인프라 영역)
```

### 2.4 SYSTEM 역할의 위상

SYSTEM은 **"사람이 로그인하는 계정"이 아니라 "시스템 내부의 권한 수준"**이다.

| 측면 | 설명 |
|------|------|
| **코드 레벨** | 권한 평가 최상위 바이패스 (`if role === SYSTEM → skip all`) |
| **서비스 레벨** | 서비스 간 내부 호출의 identity (chunk_service → Document 접근 등) |
| **부트스트랩** | 시드 스크립트의 실행 주체 (배포 시 기본 Role/Permission 생성) |
| **런타임 UI** | 없음 (로그인 화면 미제공) |
| **개발 편의** | 개발 환경에서 권한 무시하고 테스트할 때 사용 |

### 2.5 부트스트랩 문제와 시드 스크립트

최초 배포 시 Role/AdminPermission이 비어있어 ADMIN도 관리 화면에 접근할 수 없는 닭과 달걀 문제가 발생한다.

**SYSTEM 계정 로그인 방식** 대신 **시드 스크립트 방식**을 채택한다:

| 방식 | 채택 여부 | 사유 |
|------|----------|------|
| SYSTEM 계정으로 수동 로그인 → UI에서 Role 생성 | 기각 | SYSTEM 로그인 UI를 만들면 보안 공격 표면 증가, 구축 시 수동 작업 → 실수 가능성 |
| **시드 스크립트로 자동화** | **채택** | 구축 시 정의된 기본 Role 세트를 자동 시딩, 초기 관리자를 환경변수로 지정 |

```
배포 시:
  1. 환경변수·구축 설정 로드
  2. 시드 스크립트 실행 (SYSTEM 권한)
     → 기본 Role 세트 생성
     → 기본 AdminPermission 할당
     → env.INITIAL_ADMIN_USER_ID 에게 슈퍼 ADMIN Role 부여
  3. 이후 ADMIN이 관리 UI에서 추가 Role/팀/권한 관리
```

### 2.6 시스템 설정의 위치

"시스템 설정"은 환경변수·구축 시 구성으로 관리되며 런타임 권한 평가 대상이 아니다.

- 컴플라이언스 하한선(`lm:*` floor): 구축 시 최소값 고정, ADMIN은 상향만 가능
- 인프라 설정: 환경변수, 앱 재시작/재배포로만 변경

---

## 3. 근거

### 3.1 "관리 자원" 분리의 이유

기존 "시스템 자원"에 묶인 Board, Template, Tag, SharedContent 등은 **문서를 담는 그릇이나 분류 체계**이지, 시스템 인프라가 아니다. 이들의 공통점은 "ADMIN이 AdminPermission으로 CRUD한다"는 것이며, 이를 정확히 반영하는 이름이 **관리 자원**이다.

### 3.2 시스템 설정을 자원에서 분리하는 이유

배포 모드, feature flag, DB 연결 등은:
- DB에 저장되지 않고 환경변수·구축 시 구성에 존재
- 런타임 권한 평가 로직을 타지 않음
- "사람이 UI에서 조작하는 것"이 아님

따라서 자원 분류와 같은 레벨에 두면 혼란을 야기한다.

### 3.3 SYSTEM 로그인 UI를 만들지 않는 이유

- SYSTEM이 런타임에 할 일이 없음 (SYSTEM 전용 항목이 전부 환경변수·구축 시 구성)
- 로그인 UI를 만들면 보안 공격 표면이 불필요하게 확대됨
- 부트스트랩은 시드 스크립트로 자동화 가능 — 구축 시 정의에 따라 기본 Role 세트를 다르게 시딩할 수 있어 오히려 유연함
- 온프렘 구축 시 매번 수동 로그인하면 휴먼 에러 가능성 존재

### 3.4 단일 코드베이스와 배포 모드

고객사별 정책 요구사항(다단계 승인 지원 여부 등)에 대해 코드베이스를 나누거나 런타임에 기능 존재 여부까지 동적으로 바꾸는 방식은 유지보수·복잡도 측면에서 기각하고, **단일 코드베이스**를 유지한다. SaaS와 온프레미스 등 **배포 모드**와 관리자 설정·컴플라이언스 하한선(`lm:*`)으로 요구사항을 조정한다.

---

## 4. 영향

### 4.1 문서 갱신 필요

| 문서 | 변경 내용 |
|------|----------|
| [resource-classification.md](../02-architecture/resource-classification.md) | §5 "시스템 자원" → "관리 자원"으로 명칭 변경, SYSTEM 전용 자원 섹션을 참고 섹션으로 축소 |
| [permissions.md](../02-architecture/permissions.md) | Part 1 제목을 "관리 자원"으로 변경, SYSTEM 전용 섹션 정리 |

### 4.2 코드 영향

| 영역 | 영향 |
|------|------|
| 권한 평가 로직 | 변경 없음 — SYSTEM 바이패스, AdminPermission 평가 로직은 동일 |
| 시드 스크립트 | 신규 — 구축 시 정의에 따른 기본 Role/Permission 시딩 스크립트 필요 |
| SYSTEM 로그인 | 구현하지 않음 |

---

## 5. 최종 구조 요약

```
AICM 권한 체계가 다루는 것 (런타임 권한 평가 대상):
  ├── 문서 자원 (Board-scoped)  → NORMAL: BoardPermission
  ├── 관리 자원 (Admin-scoped)  → ADMIN: AdminPermission
  └── 개인 자원 (User-scoped)   → 소유자 확인

AICM 권한 체계 밖의 것 (참고):
  ├── SYSTEM 역할  → 코드 레벨 바이패스, 서비스 identity, 시드 스크립트
  └── 시스템 설정   → 환경변수·구축 시 구성
```
