# 인프라 및 배포

> Docker, Celery, Redis, 모니터링, 배포 전략에 대한 상세 문서입니다.

## 1. 인프라 구성 개요

```mermaid
graph TB
    subgraph Docker["Docker 환경"]
        APP["AICM Service<br/>Container<br/>:32012"]
    end

    subgraph Infra["인프라 서비스"]
        PG["PostgreSQL<br/>(테넌트별 DB)"]
        REDIS["Redis<br/>:6379"]
        MINIO["MinIO<br/>:9000"]
    end

    subgraph External["외부 마이크로서비스"]
        TMS["Tenant Management<br/>Service"]
        US["User Service"]
        SES["Search Engine<br/>Service"]
        NLPS["NLP Engine<br/>Service"]
        LLMS["LLM Manager<br/>Service"]
    end

    subgraph Monitoring["모니터링"]
        OTEL["OpenTelemetry<br/>Collector"]
        SIG["SigNoz / Jaeger"]
    end

    APP --> PG
    APP --> REDIS
    APP --> MINIO
    APP --> TMS & US & SES & NLPS & LLMS
    APP -->|OTLP| OTEL
    OTEL --> SIG
```

---

## 2. Docker 구성

### 2.1 Docker Compose (개발 환경)

```mermaid
graph LR
    subgraph DockerCompose["docker-compose.yml"]
        APP["aicm_service<br/>:32012"]
    end

    APP -->|env| ENV["환경변수"]

    ENV --> E1["DB_SECRET_KEY"]
    ENV --> E2["CIPHER_KEY"]
    ENV --> E3["TENANT_MANAGEMENT_SERVICE"]
    ENV --> E4["MINIO_ENDPOINT / KEY / SECRET"]
    ENV --> E5["MAX_UPLOAD_SIZE"]
```

### 2.2 환경변수 구성

| 환경변수 | 설명 | 예시 값 |
|---------|------|---------|
| `DB_SECRET_KEY` | DB 암호화 키 | `timbel-c738eb67-...` |
| `CIPHER_KEY` | AES 암복호화 키 | `EBL8sbH5uMkA...` |
| `MAX_UPLOAD_SIZE` | 최대 업로드 크기 (bytes) | `104857600` (100MB) |
| `TENANT_MANAGEMENT_SERVICE` | 테넌트 관리 서비스 URL | `61.83.191.61:31020` |
| `MINIO_ENDPOINT` | MinIO 엔드포인트 | `61.83.191.61:9000` |
| `MINIO_ACCESS_KEY` | MinIO 액세스 키 | (자격 증명) |
| `MINIO_SECRET_KEY` | MinIO 시크릿 키 | (자격 증명) |
| `MINIO_BUCKET` | MinIO 버킷명 | `aicm-bucket` |
| `USE_LLM` | LLM 사용 여부 | `False` |

### 2.3 Dockerfile 빌드 흐름

```mermaid
flowchart TD
    BASE["Python 베이스 이미지"] --> COPY["소스 코드 복사"]
    COPY --> DEPS["의존성 설치<br/>(requirements.txt)"]
    DEPS --> EXPOSE["포트 노출 (32012)"]
    EXPOSE --> CMD["python main.py run"]
```

---

## 3. 설정 관리 (`core/config.py`)

### 3.1 Pydantic Settings 기반 설정

```mermaid
flowchart TD
    subgraph Sources["설정 소스 (우선순위)"]
        ENV_VAR["1. 환경변수<br/>(최우선)"]
        ENV_FILE["2. .env 파일"]
        DEFAULT["3. 기본값<br/>(코드 내 정의)"]
    end

    subgraph Settings["Settings 클래스"]
        direction TB
        S_BASIC["기본: PROJECT_NAME, VERSION, DEBUG"]
        S_SERVER["서버: HOST, PORT, RELOAD"]
        S_AUTH["인증: INTERNAL_AUTH_KEY, CIPHER_KEY"]
        S_REDIS["Redis: HOST, PORT, DB, PASSWORD"]
        S_CELERY["Celery: BROKER_DB, RESULT_DB"]
        S_EXT["외부: NLP, LLM, SEARCH_ENGINE"]
        S_AI["AI: EMBEDDING_MODEL_PATH"]
    end

    ENV_VAR --> Settings
    ENV_FILE --> Settings
    DEFAULT --> Settings
```

