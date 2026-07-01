# 서비스 및 매니저 계층 상세

> Business Logic Layer와 Infrastructure Layer의 매니저, 서비스, 클라이언트에 대한 상세 문서입니다.

## 1. 계층 구조 개요

```mermaid
graph TB
    subgraph BusinessLogic["Business Logic Layer (services/)"]
        DS["DocumentService<br/>문서 CRUD 오케스트레이션"]
        RSS["RagSearchService<br/>RAG 검색 + DB 보강"]
        RISS["RagIntegratedSearchService<br/>통합 검색 (RAG 기반)"]
        RIS["RagInitService<br/>워크스페이스 초기화"]
        WRCS["WorkspaceRagConfigService<br/>RAG 설정 관리"]
        SS["StoreService<br/>저장소 관리"]
        BT["BackgroundTasks<br/>경량 비동기 작업"]
    end

    subgraph DataAccess["Data Access Layer (db/services/)"]
        DBS["DB Services<br/>(도메인별 CRUD)"]
        REPO["Repositories<br/>(쿼리 캡슐화)"]
    end

    subgraph Infrastructure["Infrastructure Layer"]
        subgraph Managers["Managers (싱글톤)"]
            DBM["DatabaseManager"]
            RM["RedisManager"]
            ARM["AsyncRedisManager"]
            LM["LoggerManager"]
        end

        subgraph Clients["External Clients"]
            TC["TenantClient"]
            RAGC["RagServiceClient"]
            LLMC["LLMClient"]
        end
    end

    DS --> DBS
    DS --> TC & RAGC
    DS --> DBM

    RSS --> DBS
    RSS --> RAGC

    RISS --> RAGC
    RISS --> DBS

    RIS --> RAGC
    RIS --> WRCS

    WRCS --> DBS

    BT --> DBS
    BT --> DBM

    DBS --> REPO
    REPO --> DBM
```

---

## 2. Application Services (`services/`)

### 2.1 DocumentService (`services/document_service.py`)

문서의 전체 생명주기를 관리하는 핵심 오케스트레이션 서비스입니다.

```mermaid
classDiagram
    class DocumentService {
        -TenantClient tenant_client
        -MinioClient minio_client
        -DatabaseManager db_manager
        -SearchEngineClient search_client
        +add_doc(request, files) dict
        +update_doc(request) dict
        +update_doc_form(request, files) dict
        +delete_doc(workspace_id, doc_id) dict
        +get_doc(workspace_id, doc_id) dict
        +get_doc_list(workspace_id, filters) list
        +get_doc_from_es(workspace_id, doc_id) dict
        +get_doc_versions_list(workspace_id, doc_id) list
        +approve_doc(request) dict
        +sync_documents(workspace_id) dict
        +sync_from_db(workspace_id) dict
    }
```

#### 문서 생성 상세 흐름

```mermaid
flowchart TD
    START["add_doc() 호출"] --> PARSE["요청 데이터 파싱"]
    PARSE --> META["문서 메타 저장<br/>(aicm_documents)"]
    META --> CONTENT["문서 내용 저장<br/>(aicm_documents_contents)"]
    CONTENT --> SECTION["섹션/목차 파싱 및 저장<br/>(aicm_documents_sections<br/>aicm_documents_index)"]

    SECTION --> HAS_FILES{첨부파일 있음?}
    HAS_FILES -->|Yes| CELERY["Celery 태스크 enqueue<br/>(minio_upload_task)"]
    HAS_FILES -->|No| INDEX

    CELERY --> INDEX["검색 엔진 인덱싱<br/>(SearchEngineClient)"]
    INDEX --> HIST["이력 기록<br/>(BackgroundTask)"]
    HIST --> DONE["결과 반환"]
```

#### 문서 수정 상세 흐름

```mermaid
flowchart TD
    START["update_doc() 호출"] --> LOAD["기존 문서 로드"]
    LOAD --> NEW_CONTENT["새 내용 버전 생성<br/>(documents_contents)"]
    NEW_CONTENT --> DIFF["변경 섹션 비교"]
    DIFF --> UPDATE_SEC["섹션/목차 업데이트"]
    UPDATE_SEC --> UPDATE_META["문서 메타 업데이트<br/>(current_contents_id 갱신)"]
    UPDATE_META --> REINDEX["검색 인덱스 갱신"]
    REINDEX --> VER["버전명 증가<br/>(version_name_utils)"]
    VER --> DONE["결과 반환"]
```

