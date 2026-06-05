# 문서 관리 기능정의서

| 항목 | 값 |
|------|---|
| 제품 | AICM (KMS) |
| 문서 코드 | FD-DOC |
| 버전 | 1.3 |
| 작성일 | 2026-03-31 |
| 수정일 | 2026-04-02 |
| 기준 문서 | AICM 새 기능정의서 v1 §1.1~1.3, §1.5~1.7, §1.10~1.11 |

---

## 1. 문서 저장/수정/삭제

- **[BR-DOC-001]** 문서 생성 시 게시판 선택(필수), 템플릿 선택(선택적 — 보일러플레이트 용도), 제목, 본문(블록 에디터), 태그 입력
- **[BR-DOC-002]** 삭제 시 소프트 딜리트 처리 — 관리자가 복구 가능하도록
- **[BR-DOC-036]** 승인 대기 중(`pending_review`) 문서는 삭제할 수 없다 — 승인 결과 확정(승인/반려) 후 삭제 가능
- **문서 상태 관리**: status 5단계 + 운영 플래그 분리
  - **[BR-DOC-003] 문서 상태 (status 필드, VARCHAR + CHECK, 5단계)**:
    - `draft`: 작성 중 — 작성자만 조회/수정 가능, 검색/RAG 대상 제외, 임베딩 수행 안 함
    - `pending_review`: 승인 요청 — 관리자 검토 대기 중, 검색/RAG 대상 제외, 임베딩 수행 안 함
    - `approved_scheduled`: 승인 완료 + 배포 예약 — 검색/RAG 대상 제외, 예약 시점 도래 시 `published`로 전환 ([FD-APR](FD-APR-승인워크플로.md) §9.3 예약 배포 참조)
    - `published`: 승인 완료 = 배포 — 검색/RAG/열람 대상, 이 시점에 임베딩 실행
    - `archived`: 문서 내림 — 관리자가 `published` 문서를 검색/RAG에서 제거할 때 사용. ES/Milvus 데이터 삭제, 복원 시 재인덱싱 필요
    - 반려 시 `pending_review` → `draft`로 복귀 (반려 사유 포함) — 검색에서 제외 상태 유지
    - 승인 없이 바로 게시 가능한 게시판(`Board.approval_required = false`): `draft` → `published` 직행
    - `approval_required = false`인 게시판에서 예약 게시를 설정하면 `draft` 상태를 유지한 채 `Document.scheduled_publish_at`에 게시 예정 일시를 저장한다. 예약 시점 도래 시 스케줄러(BullMQ delayed job)가 `draft` → `published` 전환을 자동 수행한다. 예약 취소 시 `scheduled_publish_at = NULL`로 초기화하고 `draft` 상태를 유지한다
    - 상태는 상호 배타적 — `published + archived` 같은 복합 상태가 불가능하여 쿼리·비즈니스 로직이 명확
  - **운영 플래그 (status와 독립적으로 동작)**:
    - `is_suspended: boolean` — 긴급 회수 플래그. `published` 상태에서만 적용. 내용 오류 등으로 긴급히 검색/RAG에서 제외해야 할 때 사용. 벡터 DB에서 물리 삭제 없이 검색 시 필터로 즉시 제외. 수정 완료 후 플래그 해제로 즉시 복원 ([FD-EMB](FD-EMB-임베딩파이프라인.md) 긴급 회수 참조)
    - `deleted_at: timestamp` — 소프트 딜리트. 어떤 상태에서든 삭제 가능, 관리자만 복구
  - **[BR-DOC-004] 검색 필터 조건**: `status == "published" AND is_suspended == false AND deleted_at IS NULL`
  - **[BR-DOC-005] 비정상 조합 방어**: DB 제약 조건으로 `is_suspended`는 `published` 상태에서만 `true` 허용

### 1.1 버전 관리 (감사/승인 이력)
- **[BR-DOC-006] 승인·버전 독립 설정 규칙**: 게시판은 `Board.approval_required`(boolean)와 `Board.versioning_enabled`(boolean)를 **독립적으로** 설정한다. `approval_required = true`이면 문서는 승인 워크플로를 거친다(구 `board_mode == 'managed'`의 승인 맥락). `versioning_enabled = true`이면 DocumentVersion/BlockSnapshot 등 버전 이력이 유지된다(구 `board_mode == 'managed'`의 버전 맥락). `approval_required = false`이면 초안에서 승인 없이 게시할 수 있다(구 `board_mode == 'free'`의 승인 맥락). 두 플래그는 루트 게시판에서만 설정하고 하위 게시판에 상속된다(CHECK·NULL 상속 패턴은 RDB 스키마에서 정의).
- **[BR-DOC-007]** **버전(document_versions)만 운영** — 임시저장용 스냅샷(document_snapshots) 없음, 자동 저장으로 유실 방지
- **[BR-DOC-008] 버전 생성 시점**: **제출(승인 요청) 시점에 1회만 생성**, 이후 status 전이(`submitted` → `published`/`rejected`)로 관리. 동일 콘텐츠 스냅샷을 2번 저장하는 것은 낭비이고 버전 간 diff가 복잡해지므로, 제출 시점에만 스냅샷을 생성한다 ([rdb.md](../../02-architecture/data/aicm/rdb.md) 설계 변경 사항 참조).
- **버전 콘텐츠 저장**: DocumentVersion(메타데이터) + **BlockSnapshot(블록 단위 스냅샷)** 분리 구조. 블록 단위로 분리하면 버전 간 블록별 diff, 재임베딩 판단(`content_hash` 비교), 블록 단위 복원이 가능하다.
- **[BR-DOC-009]** **영구 보관** — 절대 자동 삭제하지 않음
  > **UC↔FD 정합 주석**: UC-DOC-03 대안 흐름 4a에 "보관 버전 상한 초과 시 자동 정리" 서술이 남아 있으나, 결정 사항(M1 확정)에 따라 **FD 기준(영구 보관)이 최종**이다. UC 측은 별도 정합 작업에서 수정 예정.
- **저장소**: RDB (`document_versions` + `block_snapshots` 테이블)
- **DocumentVersion 테이블 구조**: `{ id, document_id, version_number, approval_id, status('submitted'|'published'|'rejected'), rejection_reason, title, embedding_status('pending'|'processing'|'completed'|'failed'|'partial'), created_by, created_at }`
- **embedding_status 역할 구분**: `Document.embedding_status`는 현재 게시본(published)의 임베딩 상태를 추적하며 검색/RAG 파이프라인의 SSoT이다. `DocumentVersion.embedding_status`는 개별 제출본의 임베딩 이력을 보존하며, 게시본 승인 시 해당 버전의 값이 Document로 복사된다.
- **BlockSnapshot 테이블 구조**: `{ id, version_id, block_id, content_raw(jsonb), content_text, content_hash, caption, block_type, heading_level, sequence, annotation(jsonb), embeddable, visible, metadata(jsonb), created_at }`
- 승인권자가 "이전 제출본 vs 현재 제출본" diff를 블록 단위로 비교할 수 있도록 승인 요청마다 BlockSnapshot을 생성
- 승인 이력([FD-APR](FD-APR-승인워크플로.md))과 연동 — 어떤 버전이 승인되었는지 추적 가능
- **라이프사이클 요약**:
  ```
  [draft — 자동 저장 영역]
    │  에디터 자동 저장 (5~10초 간격, 서버 저장)
    ▼
  승인 요청 ──→ DocumentVersion 생성 (status='submitted') + BlockSnapshot 생성
    │
    ├── 반려 → DocumentVersion.status='rejected' + draft로 복귀
    │         수정 → 재요청 → 새 DocumentVersion + BlockSnapshot 생성
    ▼
  승인 완료 ──→ DocumentVersion.status='published' + version_number 확정
    │         = published (검색/RAG 반영, 임베딩 실행)
    ▼
  운영 중 수정 → Block 테이블 수정 (기존 published 유지) → 위 흐름 반복
  ```

### 1.2 문서 담당자

- **Document.assignee_id**: 작성자(`created_by`)와 별도로 지정 가능한 문서 담당자 필드
- 담당자는 문서의 운영 책임자로, 만료 알림(§1.3)의 수신 대상
- **[BR-DOC-010]** 담당자 미지정 시 작성자가 기본 담당자로 동작
- 담당자 변경 시 감사 로그 기록 ([FD-AUD](FD-AUD-감사로그.md) 참조)
- **[BR-DOC-011]** 담당자 변경 권한: 문서 작성자, 해당 게시판 APPROVE 권한 보유자, `manage_boards` AdminPermission 보유자

