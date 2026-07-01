# 데이터 모델 및 스키마

> ORM 모델, 테이블 관계, Repository 패턴에 대한 상세 문서입니다.

## 1. 개요

AICM Service는 **SQLAlchemy ORM**을 사용하며, 모든 테이블은 PostgreSQL의 `aicm` 스키마에 정의되어 있습니다. 워크스페이스 정보만 `ce` 스키마를 사용합니다.

```mermaid
graph TB
    subgraph Schema_CE["ce 스키마"]
        WS["workspaces"]
    end

    subgraph Schema_AICM["aicm 스키마"]
        DOC["aicm_documents"]
        CONT["aicm_documents_contents"]
        SEC["aicm_documents_sections"]
        IDX["aicm_documents_index"]
        ATT["aicm_documents_attachments"]
        CAT["aicm_documents_categories"]
        TPL["aicm_documents_templates"]
        CMT["aicm_documents_comments"]
        HIST["aicm_documents_hist"]
        APR["aicm_documents_approvals"]
        DT["document_types"]
        SQ["aicm_search_query"]
        CP["aicm_category_permissions"]
        PG["aicm_permission_groups"]
        WRC["workspace_rag_config"]
    end
```

---

## 2. ER 다이어그램

### 2.1 전체 엔티티 관계

```mermaid
erDiagram
    WORKSPACES {
        uuid id PK
        string name
        datetime created_at
    }

    DOCUMENTS {
        uuid id PK
        string workspace_id FK
        string name
        uuid current_contents_id FK
        uuid effective_contents_id FK
        string category_id FK
        string creator_id
        string doc_type FK
        int hit_count
        bool is_temporary
        dict meta
        string rag_doc_id "RAG Service 문서 ID"
        datetime created_at
        datetime updated_at
    }

    DOCUMENTS_CONTENTS {
        uuid id PK
        uuid document_id FK
        string version_name
        dict contents
        string summary
        string ai_summary
        list keywords
        string creator_id
        datetime created_at
    }

    DOCUMENTS_SECTIONS {
        uuid id PK
        uuid content_id FK
        uuid index_id FK
        string title
        string content_html
        string content_text
        int depth
        int order
    }

    DOCUMENTS_INDEX {
        uuid id PK
        uuid document_id FK
        string title
        uuid parent_id FK
        int depth
        int order
    }

    DOCUMENTS_ATTACHMENTS {
        uuid id PK
        uuid document_id FK
        uuid content_id FK
        string file_name
        string object_name
        string content_type
        int file_size
        datetime created_at
    }

    DOCUMENTS_CATEGORIES {
        uuid id PK
        string workspace_id FK
        string name
        string description
        uuid parent_id FK
        string doc_type
        string icon
        int ord
        datetime created_at
    }

    DOCUMENTS_TEMPLATES {
        uuid id PK
        string workspace_id FK
        string name
        dict template
        list tags
        datetime created_at
        datetime updated_at
    }

    DOCUMENTS_COMMENTS {
        uuid id PK
        string workspace_id FK
        uuid document_id FK
        string user_id
        string comment
        bool is_anonymity
        bool is_declaration
        datetime created_at
        datetime updated_at
    }

    DOCUMENTS_HIST {
        uuid id PK
        string workspace_id FK
        uuid document_id FK
        uuid content_id FK
        string user_id
        string history
        string details
        datetime created_at
    }

    DOCUMENTS_APPROVALS {
        uuid id PK
        string workspace_id FK
        uuid document_id FK
        string version_name
        string manager_id
        bool is_approved
        datetime effective_date
        string reason
        datetime created_at
    }

    DOCUMENT_TYPES {
        uuid id PK
        string workspace_id FK
        string name
        string description
        datetime created_at
    }

    SEARCH_QUERY {
        uuid id PK
        string workspace_id FK
        string keyword
        int count
        datetime created_at
        datetime updated_at
    }

    CATEGORY_PERMISSIONS {
        uuid id PK
        uuid group_id FK
        string category_id FK
        bool enable_viewer
        bool enable_editor
        bool enable_approve
    }

    PERMISSION_GROUPS {
        uuid id PK
        string workspace_id FK
        string name
        datetime created_at
        datetime updated_at
    }

    WORKSPACE_RAG_CONFIG {
        uuid id PK
        string workspace_id FK
        string repo_id "RAG Service 레포지토리 ID"
        string api_key "암호화된 API 키"
        datetime created_at
        datetime updated_at
    }

    WORKSPACES ||--o{ DOCUMENTS : "has"
    WORKSPACES ||--o{ DOCUMENTS_CATEGORIES : "has"
    WORKSPACES ||--o{ DOCUMENTS_TEMPLATES : "has"
    WORKSPACES ||--o{ PERMISSION_GROUPS : "has"
    WORKSPACES ||--o{ DOCUMENT_TYPES : "has"
    WORKSPACES ||--o| WORKSPACE_RAG_CONFIG : "has"

    DOCUMENTS ||--o{ DOCUMENTS_CONTENTS : "versions"
    DOCUMENTS ||--|{ DOCUMENTS_INDEX : "has outline"
    DOCUMENTS ||--o{ DOCUMENTS_ATTACHMENTS : "has files"
    DOCUMENTS ||--o{ DOCUMENTS_COMMENTS : "has comments"
    DOCUMENTS ||--o{ DOCUMENTS_HIST : "has history"
    DOCUMENTS ||--o{ DOCUMENTS_APPROVALS : "has approvals"
    DOCUMENTS }o--|| DOCUMENTS_CATEGORIES : "belongs to"
    DOCUMENTS }o--o| DOCUMENT_TYPES : "typed as"

    DOCUMENTS_CONTENTS ||--o{ DOCUMENTS_SECTIONS : "has sections"
    DOCUMENTS_CONTENTS ||--o{ DOCUMENTS_ATTACHMENTS : "has files"
    DOCUMENTS_INDEX ||--o{ DOCUMENTS_SECTIONS : "references"

    DOCUMENTS_CATEGORIES ||--o{ DOCUMENTS_CATEGORIES : "parent-child"
    DOCUMENTS_CATEGORIES ||--o{ CATEGORY_PERMISSIONS : "has permissions"
    PERMISSION_GROUPS ||--o{ CATEGORY_PERMISSIONS : "contains"
```