### 3.2 설정 카테고리

```mermaid
mindmap
    root((Settings))
        기본 설정
            PROJECT_NAME
            VERSION
            API_V1_STR
            DEBUG
        서버 설정
            HOST: 0.0.0.0
            PORT: 32012
            RELOAD: False
        인증/보안
            INTERNAL_AUTH_KEY
            CIPHER_KEY
            is_cipher
        Redis
            REDIS_HOST
            REDIS_PORT
            REDIS_DB
            REDIS_PASSWORD
        Celery
            CELERY_BROKER_DB: 1
            CELERY_RESULT_BACKEND_DB: 2
        외부 서비스
            TENANT_MANAGEMENT_SERVICE
            USER_SERVICE
            NLP_ENGINE_ENDPOINT
            LLM_MANAGER_ENDPOINT
            SEARCH_ENGINE_SERVICE
        AI/ML
            EMBEDDING_MODEL_PATH
```

---

## 4. Celery 비동기 작업 시스템

### 4.1 Celery 구성

```mermaid
graph TB
    subgraph CeleryApp["Celery 앱 (core/celery.py)"]
        CONF["설정"]
        CONF --> SERIAL["task_serializer: json"]
        CONF --> TZ["timezone: Asia/Seoul"]
        CONF --> UTC["enable_utc: true"]
    end

    subgraph Broker["Redis Broker"]
        B["redis://:password@host:port/1"]
    end

    subgraph Backend["Redis Result Backend"]
        R["redis://:password@host:port/2"]
    end

    subgraph Workers["태스크"]
        W1["worker.minio_upload_task"]
        W2["worker.es_index_task"]
    end

    CeleryApp --> Broker
    CeleryApp --> Backend
    Broker --> Workers
    Workers --> Backend
```

### 4.2 Celery 태스크

#### MinIO 업로드 태스크 (`worker/minio_upload_task.py`)

```mermaid
sequenceDiagram
    participant EP as API Endpoint
    participant CEL as Celery Broker
    participant WRK as Worker
    participant MINIO as MinIO
    participant DB as Database

    EP->>CEL: minio_upload_task.delay(file_data, metadata)
    CEL->>WRK: 태스크 실행
    WRK->>MINIO: 파일 업로드
    MINIO-->>WRK: 성공/실패
    WRK->>DB: 첨부파일 메타 저장
    WRK-->>CEL: 결과 반환
```

#### ES 인덱싱 태스크 (`worker/es_index_task.py`)

```mermaid
sequenceDiagram
    participant EP as API Endpoint
    participant CEL as Celery Broker
    participant WRK as Worker
    participant SE as Search Engine

    EP->>CEL: es_index_task.delay(document_data)
    CEL->>WRK: 태스크 실행
    WRK->>WRK: 문서 → ES 액션 변환
    WRK->>SE: bulk 인덱싱 요청
    SE-->>WRK: 인덱싱 결과
    WRK-->>CEL: 결과 반환
```

### 4.3 Redis DB 분리 전략

```mermaid
graph TB
    REDIS["Redis Server<br/>:6379"]

    REDIS --> DB0["DB 0<br/>일반 캐시 / Stream"]
    REDIS --> DB1["DB 1<br/>Celery Broker<br/>(태스크 큐)"]
    REDIS --> DB2["DB 2<br/>Celery Result Backend<br/>(태스크 결과)"]
```

| Redis DB | 용도 | 사용처 |
|----------|------|--------|
| DB 0 | 일반 캐시, Redis Stream 이벤트 | `RedisManager`, `AsyncRedisManager` |
| DB 1 | Celery 메시지 브로커 | Celery Worker 태스크 큐 |
| DB 2 | Celery 결과 백엔드 | 태스크 실행 결과 저장 |

---

## 5. Redis Stream 이벤트 시스템

### 5.1 스트림 키 네이밍 규칙

```
<environment>:<tenant_id>:<service>:<domain>:<event_type>
```

예시: `production:tenant-001:aicm:document:created`