### 2.2 RagSearchService (`services/rag_search_service.py`)

RAG Service 검색 결과를 처리하고 DB 문서 데이터로 보강하는 서비스입니다.

```mermaid
classDiagram
    class RagSearchService {
        -RagServiceClient rag_client
        -DB_DocumentService doc_service
        +search(repo_id, query, workspace_id, top_k, category_ids) dict
        -_enrich_with_db(workspace_id, doc_map) list
    }
```

#### 검색 파이프라인

```mermaid
flowchart TD
    START["search()"] --> RAG["1. RAG Service 하이브리드 검색<br/>(RagServiceClient.search)"]
    RAG --> GROUP["2. aicm_doc_id 기준 그루핑<br/>(여러 청크 → 하나의 문서)"]
    GROUP --> ENRICH["3. DB 전체 문서 데이터로 보강<br/>(doc_service.get_document)"]
    ENRICH --> MERGE["4. RAG blocks_map으로 교체<br/>(score + hit_count 포함)"]
    MERGE --> RETURN["5. 결과 반환<br/>{'total': N, 'retrieved_docs': [...]}"]

    ENRICH -->|"404 NotFound"| FALLBACK["RAG 최소 데이터로 대체"]
    ENRICH -->|"500 등 기타 오류"| RERAISE["예외 재raise"]
```

### 2.3 RagIntegratedSearchService (`services/rag_integrated_search_service.py`)

통합 검색 엔드포인트(`/search/integrated`)의 검색 로직을 담당합니다. 검색 결과를 루트 카테고리 기준으로 그루핑합니다.

### 2.4 RagInitService (`services/rag_init_service.py`)

워크스페이스별 첫 문서 업로드 시 RAG 레포지토리와 API 키를 자동 프로비저닝합니다.

```mermaid
flowchart LR
    TRIGGER["문서 업로드 요청"] --> CHECK["workspace_rag_config 존재?"]
    CHECK -->|"없음"| REPO["RAG Service에 레포지토리 생성"]
    REPO --> APIKEY["API 키 생성"]
    APIKEY --> SAVE["workspace_rag_config에 저장"]
    CHECK -->|"있음"| SKIP["스킵"]
```

### 2.5 WorkspaceRagConfigService (`db/services/workspace_rag_config_service.py`)

`workspace_rag_config` 테이블의 CRUD를 담당합니다. 워크스페이스별 RAG 레포지토리 ID와 API 키를 관리합니다.

### 2.6 BackgroundTasks (`services/background_tasks.py`)

FastAPI의 BackgroundTasks를 활용한 경량 비동기 작업입니다.

```mermaid
graph LR
    subgraph Tasks["Background Tasks"]
        HIT["increment_document_hit_count<br/>문서 조회수 증가"]
        HIST["add_document_hist<br/>문서 이력 추가"]
    end

    HIT --> DBM["DatabaseManager<br/>별도 DB 세션 생성"]
    HIST --> DBM
```

---

## 3. DB Services (`db/services/`)

Data Access Layer의 서비스로, Repository를 조합하여 트랜잭션 단위의 비즈니스 로직을 처리합니다.

```mermaid
graph TB
    subgraph DBServices["DB Services"]
        direction TB

        subgraph DocGroup["문서 도메인"]
            DDS["DB_DocumentService"]
            DDTS["DB_DocumentTypeService"]
            DDSS["DB_DocumentSectionsService"]
            DDIS["DB_DocumentIndexService"]
            DDCS["DB_DocumentContentsService"]
            DDCMS["DB_DocumentCommentService"]
            DDAS["DB_DocumentAttachmentsService"]
            DDBS["DB_DashboardService"]
        end

        subgraph MgmtGroup["관리 도메인"]
            DCATS["DB_DocumentCategoryService"]
            DTPLS["DB_DocumentTemplateService"]
            DAPRS["DB_DocumentApprovalsService"]
            DHISS["DB_DocumentHistoryService"]
        end

        subgraph AuthGroup["권한/검색 도메인"]
            DCPS["DB_CategoryPermissionService"]
            DCPGS["DB_CategoryPermissionGroupService"]
            DSQS["DB_SearchQueryService"]
            DWSS["DB_WorkspaceService"]
        end
    end

    subgraph Repos["Repositories"]
        R["각 서비스 대응 Repository"]
    end

    DocGroup --> R
    MgmtGroup --> R
    AuthGroup --> R
```