### 1.3 문서 유효기간

- **Document.expires_at**: `null`이면 무기한, 값이 있으면 해당 일시에 만료 처리
- **[BR-DOC-012]** 만료 시 동작: `is_suspended = true` 전환 — 검색/RAG에서 즉시 제외
- 만료 처리 방식: BullMQ cron 배치로 주기적 스캔 → 만료 도래 문서를 자동으로 suspended 처리
- 만료 알림: 만료 N일 전 담당자(assignee_id)에게 사전 알림 발송 — 갱신 또는 폐기 판단 유도
- 만료된 문서의 복원: 담당자 또는 관리자가 유효기간을 연장하고 `is_suspended` 플래그를 해제하여 복원
- 활용 시나리오: 금융권 규정 문서의 유효기간 관리, 계절성 캠페인 문서의 자동 만료

### 1.4 문서 복제

- **[BR-DOC-013] 복제 규칙**: 기존 `published` 문서를 복제하여 새 `draft` 문서를 생성할 수 있다
  - **복사되는 필드**: 본문(블록 구조), 태그, 유효기간 설정(`expires_at`), `template_id`
  - **초기화되는 필드**: `status = 'draft'`, 버전 이력 없음, 승인 상태 없음, `created_by = 복제 수행자`, 새 `id` 발급
  - 복제 후 게시판(`board_id`)을 변경할 수 있다
- **[BR-DOC-014]** 첨부파일과 이미지는 **별도 사본**으로 복제 — 원본 문서의 파일을 참조하지 않고 오브젝트 스토리지에 독립 복사
- 복제 이력은 감사 로그에 기록 (원본 문서 ID, 복제 문서 ID)

### 1.5 AI 요약

- **[BR-DOC-015]** AI 요약은 `Document.auto_summary` 필드에 DB 저장 — `published` 전환 시 백그라운드에서 LLM 호출하여 자동 생성 ([FD-AI](FD-AI-AI어시스턴트.md) §1 자동 요약 참조)
- **[BR-DOC-016] 재요약**: 문서 상세 페이지에서 "재요약" 버튼을 누르면 LLM을 호출하여 최신 요약을 생성하고 `auto_summary` 필드를 DB에 갱신한다
  - 재요약은 `published` 상태 문서에서만 가능
  - 요약 생성 중 상태 표시: "요약 생성 중..." → 완료 시 최신 요약으로 교체
  - 요약 실패 시에도 문서 게시 상태에 영향 없음
- 문서 열람 시 `auto_summary`가 존재하면 문서 상단에 접을 수 있는 요약 카드로 표시

### 1.6 인쇄

- **[BR-DOC-017]** 인쇄 시 관리자가 설정한 워터마크(사용자명, 인쇄 일시)가 자동으로 포함된다
- **[BR-DOC-018]** 인쇄 이력이 감사 로그에 기록된다 ([FD-AUD](FD-AUD-감사로그.md) 참조)
- 인쇄에 최적화된 화면 제공 — 네비게이션, 사이드바 등 UI 요소 제거
- 비공개 블록(`visible = false`)은 인쇄 출력에서 제외

### 1.7 엔티티 통합 스키마

**Document 엔티티**:

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 문서 고유 식별자 |
| `board_id` | UUID | FK(Board), NOT NULL | 소속 게시판 |
| `title` | VARCHAR(500) | NOT NULL | 문서 제목 |
| `status` | VARCHAR + CHECK | NOT NULL, DEFAULT `'draft'` | `'draft'` \| `'pending_review'` \| `'approved_scheduled'` \| `'published'` \| `'archived'` |
| `is_suspended` | BOOLEAN | DEFAULT false | 긴급 회수 플래그 — published에서만 true 허용 [BR-DOC-005] |
| `deleted_at` | TIMESTAMP | NULL | 소프트 딜리트 |
| `template_id` | UUID | FK(Template), NULL | 사용한 템플릿 (없으면 자유 형식) |
| `assignee_id` | UUID | FK(User), NULL | 문서 담당자 — 미지정 시 created_by가 기본 [BR-DOC-010] |
| `expires_at` | TIMESTAMP | NULL | 유효기간 (null이면 무기한) |
| `retention_policy_id` | UUID | FK(RetentionPolicy), NULL | 법정 보존 정책 (§9.2) |
| `retention_expires_at` | TIMESTAMP | NULL | 보존 만료 예정일 (자동 계산) |
| `embedding_status` | VARCHAR | NOT NULL, DEFAULT `'pending'` | `'pending'` \| `'processing'` \| `'completed'` \| `'failed'` \| `'partial'` |
| `auto_summary` | TEXT | NULL | AI 자동 생성 요약 [BR-DOC-015] |
| `created_by` | UUID | FK(User), NOT NULL | 작성자 |
| `created_at` | TIMESTAMP | NOT NULL | 생성일시 |
| `updated_at` | TIMESTAMP | NOT NULL | 수정일시 |
| `scheduled_publish_at` | TIMESTAMPTZ | NULL | 예약 게시 일시. `approval_required = false`인 게시판 전용 — `approval_required = true`인 게시판은 `Approval.scheduled_publish_at` 사용. null이면 예약 없음 |

**Board 엔티티 (FD-DOC 범위에서 참조하는 필드)**:

| 필드 | 타입 | 설명 | 정의 위치 |
|------|------|------|-----------|
| `slug` | VARCHAR | URL 라우팅용 슬러그 | §6 |
| `approval_required` | BOOLEAN, NOT NULL | 승인 워크플로 필요 여부 — 루트에서 정의, 하위 상속 | §1.1 |
| `versioning_enabled` | BOOLEAN, NOT NULL | 버전(DocumentVersion 등) 이력 유지 여부 — 루트에서 정의, 하위 상속 | §1.1 |
| `mandatory_approval_config` | JSONB, NULL | 필수 승인자 등 게시판 단위 필수 승인 설정(구 `approval_policy_id` FK 대체) | §1.1 |
| `default_approval_template_id` | UUID, FK(ApprovalLineTemplate), NULL | 기본 승인 라인 템플릿(선택) | §1.1 |
| `default_template_id` | UUID, FK(Template), NULL | 기본 템플릿 | §4 |
| `default_retention_policy_id` | UUID, FK(RetentionPolicy), NULL | 기본 보존 정책 | §9.2 |

### 1.8 API 스키마

주요 API 엔드포인트의 요청/응답 DTO를 정의한다. 필드 검증 세부 규칙과 페이지네이션 파라미터는 모듈 스펙에서 최종 확정한다.

#### 문서 생성

- **요청**: `CreateDocumentDto`
  ```
  { boardId: UUID, title: string(1~500),
    templateId?: UUID, tags?: string[], expiresAt?: ISO8601,
    scheduledPublishAt?: ISO8601 }
  ```
- **응답**: `DocumentResponseDto`
  ```
  { id: UUID, boardId: UUID, title: string, status: string,
    templateId: UUID | null, tags: string[], assigneeId: UUID | null,
    isSuspended: boolean, embeddingStatus: string,
    scheduledPublishAt: ISO8601 | null,
    createdBy: UUID, createdAt: ISO8601, updatedAt: ISO8601 }
  ```

#### 문서 단건 조회

- **응답**: `DocumentDetailDto extends DocumentResponseDto`
  ```
  { ...DocumentResponseDto,
    blocks: BlockDto[], autoSummary: string | null,
    retentionPolicyId: UUID | null, retentionExpiresAt: ISO8601 | null,
    lockedBy: UUID | null, lockedAt: ISO8601 | null }
  ```
- `BlockDto`: `{ id: UUID, type: string, content: TiptapJSON, embeddable: boolean, visible: boolean, sequence: number }`

#### 문서 목록 조회

- **응답**: `PaginatedResponse<DocumentListDto>`
  ```
  { items: DocumentListDto[], total: number, page: number, pageSize: number }
  ```
- `DocumentListDto`: `DocumentResponseDto`에서 블록 본문을 제외한 메타데이터만 포함

#### 문서 수정

- **요청**: `UpdateDocumentDto`
  ```
  { title?: string(1~500), tags?: string[],
    assigneeId?: UUID | null, expiresAt?: ISO8601 | null,
    scheduledPublishAt?: ISO8601 | null }
  ```
- 블록 본문 수정은 자동 저장 API(§3)를 통해 블록 단위로 처리