```mermaid
graph LR
    KEY["스트림 키 구조"]
    KEY --> ENV["환경<br/>(dev/staging/prod)"]
    KEY --> TID["테넌트 ID"]
    KEY --> SVC["서비스명<br/>(aicm)"]
    KEY --> DOM["도메인<br/>(document/category)"]
    KEY --> EVT["이벤트 타입<br/>(created/updated/deleted)"]
```

### 5.2 이벤트 발행/구독 아키텍처

```mermaid
graph TB
    subgraph Publishers["이벤트 발행"]
        PUB_SYNC["RedisManager<br/>(동기 발행)"]
    end

    subgraph Redis["Redis Stream"]
        STREAM["스트림 키"]
    end

    subgraph Subscribers["이벤트 구독"]
        SUB_ASYNC["AsyncRedisManager<br/>(비동기 구독)"]
        HANDLER["등록된 핸들러<br/>(이벤트 처리)"]
    end

    PUB_SYNC -->|XADD| STREAM
    STREAM -->|XREAD| SUB_ASYNC
    SUB_ASYNC -->|dispatch| HANDLER
```

---

## 6. 로깅 및 모니터링

### 6.1 로깅 아키텍처

```mermaid
graph TB
    subgraph App["AICM Service"]
        LOGURU["Loguru Logger"]
        STD["Python logging"]
        INTERCEPT["InterceptHandler<br/>(logging → Loguru)"]

        STD -->|캡처| INTERCEPT
        INTERCEPT --> LOGURU
    end

    subgraph Output["출력"]
        CONSOLE["콘솔 출력<br/>(stdout)"]
        OTEL["OTLP Log Exporter"]
    end

    LOGURU --> CONSOLE
    LOGURU -->|"OTEL_ENDPOINT ≠ localhost"| OTEL

    OTEL --> COLLECTOR["OpenTelemetry<br/>Collector"]
    COLLECTOR --> SIGNOZ["SigNoz / 모니터링"]
```

### 6.2 로깅 모드

```mermaid
flowchart TD
    DEBUG{DEBUG 모드?}
    DEBUG -->|True| LOGURU_DIRECT["Loguru 직접 사용<br/>(상세 로그, 컬러 출력)"]
    DEBUG -->|False| STD_LOGGING["Python 표준 logging<br/>(구조화된 로그)"]

    OTEL_CHECK{OTEL 엔드포인트<br/>설정됨?}
    OTEL_CHECK -->|Yes, ≠ localhost| OTLP["OTLP 익스포터 활성화"]
    OTEL_CHECK -->|No / localhost| LOCAL["로컬 로깅만"]
```

---

## 7. CLI 실행 모드

### 7.1 Typer CLI 구조

```mermaid
graph TB
    CLI["python main.py"]

    CLI -->|"api"| API_CMD["FastAPI 서버 실행"]
    CLI -->|"worker"| WRK_CMD["Celery 워커 실행"]
    CLI -->|"non_cuda"| NC_CMD["CUDA 없이 서버 실행"]
    CLI -->|"run (기본)"| RUN_CMD["API + Worker 동시 실행"]

    API_CMD --> UVICORN["uvicorn main:app<br/>--host --port --reload"]

    WRK_CMD --> CELERY["celery_app.worker_main<br/>--loglevel --concurrency"]

    NC_CMD --> NC_ENV["NON_CUDA_MODE=1"]
    NC_ENV --> UVICORN

    RUN_CMD --> PROC1["subprocess: main.py api"]
    RUN_CMD --> PROC2["subprocess: main.py worker"]
    PROC1 & PROC2 --> SIGNAL["SIGINT/SIGTERM 핸들링"]
```

### 7.2 실행 명령어 정리

| 명령어 | 설명 | 옵션 |
|--------|------|------|
| `python main.py` | 기본 실행 (`run`과 동일) | - |
| `python main.py api` | FastAPI 서버만 | `--host`, `--port`, `--reload` |
| `python main.py worker` | Celery 워커만 | `--loglevel`, `--concurrency` |
| `python main.py non_cuda` | GPU 없이 서버 | - |
| `python main.py run` | API + Worker 동시 | `--host`, `--port`, `--reload`, `--worker-loglevel`, `--worker-concurrency` |

---

## 8. 의존성 관리