### 서비스-리포지토리 매핑

| DB Service | Repository | 테이블 |
|-----------|-----------|--------|
| `DB_DocumentService` | `DocumentRepository` | `aicm.aicm_documents` |
| `DB_DocumentContentsService` | `DocumentContentsRepository` | `aicm.aicm_documents_contents` |
| `DB_DocumentSectionsService` | `DocumentSectionsRepository` | `aicm.aicm_documents_sections` |
| `DB_DocumentIndexService` | `DocumentIndexRepository` | `aicm.aicm_documents_index` |
| `DB_DocumentAttachmentsService` | `DocumentAttachmentsRepository` | `aicm.aicm_documents_attachments` |
| `DB_DocumentCommentService` | `DocumentCommentRepository` | `aicm.aicm_documents_comments` |
| `DB_DocumentTypeService` | `DocumentTypeRepository` | `aicm.document_types` |
| `DB_DashboardService` | `DashboardRepository` | (다중 테이블 집계) |
| `DB_DocumentCategoryService` | `DocumentCategoriesRepository` | `aicm.aicm_documents_categories` |
| `DB_DocumentTemplateService` | `DocumentTemplatesRepository` | `aicm.aicm_documents_templates` |
| `DB_DocumentApprovalsService` | `DocumentApprovalsRepository` | `aicm.aicm_documents_approvals` |
| `DB_DocumentHistoryService` | `DocumentHistoryRepository` | `aicm.aicm_documents_hist` |
| `DB_CategoryPermissionService` | `CategoryPermissionRepository` | `aicm.aicm_category_permissions` |
| `DB_CategoryPermissionGroupService` | `CategoryPermissionGroupRepository` | `aicm.aicm_permission_groups` |
| `DB_SearchQueryService` | `SearchQueryRepository` | `aicm.aicm_search_query` |
| `DB_WorkspaceService` | `WorkspaceRepository` | `ce.workspaces` |

---

## 4. Managers (싱글톤 인프라)

### 4.1 DatabaseManager (`managers/database_manager.py`)

멀티테넌트 환경에서 동적으로 DB 연결을 관리하는 핵심 매니저입니다.

```mermaid
classDiagram
    class DatabaseManager {
        -EngineCache engine_cache
        -MinioConfigCache minio_cache
        +get_engine_by_url(db_url) Engine
        +get_session(engine) SessionMaker
        +get_db_core(request) Generator~Session~
        +get_db(request) Generator~Session~
        +get_db_by_url_core(request) Generator~Session~
        +get_db_by_url(request) Generator~Session~
    }

    class EngineCache {
        -dict~str,Engine~ cache
        -TTL ttl
        +get(db_url) Engine
        +put(db_url, engine) void
    }

    class MinioConfigCache {
        -dict~str,dict~ cache
        -TTL ttl
        +get(token) dict
        +put(token, config) void
    }

    DatabaseManager *-- EngineCache
    DatabaseManager *-- MinioConfigCache
```

#### DB 세션 생성 흐름

```mermaid
flowchart TD
    REQ["HTTP 요청"] --> TOKEN["X-auth-token 추출"]
    TOKEN --> TC["TenantClient.get_tenant_db_url()"]
    TC --> CACHE{EngineCache에<br/>엔진 존재?}
    CACHE -->|Hit| SESSION["세션 생성"]
    CACHE -->|Miss| CREATE["SQLAlchemy Engine 생성"]
    CREATE --> PUT["캐시에 저장"]
    PUT --> SESSION
    SESSION --> YIELD["세션 Yield<br/>(요청 처리)"]
    YIELD --> CLOSE["세션 Close<br/>(자동 정리)"]
```

#### FastAPI 의존성 주입 패턴

```mermaid
graph LR
    subgraph DI["의존성 유형"]
        DB1["get_db()<br/>X-DB-URL 직접 사용"]
        DB2["get_db_by_url()<br/>X-auth-token → TenantClient"]
    end

    DB1 -->|개발/디버깅| EP["Endpoint"]
    DB2 -->|운영| EP
```