---

## 3. 핵심 모델 상세

### 3.1 문서 (`aicm_documents`)

문서의 메타데이터를 저장하는 루트 엔티티입니다.

```mermaid
classDiagram
    class Documents {
        +UUID id
        +String workspace_id
        +String name
        +UUID current_contents_id
        +UUID effective_contents_id
        +String category_id
        +String creator_id
        +String doc_type
        +Integer hit_count
        +Boolean is_temporary
        +JSON meta
        +String rag_doc_id
        +DateTime created_at
        +DateTime updated_at
    }

    note for Documents "current_contents_id: 최신 편집 버전\neffective_contents_id: 승인된 유효 버전\nrag_doc_id: RAG Service에서 부여한 문서 ID"
```

#### 버전 관리 개념

```mermaid
graph LR
    subgraph Document["aicm_documents"]
        CURR["current_contents_id<br/>(최신 편집 버전)"]
        EFF["effective_contents_id<br/>(승인된 유효 버전)"]
    end

    subgraph Contents["aicm_documents_contents"]
        V1["v1.0 (초기)"]
        V2["v1.1 (편집)"]
        V3["v1.2 (최신 편집)"]
    end

    EFF --> V1
    CURR --> V3
    V1 -.->|"승인됨"| V1
    V2 -.->|"미승인"| V2
    V3 -.->|"미승인"| V3
```

### 3.2 문서 내용 (`aicm_documents_contents`)

문서의 실제 내용을 버전별로 저장합니다. 문서가 수정될 때마다 새 레코드가 생성됩니다.

```mermaid
classDiagram
    class DocumentsContents {
        +UUID id
        +UUID document_id
        +String version_name
        +JSON contents
        +String summary
        +String ai_summary
        +List~String~ keywords
        +String creator_id
        +DateTime created_at
    }

    note for DocumentsContents "contents: 에디터 JSON 구조\n(outline + blocks_map)"
```

### 3.3 문서 섹션 (`aicm_documents_sections`)

문서 내용을 섹션 단위로 분리 저장합니다. 검색 엔진 인덱싱의 기본 단위입니다.

```mermaid
classDiagram
    class DocumentsSections {
        +UUID id
        +UUID content_id
        +UUID index_id
        +String title
        +String content_html
        +String content_text
        +Integer depth
        +Integer order
    }

    note for DocumentsSections "content_id → documents_contents.id\nindex_id → documents_index.id\n검색 인덱싱의 기본 단위"
```

### 3.4 문서 목차 인덱스 (`aicm_documents_index`)

문서의 트리형 목차 구조를 저장합니다.

```mermaid
classDiagram
    class DocumentsIndex {
        +UUID id
        +UUID document_id
        +String title
        +UUID parent_id
        +Integer depth
        +Integer order
    }
```

#### 목차 트리 구조 예시

