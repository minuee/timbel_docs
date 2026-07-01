# AICM Service 구조 분석 — 처음 보는 사람을 위한 안내서

> 이 문서는 **이 소스코드를 처음 열어본 사람의 시점**으로 프로젝트를 따라가며 정리한 글입니다.
> "이게 뭐 하는 프로젝트지?" → "파일이 왜 이렇게 나뉘어 있지?" → "요청 하나가 들어오면 무슨 일이 벌어지지?"
> 순서로 읽으면 됩니다. 이미 잘 정리된 상세 문서는 `docs/architecture/` 에 있으니, 이 글은 **전체 그림을 빠르게 잡는 지도** 역할입니다.

---

## 0. 3줄 요약 (제일 먼저)

1. **이 서비스는 "AI 문서 관리 + 검색 시스템"의 백엔드**입니다. 문서를 저장/버전관리/승인하고, 사용자가 질문하면 AI가 관련 문서를 찾아 답합니다.
2. **혼자 다 하지 않습니다.** 진짜 무거운 일(벡터 검색, 임베딩, AI 답변 생성)은 **외부 서비스에게 위임**하고, 이 서비스는 그 사이를 **조율(orchestration)** 하는 "지휘자"에 가깝습니다.
3. 그래서 프로젝트 이름이 암시하듯, 핵심 키워드는 **"통합(integration)"** — 여러 외부 시스템을 엮어서 하나의 문서 서비스처럼 보이게 만드는 게 이 코드의 본질입니다.

---

## 1. 첫인상 — 루트 디렉토리를 열면 보이는 것

처음 폴더를 열면 이런 것들이 보입니다. 초심자가 어디부터 봐야 하는지 순서대로 표시했습니다.

| 파일/폴더 | 정체 | 먼저 볼 순서 |
|-----------|------|:---:|
| `main.py` | **진입점.** 여기서 서버가 뜬다. 제일 먼저 읽을 파일 | ① |
| `core/config.py` | **설정.** 어떤 외부 시스템에 연결되는지 여기 다 적혀 있음 | ② |
| `api/` | **HTTP 요청을 받는 문(門).** URL 라우트가 여기 | ③ |
| `services/` | **비즈니스 로직.** "문서 저장하면 무슨 일이 일어나나" | ④ |
| `clients/` | **외부 서비스 연결 코드.** 통합의 핵심 | ⑤ |
| `db/` | **데이터베이스 계층.** 테이블/쿼리 | ⑥ |
| `managers/` | DB 연결·Redis·로거 같은 인프라 싱글톤 | 참고 |
| `worker/` | Celery 비동기 작업 (⚠️ 현재는 거의 안 씀 — 후술) | 참고 |
| `utils/` | 암복호화·HTML변환 등 잡다한 도우미 | 참고 |
| `model_json/` | 테이블 스키마 **설계 문서**(JSON). 실제 코드는 `db/models/` | 참고 |
| `sql/`, `scripts/migrations/` | DB 인덱스/마이그레이션 SQL | 참고 |
| `Dockerfile`, `docker-compose.yml`, `deploy.sh` | 배포 | 참고 |
| `docs/`, `docs2/` | 문서 (지금 이 글이 있는 곳) | 참고 |

**기술 스택 한눈에:**
FastAPI(웹) + SQLAlchemy(ORM) + PostgreSQL(DB) + Redis(캐시/브로커) + Celery(비동기, 현재 비활성) + Typer(CLI) + Docker. Python 3.11.

---

## 2. main.py — 서버는 어떻게 뜨는가

`main.py` 하나만 읽어도 이 앱의 실행 구조가 다 보입니다. 핵심은 **Typer CLI로 4가지 실행 모드**를 제공한다는 점입니다.

```
python main.py            # (기본) run 과 동일 → API + Worker 동시 실행
python main.py api        # FastAPI 서버만 (uvicorn)
python main.py worker     # Celery 워커만
python main.py non_cuda   # GPU 없이 서버 실행
python main.py run        # API 프로세스 + Worker 프로세스를 subprocess로 함께 띄움
```

`create_application()` 함수가 FastAPI 앱을 만들고, 라우터들을 붙이고(`api_router`, `llm_manager_router`, `health_router`), 예외 핸들러를 등록합니다.

> 💡 **초심자 포인트:** `api/__init__.py` 를 보면 `setup_routers()` 를 `try/except ModuleNotFoundError` 로 감쌉니다.
> 이유는 주석에 있듯 — 로컬/테스트 환경에서 langchain 같은 무거운 의존성이 없어도 **최소한 health 엔드포인트는 뜨게** 하려는 방어 코드입니다. "왜 이렇게 방어적이지?"의 답은 "여러 환경(로컬/테스트/도커)에서 다 돌아가야 하기 때문"입니다.

---