### 4.2 RedisManager (`managers/redis_manager.py`)

Redis Stream 기반 이벤트 발행/소비를 담당합니다.

```mermaid
classDiagram
    class RedisManager {
        -Redis client
        -Lock lock
        +build_stream_key(env, tenant_id, service, domain, event_type) str
        +publish_event(stream_key, data) str
        +consume_events(stream_key, group, consumer) Generator
    }

    note for RedisManager "스트림 키 패턴:\n<env>:<tenant_id>:<service>:<domain>:<event_type>"
```

#### Redis Stream 이벤트 흐름

```mermaid
sequenceDiagram
    participant PUB as Publisher<br/>(RedisManager)
    participant REDIS as Redis Stream
    participant SUB as Subscriber<br/>(AsyncRedisManager)
    participant HANDLER as Event Handler

    PUB->>REDIS: XADD stream_key data
    Note over REDIS: 이벤트 저장

    loop 지속 구독
        SUB->>REDIS: XREAD stream_key
        REDIS-->>SUB: 새 이벤트
        SUB->>HANDLER: 핸들러 실행
    end
```

### 4.3 AsyncRedisManager (`managers/async_redis_manager.py`)

비동기 환경에서 Redis Stream을 구독하고 등록된 핸들러를 실행합니다.

```mermaid
classDiagram
    class AsyncRedisManager {
        -AsyncRedis client
        -dict handlers
        +build_stream_key(env, tenant_id, service, domain, event_type) str
        +register_event_handler(stream_key, handler) void
        -_consume_events(stream_key) coroutine
    }
```

### 4.4 LoggerManager (`managers/logger_manager.py`)

Loguru와 OpenTelemetry를 통합하는 로깅 매니저입니다.

```mermaid
flowchart TD
    INIT["init_logging()"] --> CHECK{OTEL 엔드포인트가<br/>localhost?}
    CHECK -->|No| OTEL["OTLP Log Exporter 설정"]
    CHECK -->|Yes| LOGURU["Loguru만 사용"]

    OTEL --> BRIDGE["표준 logging ↔ Loguru 양방향 전파"]
    LOGURU --> BRIDGE

    BRIDGE --> INTERCEPT["InterceptHandler<br/>logging → Loguru 캡처"]
```

### 4.5 EmbeddingModelManager (`managers/embedding_model_manager.py`)

SentenceTransformer 임베딩 모델의 초기화 및 제공을 담당합니다.

```mermaid
classDiagram
    class EmbeddingModelManager {
        -SentenceTransformer model
        -str model_path
        +init_model() void
        +get_model() SentenceTransformer
    }

    note for EmbeddingModelManager "현재 주석 처리되어 비활성 상태.\n검색은 외부 SearchEngineClient로 전환됨."
```

> 현재 `EmbeddingModelManager`는 `main.py`에서 주석 처리되어 있습니다. 문서 임베딩 및 검색은 외부 Search Engine Service로 위임되어 있습니다.

---

## 5. External Clients (`clients/`)

### 5.1 클라이언트 간 관계

```mermaid
graph TB
    subgraph Clients["External Clients"]
        TC["TenantClient"]
        RAGC["RagServiceClient"]
        LLMC["LLMClient"]
    end

    subgraph Services["사용처"]
        DBM["DatabaseManager"]
        DS["DocumentService"]
        RSS["RagSearchService"]
        RISS["RagIntegratedSearchService"]
        RIS["RagInitService"]
    end

    TC --> DBM
    TC --> DS
    RAGC --> DS
    RAGC --> RSS
    RAGC --> RISS
    RAGC --> RIS
    LLMC --> DS
```

### 5.2 TenantClient

멀티테넌트 환경에서 테넌트 설정을 조회하는 핵심 클라이언트입니다.

```mermaid
classDiagram
    class TenantClient {
        -Settings settings
        +generate_auth_token(timestamp) str
        +get_tenant_config(token) dict
        +get_tenant_id_by_token(token) str
        +get_tenant_db_url(token) str
        +get_tenant_minio_config(token) dict
        +get_tenant_es_config(token) dict
        +get_all_tenants_configs() list
    }
```