#### 문서 삭제

- `DELETE /documents/:id` → `204 No Content` (소프트 딜리트)
- 차단 조건: 보존기간 내 [BR-DOC-032], 승인 대기 중 [BR-DOC-036], 편집 잠금 중 [BR-DOC-020]

#### 상태 변경

| 동작 | 요청 DTO | 결과 |
|------|----------|------|
| 승인 요청 | `SubmitForReviewDto { documentId: UUID }` | `pending_review` 전환 + DocumentVersion 생성 |
| 긴급 회수 | `SuspendDocumentDto { documentId: UUID, reason: string }` | `is_suspended = true` |
| 회수 해제 | `UnsuspendDocumentDto { documentId: UUID }` | `is_suspended = false` |
| 보관 처리 | `ArchiveDocumentDto { documentId: UUID }` | `archived` 전환 |

#### 자동 저장

- **요청**: `AutoSaveDto`
  ```
  { documentId: UUID, blocks: BlockDelta[], clientVersion: number }
  ```
- `BlockDelta`: `{ blockId: UUID, action: 'upsert' | 'delete', content?: TiptapJSON, metadata?: { embeddable?: boolean, visible?: boolean } }`
- **응답**: `{ savedAt: ISO8601, serverVersion: number }` — 클라이언트 `clientVersion`과 서버 버전을 비교하여 충돌 감지

#### 문서 복제

- **요청**: `CloneDocumentDto { sourceDocumentId: UUID, targetBoardId?: UUID }`
- **응답**: `DocumentResponseDto` (새 `draft` 문서, [BR-DOC-013] 복제 규칙 적용)

#### 잠금/해제

| 동작 | 엔드포인트 | 응답 |
|------|-----------|------|
| 잠금 획득 | `POST /documents/:id/lock` | `{ lockedBy: UUID, lockedAt: ISO8601, expiresAt: ISO8601 }` |
| 잠금 해제 | `DELETE /documents/:id/lock` | `204 No Content` |
| 잠금 상태 조회 | `GET /documents/:id/lock` | `{ isLocked: boolean, lockedBy?: UUID, lockedAt?: ISO8601, expiresAt?: ISO8601 }` |

---

## 2. 블록 에디터

- **개요**: 노션 스타일의 블록 기반 에디터 — 문서 본문이 블록의 순서 배열로 구성되며, 각 블록이 독립적인 콘텐츠 단위
- **기술 스택**: Tiptap(ProseMirror 기반) — 블록 구조 + 슬래시 명령 + 커스텀 블록 유연 + Vue 3 호환
- **블록 타입**:
  - **텍스트 블록**: 본문 텍스트 (굵게, 기울임, 밑줄, 취소선, 코드, 하이라이트, 링크 등 인라인 서식)
  - **헤딩 블록**: H1 ~ H3 (문서 구조/목차 생성, 섹션 앵커 링크 자동 생성 — §6과 연동)
  - **리스트 블록**: 순서 있는 목록(ol), 순서 없는 목록(ul), 체크리스트(todo)
  - **이미지 블록**: 이미지 업로드 (드래그 앤 드롭, 클립보드 붙여넣기, URL 삽입)
    - 업로드된 이미지는 오브젝트 스토리지(S3/MinIO)에 저장, 블록 데이터에는 URL 참조
    - 이미지 리사이징/압축 처리 (원본 보존 + 썸네일 생성)
    - 캡션, 대체 텍스트(alt) 입력 지원
    - 허용 포맷/용량 제한 정책 설정
  - **테이블 블록**: 행/열 추가·삭제, 셀 병합, 헤더 행/열 지정 — 중첩 표는 셀 내부에 하위 블록 허용으로 처리
  - **코드 블록**: 구문 강조(syntax highlighting) 지원, 언어 선택
  - **인용 블록**: 인용문(blockquote) 스타일
  - **구분선 블록**: 수평선(hr)
  - **파일 첨부 블록**: PDF, DOCX, HWP 등 파일 첨부 — 다운로드 링크 제공, 인라인 미리보기(선택적)
  - **임베드 블록**: 외부 콘텐츠 임베드 (YouTube, 외부 URL 미리보기 등 — 허용 도메인 화이트리스트 관리)
  - **콜아웃/알림 블록**: 정보(info), 경고(warning), 위험(danger), 팁(tip) 등 강조 박스
  - **접기(토글) 블록**: 클릭 시 펼쳐지는 토글 섹션 — 긴 참고 내용, 부록 등에 활용
  - **공통 컨텐츠 인라인 참조**: 공통 컨텐츠 ID를 참조하는 인라인 변수 (§5와 연동) — 문장 중간에 변수처럼 삽입, 편집 모드에서 시각적 구분, 열람 모드에서 자연스러운 렌더링
  - **수학 수식 블록**: LaTeX/KaTeX 기반 수식 렌더링 (선택적)
- **슬래시 명령 (`/` 커맨드)**:
  - 빈 블록에서 `/` 입력 시 블록 타입 선택 메뉴 표시
  - 타입 필터링 검색: `/이미지`, `/표`, `/코드`, `/공통`, `/콜아웃`, `/ai` 등
  - `/ai`: AI 글쓰기 개선 메뉴 호출 ([FD-AI](FD-AI-AI어시스턴트.md) §2와 연동) — 문장 다듬기, 톤 변경, 간결하게, 상세하게, 번역 등
  - 자주 사용하는 블록 타입 상단 노출 (사용 빈도 기반 정렬)
- **블록 조작**:
  - 드래그 앤 드롭으로 블록 순서 변경
  - 블록 복제, 삭제, 블록 타입 변환 (예: 텍스트 → 헤딩, 리스트 → 체크리스트)
  - 블록 선택 시 플로팅 툴바: 서식 변경, 블록 타입 변경, 블록 메타 설정, **AI 개선 ([FD-AI](FD-AI-AI어시스턴트.md) §2와 연동)**
  - 다중 블록 선택 → 일괄 삭제/이동/서식 변경
- **블록 메타데이터**: 각 블록은 콘텐츠 외에 메타데이터를 가짐
  - `{ id, type, content, embeddable, visible, ... }` — 임베딩 제외/가시성 제어 ([FD-SCH](FD-SCH-검색.md) §4와 연동)
  - 블록 ID는 고유값 — 섹션 앵커, 임베딩 추적, 공통 컨텐츠 참조 등에 활용
- **문서 저장 포맷**:
  - 블록 배열을 Tiptap JSON 구조(네이티브 포맷)로 저장 — 필요 시 추상화 레이어 추가
  - 각 블록의 타입, 콘텐츠, 메타데이터를 구조화하여 저장
  - HTML 렌더링은 뷰어에서 JSON → HTML 변환으로 처리 (서버사이드/클라이언트사이드)