```mermaid
graph TD
    ROOT["문서 루트"]
    ROOT --> CH1["1. 개요 (depth=0)"]
    ROOT --> CH2["2. 본문 (depth=0)"]
    ROOT --> CH3["3. 결론 (depth=0)"]

    CH2 --> CH2_1["2.1 배경 (depth=1)"]
    CH2 --> CH2_2["2.2 방법론 (depth=1)"]

    CH2_2 --> CH2_2_1["2.2.1 접근법 A (depth=2)"]
    CH2_2 --> CH2_2_2["2.2.2 접근법 B (depth=2)"]
```

### 3.5 문서 카테고리 (`aicm_documents_categories`)

계층형 카테고리 구조를 지원합니다.

```mermaid
classDiagram
    class DocumentCategories {
        +UUID id
        +String workspace_id
        +String name
        +String description
        +UUID parent_id
        +String doc_type
        +String icon
        +Integer ord
        +DateTime created_at
    }

    DocumentCategories --> DocumentCategories : parent_id (self-ref)
```

#### 카테고리 트리 예시

```mermaid
graph TD
    ROOT1["기술 문서 (ord=1)"]
    ROOT2["운영 매뉴얼 (ord=2)"]
    ROOT3["정책/규정 (ord=3)"]

    ROOT1 --> T1["API 가이드"]
    ROOT1 --> T2["설계 문서"]
    ROOT2 --> O1["배포 절차"]
    ROOT2 --> O2["장애 대응"]
```

### 3.6 문서 승인 (`aicm_documents_approvals`)

문서 승인 워크플로우를 관리합니다.

```mermaid
stateDiagram-v2
    [*] --> 초안: 문서 생성
    초안 --> 승인대기: 승인 요청
    승인대기 --> 승인됨: approve (is_approved=true)
    승인대기 --> 반려됨: reject (is_approved=false)
    반려됨 --> 초안: 재편집
    승인됨 --> 초안: 새 버전 편집

    note right of 승인됨
        effective_contents_id 갱신
        검색 인덱스 approved 상태 반영
    end note
```

### 3.8 워크스페이스 RAG 설정 (`workspace_rag_config`)

워크스페이스별 RAG Service 레포지토리 ID와 API 키를 저장합니다. 첫 문서 업로드 시 `RagInitService`가 자동으로 생성합니다.

```mermaid
classDiagram
    class WorkspaceRagConfig {
        +UUID id
        +String workspace_id
        +String repo_id
        +String api_key
        +DateTime created_at
        +DateTime updated_at
    }

    note for WorkspaceRagConfig "api_key는 AES 암호화 저장\nworkspace_id당 1개 레코드 (unique)"
```

---

### 3.7 카테고리 권한 (`aicm_category_permissions` + `aicm_permission_groups`)

```mermaid
classDiagram
    class PermissionGroups {
        +UUID id
        +String workspace_id
        +String name
        +DateTime created_at
        +DateTime updated_at
    }

    class CategoryPermissions {
        +UUID id
        +UUID group_id
        +String category_id
        +Boolean enable_viewer
        +Boolean enable_editor
        +Boolean enable_approve
    }

    PermissionGroups "1" --> "*" CategoryPermissions : contains
    CategoryPermissions --> DocumentCategories : references
```

#### 권한 모델

```mermaid
graph TB
    PG["권한 그룹<br/>(예: 편집팀)"]

    PG --> P1["카테고리 A<br/>viewer: ✓ editor: ✓ approve: ✗"]
    PG --> P2["카테고리 B<br/>viewer: ✓ editor: ✗ approve: ✗"]
    PG --> P3["카테고리 C<br/>viewer: ✓ editor: ✓ approve: ✓"]
```

---

## 4. 문서 내용 구조 (JSON)

`documents_contents.contents` 필드는 에디터의 JSON 구조를 저장합니다.

```mermaid
graph TB
    CONTENTS["contents (JSON)"]
    CONTENTS --> OUTLINE["outline<br/>(트리 구조 배열)"]
    CONTENTS --> BLOCKS["blocks_map<br/>(블록 ID → 내용 매핑)"]

    OUTLINE --> NODE1["{ id, type, children }"]
    OUTLINE --> NODE2["{ id, type, children }"]

    BLOCKS --> B1["block_id_1 → { type, html, ... }"]
    BLOCKS --> B2["block_id_2 → { type, html, ... }"]
```

#### outline → sections 변환 흐름

```mermaid
flowchart LR
    OUTLINE["outline\n(트리 순회)"] --> COLLECT["collect_blocks()\n(블록 ID 수집)"]
    COLLECT --> BLOCKS["blocks_map에서\n내용 추출"]
    BLOCKS --> HTML["HTML 내용 조합"]
    HTML --> SECTION["DocumentSection 생성"]
    HTML --> TEXT["html_to_plain_text()\n(검색용 텍스트)"]
```

