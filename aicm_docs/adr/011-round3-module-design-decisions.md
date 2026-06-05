# ADR-011: 라운드 3 모듈 스펙 설계 결정 — 1차 배치 리뷰 기반

- **상태**: 승인됨
- **날짜**: 2026-04-01
- **의사결정자**: AI 오케스트레이터 (시니어 리뷰 기반 자율 결정, 후속 인간 검토 필요)
- **관련 문서**: [approval/](../03-module-design/approval/), [shared-content/](../03-module-design/shared-content/), [community/](../03-module-design/community/), [export/](../03-module-design/export/), [1차 리뷰 결과](../reviews/20260401-100000_batch_senior/)

---

## 1. 컨텍스트

라운드 3 모듈(approval, shared-content, community, export) 4건에 대한 1차 배치 리뷰에서 총 18건의 설계 질문(DQ)이 도출되었다. FD와 모듈 스펙(data.md) 간의 불일치, 아키텍처 문서 간의 모순 등이 원인이며, 모듈 스펙 완성을 위해 즉시 결정이 필요하다.

모든 결정은 **FD 원본 > 아키텍처 문서 > 실무 판단** 우선순위로 내려졌으며, 인간 리뷰어의 후속 검토에서 번복 가능하다.

---

## 2. 결정 사항

### A. Approval 모듈 (5건)

#### A-1. 위임(Delegation) 기능 Phase 1 포함 여부

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) Phase 1 포함 ✅** | FD-APR 명시적 결정 준수, 금융권 부재 대응 필수 | 초기 구현 범위 증가 |
| (b) Phase 2 이후 | 초기 범위 축소 | FD 결정사항 위반, 금융권 요건 미충족 |

**결정: (a) Phase 1 포함**
- 근거: FD-APR 결정사항에 "Phase 1 정식 기능"으로 명시. BR-APR-020/021과 ApprovalDelegation 엔티티가 정의됨. 금융권 교대 근무·부재 시 승인 위임은 필수.
- 조치: data.md에 ApprovalDelegation 엔티티 추가, api/rules/events에 위임 관련 항목 반영.

#### A-2. 승인 요청 진입점 오케스트레이션 주체

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) Document Controller → ApprovalService 내부 호출 ✅** | 사용자 UX 일관성 (문서 컨텍스트에서 제출), 기존 Document API 유지 | 모듈 간 DI 결합도 증가 |
| (b) 프론트엔드가 Approval API 직접 호출 | 모듈 독립성 높음 | Document submit과 이중 경로, 프론트엔드 복잡도 증가 |

**결정: (a) Document Controller → ApprovalService 내부 호출**
- 근거: Document 모듈의 `POST /documents/:id/submit`이 이미 정의되어 있고, 사용자 입장에서 "문서 제출"은 문서 컨텍스트. Approval 모듈의 `POST /api/approvals`는 직접 승인/반려/위임 등 결재 행위 전용. 모듈 아키텍처 §3.3.1에서 `ApprovalModule → DocumentModule (쓰기, Critical)`로 정의된 방향과도 부합.
- 조치: approval/api.md에 Approval 전용 엔드포인트만 정의(Decide, Withdraw, Bypass, Delegate 등). 문서 제출은 Document API 소관으로 명시.

#### A-3. 정책 스냅샷 전략

| 선택지 | 장점 | 단점 |
|--------|------|------|
| (a) FD 방식: Approval.policy_snapshot JSONB 전체 | 단순 구현, 단일 JSONB 조회 | 대형 JSONB, 정책 변경 시 비교 어려움 |
| **(b) data.md 방식: template_id FK + StepResult 단계별 스냅샷 ✅** | 정규화, 단계별 템플릿 추적 가능, 정밀 감사 | FD 동기화 필요 |

**결정: (b) data.md 방식 — template_id FK + 단계별 스냅샷**
- 근거: 각 승인 단계에서 당시 결재라인 템플릿을 기록하여 정밀 감사 추적 가능. 템플릿 변경 후에도 진행 중 승인의 각 단계가 어떤 템플릿 하에 처리되었는지 추적 가능. data.md의 설계 결정 §에 이미 근거가 명시됨.
- 조치: FD-APR의 Approval.policy_snapshot 필드는 "모듈 스펙에서 정규화 결정" 주석 추가 예정.