### 8.1 의존성 파일 구조

```mermaid
graph TB
    REQ["requirements.txt<br/>(메인 의존성)"]
    REQ_BASE["requirements-base.txt<br/>(CUDA 런타임)"]
    REQ_APP["requirements-app.txt<br/>(CUDA + ML 모델)"]

    REQ_BASE --> CUDA["nvidia-cublas-cu12<br/>nvidia-cuda-nvrtc-cu12<br/>등"]
    REQ_APP --> CUDA
    REQ_APP --> ML["sentence-transformers<br/>torch"]
    REQ --> CORE["FastAPI, SQLAlchemy<br/>Celery, Pydantic<br/>Elasticsearch<br/>LangChain, MinIO"]
```

### 8.2 핵심 의존성 목록

| 카테고리 | 패키지 | 용도 |
|---------|--------|------|
| **웹 프레임워크** | `fastapi`, `uvicorn` | REST API 서버 |
| **CLI** | `typer` | 명령줄 인터페이스 |
| **ORM** | `sqlalchemy`, `psycopg2-binary` | DB 연결 및 ORM |
| **비동기** | `celery` | 비동기 태스크 처리 |
| **캐시/브로커** | `redis` | Redis 연결 |
| **검증** | `pydantic`, `pydantic-settings` | 데이터 검증 및 설정 |
| **스토리지** | `minio` | 오브젝트 스토리지 |
| **검색** | `elasticsearch`, `langchain` | 검색 엔진 연동 |
| **AI/ML** | `sentence-transformers`, `torch` | 임베딩 모델 (선택) |
| **로깅** | `loguru`, `opentelemetry-*` | 구조화 로깅 및 원격 추적 |
| **보안** | `pycryptodome` | AES 암복호화 |
| **HTTP** | `requests`, `httpx` | 외부 API 호출 |

---

## 9. 보안 고려사항

### 9.1 인증 체계

```mermaid
flowchart TD
    subgraph External["외부 인증"]
        TOKEN["X-auth-token<br/>(JWT/세션 토큰)"]
    end

    subgraph Internal["내부 인증"]
        HMAC["X-Internal-Auth<br/>(HMAC-SHA256)"]
        TS["X-Internal-Timestamp"]
    end

    subgraph Encryption["데이터 암호화"]
        AES["AES 암복호화<br/>(cipher_utils)"]
        DB_URL["DB URL 암호화<br/>(is_cipher=true 시)"]
    end

    TOKEN --> TENANT["테넌트 식별<br/>DB 세션 생성"]
    HMAC --> INTERNAL["서비스 간 통신"]
    TS --> INTERNAL
    AES --> DB_URL
```

### 9.2 보안 요소

| 영역 | 메커니즘 | 설명 |
|------|---------|------|
| **API 인증** | `X-auth-token` 헤더 | 모든 엔드포인트에서 필수 |
| **내부 통신** | HMAC-SHA256 + 타임스탬프 | 서비스 간 내부 API 호출 |
| **데이터 암호화** | AES (`cipher_utils`) | DB URL 등 민감 정보 암호화 |
| **CORS** | 미들웨어 설정 | 현재 `*` (운영 시 제한 필요) |
| **데이터 격리** | Database-per-Tenant | 테넌트 간 완전한 데이터 격리 |

---

## 10. 운영 체크리스트

### 배포 전 확인사항

```mermaid
flowchart TD
    A["배포 전 체크리스트"] --> B["환경변수 설정 확인"]
    A --> C["DB 마이그레이션 확인"]
    A --> D["Redis 연결 확인"]
    A --> E["외부 서비스 연결 확인"]
    A --> F["CORS 설정 제한"]
    A --> G["로그 레벨 조정"]

    B --> B1["CIPHER_KEY 변경"]
    B --> B2["INTERNAL_AUTH_KEY 변경"]
    B --> B3["MINIO 자격증명 설정"]

    E --> E1["Tenant Management Service"]
    E --> E2["Search Engine Service"]
    E --> E3["NLP Engine Service"]

    F --> F1["allow_origins를 특정 도메인으로 제한"]
    G --> G1["DEBUG=False 확인"]
    G --> G2["Worker loglevel 조정"]
```