## 3. 이 서비스가 연결되는 외부 시스템 (통합의 지도)

이 프로젝트의 이름이 `integration.md` 인 이유가 여기 있습니다. **이 서비스는 최소 7개의 외부 시스템과 대화합니다.** `clients/` 폴더의 파일 하나하나가 곧 "말을 거는 상대"입니다.

```
                          ┌─────────────────────────────┐
   클라이언트(웹/앱) ─────▶│      AICM Service (이 코드)   │
                          │        FastAPI 지휘자         │
                          └──────────────┬──────────────┘
                                         │
        ┌────────────┬───────────┬───────┼────────┬───────────┬──────────┐
        ▼            ▼           ▼       ▼        ▼           ▼          ▼
   User Service  Tenant Svc   RAG Svc   NLP Eng  LLM Manager  MinIO   PostgreSQL
   (누구인가)    (어느 회사?)  (검색핵심) (한글분석) (AI답변)   (파일)   (메타DB)
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
              Qdrant(벡터DB)          Elasticsearch(키워드)
              ※ RAG Service 내부에서 관리
```

각 클라이언트가 하는 일 (`clients/` 폴더):

| 파일 | 상대 | 무엇을 위해 | 인증 방식 |
|------|------|-------------|-----------|
| `user_service_client.py` | User Service | "이 토큰의 주인은 누구? 권한은?" | `X-auth-token` 헤더 |
| `tenants_client.py` | Tenant Mgmt Service | "이 회사(테넌트)의 DB·MinIO·ES 주소는?" | `X-auth-token` / 내부배치는 HMAC-SHA256 |
| `rag_service_client.py` | **RAG Service (KMS)** | **문서 업로드·인덱싱·하이브리드 검색·카테고리·동의어** — 가장 중요 | `X-Tenant-Id`(내부망) / `X-API-Key`(외부) / 선택적 admin JWT |
| `nlp_engine_client.py` | NLP Engine | 한글 형태소 분석 (검색 정확도↑) | `X-auth-token` |
| `llm_client.py` | LLM Manager | 검색된 문서 + 질문 → **AI 답변 생성** | `Authorization: Bearer` |
| `minio_client.py` | MinIO (S3 호환) | 원본 파일(PDF/Word) 저장·다운로드 | Access/Secret Key |
| `search_engine_client.py` | Elasticsearch | 직접 풀텍스트 검색 (레거시/옵션) | `X-auth-token` |

> 💡 **초심자 포인트 — "RAG"가 뭔지 모른다면:**
> RAG = **R**etrieval(검색) **A**ugmented(보강) **G**eneration(생성). 즉 "AI에게 그냥 물어보지 말고, **먼저 관련 문서를 찾아서(Retrieval)** 그걸 **근거로 주고(Augmented)** 답을 쓰게 하는(Generation)" 방식입니다. AI가 지어내는(환각) 걸 막으려는 기법이죠.
> - **Retrieval** = `RagServiceClient.search()` (Qdrant 벡터 + Elasticsearch 키워드 하이브리드)
> - **Generation** = `LLMClient.request_RAG()` (검색 결과를 근거로 답변 작성)

---

## 4. 4계층 아키텍처 — 코드가 왜 이렇게 나뉘어 있나

이 프로젝트는 전형적인 **4계층(Layered) 구조**입니다. 요청이 위에서 아래로 흐릅니다.

```
┌─────────────────────────────────────────────────────────┐
│ ① Presentation  — api/endpoints/, api/schemas/          │  HTTP 받고, 입력 검증
├─────────────────────────────────────────────────────────┤
│ ② Business      — services/                             │  "무슨 일을 할지" 조율
├─────────────────────────────────────────────────────────┤
│ ③ Data Access   — db/services/, db/repositories/        │  DB CRUD, 트랜잭션
├─────────────────────────────────────────────────────────┤
│ ④ Infrastructure— managers/, clients/, worker/          │  DB연결·Redis·외부API
└─────────────────────────────────────────────────────────┘
```

**초심자가 자주 헷갈리는 것 — `services/` 가 두 군데 있다!**

| 위치 | 이름 | 역할 | 예시 |
|------|------|------|------|
| `services/` (루트) | **애플리케이션 서비스** | 외부 시스템까지 아우르는 큰 그림 조율 | `document_service`, `rag_search_service` |
| `db/services/` | **DB 서비스** | DB 트랜잭션 단위의 비즈니스 규칙 | `DB_DocumentService`, `document_approvals_service` |

그리고 `db/services/` 아래에 또 `db/repositories/` 가 있습니다:
- **Repository** = 순수 SQL 실행 (create/read/update/delete 쿼리)
- **DB Service** = Repository 여러 개를 묶어 트랜잭션·승인·이력 같은 **규칙**을 적용