#### A-4. 자동 반려 시 별도 상태값 (`auto_rejected`)

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) `auto_rejected` 별도 status ✅** | 감사 추적 명확, 쿼리 용이, FD 일치 | CHECK 제약 확장, 상태 수 증가 |
| (b) `rejected` + History action 구분 | 상태 수 최소화 | 필터링 시 JOIN 필요, 감사 복잡도 증가 |

**결정: (a) `auto_rejected` 별도 status 추가**
- 근거: 금융권 감사 추적에서 수동/자동 반려 구분은 필수. FD-APR status enum에 이미 포함. 상태 기반 대시보드 필터링이 History JOIN보다 효율적.
- 조치: data.md CHECK 제약에 `auto_rejected` 추가.

#### A-5. 긴급 발행(Bypass) 상태값

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) `bypassed` 별도 status ✅** | 쿼리 일관성, FD 일치, 감사 명확 | `is_bypass` boolean 중복 가능성 |
| (b) `is_bypass` boolean만 유지 | 기존 data.md 유지 | status 기반 쿼리 불가, FD 불일치 |

**결정: (a) `bypassed` 별도 status 추가, `is_bypass` boolean 제거**
- 근거: status enum으로 통합하면 일관된 쿼리 인터페이스. `is_bypass`는 status='bypassed'와 중복. FD-APR DTO에서 `status: 'bypassed'`를 응답.
- 조치: data.md CHECK 제약에 `bypassed` 추가, `is_bypass` 컬럼 제거.

---

### B. Community 모듈 (6건)

#### B-1. 이벤트 전달 채널 (BullMQ vs EventBus)

| 선택지 | 장점 | 단점 |
|--------|------|------|
| (a) FD-COM 방식: BullMQ `community.events` 큐 | 이벤트 유실 방지, 재시도/DLQ | 인프라 비용, 아키텍처 문서 불일치 |
| **(b) 아키텍처 방식: EventBus Best-effort ✅** | 아키텍처 결정 준수, 경량 | 이벤트 유실 가능 |

**결정: (b) EventBus Best-effort**
- 근거: 커뮤니티 이벤트(댓글/좋아요/신고/북마크)는 모듈 아키텍처 §3.3.1 Best-effort 티어에 명시적으로 분류됨. 알림 누락은 UX 이슈이나 데이터 무결성 미영향. 감사 로그는 AuditLog Interceptor(HTTP 레벨)가 별도 처리하므로 EventBus 유실과 무관.
- 조치: FD-COM §9.1의 BullMQ 명시를 아키텍처 결정 반영으로 수정 필요 표시. events.md에는 EventBus 패턴 적용.

#### B-2. 자유게시판 게시글 CRUD 책임 소재

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) BoardModule/DocumentModule 책임 ✅** | Document 엔티티 재사용 원칙 준수, 모듈 아키텍처 일치 | CommunityModule 범위가 소셜 기능으로 한정 |
| (b) CommunityModule에서 게시글 API 제공 | 커뮤니티 기능 집약 | Document/Board와 책임 중복 |

**결정: (a) BoardModule/DocumentModule 책임**
- 근거: FD-COM §1에 "자유게시판 글은 기존 Document 엔티티를 그대로 사용"이 명시. 게시글 API 경로 `/api/boards/:boardId/posts`는 Board 컨텍스트. CommunityModule은 소셜 인터랙션(댓글/좋아요/신고/북마크)에 집중하여 응집도 높임.
- 조치: community/README.md에 "자유게시판 게시글 CRUD는 BoardModule/DocumentModule 소관, CommunityModule은 소셜 인터랙션만 담당" 명시.