- **키보드 단축키**:
  - 마크다운 단축키 지원: `#`→H1, `##`→H2, `-`→리스트, `[]`→체크리스트, `` ` ``→코드 등
  - 서식 단축키: `Ctrl+B`(굵게), `Ctrl+I`(기울임), `Ctrl+K`(링크) 등
  - 블록 탐색: `Enter`(새 블록), `Backspace`(빈 블록 삭제/이전 블록 병합), `Tab`(들여쓰기)
- **성능 고려사항**:
  - 대형 문서(수백 블록) 렌더링 최적화 — **점진적 로딩** 적용 (스크롤에 따라 점진적으로 블록 로드)
  - 이미지 블록 lazy loading
  - 자동 임시저장 시 변경된 블록만 diff 전송 (전체 문서 재전송 방지)
- **[BR-DOC-019] 블록 수 상한**: 관리자가 설정한 블록 수 상한(예: 300개)에 근접하면 편집기 상단에 안내 표시, 상한 초과 시 추가 블록 삽입 제한 — `lm:document.max_blocks` ([FD-SYS](FD-SYS-시스템설정.md) §3 참조)

---

## 3. 자동 저장과 드래프트

- **노션 스타일 자동 저장**: 명시적 "저장" 버튼 없이 편집 내용이 자동으로 저장 — 사용자는 "저장" 행위를 의식하지 않고 작성에 집중
  - 에디터 작성 중 짧은 간격(예: 5~10초, 유휴 감지)으로 서버에 자동 저장
  - 브라우저 종료/이탈 시 데이터 유실 방지
  - 저장 상태 표시: 에디터 상단에 "저장됨" / "저장 중..." 인디케이터 (노션과 동일한 UX)
- **드래프트 문서 목록**: 마이페이지에서 내 드래프트 문서 목록 조회 — 제목, 대상 게시판, 마지막 수정 시간 표시
- **드래프트 → 승인 요청 전환**: 에디터에서 "승인 요청" 버튼 클릭 시 `draft` → `pending_review` 상태 전환 + 제출 버전(document_versions) 자동 생성
- **드래프트 문서 관리**:
  - 드래프트 상태에서는 작성자만 조회/수정/삭제 가능
  - 검색 결과 및 RAG 대상에서 제외
  - 청킹/임베딩 파이프라인을 타지 않음 (`published` 상태 전환 시 최초 실행)
- **드래프트 방치 알림**: 드래프트는 자동 삭제하지 않음 — 일정 기간(관리자 설정) 방치 시 작성자에게 알림 발송, 관리자 대시보드에서 장기 미처리 드래프트 목록 조회 가능, 삭제는 작성자 또는 관리자가 수동으로만 처리
- **동시 편집 충돌 방지**:
  - **[BR-DOC-020]** **비관적 락킹** — 동일 드래프트를 다른 사용자가 편집 중이면 "편집 중입니다" 잠금 표시, 대부분 1인 작성 후 승인 흐름이므로 동시편집 불필요
  - **[BR-DOC-021]** 잠금 자동 해제: 관리자가 설정한 시간(기본 30분) 경과 시 자동 해제. 편집 중인 사용자의 브라우저 종료/네트워크 끊김 시 연결 확인(heartbeat) 실패를 감지하여 자동 해제. 운영 관리자는 잠금 관리 화면에서 강제 해제 가능
  - **[BR-DOC-022] 충돌 해결**: 잠금이 예기치 않게 해제되어(잠금 시간 만료, 네트워크 끊김 등) 두 사용자가 동일 문서를 수정한 경우, 나중에 저장을 시도하는 사용자에게 다음 해결 옵션 제공:
    - **내 내용으로 덮어쓰기**: 상대방의 변경을 무시하고 내 수정 내용으로 저장
    - **상대방 내용 유지**: 내 변경을 취소하고 상대방이 저장한 최신 내용을 수용
    - **사본으로 저장**: 내 수정 내용을 별도의 새 `draft` 문서로 저장하여 수동 대조·통합
    - 양쪽 변경 내용의 차이를 나란히 비교 표시, 충돌 해결 이력(충돌 발생 시각, 관련 사용자, 선택 방식)은 감사 로그에 기록

---

## 4. 문서 템플릿

- **템플릿 개요**: 문서의 초기 본문 구조(보일러플레이트)와 기본 태그를 사전 정의하여 일관된 문서 작성을 유도 — "쓰면 편한 시작점"이지 강제 사항이 아님
- **템플릿 엔티티 구조**:
  - 독립 엔티티로 관리 — 게시판에 직접 종속되지 않고, 여러 게시판에서 재사용 가능
  - 주요 필드: id, 템플릿명, 설명, 카테고리(`SOP`, `FAQ`, `체크리스트`, `공지`, `장애대응` 등), 기본 본문(블록 JSON — §2 블록 에디터와 동일한 포맷), 기본 태그, 작성자, is_active
- **기본 본문 (보일러플레이트)**:
  - 템플릿 선택 시 블록 에디터에 자동으로 채워지는 초기 블록 구조
  - 헤딩 블록, 안내 문구(콜아웃 블록), 작성 가이드라인, 빈 텍스트 블록(작성 위치 안내) 등을 미리 배치
  - 작성자가 보일러플레이트 블록들 사이에서 내용을 채워나가는 방식
  - 특정 블록을 "잠금"(편집 불가) 처리 가능 — 면책 조항 블록, 필수 안내 문구 등 작성자가 삭제/수정할 수 없는 고정 블록
  - 관리자가 블록 에디터에서 직접 템플릿 본문을 작성하고 저장
- **게시판 × 템플릿 연결**:
  - 게시판별 기본 템플릿(`default_template_id`) 지정 — 새 문서 생성 시 자동 선택
  - **[BR-DOC-023]** 템플릿 선택은 항상 **선택적** — 빈 문서로 자유 작성 가능
  - 문서 생성 시 활성 템플릿 전체 목록에서 선택 가능 — 게시판별 허용 목록 제한 없음
- **문서 × 템플릿 참조**:
  - 문서 생성 시 선택한 템플릿의 ID를 문서에 기록 (`template_id`)
  - 템플릿은 불변(immutable) 엔티티이므로 문서가 참조하는 템플릿이 변경될 일이 없음 — 기존 문서 보호가 구조적으로 보장
  - 템플릿 없이 생성된 문서는 `template_id: null` — 자유 형식
- **[BR-DOC-024] 템플릿 불변 원칙 및 복제(Clone)**:
  - 템플릿은 한번 생성되면 **수정 불가(immutable)** — 변경이 필요하면 기존 템플릿을 복제하여 새 템플릿을 생성
  - **복제 흐름**: 기존 템플릿 선택 → "복제" → 기존 내용이 복사된 새 템플릿 생성 → 필요한 부분 편집 → 저장 (새로운 `template_id` 발급)
  - 더 이상 사용하지 않는 기존 템플릿은 **비활성 처리** (`is_active: false`) — 새 문서 생성 시 선택 목록에서 제외, 기존 문서 참조는 유지
  - **설계 근거**: 템플릿 본문이 변경되면 사실상 다른 템플릿이므로, 버전 관리 대신 clone이 개념적으로 정확하고 구현 복잡도가 낮음
- **RAG 파이프라인 연동**:
  - `template_id`를 기반으로 청킹 전략 분기 가능 — FAQ 템플릿은 Q&A 쌍 단위, SOP 템플릿은 스텝 단위 청킹
  - 템플릿 카테고리별로 임베딩 모델/프롬프트 분기 가능 (고도화 시)
- **승인 라인과 완전 분리**: 템플릿은 순수하게 본문 구조 프리셋 역할만 담당 — 승인 ON/OFF·필수 승인자·기본 승인 라인 템플릿은 게시판(`approval_required`, `mandatory_approval_config`, `default_approval_template_id`) 단위로만 관리

---

## 5. 공통 컨텐츠 (Shared Content Block)

- **개요**: 여러 문서에서 공통으로 참조하는 재사용 가능한 컨텐츠 블록 — 환경변수처럼 한 번 수정하면 참조하는 모든 문서에 즉시 반영
- **공통 컨텐츠 엔티티**:
  - 독립 엔티티로 관리
  - 예시: 회사 대표번호, 고객센터 운영시간, 약관 문구, 면책 조항, 공통 안내 문구, 제품 스펙 요약 등
  - 카테고리별 그룹핑: `법률/약관`, `연락처`, `상품정보`, `공통안내` 등

**SharedContent 엔티티 구조**:

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | UUID | PK | 공통 컨텐츠 고유 식별자 |
| `name` | VARCHAR(200) | NOT NULL, UNIQUE | 이름(슬러그) — 검색/자동완성용 |
| `description` | TEXT | NULL | 설명 |
| `content` | JSONB | NOT NULL | 본문 (블록 에디터 JSON — §2와 동일) |
| `category` | VARCHAR(50) | NOT NULL | 카테고리 |
| `version` | INTEGER | NOT NULL, DEFAULT 1 | 버전 번호 (수정 시 +1 증가) |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT true | 활성 여부 |
| `replacement_id` | UUID | FK(SharedContent), NULL | 비활성 시 대체 컨텐츠 |
| `created_by` | UUID | FK(User), NOT NULL | 작성자 |
| `updated_by` | UUID | FK(User), NOT NULL | 최종 수정자 |
| `created_at` | TIMESTAMP | NOT NULL | 생성일시 |
| `updated_at` | TIMESTAMP | NOT NULL | 수정일시 |

- **문서 내 삽입 방식**:
  - 슬래시 명령 `/공통` 또는 전용 삽입 버튼으로 공통 컨텐츠 검색/삽입 — §2 블록 에디터의 "공통 컨텐츠 참조 블록"으로 삽입
  - 자동완성으로 공통 컨텐츠 검색 → 선택 시 문서 본문에 **참조 블록**으로 삽입
  - 참조 블록은 실제 내용을 복사하는 것이 아니라 공통 컨텐츠 ID를 참조 — 원본 수정 시 참조하는 모든 문서에 반영
  - 에디터에서 공통 컨텐츠 블록은 시각적으로 구분 (배경색, 아이콘, "공통 컨텐츠" 라벨 등) — 일반 본문과 혼동 방지
  - **인라인 삽입만 지원** (문장 중간에 변수처럼 삽입) — 블록 단위 삽입은 미지원
- **[BR-DOC-025] 버전 정책**: **항상 최신 버전만** 참조 — 버전 고정(pinning) 미지원, 단순 운영 우선
- **렌더링 방식**:
  - **실시간 렌더링**: 문서 열람 시 공통 컨텐츠 ID → 최신 본문으로 치환하여 표시
  - 에디터(편집 모드)에서는 참조 블록임을 명시적으로 표시, 뷰어(열람 모드)에서는 자연스럽게 본문에 녹아들어 표시
  - 공통 컨텐츠 블록 클릭 시 원본으로 이동하는 링크 제공 (관리자/작성자용)
- **수정 및 전파**:
  - **[BR-DOC-027]** 공통 컨텐츠 수정 시 **참조하는 모든 문서에 즉시 반영** — 개별 문서 수정 불필요
  - 수정 권한: 공통 컨텐츠 관리 권한을 가진 관리자만 수정 가능
  - 수정 이력(버전 히스토리) 관리 — 이전 버전 확인/롤백 가능
  - 수정 시 영향 범위 확인: 해당 공통 컨텐츠를 참조하는 문서 목록 조회 기능 (영향도 분석) — 수정 전 "N개 문서에 영향됩니다" 경고 확인
  - 공통 컨텐츠 수정에 별도 승인 워크플로우 없음 — 관리자 권한으로 충분, 수정 이력과 영향도 확인으로 통제
- **RAG 파이프라인 연동**:
  - **[BR-DOC-028]** 공통 컨텐츠 수정 시 해당 블록을 참조하는 모든 문서의 관련 청크 재임베딩 트리거
  - **재임베딩 전략: 큐 기반 점진적 처리** — 참조 문서가 많을 수 있으므로 Bull(Redis) 큐에서 비동기 순차 처리, 즉시 전체 재임베딩은 서버 부하 위험
  - 공통 컨텐츠 자체도 독립 청크로 임베딩 가능 — RAG 답변 시 출처를 공통 컨텐츠로 표시
  - 재임베딩 진행 상황 모니터링 — 관리자 대시보드에서 진행률 확인
- **삭제/비활성 처리**:
  - **[BR-DOC-026]** 참조하는 문서가 존재하면 삭제 차단 또는 경고 — "N개 문서에서 참조 중" 표시
  - 비활성(deprecated) 처리 시 참조 문서에서 해당 블록에 경고 표시 ("이 공통 컨텐츠는 더 이상 유효하지 않습니다")
  - 비활성된 공통 컨텐츠를 대체할 새 공통 컨텐츠 지정 가능 (리다이렉트)

---

## 6. 지식 URL 복사

- **문서 고유 URL**: 모든 `published` 문서는 고유한 접근 URL을 가짐
  - URL 형식: `/{board_slug}/{document_id}` (ID 기반 — 안정성 최우선, 내부 시스템이라 slug 가독성 불필요)
  - 문서 상세 페이지에서 **"URL 복사"** 버튼 제공 → 클립보드에 복사
  - 복사 시 알림 토스트 ("링크가 복사되었습니다")
- **URL 공유 범위 및 권한**:
  - URL 접근 시 해당 문서의 게시판 권한 체계를 따름 — 권한 없는 사용자는 "접근 권한이 없습니다" 안내
  - 로그인하지 않은 사용자에 대한 처리: 로그인 페이지로 리다이렉트 후 원래 문서로 복귀
  - 공개(public) 게시판의 문서는 로그인 없이 접근 가능 여부 설정
- **URL 안정성**:
  - 문서 제목/게시판 변경 시에도 기존 URL이 유효하도록 처리 (ID 기반 라우팅 또는 리다이렉트)
  - 삭제/보관 처리된 문서 URL 접근 시 적절한 안내 ("이 문서는 보관되었습니다" / "삭제된 문서입니다")
- **블록 단위 링크 (Block-level URL)**:
  - 모든 블록은 고유 ID를 가지므로 블록 단위 직접 링크 지원 — URL fragment(`#block-{blockId}`)로 특정 블록에 딥링크
  - URL 형식: `/{board_slug}/{document_id}#block-{blockId}` — 문서 단위 URL + fragment 조합
  - **블록 링크 복사 UI**: 블록 호버 시 링크 아이콘 표시 또는 블록 메뉴에서 "링크 복사" 옵션 제공
  - **페이지 진입 시 동작**: URL에 `#block-xxx` fragment가 있으면 해당 블록으로 자동 스크롤 + 하이라이트 효과 (잠깐 반짝이는 시각적 피드백)
  - **활용 시나리오**: 긴 SOP 문서의 특정 스텝 공유, 슬랙/사내 메신저에서 정확한 위치 공유, 댓글에서 문서 내 특정 블록 인용 참조
  - 헤딩 블록뿐만 아니라 **모든 블록 타입**(텍스트, 테이블, 코드, 콜아웃 등)에 대해 링크 복사 지원
  - 블록 삭제 시 해당 fragment URL 접근 → 문서 상단으로 폴백 + "해당 섹션을 찾을 수 없습니다" 안내