> 정리: `services/document_service.py`(큰 조율) → `db/services/document/document_service.py`(DB 트랜잭션) → `db/repositories/document/document_repository.py`(SQL) → `db/models/`(테이블) 순으로 내려갑니다.

---

## 5. 데이터 모델 — 무엇을 저장하는가

핵심 도메인은 **문서(Document)** 이고, 다음과 같은 계층으로 조직됩니다. (`db/models/` 참고)

```
📦 Workspace (워크스페이스)          — 테넌트별 작업 공간
├── 📁 Store (저장소)               — 문서를 묶는 그룹, RAG Repository와 1:1
│    ├── StorePermission            — 저장소 접근 권한
│    └── StorePermissionGroup
│
├── 📄 Document (문서 메타)          — 문서 "한 건"
│    ├── DocumentContent (내용/버전) — ⭐ 한 문서가 여러 버전을 가짐
│    │    ├── DocumentSection        — 내용을 섹션 단위로 쪼갠 것
│    │    ├── DocumentIndex          — 목차/색인
│    │    └── DocumentHistory        — 변경 이력
│    ├── DocumentComment             — 댓글
│    ├── DocumentApproval            — 승인/결재
│    └── DocumentAttachment          — 첨부파일(MinIO 경로)
│
├── 🏷️ Category (카테고리)          — 계층형 분류 (parent_id, root_id 자기참조)
│    ├── CategoryPermission
│    └── CategoryPermissionGroup
│
└── 📋 Template (템플릿)             — 문서 생성용 틀
```

**꼭 기억할 개념 — "문서 1건 = 여러 버전":**
- `aicm_documents` (문서 메타) 는 `current_contents_id`(현재 편집본)와 `effective_contents_id`(현재 효력 있는 승인본)를 가리킵니다.
- 실제 내용은 `aicm_documents_contents` 에 **버전별로** 쌓입니다.
- 승인·효력일(`effective_date`)·만료일(`expire_date`)로 "언제부터 언제까지 이 버전이 검색에 노출되는가"를 제어합니다.

- **DB**: PostgreSQL (`aicm` 스키마)
- **ORM**: SQLAlchemy (동기식)
- **`model_json/`**: 실제 코드가 아니라 테이블 **설계 참고 문서**. 진짜 모델은 `db/models/*.py`.
- **`scripts/migrations/`**: DB 스키마 변경 이력(001~005번 SQL). RAG 전환하면서 `rag_doc_id`, `store` 테이블, `rag_status` 등이 추가된 흔적이 보입니다.

---

## 6. 멀티테넌트 — "한 서버가 여러 회사를 동시에"

이 서비스의 중요한 특징: **Database-per-Tenant** (회사마다 DB가 따로). 이게 코드 곳곳의 `X-auth-token`, `token`, `workspace_id` 파라미터의 이유입니다.

```
HTTP 요청 (X-auth-token 헤더)
   │
   ▼
TenantClient.get_tenant_db_url(token)   ← "이 토큰은 어느 회사?"
   │
   ▼
DatabaseManager.get_db_by_url(url)      ← 그 회사 DB 엔진 (TTL 캐싱, 30분)
   │
   ▼
요청마다 독립 세션 → 회사 A와 회사 B 데이터는 절대 안 섞임
```

- `managers/database_manager.py` 가 테넌트별 SQLAlchemy Engine을 캐싱합니다(매번 새로 연결하면 느리니까).
- 그래서 거의 모든 서비스 메서드가 `token` 또는 `db`(세션)를 인자로 받습니다. "왜 이 함수는 토큰을 받지?" → "어느 테넌트 DB를 쓸지 정하려고".

---

## 7. 핵심 흐름 ① — 문서를 저장하면 무슨 일이?

`POST /docs/add_doc_with_files` 요청을 따라가 봅시다.

```
1. API 엔드포인트가 X-auth-token으로 테넌트 DB 세션 확보
2. services/document_service.py 가 조율 시작
   ├─ DB에 문서 메타 저장 (aicm_documents)
   ├─ DB에 내용 저장 (aicm_documents_contents, version v1)
   ├─ 내용을 섹션으로 분할 저장 (aicm_documents_sections)
   ├─ 첨부파일 있으면 → MinIO 업로드 (동기)
   └─ RAG Service에 인덱싱 요청 (RagServiceClient)
        · 첨부파일 문서: MinIO에서 받아 RAG로 업로드
        · 직접입력 문서: outline → Markdown 변환 후 RAG로 업로드
        · 결과로 rag_doc_id 저장, rag_status="processing"
3. 201 Created 응답
```