#### 테넌트 설정 조회 구조

```mermaid
graph TB
    TOKEN["X-auth-token"] --> TC["TenantClient"]

    TC --> CONFIG["get_tenant_config()"]
    CONFIG --> TMS["User Service<br/>/api/configs/get_configs"]

    TMS -->|응답| RESP["configs"]
    RESP --> DB_CFG["db_config<br/>(PostgreSQL URL)"]
    RESP --> MINIO_CFG["minio_config<br/>(endpoint, key, secret)"]
    RESP --> ES_CFG["es_config<br/>(Elasticsearch 설정)"]
    RESP --> TENANT_ID["tenant_id"]
```

### 5.3 MinioClient

S3 호환 오브젝트 스토리지 클라이언트입니다.

```mermaid
classDiagram
    class MinioClient {
        -Minio client
        -str bucket
        +ensure_bucket() void
        +upload_file(data, name, type) str
        +get_presigned_url(name, expires) str
        +download_to_tempfile(name) str
        +list_objects(prefix) list
        +delete_object(name) void
        +delete_objects_with_prefix(prefix) void
    }
```

### 5.4 RagServiceClient (`clients/rag_service_client.py`)

RAG Service와 통신하는 핵심 클라이언트입니다. API 키 및 토큰 기반 인증 모드를 모두 지원합니다.

```mermaid
classDiagram
    class RagServiceClient {
        -str base_url
        -str auth_mode
        -str api_key
        -float timeout
        +create_repo(workspace_id) dict
        +create_api_key(repo_id) dict
        +delete_repo(repo_id) void
        +index_document(repo_id, doc_id, content, metadata) dict
        +delete_document(repo_id, rag_doc_id) void
        +search(repo_id, query, category_ids, top_k) dict
        +get_document_preview(repo_id, rag_doc_id) Response
        +download_document(repo_id, rag_doc_id) Response
        +list_categories(repo_id) list
        +create_category(repo_id, data) dict
        +update_category(repo_id, category_id, data) dict
        +delete_category(repo_id, category_id) void
        +bulk_upload_categories(repo_id, categories) dict
        +list_synonyms(repo_id) list
        +create_synonym(repo_id, data) dict
        +delete_synonym(repo_id, synonym_id) void
        +health_check(repo_id) dict
    }
```

> `SearchEngineClient`(ES 기반)와 `NLPEngineClient`(형태소 분석)는 RAG Service 전환으로 폐기되었습니다.

---

## 6. 유틸리티 (`utils/`)

```mermaid
graph TB
    subgraph Utils["유틸리티 모듈"]
        HTML["html_utils.py<br/>HTML↔마크다운 변환<br/>html_to_plain_text<br/>ES 하이라이트 병합"]
        CIPHER["cipher_utils.py<br/>AES 암복호화"]
        CAL["calendar_utils.py<br/>기간 계산"]
        VER["version_name_utils.py<br/>버전명 증가 (v1.0 → v1.1)"]
        STR["str_utils.py<br/>문자열 정리"]
        OUTLINE["outline_utils.py<br/>문서 아웃라인에서<br/>블록 ID 수집"]
        MEM["memory_utils.py<br/>GC, GPU 메모리 정리"]
    end

    subgraph Usage["주요 사용처"]
        DS["DocumentService"] --> HTML & VER & OUTLINE
        DBM["DatabaseManager"] --> CIPHER
        DASH["Dashboard"] --> CAL
        EP["Endpoints"] --> MEM
    end
```

| 유틸리티 | 주요 함수 | 사용처 |
|----------|----------|--------|
| `html_utils` | `html_to_plain_text()`, `merge_highlight()` | 문서 텍스트 처리 |
| `cipher_utils` | `encrypt_str()`, `decrypt_str()` | DB URL 암복호화 |
| `calendar_utils` | `get_period_date()` | 대시보드 기간 필터 |
| `version_name_utils` | `next_version_name()` | 문서 버전 관리 |
| `outline_utils` | `collect_blocks()` | 문서 섹션 파싱 |
| `str_utils` | `remove_leading_newlines()` | 텍스트 정리 |
| `memory_utils` | `cleanup_memory()` | GC/GPU 메모리 해제 |