- **문서 내 특정 섹션 링크**:
  - 문서 내 헤딩(h1~h3)에 앵커 자동 생성 — 블록 단위 링크의 서브셋으로 동작
  - 섹션 헤딩 호버 시 링크 아이콘 표시 → 클릭으로 해당 섹션 URL 복사
  - 목차(TOC)에서 섹션 클릭 시 해당 헤딩으로 스크롤 (§2 헤딩 블록과 연동)
- ~~**단축 URL**~~: **미지원** — 내부 시스템이라 URL 길이 문제 없음

---

## 7. 게시판 분류 체계

- **개요**: 게시판은 **재귀 트리**(parent_id)로 사이드바 네비게이션 계층을 구성하며, 하위 게시판으로 콘텐츠를 분류한다. 운영 정책(승인/권한/RAG)은 게시판 단위로 독립 관리한다
  - **게시판(Board)**: "이 문서가 어떤 운영 규칙(권한/승인/RAG)을 따르는가"를 결정하는 운영 정책 단위이자 콘텐츠 분류 단위. 게시판은 재귀 트리(parent_id)로 사이드바 네비게이션 계층을 구성하며, 하위 게시판을 통해 주제별 분류 체계를 표현한다
- **게시판 트리 구조**:
  - 게시판은 `Board.parent_id`로 재귀 트리를 구성
  - 예시:
    ```
    [금융 게시판]                    [의약품 게시판]
    ├── 투자                         ├── 약품 관리
    │   ├── 해외주식                  └── 임상 시험
    │   └── 국내주식
    └── 보험
    ```
- **문서 × 게시판 관계**:
  - 문서는 `board_id`(필수)를 가짐
  - `board_id`는 운영 정책(승인/권한/RAG) 결정 및 콘텐츠 분류를 겸한다
- **게시판 기반 조회**:
  - 특정 게시판의 하위 트리 전체에서 문서 검색 가능 (하위 board_id 수집 → 필터)
- **검색/RAG 연동**:
  - 검색 필터로 게시판 사용 — 하위 게시판 포함/미포함 선택 가능
  - RAG 질의 시 특정 게시판 트리로 검색 범위 한정 가능

---

## 8. 태그 관리

- **개요**: 문서에 자유롭게 부착하는 키워드 라벨 — 게시판 트리(구조적 분류)를 보완하는 유연한 분류 수단
  - 게시판은 '이 문서의 위치/분류'(계층적), 태그는 "이 문서의 특성/키워드"(복수, 평탄)
- **태그 입력 방식**: 자유 입력 + 자동완성
  - 작성자가 새 태그를 자유롭게 생성 가능 — 별도 관리자 사전 등록 불필요
  - 입력 시 기존 태그 자동완성 제안 — 유사 태그 중복 생성 방지 (예: "고객상담" 입력 시 "고객 상담", "고객상담매뉴얼" 등 기존 태그 제안)
  - **자동완성 정렬 우선순위**: ① 입력 문자열 prefix 매칭 → ② 현재 게시판 내 사용 빈도 → ③ 전체 사용 빈도(`usage_count`). 전체 인기도만으로 정렬하지 않는다 — 지금 작성 중인 문서의 게시판 맥락에 적합한 태그가 먼저 노출되어야 한다
  - **[BR-DOC-031]** 문서당 최대 태그 수는 시스템 설정값으로 관리 (기본 10, `lm:document.max_tags` — [FD-SYS](FD-SYS-시스템설정.md) §3.2 참조)