> 💡 **초심자 포인트 — "RAG 실패해도 DB는 커밋":**
> 만약 RAG 인덱싱이 실패하면? DB 저장은 그대로 두고 `rag_status="failed"` 로 표시합니다. 나중에 재시도할 수 있고, "검색엔진 문제로 문서 저장 자체가 통째로 실패"하는 걸 막습니다. 반대로 KMS(RAG)에만 있고 AICM DB엔 없는 "고아 문서"도 자동으로 입양(adopt)하는 방어 로직이 있습니다. (최근 커밋 `0b753ac` 참고)

---

## 8. 핵심 흐름 ② — 검색하면 무슨 일이?

`POST /search/...` 요청 흐름 (`services/rag_search_service.py`, `rag_integrated_search_service.py`):

```
사용자: "연차는 며칠이야?"
   │
   ▼
RagServiceClient.search()  ← 하이브리드 검색
   ├─ Qdrant: 질문을 벡터로 바꿔 "의미가 비슷한" 문단 찾기
   └─ Elasticsearch: "연차" 키워드 매칭도 병렬로
   │
   ▼ (RAG가 블록 단위 결과 반환)
aicm_doc_id 기준으로 그룹핑
   │
   ▼
DB 조회로 문서 상세 보강 (제목·요약·키워드)
   │
   ▼
PermissionEnforcer로 권한 필터링
   (관리자=전부 / 에이전트=허가된 카테고리만)
   │
   ▼
검색 0건이면 → DB fallback (제목·요약 텍스트 검색)
   │
   ▼
{ total, retrieved_docs / categories } 응답
```

> ⚠️ **정정 — "AI 답변" 경로는 3개이고, 실제 문장 생성은 이 레포가 아니라 RAG Service(KMS) 안에서 일어납니다.** (아래 §8.1 참고)

### 8.1 "AI 답변" 경로 3가지 — LLM은 어디서 도는가 (실사용 디버깅용)

이 부분이 실무에서 가장 헷갈리는 지점입니다. `grep` 으로 실제 호출부를 추적한 결과, "AI가 답을 만든다"는 표면이 **3개**로 나뉘고, **셋 다 최종 텍스트 생성은 RAG Service(KMS/rag-parser) 내부에서** 일어납니다. 이 레포(aicm-service)는 중계자/입력 준비자입니다.

| # | 진입 엔드포인트 | 이 레포의 코드 | 실제 LLM 생성 위치 | 이 레포가 제어하는 것 |
|---|-----------------|----------------|--------------------|------------------------|
| **①** | `POST /search/rag_assist` (SSE) | `search_endpoints.py` → `RagServiceClient.assist_stream()` | **KMS** `POST /api/v1/rag/assist-stream` (intent→search→distill→generate 전체) | query, category_ids, `enable_distill`, conversation_history, `enable_intent_gate=False`(하드코딩) — **프롬프트/모델/온도 제어 불가(순수 패스스루)** |
| **②** | `POST /api/llm-manager/v1/llm/aicm/ai-answer/stream` (SSE) 및 `ai-writing/stream`, `document-outline-optimize` | `llm_manager_endpoint.py` → `_call_rag_generate()` | **KMS** `POST /api/v1/rag/generate` | question, context(=`contents`를 `\n\n`으로 조인), **`max_answer_tokens=800`**, **`temperature=0.3`** |
| **③** | (레거시) ES 검색의 `with_llm=True` | `es_service.py` → `LLMClient.request_RAG()` | **별도 LLM Manager 서비스**(`LLM_MANAGER_ENDPOINT`) | question, retrieved_contents. **현재 실사용 경로 아님(레거시)** |

> 💡 **핵심:** "LLM이 제대로 답을 못한다"의 원인은 보통 두 갈래입니다.
> - **(A) 재료(검색 결과)가 나쁨** → LLM은 준 문서만 보고 답하므로 검색이 엉뚱하면 답도 엉뚱. **이 레포에서 제어 가능** (top_k·rerank·llm_rewrite·category_ids·threshold·intent_gate·distill).
> - **(B) 생성 자체(프롬프트/모델/토큰상한)** → **이 레포가 아니라 RAG Service(KMS) 저장소**에서 고쳐야 함. 단, ②경로의 `max_answer_tokens=800`(답변 잘림)·`temperature=0.3` 은 `llm_manager_endpoint.py`에서 바꿀 수 있음.
>
> 즉 ①경로(`rag_assist`)를 쓰면 이 레포에서 답변 품질을 직접 손댈 수 있는 건 **"검색 입력"뿐**이고, 문장 생성 튜닝은 KMS 몫입니다.

### 8.2 `rag_assist` 심층 분석 — workspace_id → repository_id 매핑과 "엉뚱한 답" 원인

> 실사용 경로가 ①(`rag_assist`)이고 증상이 **"엉뚱한/관련 없는 답"** 일 때의 분석 기록입니다.
> (호출 주체 = `asst-service`. 아래 4개 필드만 보내고 나머지 검색 손잡이는 전부 AICM이 결정합니다.)