#### B-3. Bookmark 업데이트 배지 판단 방식

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) `last_seen_version` INTEGER ✅** | 정확한 버전 비교, FD 일치 | 비관리 게시판에서도 version 증가 필요 (이미 Document에서 보장) |
| (b) `last_viewed_at` TIMESTAMPTZ | 구현 단순 | 시계 동기화 문제, 동시 수정 시 부정확 |

**결정: (a) `last_seen_version` INTEGER**
- 근거: Document.version은 모든 수정 시 자동 증가하므로 비관리 게시판에서도 동작. 버전 번호 비교가 타임스탬프보다 정확하고 결정적(deterministic). FD-COM BR-COM-057 준수.
- 조치: data.md의 `last_viewed_at`을 `last_seen_version INTEGER DEFAULT 0`으로 변경.

#### B-4. Report status와 action_type 관계

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) FD-COM 방식: pending→reviewing→resolved + action_type ✅** | 처리 중 상태 필터 가능, FD 일치, 유연한 세분화 | 상태 3종 + action_type 3종 관리 |
| (b) data.md 방식: pending/resolved/dismissed | 상태 수 최소화 | `reviewing` 누락, 처리 중 필터 불가, FD 불일치 |

**결정: (a) FD-COM 방식 채택**
- 근거: `reviewing` 상태가 있어야 관리자 대시보드에서 "처리 중" 신고를 필터링 가능. `dismissed`는 `action_type='dismissed'` + `status='resolved'`로 표현하여 상태 전이를 단순화하면서도 조치 세분화 달성.
- 조치: data.md의 status CHECK 제약을 `pending/reviewing/resolved`로 변경, `action_type` 필드 추가.

#### B-5. BookmarkFolder 계층 구조 (parent_id)

| 선택지 | 장점 | 단점 |
|--------|------|------|
| (a) self-ref parent_id 유지 | 향후 확장성 | FD에 없는 요구사항, 과잉 설계, 순환 참조 방지 로직 필요 |
| **(b) parent_id 제거 — 평탄 폴더 ✅** | FD 준수, 단순 구현, UI 복잡도 감소 | 향후 계층 추가 시 migration 필요 |

**결정: (b) parent_id 제거**
- 근거: FD-COM §5.2 BookmarkFolder에 parent_id 없음. BR-COM-050~060에 하위 폴더 요구사항 없음. YAGNI 원칙. 향후 필요하면 non-breaking migration으로 추가 가능.
- 조치: data.md의 BookmarkFolder에서 parent_id, sort_order 제거. DDL에서 self-ref FK 삭제.

#### B-6. 댓글/좋아요 수 집계 Redis 캐시

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) CommunityModule에서 Redis 카운터 사용 ✅** | FD §10.1 성능 요구 충족 (≤200ms), 좋아요 수와 동일 패턴 | 아키텍처 §C 테이블 수정 필요 |
| (b) AggregationModule에 위임 | CommunityModule Redis 미사용 | 좋아요 토글 응답에 집계값 포함 어려움, 모듈 간 호출 증가 |

**결정: (a) CommunityModule에서 Redis INCR/DECR 사용**
- 근거: FD-COM §10.1에서 "좋아요 수 집계: Redis 캐시 기반"을 명시. 좋아요 토글 API 응답에 즉시 갱신된 카운트를 반환하려면 동일 모듈 내 Redis 접근 필수. AggregationModule은 대시보드/피드용 집계이지 실시간 카운터 용도가 아님.
- 조치: 아키텍처 02-module-architecture.md §표 C의 CommunityModule Redis 칼럼에 ● 추가 필요 표시. cache.md에 좋아요/댓글 수 Redis 카운터 전략 작성.

---

### C. SharedContent 모듈 (5건)

#### C-1. API 경로

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) `/api/shared-contents/...` 독립 경로 ✅** | 독립 모듈 구조 반영, RESTful | — |
| (b) `/api/documents/.../shared-contents` 하위 경로 | 문서 연관성 표현 | 모듈 아키텍처와 불일치, 순환 의존 암시 |

**결정: (a) 독립 경로**
- 근거: SharedContentModule은 모듈 아키텍처에서 독립 도메인 모듈. 공통 컨텐츠는 문서에 종속되지 않으며 관리자가 독립적으로 관리.