- **태그 엔티티 구조**:
  - 주요 필드: `{ id, name, slug, usage_count, created_by, created_at }`
  - **[BR-DOC-035]** 태그명은 대소문자/공백 정규화하여 중복 방지 (예: "고객 상담"과 "고객상담"은 동일 태그로 처리)
  - `usage_count`: 해당 태그가 부착된 문서 수 — 자동완성 보조 정렬(동일 매칭 시 tiebreaker) 및 인기 태그 표시에 활용
- **태그 관리 (관리자)**:
  - 태그 목록 조회: 전체 태그 + 사용 건수 + 생성일 — 정렬/검색 가능
  - **태그 병합**: 유사/중복 태그를 하나로 병합 (예: "CS", "고객서비스", "고객 서비스" → "고객서비스"로 통합) — 병합 시 소속 문서의 태그도 자동 교체
  - **태그 삭제**: 미사용(usage_count == 0) 태그 일괄 정리, 사용 중인 태그 삭제 시 소속 문서에서 자동 해제 + 확인 경고
  - **태그 이름 변경**: 기존 태그명 수정 시 참조하는 모든 문서에 반영
- **검색/RAG 연동**:
  - 검색 필터로 태그 사용 가능 — 게시판과 독립적으로 조합
  - RAG 질의 시 태그로 검색 범위 한정 가능
  - 청크 메타데이터에 `tags[]` 포함 — 벡터 검색 시 태그 기반 필터링
- **AI 태그 추천**: 문서 편집 중 AI가 본문을 분석하여 기존 태그 풀에서 적합한 태그를 추천 — 태그 부착 부담 감소, 기존 태그 재사용 유도로 태그 품질 유지. 상세: [FD-AI](FD-AI-AI어시스턴트.md) §6
- **태그 활용**:
  - 문서 목록/상세 페이지에 태그 표시 — 클릭 시 해당 태그의 문서 목록으로 이동
  - 인기 태그 클라우드: 전체 또는 게시판별 인기 태그 시각화 (선택적)
  - 관련 문서 추천: 동일 태그를 공유하는 문서 목록 제안 (선택적)

---

## 9. 법정 보존기간 및 폐기 프로세스

### 9.1 개요

- `expires_at`(§1.3)은 **콘텐츠 유효기간**으로 내용의 유효성 관점이며, 법정 보존기간은 **규제 관점**에서 문서의 최소 보관 의무를 정의
  - 예: 투자권유 문서 10년, 내부통제 문서 5년 보존 (자본시장법, 금융회사 내부통제기준 등)
- 보존기간 만료 전에는 삭제(`soft_delete` 포함)가 차단됨

### 9.2 보존 정책 엔티티

**RetentionPolicy 엔티티**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | UUID | PK |
| `name` | string | 정책명 (예: "투자권유 문서", "내부통제 문서") |
| `description` | string | 정책 설명 |
| `retention_period_days` | integer | 보존 기간 일수 (예: 3650 = 10년, 1825 = 5년) |
| `retention_start_type` | enum | 기산일 기준: `'published_at'` \| `'last_modified_at'` |
| `expiry_action` | enum | 만료 시 처리: `'archive'` \| `'mark_for_disposal'` |
| `require_disposal_approval` | boolean | 폐기 시 승인 필요 여부 |
| `is_active` | boolean | 활성 여부 |
| `created_by` | UUID | 생성자 FK (User) |
| `created_at` | timestamp | 생성일시 |

**Document ↔ RetentionPolicy 관계**:

| 필드 | 위치 | 설명 |
|------|------|------|
| `retention_policy_id` | Document | nullable FK → RetentionPolicy. 보존 정책 미지정 시 `null` |
| `retention_expires_at` | Document | 자동 계산: retention_start_date + retention_period_days. 보존 만료 예정일 |
| `default_retention_policy_id` | Board | nullable FK → RetentionPolicy. 게시판 레벨 기본 보존 정책 |

- 게시판에 `default_retention_policy_id`가 설정된 경우, 해당 게시판에 생성되는 문서에 보존 정책이 자동 적용
- `retention_expires_at`은 문서 게시(`published`) 또는 수정 시점에 `retention_start_type` 기준으로 자동 재계산

### 9.3 보존기간 동작 규칙

- **[BR-DOC-032] 삭제 차단**: `retention_expires_at`이 미래인 문서에 대해 `soft_delete` 요청 시 `403` 반환 + 사유 메시지
  - 응답 메시지: "법정 보존기간 내 문서는 삭제할 수 없습니다. 만료일: YYYY-MM-DD"
  - **[BR-DOC-033]** `is_suspended` 전환, `archived` 상태 전환도 차단 — 보존기간 내 문서의 상태 변경은 정상 운영 범위(수정, 재승인 등)만 허용
- **[BR-DOC-034] 만료 자동 처리**: BullMQ cron 배치로 `retention_expires_at` 도래 문서 탐색
  - `expiry_action = 'archive'`: 자동으로 `status = 'archived'` 전환 + ES/Milvus 데이터 삭제
  - `expiry_action = 'mark_for_disposal'`: 폐기 대기 상태로 전환, 관리자 대시보드에 노출
- **폐기 승인 워크플로**: `require_disposal_approval = true`인 경우, [FD-APR](FD-APR-승인워크플로.md) 승인 엔진과 연동하여 폐기 전용 승인 유형 사용
  - 폐기 승인 요청 → 승인권자 검토 → 승인 시 영구 삭제 또는 아카이빙 실행
  - 반려 시 폐기 대기 상태 유지, 사유 기록
- **폐기 감사 로그**: 문서 폐기(영구 삭제 또는 아카이빙) 시 [FD-AUD](FD-AUD-감사로그.md) 감사 로그에 기록
  - action: `document.disposed`
  - details: 보존 정책명, 보존 기간, 기산일, 만료일, 폐기 처리 방식(`archive` / `permanent_delete`), 승인 ID(해당 시)

### 9.4 관리자 기능

- **보존 정책 CRUD**: 관리자가 보존 정책을 생성/수정/삭제
  - 사용 중인 정책(문서 또는 게시판에 연결된 정책)은 삭제 차단 — "N개 문서/게시판에서 사용 중" 경고
  - 비활성 처리(`is_active = false`)로 신규 적용만 차단, 기존 적용은 유지
- **게시판별 기본 보존 정책 지정**: 게시판 설정에서 기본 보존 정책을 선택하면, 해당 게시판에 생성되는 문서에 자동 적용
- **보존기간 대시보드**:
  - 보존기간 임박(30일 이내) 문서 목록
  - 보존기간 임박(7일 이내) 문서 목록
  - 만료 문서 목록
  - 폐기 대기 문서 목록
- **일괄 아카이빙**: 만료 문서를 선택하여 일괄 아카이빙 처리
- **보존기간 알림**: 만료 N일 전 담당자(`assignee_id`)에게 알림 발송 (§1.3 만료 알림과 동일 채널)

---

## 10. 문서 내보내기

문서 내보내기(PDF, DOCX, HTML, Markdown) 기능은 별도 기능정의서로 분리되었다.

> 상세: [FD-EXP-내보내기](FD-EXP-내보내기.md) 참조

> **UC↔FD 정합 주석**: UC-DOC-08(문서 내보내기)이 여전히 `FD-DOC §2`를 참조하고 있으나, 내보내기는 **FD-EXP로 분리(B3 확정)** 되었다. UC 측 참조는 별도 정합 작업에서 `FD-EXP` 및 적절 섹션으로 수정 예정.

---

## 도메인 이벤트

이 모듈이 **발행**하는 도메인 이벤트 목록이다. 소비자 모듈은 이벤트를 구독하여 후속 처리를 수행한다.