**asst-service가 AICM으로 보내는 것 (딱 4개):**
```jsonc
POST {AICM_HOST}/api/aicm/v1/search/rag_assist   // 헤더: X-auth-token 필수, Accept: text/event-stream
{
  "workspace_id": "<AICM 워크스페이스 UUID>",   // ← 매핑의 입력
  "query": "<고객 현재 발화 원문>",
  "enable_distill": false,                       // 항상 false 고정
  "conversation_history": [ {"role":"user"|"assistant","content":"..."} ]
}
```
→ `repository_id`, `enable_intent_gate`, `category_ids` 는 **asst-service가 보내지 않고**, AICM 내부에서 정해 KMS로 전달됩니다. 특히 `category_ids`가 없으므로 **분류 스코프 = None = 워크스페이스 전체 검색**입니다(분류 오필터는 원인에서 제외).

#### 매핑이 도는 전체 경로

```
asst-service ──POST /search/rag_assist { workspace_id, query, enable_distill:false, conversation_history }
              (X-auth-token)
   │
   ▼  api/endpoints/documents/search_endpoints.py  rag_assist()
① db_manager.session_optional_token_for_workspace(workspace_id, token)
     token 있음 → TenantClient.get_tenant_db_url(token)
     = "토큰의 테넌트" AICM DB 세션 확보
     ⚠️ DB 선택 기준은 workspace_id가 아니라 '토큰'. 토큰 테넌트 ≠ workspace 테넌트면 어긋남.
   │
   ▼
② WorkspaceService(db).check_workspace(workspace_id)
     이 DB(ce.workspaces)에 workspace 없으면 409 (토큰≠workspace 테넌트면 보통 여기서 걸림)
   │
   ▼  api/dependencies/rag_dependencies.py  get_rag_client_for_workspace()
③ WorkspaceRagConfigService.get_rag_config(workspace_id)
     = SELECT * FROM aicm.workspace_rag_config WHERE workspace_id = ?   (workspace_id가 PK, 단건 조회)
       └ row: { tenant_id, repository_id, api_key(암호화) }
     row 없으면 → lazy init (services/rag_init_service.py):
        · RAG_DEFAULT_REPOSITORY_ID 설정 시 → 그 repo_id를 '모든' workspace에 공용 저장  ⚠️⚠️
        · 아니면 → KMS create_repository(name=workspace_id) → 새 repo_id 발급 후 저장
   │
   ▼
④ build_rag_client(tenant_id, api_key) + repository_id 반환
     (tenant_id는 _normalize_rag_tenant_id로 company_<uuid> → <uuid> 정규화)
   │
   ▼
⑤ rag_client.assist_stream(repo_id, query, enable_distill=false, conversation_history, category_ids=None)
     → KMS POST /api/v1/rag/assist-stream { query, repository_id: repo_id, enable_intent_gate:False, ... }
     → KMS가 그 repo 코퍼스에서 검색 + 생성
```

**핵심 사실:** `workspace_id`는 `aicm.workspace_rag_config` 테이블의 **기본키(PK)** 이고, 그 행에 저장된 `repository_id`로 매핑됩니다. 그리고 **이 매핑은 최초 init 때 한 번 INSERT되고 이후 어디서도 UPDATE되지 않습니다**(코드 전수 확인 — 쓰기는 init 시 `save_rag_config` 뿐, 갱신 경로 없음). 즉 **write-once**입니다.

> 관련 모델/서비스: `db/models/workspace_rag_config.py`(PK=workspace_id, cols: tenant_id·repository_id·api_key),
> `db/services/workspace_rag_config_service.py`, `db/repositories/workspace_rag_config_repository.py`,
> `services/rag_init_service.py`(프로비저닝), `api/dependencies/rag_dependencies.py`(조회+lazy init).

#### "엉뚱한 답" 원인 순위 (코드 근거)

| 순위 | 원인 | 왜 엉뚱한 답이 되나 | 확인 지점 |
|:--:|------|---------------------|-----------|
| **1** | **`RAG_DEFAULT_REPOSITORY_ID` 설정됨** | `RagInitService`가 **모든 workspace에 동일 repo_id 저장**(rag_init_service.py:28-38) → workspace_id 무의미, **전 회사가 한 저장소 공유 검색** → 남의 문서 섞여 엉뚱 | 배포 env `RAG_DEFAULT_REPOSITORY_ID` 값 유무 |
| **2** | **저장된 매핑이 낡음/틀림** (write-once, 갱신 안 됨) | KMS repo 재생성으로 UUID 바뀌었는데 AICM은 옛 repo_id 보유 → 죽은/빈/옛 코퍼스. 또는 **최초 lazy init이 엉뚱한 토큰**으로 돼 잘못된 tenant/repo가 영구 고정 | `aicm.workspace_rag_config` 행을 KMS repo와 대조 |
| **3** | 토큰 테넌트 ≠ workspace 테넌트 | 다른 테넌트 DB의 config를 읽음 (단, 보통 ②에서 409) | `[rag_assist]` 로그의 `tenant_id`/`repo_id` |
| **4** | `enable_intent_gate=False` (하드코딩, 최근 커밋 10396ed) | 근거 약한 질문도 게이트 없이 생성 → 환각/엉뚱 | `clients/rag_service_client.py` `assist_stream` |
| **5** | KMS repo 코퍼스 자체 오염 | (KMS 저장소 문제 — 이 레포 밖) | KMS 측 |