---

## 5. Repository 패턴

### 5.1 패턴 구조

```mermaid
graph TB
    subgraph Pattern["Repository 패턴"]
        EP["Endpoint"] -->|"Depends"| SVC["DB Service"]
        SVC -->|"사용"| REPO["Repository"]
        REPO -->|"쿼리"| MODEL["SQLAlchemy Model"]
        MODEL -->|"매핑"| TABLE["PostgreSQL Table"]
    end
```

### 5.2 계층별 책임

```mermaid
graph LR
    subgraph DBService["DB Service"]
        direction TB
        S1["트랜잭션 관리"]
        S2["여러 Repository 조합"]
        S3["도메인 로직"]
    end

    subgraph Repository["Repository"]
        direction TB
        R1["단일 테이블 쿼리"]
        R2["CRUD 메서드"]
        R3["복합 쿼리 캡슐화"]
    end

    subgraph Model["ORM Model"]
        direction TB
        M1["테이블 매핑"]
        M2["컬럼 정의"]
        M3["관계 정의"]
    end

    DBService --> Repository --> Model
```

### 5.3 Repository 목록

| Repository | 모델 | 주요 쿼리 |
|-----------|------|----------|
| `DocumentRepository` | `Documents` | 문서 CRUD, 목록 조회, 조회수 증가 |
| `DocumentContentsRepository` | `DocumentsContents` | 버전별 내용 저장/조회 |
| `DocumentSectionsRepository` | `DocumentsSections` | 섹션 CRUD, 내용별 조회 |
| `DocumentIndexRepository` | `DocumentsIndex` | 목차 트리 CRUD |
| `DocumentAttachmentsRepository` | `DocumentsAttachments` | 첨부파일 메타 CRUD |
| `DocumentCommentRepository` | `DocumentsComments` | 댓글 CRUD, 사용자별 조회 |
| `DocumentCategoriesRepository` | `DocumentCategories` | 카테고리 트리 CRUD |
| `DocumentTemplatesRepository` | `DocumentTemplates` | 템플릿 CRUD, 태그 필터 |
| `DocumentApprovalsRepository` | `DocumentApprovals` | 승인 레코드 CRUD |
| `DocumentHistoryRepository` | `DocumentsHist` | 이력 기록/조회 |
| `DocumentTypeRepository` | `DocumentTypes` | 문서 타입 CRUD |
| `DashboardRepository` | (다중 테이블) | 대시보드 집계 쿼리 |
| `CategoryPermissionRepository` | `CategoryPermissions` | 권한 CRUD |
| `CategoryPermissionGroupRepository` | `PermissionGroups` | 권한 그룹 CRUD |
| `SearchQueryRepository` | `SearchQuery` | 검색어 저장/통계 |
| `WorkspaceRepository` | `Workspace` | 워크스페이스 검증 |

---

## 6. 데이터베이스 스키마 관리

### 6.1 스키마 구성

| 스키마 | 용도 | 테이블 수 |
|--------|------|----------|
| `aicm` | AICM 서비스 전용 | 15개 (`workspace_rag_config` 추가) |
| `ce` | 공통 엔티티 (워크스페이스) | 1개 |

### 6.2 인덱스 전략

`sql/create_indexes_for_get_filtered_doc.sql`에 정의된 성능 최적화 인덱스가 존재합니다.

```mermaid
graph TB
    PERF["성능 최적화"]

    PERF --> IDX1["문서 목록 필터 인덱스<br/>(workspace_id, category_id, status)"]
    PERF --> IDX2["검색어 통계 인덱스<br/>(workspace_id, keyword)"]
    PERF --> IDX3["이력 조회 인덱스<br/>(document_id, created_at)"]
```

### 6.3 JSON 스키마 정의 (`model_json/`)

각 모델의 JSON 스키마 정의가 `model_json/` 디렉토리에 유지됩니다. API 문서화 및 클라이언트 코드 생성에 활용됩니다.

| 파일 | 대응 모델 |
|------|----------|
| `documents_model.json` | `aicm_documents` |
| `document_sections.json` | `aicm_documents_sections` |
| `document_index.json` | `aicm_documents_index` |
| `document_approvals.json` | `aicm_documents_approvals` |
| `document_categories.json` | `aicm_documents_categories` |
| `document_comment.json` | `aicm_documents_comments` |
| `documents_history.json` | `aicm_documents_hist` |
| `document_templates.json` | `aicm_documents_templates` |
| `document_page_model.json` | 페이지네이션 모델 |
| `levels_model.json` | 계층 구조 모델 |
| `store.json` | 저장소 설정 |
| `store_role.json` | 저장소 역할 |