| 이벤트명 | 트리거 | 페이로드 주요 필드 | 멱등성 키 | 소비자 |
|----------|--------|-------------------|-----------|--------|
| `document.published` | 문서 게시 (published 전환) | `{ documentId, versionId, boardId, changedBlockIds, schemaVersion }` | `documentId:versionId` | EMB, SCH, NTF, AGG |
| `document.suspended` | 긴급 회수 (`is_suspended = true`) | `{ documentId, reason, suspendedBy, schemaVersion }` | `documentId:timestamp` | SCH, NTF |
| `document.unsuspended` | 회수 해제 (`is_suspended = false`) | `{ documentId, restoredBy, schemaVersion }` | `documentId:timestamp` | SCH, NTF |
| `document.archived` | 문서 보관 (archived 전환) | `{ documentId, previousVersionId, schemaVersion }` | `documentId:timestamp` | SCH |
| `document.deleted` | 문서 삭제 (soft delete) | `{ documentId, deletedBy, boardId, schemaVersion }` | `documentId:timestamp` | SCH, NTF, AGG |
| `document.restored` | 삭제 문서 복구 | `{ documentId, restoredBy, schemaVersion }` | `documentId:timestamp` | NTF |
| `document.expired` | 유효기간 만료 처리 | `{ documentId, expiresAt, assigneeId, schemaVersion }` | `documentId:expiresAt` | NTF, SCH |
| `document.assignee-changed` | 담당자 변경 | `{ documentId, oldAssigneeId, newAssigneeId, changedBy, schemaVersion }` | `documentId:changedBy:timestamp` | NTF, AUD |
| `shared-content.updated` | 공통 컨텐츠 수정 | `{ sharedContentId, updatedBy, referencingDocumentIds, schemaVersion }` | `sharedContentId:version` | EMB |
| `retention.expired` | 보존기간 만료 | `{ documentId, retentionPolicyId, expiryAction, schemaVersion }` | `documentId:retentionPolicyId` | DOC (배치 잡) |
| `draft.stale` | 드래프트 방치 감지 (배치) | `{ documentId, lastModifiedAt, ownerId, schemaVersion }` | `documentId:lastModifiedAt` | NTF |

**이벤트 전달 계약**:

- **전달 채널**: BullMQ (Redis) — 모든 도메인 이벤트는 BullMQ 큐를 통해 비동기 전달
- **큐 명명 규칙**: `{발행모듈}.events` (예: `document.events`, `shared-content.events`)
  - 단일 큐 내에서 이벤트명(`name` 필드)으로 라우팅, 소비자는 이벤트명 기반 핸들러 분기
- **재시도 정책**: 기본 3회, 지수 백오프 (초기 지연 1초, 배율 ×2, 최대 지연 30초)
  - 3회 실패 시 DLQ(`{큐명}:dlq`)로 이동 — 운영자가 수동 재처리 또는 원인 분석
  - `retention.expired`는 규제 관련이므로 5회 재시도 + DLQ 알림 필수
- **멱등성**: 소비자는 멱등성 키(위 표 참조)로 중복 처리를 방지한다. 멱등성 키는 Redis SET 기반으로 TTL 24시간 유지
- **스키마 버전**: 모든 페이로드에 `schemaVersion: number` 포함 — 소비자는 지원 버전만 처리하고, 미지원 버전은 DLQ로 이동하여 업그레이드 후 재처리

---

## 에러 코드

| 코드 | HTTP | 설명 | 관련 BR |
|------|------|------|---------|
| `DOC_NOT_FOUND` | 404 | 문서를 찾을 수 없음 | — |
| `DOC_LOCKED` | 409 | 다른 사용자가 편집 중 | BR-DOC-020 |
| `DOC_CONFLICT_DETECTED` | 409 | 동시 편집 충돌 감지 | BR-DOC-022 |
| `DOC_SUSPENDED_INVALID_STATE` | 422 | published 외 상태에서 is_suspended 설정 시도 | BR-DOC-005 |
| `DOC_RETENTION_DELETE_BLOCKED` | 403 | 법정 보존기간 내 문서 삭제 차단 | BR-DOC-032 |
| `DOC_RETENTION_STATE_BLOCKED` | 403 | 보존기간 내 is_suspended/archived 전환 차단 | BR-DOC-033 |
| `DOC_TAG_LIMIT_EXCEEDED` | 422 | 태그 최대 개수 초과 | BR-DOC-031 |
| `DOC_TAG_DUPLICATE` | 422 | 정규화 후 중복 태그 감지 | BR-DOC-035 |
| `DOC_BLOCK_LIMIT_EXCEEDED` | 422 | 블록 수 상한 초과 | BR-DOC-019 |
| `DOC_SHARED_CONTENT_IN_USE` | 409 | 참조 중인 공통 컨텐츠 삭제 시도 | BR-DOC-026 |
| `DOC_TEMPLATE_IN_USE` | 409 | 사용 중인 템플릿(is_active 체크) 삭제 시도 | BR-DOC-024 |
| `DOC_PENDING_DELETE_BLOCKED` | 409 | 승인 대기 중(pending_review) 문서 삭제 시도 | BR-DOC-036 |
| `DOC_EDITING_DELETE_BLOCKED` | 409 | 다른 사용자가 편집 중인 문서 삭제 시도 | BR-DOC-020 |
| `DOC_SCHEDULE_PAST_TIME` | 422 | 예약 게시 시간이 현재 시각 이전 (`scheduled_publish_at`이 과거 시점) | — |
| `DOC_SCHEDULE_NOT_FREE_MODE` | 422 | `approval_required = true`인 게시판에서 `Document.scheduled_publish_at` 직접 설정 시도 — 해당 게시판에서는 `Approval.scheduled_publish_at`을 사용해야 함 | — |

---

## 비기능 요구사항

| 항목 | 요구사항 | 근거 |
|------|----------|------|
| 문서 열람 초기 로딩 | 2초 이내 | UC-DOC-02 현업 시나리오 (상담사 통화 중 빠른 열람) |
| 자동 저장 응답 | 500ms 이내 | 편집 UX 유지, 사용자 인지 지연 방지 |
| 자동 저장 간격 | 5~10초 (유휴 감지 기반) | 서버 부하와 데이터 유실 리스크 균형 |
| 편집 잠금 기본 타임아웃 | 30분 (관리자 설정 가능, `lm:document.lock_timeout_minutes`) | 비정상 종료 시 장기 잠금 방지 |
| 유효기간 만료 배치 주기 | 1시간 (BullMQ cron) | 만료 처리 지연 최소화 |
| 보존기간 만료 배치 주기 | 1일 (BullMQ cron) | 일 단위 정밀도로 충분 |
| 공통 컨텐츠 재임베딩 SLA | 수정 후 1시간 이내 모든 참조 문서 반영 완료 | 큐 기반 점진적 처리 (§5) |
| 동시 편집 세션 | 문서당 1명 (비관적 락킹) | [BR-DOC-020] |
| 설정 변경 반영 | 캐시 + 이벤트 무효화 방식 — 설정 변경 시 관련 캐시를 이벤트로 무효화하여 재시작 없이 반영 | T4 설계 결정 |

---

## 결정 사항