#### 서버에서 원인 특정하는 최소 확인 2가지 (테스트 단계에서 수행)

**(1) env 확인 — 1순위 즉시 판별**
`RAG_DEFAULT_REPOSITORY_ID`가 채워져 있으면 → workspace_id 매핑이 무의미하고 모두가 그 repo 하나를 검색하는 것. 원인 거의 확정.

**(2) 매핑 테이블 조회 — 2순위 판별 (해당 테넌트 DB에서)**
```sql
-- 문제의 workspace가 어느 repo로 매핑돼 있나
SELECT workspace_id, tenant_id, repository_id, created_at
FROM aicm.workspace_rag_config
WHERE workspace_id = '<문제의 workspace_id>';

-- 여러 workspace가 한 repo를 공유하는지 (1순위 증상 확인)
SELECT repository_id, count(*) AS ws_cnt
FROM aicm.workspace_rag_config
GROUP BY repository_id ORDER BY ws_cnt DESC;
```
두 번째 쿼리에서 한 `repository_id`에 여러 workspace가 몰리면 → 1순위(공용 repo) 확정. 매핑된 `repository_id`가 KMS의 올바른 저장소와 일치하는지도 대조.

> **디버깅 로그:** `rag_assist` 호출 시 `search_endpoints.py`가 다음을 남깁니다 —
> `[rag_assist] workspace=... repo_id=... tenant_id=... authed=... query=... category_ids=...`
> 여기서 `repo_id`/`tenant_id`가 올바른 저장소를 가리키는지, `query`가 원문 그대로인지 먼저 확인.

> **다음 단계(미착수):** ① `sources` SSE 이벤트를 캡처해 "검색된 근거문서 vs 답변"을 대조하면
> 원인이 **검색(retrieval)** 인지 **생성(generation)** 인지 즉시 갈립니다. (진단 스크립트는 준비돼 있으나 로컬 미구동으로 테스트는 홀딩.)

### 8.3 KMS(rag-parser) 소스 실측 — `assist-stream` 파이프라인과 `cited_refs`의 정체

> **AICM은 이 부분을 구현하지 않습니다.** 검색·생성·인용 판정은 전부 KMS(rag-parser) 저장소에서 일어나고, AICM은 §8.1처럼 바이트 패스스루만 합니다.
> 아래는 KMS 소스(`rag-parser-engine-develop` = **Locus-KMS**, KMS-only standalone)를 직접 열어 확인한 실측 기록입니다.
> **핵심 파일:** `src/api/routers/rag_assist.py` (912줄, assist-stream 파이프라인 전체가 이 한 파일).

#### assist-stream이 내려주는 SSE 이벤트 순서 (KMS가 생성)

```
intent → sources → (distilled) → token × N → done
```

| 이벤트 | 내용 | 생성 근거 (KMS 코드) |
|--------|------|----------------------|
| `intent` | 검색 의도 판정 (intent gate) | AICM이 `enable_intent_gate=False`로 보내면 게이트 우회 |
| `sources` | 검색된 근거문서 목록 + `confidence` | `hits`를 랭크순 번호매김. `confidence = hits[0].score`(top 청크 점수) |
| `distilled` | 정제 요약(옵션) | AICM이 `enable_distill`로 on/off (asst-service는 항상 false) |
| `token` × N | LLM 답변 조각 스트리밍 | `full_answer`에 누적 |
| `done` | 종료 메타 + **`cited_refs`** + token_usage + 단계별 timing | 아래 참조 |

#### `cited_refs`는 무슨 근거로 채워지나 — **답변 텍스트의 `[숫자]`를 정규식으로 회수**

RAG/LLM이 "이 문서를 인용했다"를 **별도 필드로 주는 게 아니라**, LLM이 생성한 답변 문장 속 `[1]`, `[2,3]` 같은 마커를 **텍스트 파싱**해서 만듭니다. 전체 사슬:

**① 검색결과에 1-based 번호 매김** (`rag_assist.py:486, 511-512`)
```python
for rank, h in enumerate(hits, 1):            # 1번부터
    sources_payload.append({"ref_num": rank, ...})   # [1],[2],[3]… = 검색 랭크
```