#### C-2. category nullable 여부

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) NOT NULL + 기본 카테고리 'general' ✅** | FD 준수, 검색 누락 방지, 자동완성 일관성 | 카테고리 미지정 시 기본값 강제 |
| (b) nullable 유지 | 미분류 허용 유연성 | FD 불일치, 카테고리 기반 검색에서 NULL 처리 복잡 |

**결정: (a) NOT NULL**
- 근거: FD-DOC §5에서 NOT NULL로 정의. 카테고리 기반 검색/자동완성이 핵심 기능이므로 NULL은 검색 누락 초래. 미분류 대신 'general' 기본 카테고리 할당.
- 조치: data.md의 category 컬럼에 `NOT NULL DEFAULT 'general'` 적용.

#### C-3. 수정 시 영향 범위 경고 제공 방식

| 선택지 | 장점 | 단점 |
|--------|------|------|
| (a) PUT dry-run 파라미터 | 단일 엔드포인트 | PUT 시맨틱 오염, 캐싱 어려움 |
| (b) 수정 응답에 영향 수 포함 | 추가 API 불필요 | 사전 확인 불가 (수정 후 알림) |
| **(c) 별도 영향 범위 조회 API ✅** | 수정 전 사전 확인, 캐싱 가능, 재사용 | 추가 엔드포인트 1개 |

**결정: (c) `GET /shared-contents/:id/impact` 별도 API**
- 근거: 수정 전에 "N개 문서에 영향됩니다" 경고를 표시하는 UX 플로우에 적합. GET 메서드로 캐싱 가능. 관리자 대시보드에서도 재사용 가능.

#### C-4. re-embedding 진행 상황 API

| 선택지 | 장점 | 단점 |
|--------|------|------|
| (a) 별도 상태 API 제공 | 관리자 친화적 | 추가 개발, BullMQ Job 상태와 중복 |
| **(b) BullMQ Bull Board 대시보드로 관리 ✅** | 추가 개발 불필요, Job 상태 상세 제공 | 관리자에게 Bull Board 접근 권한 필요 |

**결정: (b) Bull Board 대시보드 활용**
- 근거: re-embedding은 인프라 수준 작업. BullMQ Bull Board가 Job 상태·진행률·실패 내역을 이미 제공. 별도 API는 Bull Board 기능과 중복. AdminModule 대시보드에서 Bull Board 링크 제공으로 충분.

#### C-5. 공통 컨텐츠 UI 노출 연동

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) 클라이언트에 공통 컨텐츠 기능 노출 여부를 포함한 설정 전달 ✅** | 기존 메커니즘 활용, 일관성 | — |
| (b) 별도 API로 기능 플래그 조회 | — | 기존 패턴과 불일치, 추가 호출 |

**결정: (a) 클라이언트 설정에 공통 컨텐츠 노출 여부 반영**
- 근거: 서버가 프론트엔드에 전달하는 클라이언트 설정으로 `/공통` 슬래시 명령 등 공통 컨텐츠 관련 UI 노출 여부를 일관되게 결정한다.

---

### D. Export 모듈 (2건)

#### D-1. ExportJob 엔티티 관리 방식

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **(a) PostgreSQL — data.md 신규 작성 ✅** | 감사 추적, 이력 조회, 장기 보관, FD-EXP §3 준수 | 추가 테이블 |
| (b) Redis 기반 Job 상태 관리 | 경량, BullMQ 내장 상태 활용 | 이력 휘발, 감사 추적 불가, 관리자 이력 조회 불가 |

**결정: (a) PostgreSQL data.md 작성**
- 근거: FD-EXP §3에 ExportJob 엔티티가 12개 필드로 상세 정의. 내보내기 이력 조회(사용자용, 관리자용)와 감사 로그 연동이 RDB 없이 불가. Redis는 휘발성이라 서버 재시작 시 이력 유실.
- 조치: export/data.md 신규 작성. 모듈 레지스트리의 export data 칼럼을 ✅로 갱신.

#### D-2. 공통 컨텐츠 인라인 치환 시 의존 관계