| 항목 | 결정 | 근거 |
|------|------|------|
| 문서 상태 모델 | **status 5단계** (`draft`, `pending_review`, `approved_scheduled`, `published`, `archived`) + **운영 플래그** (`is_suspended`, `deleted_at`) | status VARCHAR + CHECK로 통합하여 상태가 상호 배타적. `archived`를 별도 플래그로 두면 `published + is_archived = true`인 복합 상태가 발생하여 복잡해지므로 status에 통합 |
| 문서 이력 관리 | **DocumentVersion + BlockSnapshot** 분리 구조 | 블록 단위 스냅샷으로 버전 간 블록별 diff, 재임베딩 판단, 블록 단위 복원이 가능 |
| 버전 생성 시점 | **제출 시점에만 1회 생성**, status 전이(`submitted` → `published`/`rejected`)로 관리 | 동일 콘텐츠 스냅샷 2회 저장은 낭비이고 diff 비교가 복잡해짐 |
| 버전 보관 정책 | **영구 보관 — 절대 자동 삭제하지 않음** | 금융권 감사 요건 대응, 스토리지 비용보다 규제 준수 우선 (M1 확정) |
| 승인·버전 설정 | `Board.approval_required` + `Board.versioning_enabled` 독립 플래그. 루트 게시판에서만 설정·하위 상속 | 고객사별로 승인만·버전만·둘 다 등 조합을 데이터로 구성 가능(구 `board_mode` 단일 축 제거) |
| 에디터 저장 방식 | **노션 스타일 자동 저장** (명시적 저장 버튼 없음) | 블록 에디터 UX와 일관, 사용자 인지 부하 감소 |
| 블록 에디터 기술 스택 | **Tiptap (ProseMirror 기반)** | Vue 3 호환, 커스텀 블록 유연, CRDT 협업 확장 가능 |
| 블록 에디터 협업 모드 | **비관적 락킹** | 대부분 1인 작성 후 승인 흐름, 동시편집 니즈 낮음 |
| 동시 편집 충돌 해결 | 잠금 실패 시 **3가지 옵션** (덮어쓰기/유지/사본 저장) | UC-DOC-03 대안 흐름 3c 반영, 사용자 선택권 보장 |
| 문서 저장 포맷 | **Tiptap JSON (네이티브 포맷)**, 필요 시 추상화 레이어 추가 | 점진적 접근, 에디터 교체 시 마이그레이션 레이어 추가로 대응 |
| 블록 타입 확장 방식 | **초기엔 하드코딩**, 추후 플러그인 설계 고려 | 정의서 블록 타입으로 충분, 커스텀 블록 니즈 낮음 |
| 대형 문서 성능 최적화 | **점진적 로딩** | 성능과 구현 난이도 균형, 가상 스크롤링은 필요 시 추가 |
| 드래프트 만료 | **자동 삭제 없음** + 장기 방치 알림 | 임시저장 문서도 함부로 삭제하지 않음, 작성자/관리자 수동 정리 |
| 템플릿 구조 | **보일러플레이트(블록 JSON + 기본 태그)** — 커스텀 필드 스키마 제거 | 템플릿은 문서 시작점이지 폼 스키마가 아님, GUI 빌더/JSON Schema 불필요 |
| 템플릿 승인 오버라이드 | **없음** — 승인은 게시판 단위로만 | 템플릿은 본문 구조 프리셋, 게시판 승인 설정과 완전 분리 |
| 템플릿 필수 강제 | **없음** — 항상 선택적 | 템플릿은 쓰면 편한 시작점, 강제할 필요 없음 |
| 템플릿 블록 잠금 | **초기 미지원**, 컴플라이언스 니즈 확인 후 추가 | 승인 과정에서 검증으로 대체 |
| 공통 컨텐츠 수정 시 승인 | **승인 없음** — 관리자 권한 + 영향도 확인으로 통제 | 관리자만 수정 가능하므로 별도 승인 불필요, 수정 전 영향 문서 목록 표시 |
| 공통 컨텐츠 삽입 방식 | **인라인만** (문장 중간에 변수처럼) | 블록 단위 삽입 미지원, 초기 구현 단순화 |
| 공통 컨텐츠 버전 고정 | **항상 최신 버전만** — 버전 고정 미지원 | 단순 운영 우선, 계약서 등 특수 케이스는 고려하지 않음 |
| 공통 컨텐츠 재임베딩 전략 | **큐 기반 점진적 처리** | 대량 참조 시 서버 안정성 우선, 즉시 전체 재임베딩은 부하 위험 |
| 문서 URL 형식 | **ID 기반** (`/{board_slug}/{document_id}`) | 안정성 최우선, 내부 시스템이라 SEO/slug 가독성 불필요 |
| 블록 단위 링크 범위 | **모든 블록에 딥링크 지원** | 블록마다 고유 ID 있으므로 추가 비용 낮음, SOP 특정 스텝 공유 등 실무 효용 높음 |
| 단축 URL | **미지원** | 내부 시스템이라 URL 길이 문제 없음, 우선순위 낮음 |
| 게시판 구조 | **재귀 트리**(parent_id) — 사이드바 네비게이션 계층 구성 및 콘텐츠 분류, 운영 정책(승인/권한/RAG)은 게시판 단위 독립 관리(부모→자식 상속 없음). 하위 게시판으로 주제별 분류 체계를 표현 | [rdb.md](../../02-architecture/data/aicm/rdb.md) Board 엔티티, [03-auth-architecture.md §4](../../02-architecture/03-auth-architecture.md) |
| 태그 입력 방식 | **자유 입력 + 자동완성** — 새 태그 자유 생성, 기존 태그 자동완성 제안 | 사전 등록 관리 부담 없이 유연한 태그 운영, 자동완성으로 중복 방지 |
| 문서당 태그 수 | **시스템 설정** (기본 10, `lm:document.max_tags`) | 과도한 태그 방지, 분류 일관성 유지, 운영에서 조정 가능 |
| 삭제 요청 결재 | `Board.approval_required = true`인 게시판에서는 삭제 시에도 동일 승인 라인(템플릿·필수 승인자 설정) 적용 | 금융권 고객 요구 수용, `approval_required = false`에서는 기존 동작(즉시 소프트 딜리트) 유지 |
| 문서 유효기간 | **Document.expires_at** — null이면 무기한, 만료 시 `is_suspended = true` 전환 + 담당자 알림 | 금융권 규정 문서의 유효기간 관리 요구 수용, BullMQ cron 배치로 만료 처리 |
| 문서 담당자 | **Document.assignee_id** — 작성자(created_by)와 별도 지정 가능, 만료 알림 수신 대상 | 고객사 "담당자변경" 요구 수용, 담당자 변경 시 감사 로그 기록 |
| 법정 보존기간 관리 | 관리자 설정으로 활성화 가능 — RetentionPolicy 기반 보존·만료·폐기 처리 | 금융권 등 규제 환경에서 투자권유 문서 10년, 내부통제 문서 5년 등 보존 의무 대응에 활용 |
| 보존기간 만료 후 처리 | 정책별 선택 (`archive` 또는 `mark_for_disposal`) | 고객사마다 폐기 정책이 다름 — 자동 아카이빙 vs 승인 후 폐기 선택권 제공 |
| 문서 내보내기 소속 | **별도 FD-EXP로 분리** | 내보내기는 문서 관리와 독립적인 변환/렌더링 로직, FD-DOC 범위 축소 (B3 확정) |
| AI 요약 저장 방식 | **DB 저장** (`Document.auto_summary`), 재요약 시 LLM 호출하여 갱신 | 매 열람마다 LLM 호출 불필요, DB 캐싱으로 성능 보장 (M3 확정) |
| 설정 변경 반영 방식 | **캐시 + 이벤트 무효화** — 설정 변경 시 관련 캐시 무효화 이벤트 발행 | 서비스 재시작 없이 설정 반영, 이벤트 기반 느슨한 결합 (T4 확정) |
| 예약 게시 범위 | **`approval_required = true`**: FD-APR `Approval.scheduled_publish_at` + `approved_scheduled` 상태 / **`approval_required = false`**: `Document.scheduled_publish_at` + `draft` 상태 유지 → 스케줄러가 `published` 전환 | 전자는 "승인 = 배포" 원칙의 시간축 확장(FD-APR §11.3), 후자는 승인 없이 예약 게시가 필요한 시나리오(공지 예약 등) 지원. 기존 `scheduled-publish` BullMQ 큐를 재활용하여 구현 비용 최소화 |

---

## 관련 문서

| 문서 | 관계 |
|------|------|
| [FD-APR-승인워크플로](FD-APR-승인워크플로.md) | 승인 워크플로 — 문서 상태 전이의 핵심 트리거 |
| [FD-EMB-임베딩파이프라인](FD-EMB-임베딩파이프라인.md) | 임베딩 전략 — published 시점 임베딩, 긴급 회수 처리 |
| [FD-ACL-권한체계](FD-ACL-권한체계.md) | 권한 — BoardPermission 게이트키퍼 |
| [FD-SCH-검색](FD-SCH-검색.md) | 검색 — 블록별 임베딩/가시성 제어, 자동 청킹, 게시판 필터 |
| [FD-AI-AI어시스턴트](FD-AI-AI어시스턴트.md) | AI 기능 — 블록 에디터 내 AI 글쓰기 개선, AI 요약 |
| [FD-EXP-내보내기](FD-EXP-내보내기.md) | 문서 내보내기 — PDF/DOCX/HTML/Markdown 변환 |
| [FD-AUD-감사로그](FD-AUD-감사로그.md) | 감사 로그 — 문서 변경/삭제/인쇄/내보내기 이력 기록 |
| [FD-NTF-알림](FD-NTF-알림.md) | 알림 — 만료/회수/방치/담당자변경 등 알림 발송 |
| [FD-SYS-시스템설정](FD-SYS-시스템설정.md) | 시스템 설정 — 블록 수 상한, 잠금 타임아웃 등 운영 파라미터 |
| [UC-DOC-문서관리](../usecases/user/UC-DOC-문서관리.md) | 대응 유즈케이스 (UC-DOC-01~10) |