**② system_prompt가 LLM에게 인용 지시** (`rag_assist.py:620-623`)
```
"참고자료에 [1], [2] 등의 번호가 부여되어 있습니다."
"답변 내에서 해당 내용의 근거를 인라인 인용 마커 [1], [2] 등으로 표시하세요."
```

**③ LLM이 `[n]` 마커를 섞어 답변 생성** → `full_answer`

**④ done 직전, 답변에서 `[n]` 회수** (`rag_assist.py:846-851`)
```python
_cited = sorted({ int(d)
    for m in _re.findall(r"(?<![A-Za-z])\[([\d,\s]+)\]", full_answer)
    for d in m.split(",") if d.strip().isdigit() })
```

→ **`cited_refs` = "LLM이 최종 답변에 실제로 적어넣은 인용번호"** 이고, 그 번호는 `sources`의 `ref_num`(검색 랭크)을 가리킴.

#### 이 구현의 취약점 3가지 (엉뚱한 답 디버깅과 직결)

1. **전적으로 LLM 순응에 의존** — LLM이 `[n]`을 안 쓰면, 실제로 그 문서로 답했어도 `cited_refs`는 **빈 배열**. (근거 부재가 아니라 표기 누락)
2. **범위 검증 없음** — 정규식이 답변 속 **모든** `[숫자]`를 인용으로 간주. `len(sources)`와 대조 안 함. 그래서 `[2024]년`·`제[3]항`·`[500]만원` 같은 본문 표현이 **가짜 인용번호**로 잡혀 유령 ref가 섞일 수 있음.
3. **인용번호 ≠ 관련성 보증** — `cited_refs`가 `[1]`을 가리켜도 그 `[1]` 소스 자체가 엉뚱하면(=검색 실패) 답도 엉뚱. 결국 **`sources`가 맞는지부터** 봐야 함.

#### "엉뚱한 답"일 때 판별 순서 (확정)

```
sources 이벤트의 문서가 질문과 맞나?
├─ 아니오 → 검색(retrieval) 문제 → AICM의 repository_id 매핑(§8.2) / KMS src/search/ 코퍼스
└─ 예     → sources는 맞는데 답이 근거를 벗어나거나 cited_refs가 빔
             → LLM grounding/인용 순응 문제 → KMS system_prompt·모델 튜닝 (rag_assist.py:620~)
```

#### 확인된 KMS 파이프라인 구성 (앞선 추측이 실제로 구현돼 있음)

- **intent gate** — 의도 판정(AICM이 껐음), **distill** — 정제요약(`distilled.selected_refs` 비면 raw context로 폴백해 "정보 없음" 오도 방지), **query 리라이팅(reformulate)** — 멀티턴 대명사/생략 복원(`rewritten_query`), **confidence** = top hit score.
- 검색 로직: `src/search/`, 생성/프롬프트/cited_refs: `src/api/routers/rag_assist.py`.
- 이 저장소는 **Locus-KMS**(KMS-only standalone). 통합 본체(AICM-APIs `KMS-Plus`)와 별도 repo·별도 배포. 인증 기본값 `LUCAS_AUTH_DISABLED=true`, 기본 tenant `00000000-...-0001`.

> **요약:** `cited_refs` 튜닝/버그(유령 ref, 빈 배열)나 "엉뚱한 답의 생성 측 원인"은 **AICM이 아니라 KMS `rag_assist.py`에서** 손봐야 합니다. AICM에서 손댈 수 있는 건 검색 입력(§8.1~8.2)뿐입니다.

---

## 9. 권한 제어 — PermissionEnforcer

`services/permission_enforcer.py` 가 "누가 무엇을 볼/고칠 수 있나"를 판정합니다. 검색·조회·편집 곳곳에서 호출됩니다.

```
관리자(admin) ──▶ viewable_category_ids = None  (= 전부 허용)
에이전트(agent) ─▶ 권한그룹에 할당된 카테고리 목록만 허용
```

| 동작 | 규칙 |
|------|------|
| 조회 | 관리자 OK / 에이전트는 권한 있는 카테고리만 |
| 편집 | 현재+신규 카테고리 **둘 다** 권한 있어야 |
| 승인 | 관리자만 |
| 검색 | 결과를 권한으로 다시 필터 (권한 없는 문서는 빠짐) |

카테고리 미지정 문서는 "조회는 허용, 편집은 불허" 로 처리됩니다.

---

## 10. ⚠️ 함정 주의 — Celery 워커는 사실상 껍데기

처음 보면 `worker/es_index_task.py`, `worker/minio_upload_task.py` 가 있어서 "아, Celery로 비동기 인덱싱하는구나" 생각하기 쉽습니다. **하지만 이 태스크들은 현재 `noop`(아무 일도 안 함) 상태입니다.**