| 선택지 | 장점 | 단점 |
|--------|------|------|
| (a) Export → SharedContent 직접 의존 | 명시적 의존 | 아키텍처 매트릭스에 없는 경로 추가, 모듈 간 결합도 증가 |
| **(b) Document 모듈이 블록 조회 시 치환된 결과 반환 ✅** | 아키텍처 매트릭스 준수, Export는 변환에 집중 | Document 모듈 책임 약간 증가 |

**결정: (b) Document 모듈 경유**
- 근거: 모듈 아키텍처 의존성 매트릭스에 Export→SharedContent 경로 없음. Document 모듈이 블록 조회 시 공통 컨텐츠를 인라인 치환하여 "소비자가 바로 사용할 수 있는 블록"을 반환하는 것이 책임 분리에 적합. Export는 순수 변환 로직에 집중.
- 조치: export/README.md 의존 관계에 "Export → Document (읽기, 치환된 블록 포함)" 명시. SharedContent 직접 의존 없음 확인.

---

---

## 3. 2차 리뷰 추가 결정 사항 (4건)

> 2차 리뷰에서 도출된 설계 질문에 대한 추가 결정.

### E-1. ApprovalLineTemplate CRUD API 소관 모듈

**결정: ApprovalModule 소관**
- 근거: 결재라인 템플릿은 ApprovalModule의 핵심 도메인 설정. Board 모듈은 `default_approval_template_id`·`mandatory_approval_config`로 연결만 하므로 템플릿 CRUD는 Approval이 제공하는 것이 응집도에 적합.
- 조치: approval/api.md에 ApprovalLineTemplate CRUD 4개 엔드포인트 추가 (관리자 전용).

### E-2. 유지보수 모드 SLA 일시 정지 Phase 1 포함 여부

**결정: Phase 1 포함 — 단순 구현**
- 근거: FD-APR §4.4에 "시스템 점검 기간 SLA 타이머 일시 정지" 명시. SystemConfig의 `maintenance_mode` 플래그 기반으로 schedule.md 자동 반려 배치에서 skip 로직만 추가하면 구현 복잡도 낮음.
- 조치: schedule.md 자동 반려 배치에 maintenance_mode 체크 추가. rules.md에 BR-APR-023(SLA 일시 정지) 추가.

### E-3. Community 댓글 수정 시간 제한

**결정: Phase 1 포함 — FD-COM BR-COM-017 준수**
- 근거: FD-COM BR-COM-017에 "댓글 수정은 작성 후 N분 이내만 가능" 정의. 기본값 30분, SystemConfig에서 조직별 설정 가능.
- 조치: community/rules.md에 BR-COM-017 추가. api.md PATCH /comments/:commentId 에러 조건에 시간 초과 에러 추가.

### E-4. Community 이벤트 접두사 규칙

**결정: `community.` 접두사 추가 — 아키텍처 네이밍 컨벤션 준수**
- 근거: 모듈 아키텍처 §3.3.1에서 이벤트명 패턴이 `{module}.{entity}.{action}`. FD-COM §9도 `community.comment_created` 형식. 현행 events.md의 접두사 없는 이름(`comment.created`)은 다른 모듈 이벤트와 충돌 위험.
- 조치: events.md의 모든 이벤트명에 `community.` 접두사 추가. `report.reviewed` → `community.report.resolved`로 변경 (status와 일치).

---

## 4. 후속 조치

| 항목 | 상태 |
|------|------|
| 1차 모듈 스펙 수정 반영 | 완료 |
| 2차 잔여 지적사항 수정 반영 | 진행 중 |
| FD-COM §9.1 BullMQ→EventBus 불일치 표시 | 대기 (FD 수정은 별도 작업) |
| 02-module-architecture.md §표 C CommunityModule Redis ● 추가 | 대기 |
| 05-async-event-architecture.md §6.1 export 큐 등록 | 대기 |
| 모듈 레지스트리 export data ✅ 갱신 | 완료 |
| 인간 리뷰어 검토 | 필요 — 22건 결정 모두 번복 가능 |