```python
# worker/es_index_task.py (요약)
@celery_app.task
def es_index_task(...):
    return {"status": "noop", "reason": "replaced by RAG Service"}
```

**왜?** 과거엔 Celery가 Elasticsearch 인덱싱과 MinIO 업로드를 비동기로 했지만, **RAG Service로 전환**하면서 그 일들을 RAG Service가 (API 요청 안에서 동기로) 대신하게 됐기 때문입니다.

그래서 현재 "비동기"는 두 가지만 남았습니다:
- **FastAPI BackgroundTasks** (`services/background_tasks.py`) — 조회수 증가, 이력 기록 같은 **가벼운 부수효과**. 실패해도 메인 응답엔 영향 없음.
- **Redis Stream** — 서비스 간 이벤트 발행/구독 (`managers/redis_manager.py`, `async_redis_manager.py`).

> 💡 이 부분이 **문서와 코드의 드리프트(drift)** 가 살짝 있는 지점입니다. `docs/architecture/ARCHITECTURE.md` 는 "worker 태스크 폐기"라고 서술하지만, 파일 자체는 아직 `noop` 형태로 남아 있습니다. 새로 코드를 볼 때 헷갈리지 마세요 — **인덱싱/업로드는 이제 동기 + RAG Service** 입니다.

---

## 11. 설정 — core/config.py 로 모든 연결이 결정된다

`core/config.py` 의 `Settings`(pydantic-settings)가 환경변수/`.env`/기본값 순으로 설정을 읽습니다. **"이 서버가 어디에 연결되는가"는 전부 여기 있습니다.**

| 카테고리 | 주요 설정 |
|----------|-----------|
| 서버 | `HOST=0.0.0.0`, `PORT=32012` |
| 외부 서비스 | `TENANT_MANAGEMENT_SERVICE`, `USER_SERVICE`, `NLP_ENGINE_ENDPOINT`, `LLM_MANAGER_ENDPOINT` |
| **RAG** | `RAG_SERVICE_URL`, `RAG_AUTH_MODE`(tenant_id/api_key), `RAG_DEFAULT_REPOSITORY_ID`, `RAG_JWT_SECRET` |
| Redis | `REDIS_HOST/PORT/DB`, `CELERY_BROKER_DB=1`, `CELERY_RESULT_BACKEND_DB=2` |
| 보안 | `INTERNAL_AUTH_KEY`(내부 HMAC), `CIPHER_KEY`(AES), `is_cipher` |
| 임베딩 | `EMBEDDING_MODEL_PATH="jhgan/ko-sbert-nli"` (한국어 모델) |

`docker-compose.yml` 에는 MinIO 엔드포인트·자격증명, 테넌트 서비스 주소 등이 환경변수로 주입되는 예시가 있습니다.

---

## 12. 처음 온 사람을 위한 추천 학습 경로

이 순서로 파일을 열어보면 가장 빠르게 이해됩니다:

1. **`main.py`** — 서버가 어떻게 뜨는지 (5분)
2. **`core/config.py`** — 어떤 외부 시스템에 연결되는지 (5분)
3. **`api/__init__.py`** — 어떤 URL 라우터들이 붙는지 전체 목록 (5분)
4. **`api/endpoints/documents/documents_endpoint.py`** — 대표 CRUD 엔드포인트 하나 (10분)
5. **`services/document_service.py`** — 문서 저장 로직이 외부 시스템을 어떻게 조율하는지 (15분)
6. **`clients/rag_service_client.py`** — 통합의 심장, RAG 연동 (15분)
7. **`services/rag_search_service.py`** + **`permission_enforcer.py`** — 검색과 권한 (15분)
8. **`db/services/document/` ↔ `db/repositories/document/`** — DB 계층 대조 (10분)

그리고 더 깊이 보려면 이미 잘 정리된 **`docs/architecture/`** 문서 4종(`ARCHITECTURE.md`, `api-layer.md`, `service-layer.md`, `data-model.md`, `infrastructure.md`)을 참고하세요.

---

## 13. 한 문장 결론

> **AICM Service는 "직접 검색 엔진이 되려 하지 않고", PostgreSQL(메타·권한)과 RAG Service(벡터·키워드 검색)·LLM(답변)·MinIO(파일)를 멀티테넌트로 엮어, '문서를 저장·승인·검색하고 AI가 답하게 하는' 흐름을 조율하는 FastAPI 지휘자다.**

이 코드에서 어렵게 느껴지는 부분 대부분은 결국 **"여러 외부 시스템을 안전하게 통합"** 하려다 생긴 것들입니다 — 멀티테넌트 라우팅, RAG 실패 시 방어, 고아 문서 입양, 권한 필터링, deprecated된 Celery 흔적까지. 이 관점을 쥐고 보면 코드가 훨씬 잘 읽힙니다.
