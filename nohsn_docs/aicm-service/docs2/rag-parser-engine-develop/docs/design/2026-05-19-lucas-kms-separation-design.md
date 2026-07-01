# Lucas-KMS 분리 배포 — Design Spec (rev2)

작성: 2026-05-19
브랜치: KMS-Plus (작업) / 분리 후 Lucas-KMS 신규 repo
사용자 결정:
1. Architecture: **Option 3 — 완전 monorepo 분할** (lucas-kms / lucas-agent / shared 패키지)
2. LLM: **Gemma-4-31B 단일 권장**
3. 노션 스타일 노트: 기존 Library 의 노트 기능 활용 (신규 X)
4. Brand: **Lucas-KMS** 확정
5. Frontend: **V1 + KMS patch** + Swagger 병행

GPT-5.5 verdict (rev1): FAIL_WITH_NOTES → 보강 사항 반영하여 rev2 작성.

---

## 1. Goal

> **Locus AI 플랫폼에서 KMS 영역만 분리해 *Lucas-KMS* 단독 배포 product 로 제공한다.**

- 분리 후에도 통합 솔루션 (Locus 전체) 은 동일 monorepo 에서 빌드 가능
- Lucas-KMS 단독 배포 시 agent 코드 *완전 제외* (보안/라이센싱)
- 운영자는 V1 frontend 의 Library UI 로 일상 운영, 개발자는 Swagger 로 API 통합

---

## 2. Non-Goals

- agent_framework 의 재작성 / refactor (분리만, 내부 X)
- 신규 노션 노트 기능 (기존 활용)
- frontend-v3 의 chat-first SPA 를 Lucas-KMS 에 포함
- 다른 LLM (Claude, GPT-5 등) 정식 권장 — *Gemma-4-31B 단일*
- 신규 검색 알고리즘 (현 BGE-M3 + reranker 그대로)
- Lucas-KMS 의 *agent 호출* (Lucas-KMS 가 lucas-agent 에 의존 0)

---

## 3. Architecture

### 3.1 Monorepo 구조

```
AICM-APIs/  (기존 repo — 통합 솔루션 base, monorepo)
├── packages/
│   ├── lucas-kms/                # Lucas-KMS 패키지 (단독 배포 가능)
│   │   ├── src/lucas_kms/
│   │   │   ├── api/              # FastAPI routers (KMS only)
│   │   │   ├── pipeline/         # ingest workers
│   │   │   ├── search/           # 검색 service
│   │   │   ├── models/           # KMS DB models only
│   │   │   ├── migrations/       # *KMS-only* Alembic branch
│   │   │   ├── app.py            # KMS app factory
│   │   │   └── main.py           # ASGI entry (uvicorn 진입)
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile             # build context = . (this dir + shared wheel)
│   │   ├── .dockerignore          # agent / frontend-v3 / tests/full 제외
│   │   └── docker-compose.yml
│   ├── lucas-agent/              # Agent layer 패키지
│   │   ├── src/lucas_agent/
│   │   │   ├── runtime/
│   │   │   ├── tools/
│   │   │   ├── skills/
│   │   │   ├── migrations/       # *Agent-only* Alembic branch
│   │   │   ├── app.py            # Agent app factory
│   │   │   └── main.py
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── shared/                   # 양쪽 공통 — *stable contract only*
│   │   ├── src/lucas_shared/
│   │   │   ├── config/           # Settings base
│   │   │   ├── auth/             # JWT, tenant context
│   │   │   ├── db/               # session, RLS helpers, base classes
│   │   │   ├── kafka/            # producer/consumer abstraction
│   │   │   ├── llm/              # vLLM 클라이언트 (gemma-4-31b)
│   │   │   ├── redis/            # cache + lock
│   │   │   ├── minio/            # file storage
│   │   │   ├── audit/            # 감시 로그 contract
│   │   │   ├── time_utils.py
│   │   │   ├── logging.py
│   │   │   ├── models/           # *shared* DB models only (tenant/user/api_key/audit_log)
│   │   │   └── migrations/       # *shared* Alembic branch (base tables)
│   │   └── pyproject.toml
│   └── full-app/                 # 통합 솔루션 entry — lucas-kms + lucas-agent 조립
│       ├── src/lucas_full/
│       │   └── main.py           # 두 router 모두 mount
│       ├── Dockerfile             # full build context
│       └── pyproject.toml
├── frontend-v1/                  # Lucas-KMS 전용 lightweight UI (patch)
├── frontend-v3/                  # Locus 통합 SPA (기존)
├── tools/
│   ├── import_audit/             # import-linter, import graph 도구
│   ├── docker_scan/              # Docker image filesystem scan
│   └── alembic_audit/            # migration product audit
├── docs/
├── tests-integration/            # 패키지 간 통합 테스트 (별도)
├── pyproject.toml                # uv workspace 정의
└── docker-compose.full.yml       # 통합 솔루션 dev
```

### 3.2 패키지 의존 관계 (불변 contract)

```
lucas-shared  (외부 의존만 — 다른 lucas-* 미의존)
   ↑
   ├── lucas-kms     (lucas-shared 만 의존; lucas-agent 0 import)
   ├── lucas-agent   (lucas-shared 만 의존; lucas-kms 0 import)
   └── full-app      (lucas-shared + lucas-kms + lucas-agent 모두 의존)
```

**불변**:
- `lucas-kms` 가 `lucas-agent` import 시 **CI fail**
- `lucas-agent` 가 `lucas-kms` import 시 **CI fail**
- 두 패키지가 통신해야 한다면 *HTTP 또는 Kafka event* 만 (직접 import 금지)

### 3.3 통합 솔루션 (Locus) vs Lucas-KMS

| 배포 | 포함 패키지 | 컨테이너 | UI |
|---|---|---|---|
| **Lucas-KMS** 단독 | lucas-shared + lucas-kms | lucas-kms-api + workers + infra | frontend-v1 (KMS only) + Swagger (auth-gated in prod) |
| **Locus 통합** | + lucas-agent + full-app | + lucas-agent-api | frontend-v3 (chat-first SPA) + frontend-v1 (admin) |

---

## 4. 컴포넌트 분류 — 최종 확정

### 4.1 lucas-kms (KMS 코어)

**API Routers** (포함):
- repositories, documents, blocks, chunks, sections
- search, rag, rag_assist (assist-stream — retrieval-only 응답)
- categories, document_types, library_folders_v1
- notes (노션 스타일 노트 — 기존 활용)
- preview, playground

**Pipeline Workers** (포함):
- chunk_worker, embed_worker, block_worker
- DLQ scheduler (split_job_starvation 차단 + 자동 retry)
- supervisor + per-doc Lock

**Search**:
- hybrid (BGE-M3 dense + sparse + reranker)
- intent_classifier — time_context 분리 후 (lucas-shared 사용)

**DB Models**:
- repositories, documents, chunks, blocks, sections
- categories, document_categories, document_types
- library_folders, notes
- search_logs, intent_logs (KMS 전용 telemetry — shared 가 아닌 lucas-kms 소속)

### 4.2 lucas-agent (Agent layer — Lucas-KMS 단독 배포 시 완전 제외)

**API Routers**:
- agents_v1, chat_v1, agent_management
- activation, external_agent_v1
- agent_documents_v1, tools_v1, custom_tools_v1, skills_catalog_v1
- manifest, context_v1, feed_v1
- schedule_v1, diary_v1, expense_v1, stock_v1, memo_v1
- sop_samples_v1, verification_v1, doc_draft_v1

**Runtime**:
- engine (engine.turn), delegate_router, sop_inject_builder
- tools/, skills/, classifier/, conversation/, activation, manifest, storage, workers

**DB Models**:
- agents, agent_channels, agent_documents
- channel_user_mappings, channel_inbound_dedup
- custom_tools, scheduled_actions
- lifecycle_feedback (agent 피드백 telemetry — agent 전용)

### 4.3 lucas-shared (*stable contract only*)

**원칙**: god package 방지 — *양쪽이 진짜로 함께 쓰는 stable contract* 만. agent 전용/KMS 전용 telemetry 는 각 패키지로 분리.

**모듈**:
- `config/` — pydantic Settings base
- `auth/` — JWT, tenant_id 컨텍스트
- `db/` — session, RLS context helper, Base class
- `kafka/` — producer/consumer abstraction
- `llm/` — vLLM 클라이언트 (gemma-4-31b)
- `redis/` — 캐시 + lock primitives
- `minio/` — 파일 storage 클라이언트
- `audit/` — `AuditLog` contract (양쪽이 쓰는 단일 audit ledger)
- `time_utils.py`, `logging.py`, `i18n/` (선택)

**DB Models (shared base)**:
- `tenants`, `users`, `api_keys`, `user_repository_access`
- `audit_logs`, `integrations`, `llm_usage`
- `anonymization_logs`, `dlq_messages` (양쪽 worker 가 쓰는 단일 DLQ)

**shared 에서 *제거* (rev1 → rev2 변경)**:
- `intent_logs` → lucas-kms 로 이동 (KMS 전용 telemetry)
- `lifecycle_feedback` → lucas-agent 로 이동 (agent 전용)
- `search_logs` → lucas-kms

---

## 5. Frontend 전략

### 5.1 frontend-v1 KMS-Only Patch — MVP 스코프 명시

**MVP (Phase 4 의 blocker)**:
- 기존 `frontend/` (V1) 의 KMS 페이지 baseline 사용
- 노션 스타일 노트 핵심 (텍스트 블럭 + 표 편집 + validity 상태 토글)
- citation deep-link PDF.js viewer
- repo CRUD / doc lifecycle / review / archive

**Post-MVP (Phase 5+)**:
- drag-drop, slash command, mention
- 다국어 (한/영 토글)
- 고급 search UX (filter facet UI)

### 5.2 Swagger 노출 정책 (보안 보강)

| 환경 | Swagger 노출 | 인증 |
|---|---|---|
| **dev/staging** | 항상 활성 (`/api/v1/docs`) | 무인증 |
| **production (multi-tenant SaaS)** | 활성 | **JWT or basic auth + IP allowlist** |
| **production (single-tenant on-prem)** | env `ENABLE_SWAGGER=true` 시만 | 기본 비활성 (운영자 명시 활성) |

env:
- `ENABLE_SWAGGER` (default: dev=true, prod=false)
- `SWAGGER_AUTH_MODE` (none / basic / jwt)
- `SWAGGER_IP_ALLOWLIST` (comma-separated CIDR)

### 5.3 frontend-v3 (Locus 통합용)

- 그대로 유지 — Lucas-KMS 단독 배포 시 미포함 (.dockerignore)

---

## 6. LLM 전략

### 6.1 단일 권장 모델

- **vLLM + Gemma-4-31B** (현 tunneled deployment 유지)
- 외부 GPU 서버 — 현 운영의 `VLLM_URL=http://vllm:8000/v1` 그대로 (B200 SSH tunnel)
- 모델 식별자: 현 `VLLM_MODEL` 값 그대로 (현재 `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` — 사용자 명명 *Gemma-4-31B*)
- 운영 매뉴얼에 *Gemma-4-31B (현 tunneled deployment 유지)* 만 명시
- Lucas-KMS 단독 배포 시 `LUCAS_VLLM_ENDPOINT` 기본값 = 기존 `VLLM_URL` (변경 없음)
- 2026-05-19 사용자 결정 — *vLLM 은 기본값으로 현 터미널링 gemma-4 그대로 유지*

### 6.2 외부 vLLM Endpoint 운영 정책 (신설 — rev2)

Lucas-KMS 는 외부 vLLM 에 의존 → 안정 운영 필수:

| 항목 | 정책 |
|---|---|
| **Auth** | `LUCAS_VLLM_API_KEY` env — Authorization header (Bearer) |
| **TLS** | HTTPS 필수 (`LUCAS_VLLM_ENDPOINT=https://...`). 자체서명 인증 시 `LUCAS_VLLM_CA_CERT` |
| **Timeout** | connect 5s / total 60s (segmentation), 30s (intent/distill) |
| **Retry** | exponential backoff (1s/2s/4s), max 3 회. idempotent 만 retry |
| **Circuit Breaker** | 5분 windows 에 50% 이상 실패 시 30초 open. open 상태에서는 fallback 사용 |
| **Concurrency** | per-endpoint semaphore (default 8, env `LUCAS_VLLM_MAX_CONCURRENT`) |
| **Model Revision** | `LUCAS_VLLM_MODEL_REVISION` 명시. mismatch 시 startup fail |
| **Health Check** | 60초 주기 `/v1/models` ping. unhealthy 시 alert |
| **Logging/PII** | request/response 의 PII redact filter (이메일/주민번호/카드 패턴) |
| **Audit** | LLM call → `audit_logs` 에 (tenant_id, agent_id=null, endpoint, latency, status) |

### 6.3 LLM 사용처 (Lucas-KMS 내)

| 사용처 | 필수도 | fallback |
|---|---|---|
| Segmentation (LLM block segmenter) | 권장 | fallback_segmenter (품질↓) |
| Distill (검색 결과 압축) | 권장 | raw chunk 그대로 응답 |
| Intent gate (검색 query 분류) | 선택 | 항상 in_domain 가정 |
| Query expansion (HyDE 등) | 선택 | off (단순 검색만) |

`FEATURE_LLM=true` (default) — 모두 활성. `false` 시 fallback.

---

## 7. DB Schema 분리 — Alembic Product-Aware Migration (rev1 → rev2 전면 재설계)

### 7.1 Multi-Branch Migration 전략

기존 단일 Alembic history 의 `target_metadata` 제한 만으로는 부족 (FAIL_WITH_NOTES). 대신:

**3개 migration branch** (Alembic dependency 표시):
- `shared` — base tables (tenants, users, api_keys, audit_logs, integrations, llm_usage, anonymization_logs, dlq_messages)
- `kms` — KMS tables (repositories, documents, chunks, blocks, sections, categories, library_folders, notes, search_logs, intent_logs)
- `agent` — Agent tables (agents, agent_channels, ...)

각 패키지는 자기 branch 만 관리:
- `packages/shared/src/lucas_shared/migrations/`
- `packages/lucas-kms/src/lucas_kms/migrations/`
- `packages/lucas-agent/src/lucas_agent/migrations/`

### 7.2 배포 시나리오별 migration

| 시나리오 | 적용 branch |
|---|---|
| **Lucas-KMS 단독 fresh DB** | `shared` → `kms` (agent 미적용) |
| **Lucas-Agent 단독 fresh DB** | `shared` → `agent` (KMS 미적용) — 운영적으로 의미 적음, 테스트 케이스용 |
| **Locus 통합 fresh DB** | `shared` → `kms` + `agent` |
| **기존 Locus DB upgrade** | 기존 history → 신규 multi-branch 로 *전환 migration* 1회 적용 |

전환 migration 은 별도 task — 기존 DB 의 alembic_version 테이블을 multi-branch 형식으로 변환.

### 7.3 검증 게이트

- T7 (Phase 0): `tools/alembic_audit/` — 각 model 의 branch 소속 자동 식별. 누락 시 fail.
- T13 (Phase 2): KMS fresh DB 에 `kms` branch upgrade 후 `\dt` 에 agent table *0개* 검증.
- T14: Full fresh DB 에 모든 branch upgrade 검증.
- T15: 기존 Locus DB upgrade 회귀 (staging 에서 검증 후 prod).

### 7.4 Alembic Multi-Branch 구체 절차 (rev3 신설)

**Alembic 설정** (`alembic.ini`):
```ini
[alembic]
version_locations = packages/shared/src/lucas_shared/migrations/versions
                    packages/lucas-kms/src/lucas_kms/migrations/versions
                    packages/lucas-agent/src/lucas_agent/migrations/versions
version_path_separator = newline
```

**Branch label** (revision 파일 헤더):
```python
# shared 의 첫 revision
revision = "shared_0001"
down_revision = None
branch_labels = ("shared",)
depends_on = None

# kms 의 첫 revision
revision = "kms_0001"
down_revision = None
branch_labels = ("kms",)
depends_on = ("shared",)   # shared 가 먼저 적용되어야 함

# agent 의 첫 revision
revision = "agent_0001"
down_revision = None
branch_labels = ("agent",)
depends_on = ("shared",)
```

**기존 Locus DB transition** (T17 의 transition migration):
1. 기존 단일 history 의 마지막 revision 식별
2. 신규 multi-branch heads (`shared`, `kms`, `agent`) 의 첫 revision 의 `down_revision` 을 기존 마지막 revision 으로 설정
3. `alembic stamp` 로 기존 DB 의 `alembic_version` 을 multi-branch heads 로 변환
4. 이후 매 product 의 신규 revision 은 자기 branch head 에서 분기

**Rollback 절차**:
- branch 별 `alembic downgrade <branch>@-1`
- staging 에서 1회 검증 후 prod 적용
- prod rollback 시 *반드시* DB snapshot 선행

**env.py** — 패키지별로 별도 `env.py`:
- `packages/shared/.../env.py` 는 shared metadata 만 import
- `packages/lucas-kms/.../env.py` 는 shared + kms metadata
- `packages/lucas-agent/.../env.py` 는 shared + agent metadata
- 통합 `full-app/.../env.py` 는 셋 모두

배포 시 사용할 env.py 가 결정 — KMS-only 컨테이너는 lucas-kms 의 env.py 사용 → shared + kms branch 만 upgrade.

---

## 8. Multi-Store Tenant Isolation (rev2 신설)

### 8.1 PostgreSQL — RLS 정책 정확 적용

- 모든 tenant-scoped table 에 RLS policy + `FORCE ROW LEVEL SECURITY`
- **중요 (rev3 수정)**: `FORCE RLS` 는 *table owner* 까지 RLS 적용함. 하지만 *superuser/`BYPASSRLS` 권한 보유자* 는 정책 우회 가능 → **app role 은 NOSUPERUSER + NOBYPASSRLS + 비-owner 로 운영**.
  - `CREATE ROLE lucas_kms_app WITH LOGIN NOSUPERUSER NOBYPASSRLS`
  - DDL/migration 용 `lucas_kms_migrate` role 은 별도 (owner)
  - app role 은 `GRANT SELECT/INSERT/UPDATE/DELETE` 만 부여
- session helper:
  - `SET LOCAL app.current_tenant_id = ?` (transaction scope — connection pool 재사용 안전)
  - default deny: tenant_id 미설정 시 policy 가 `false` → 데이터 *0 행* 노출
  - worker 의 매 message 처리 진입부에 transaction 시작 + tenant_id 설정
- write path (INSERT/UPDATE/DELETE) 회귀 테스트 필수 — read-only RLS 보호 만으로 부족

### 8.2 Qdrant

- collection 분리: `lucas_{tenant_id}_{repo_id}` naming
- 검색 시 항상 `must` filter 에 `tenant_id` 추가
- 검증: cross-tenant search test 매 PR 회귀

### 8.3 Elasticsearch

- index naming: `lucas-{tenant_id}-{repo_id}`
- 검색 시 항상 `_index` + `tenant_id` filter
- alias 정책: `lucas-{tenant_id}-*` 로만 검색 가능

### 8.4 MinIO

- bucket naming: `lucas-{tenant_id}` per tenant
- IAM policy: tenant 별 access key (또는 prefix 기반 policy)

### 8.5 Redis

- key namespace: `lucas:{tenant_id}:*`
- shared key (rate limit 등) 는 명시적 `lucas:_shared:*` namespace

### 8.6 Kafka

- topic naming: 기존 `aicm.document.*` 유지. message body 에 `tenant_id` 필수 field
- consumer 에서 tenant_id 추출 → DB session 의 RLS context 설정

### 8.7 DLQ

- 단일 `dlq_messages` 테이블 with `tenant_id` 컬럼 + RLS policy
- DLQ scheduler 도 tenant 별 isolation (한 tenant 의 storm 이 다른 tenant 처리 막지 않음)

---

## 9. Migration Phase (재구성 — Phase 0 신설)

### Phase 0 — Inventory & Gates (1-2일)

- T1: **Import graph 생성** — `pip install grimp` 사용. 현 `src/` 의 모든 모듈 의존성 그래프 → `tools/import_audit/graph.json`. 식별: lucas-agent 후보 → lucas-kms 후보 import 발생 list.
- T2: **Router inventory** — 각 router 가 어떤 service/db model 호출하는지 mapping
- T3: **Worker inventory** — 각 Kafka topic 의 consumer 위치 식별
- T4: **DB model inventory** — 각 model 의 branch 소속 판정 (KMS / Agent / Shared) — `tools/alembic_audit/`
- T5: **Frontend API call inventory** — V1/v3 가 호출하는 endpoint list
- T6: **Storage tenant-scope audit** — Qdrant/ES/MinIO/Redis/Kafka 현재 tenant isolation 상태
- T7: **CI gate 초안** — import-linter, docker layer scan, alembic branch check 도구 구축

### Phase 1 — Boundary Hardening (2-3일)

- T8: `time_context` → `lucas-shared/time_utils.py` 이동 + import 교체
- T9: `classify_worker.py` env gate (`ENABLE_INTENT_CLASSIFICATION`)
- T10: `documents.py _activation_shim` 주석 + agent interface 명시 (KMS 가 agent 에 알리는 hook 패턴)
- T11: KMS app factory 분리 (`lucas_kms.app.create_app()`)
- T12: Full app factory 분리 (`lucas_full.main.create_app()` — KMS + Agent mount)
- T13: KMS worker registry / Agent worker registry 분리
- T14: legacy `src/` shim 정책 — phase-out timeline 명시
- T15: **import-linter contract 적용** — CI 에서 자동 검증

### Phase 2 — Alembic / RLS 분리 (2-3일)

- T16: Alembic multi-branch 셋업 (shared / kms / agent)
- T17: 기존 migration → 3 branch 로 분류 (자동 + 수동 검증)
- T18: KMS fresh DB migration pass — agent table 0개 검증
- T19: Full fresh DB migration pass — 모든 table 생성
- T20: 기존 Locus DB upgrade pass — staging 회귀
- T21: PostgreSQL RLS FORCE 적용
- T22: Qdrant/ES/MinIO/Redis/Kafka tenant isolation test 작성 + 회귀

### Phase 3 — Packaging / Docker (2-3일)

- T23: `packages/lucas-shared` wheel build
- T24: `packages/lucas-kms` wheel build
- T25: `packages/lucas-agent` wheel build
- T26: **Dockerfile.lucas-kms build context** = `packages/lucas-kms` 디렉토리. shared 는 사전 빌드된 wheel 로 주입 (root context COPY 금지).
  ```dockerfile
  # 빌드 단계
  COPY packages/shared/dist/lucas_shared-*.whl /tmp/
  COPY packages/lucas-kms ./
  RUN pip install /tmp/lucas_shared-*.whl . && rm -rf /tmp/*.whl
  ```
- T27: `.dockerignore` — `packages/lucas-agent`, `frontend-v3`, `tests/full`, `src/agent_framework` 명시 제외
- T28: **Multi-layer artifact scan** — `tools/docker_scan/`:
  - `docker history` → 모든 layer 에 `lucas_agent` 미존재
  - 최종 image 의 `find / -name "lucas_agent" -o -name "lucas-agent"` → 0건
  - `pip show lucas-agent` → not found
  - `python -c "import lucas_agent"` → ImportError
- T29: SBOM / license scan (cyclonedx)
- T30: KMS-only `pip install` smoke test (clean venv)
- T30.5: **vLLM 운영 정책 코드 구현** (Section 6.2) — `lucas_shared/llm/` 에 timeout/retry/circuit_breaker/health/concurrency 적용. Phase 4 E2E 의 안정성 기반.

### Phase 4 — Runtime E2E + Frontend MVP (2-3일)

- T31: end-to-end 시나리오 — upload → ingest → search → RAG retrieve → answer
- T32: DLQ / retry 정상 동작 회귀
- T33: V1 frontend MVP UI (텍스트 블럭 + 표 + validity + citation viewer)
- T34: Swagger auth policy 적용 (env gate + IP allowlist)
- T35: Multi-tenant 2 tenant 동시 시나리오 (cross-tenant 0 검증)

**중요 (rev3 변경)**: vLLM 운영 정책 코드 (timeout / retry / circuit breaker / health) 는 Phase 4 *이전* 에 lucas-shared 의 LLM 클라이언트에 구현 필수. Phase 4 의 E2E 시나리오가 vLLM 안정성에 의존하기 때문. → **T30.5 (Phase 3 후반) 로 이동**.

### Phase 5 — Release (1-2일)

- T36: vLLM failure mode tests (endpoint down / model mismatch / TLS error)
- T37: 최종 artifact scan + Lucas-KMS 운영자 매뉴얼
- T38: **subtree push history audit** — Lucas-KMS repo 의 `git log --all --name-only` 에 `lucas_agent | lucas-agent | frontend-v3` 흔적 0건 검증
- T39: Lucas-KMS repo 에 push (subtree)
- T40: 통합 솔루션 (Locus) 전체 회귀
- T41: **GPT-5.5 최종 verdict + 사용자 동의** → 배포

---

## 10. Repo Split 전략 (rev2 신설)

monorepo 에서 분리 후 Lucas-KMS 신규 repo 로 *coherent self-contained* 코드 푸시 방식:

| 방식 | 장점 | 단점 | 선택 |
|---|---|---|---|
| **Git subtree** | history 보존, 양방향 sync 가능 | subtree 명령 학습 필요 | **권장** |
| **Path dependency (uv)** | dev 시 편함 | split repo 에서 깨짐 | 본 monorepo 내부만 |
| **Private wheel registry** | 깔끔한 분리 | registry 인프라 필요 (cost) | 향후 검토 |
| **Submodule** | 표준적 | dev 복잡 | X |

**선택: subtree**
- Lucas-KMS 신규 repo 에는 `packages/lucas-shared` + `packages/lucas-kms` + `frontend-v1` + `docs` 만 subtree 로 push
- 매 분리 release 시 `git subtree push` 로 sync
- 양방향 sync 도 가능 (bug fix 가 lucas-kms repo 에서 발생 시 monorepo 로 pull-back)

---

## 11. Risks (재분류 — Critical / High / Medium)

| Risk | Impact | Mitigation |
|---|---|---|
| Alembic migration 분리 시 schema 누락/충돌 | **Critical** | Multi-branch 도입 + KMS/Full fresh DB 회귀 (T18-T20) + staging 1회 dry-run |
| import leakage (lucas-kms → lucas-agent) | **Critical** | import-linter CI gate (T15) + grep + grimp graph |
| Docker image layer 에 agent 코드 잔존 | **Critical** | build context 제한 + .dockerignore + image filesystem scan (T28) |
| Multi-store tenant 격리 깨짐 (Qdrant/ES/MinIO 등) | **Critical** | Section 8 전체 적용 + cross-tenant test 회귀 (T22) |
| 외부 vLLM endpoint 장애 시 KMS 전체 멈춤 | **High** | Section 6.2 의 circuit breaker + fallback (T36) |
| RLS policy bypass (superuser 또는 미적용 모델) | **High** | FORCE RLS + audit (T21) |
| V1 frontend MVP 작업량 과소평가 | **High** | MVP 범위 명시 (Section 5.1) + 초과 시 Phase 5 로 deferral |
| 기존 Locus DB upgrade 시 다운타임 | **High** | staging 회귀 + rollback 계획 (T20) |
| god package (shared 비대화) | Medium | rev2 Section 4.3 의 "stable contract only" 원칙 |
| Swagger prod 노출 보안 | Medium | env gate + auth (Section 5.2) |
| subtree sync 복잡도 | Medium | scripts/ 에 helper 작성 + 매뉴얼 문서화 |
| Kafka topic naming 변경 | Low | 기존 `aicm.document.*` 유지 |

---

## 12. Success Criteria (구체 측정 기준 — rev2 재작성)

### 12.1 분리 검증 (CI 자동) — 정적/동적/artifact 다층

**Static**:
- [ ] `python -m import_linter --config tools/import_audit/contract.toml` 통과 (0 violation)
- [ ] `grep -rE "lucas_agent|from lucas_agent" packages/lucas-kms/src/` → empty
- [ ] `grimp` 의 dependency graph 에서 lucas-kms → lucas-agent edge 0개

**Dynamic**:
- [ ] lucas-kms 컨테이너에서 `python -c "import lucas_kms; print(sys.modules.keys())"` → `lucas_agent` 키 0건
- [ ] entrypoint warm-up 후 `sys.modules` snapshot 에 agent 모듈 0건

**Artifact**:
- [ ] `docker history lucas-kms:latest` 의 모든 layer 에 agent 흔적 0건
- [ ] `find /` in container → `lucas_agent | lucas-agent` 디렉토리 0건
- [ ] `pip show lucas-agent` → not found
- [ ] `pip list --format=json` 에 agent 패키지 0건
- [ ] **OpenAPI schema** (`curl /api/v1/openapi.json`) 에 agent endpoint 0건
- [ ] **SBOM** (cyclonedx) 에 lucas-agent metadata 0건

**Repo history** (subtree push 결과):
- [ ] `git log --all --name-only` 에 `lucas_agent | lucas-agent | frontend-v3 | src/agent_framework` 흔적 0건

### 12.2 기능 검증 (Lucas-KMS 단독 fresh DB)

```bash
# 시나리오 1: 기동
git clone https://github.com/RickySonYH/Lucas-KMS
cp .env.example .env
docker compose -f docker-compose.lucas-kms.yml up -d
sleep 30

# 시나리오 2: healthz
curl -sf http://localhost:5101/healthz | grep -q '"ok"'

# 시나리오 3: DB 상태 — KMS table 만 존재
docker compose exec postgres psql -U lucas_kms -d lucas_kms_db -c "\dt" \
  | grep -c "documents" | grep -q "^1$"
docker compose exec postgres psql -U lucas_kms -d lucas_kms_db -c "\dt" \
  | grep -E "^.+agents\s+\|" | wc -l | grep -q "^0$"  # agent table 0건

# 시나리오 4: PDF upload + ingest + search
pytest tests-integration/lucas_kms/test_e2e_pdf_pipeline.py -v
# 통과 기준: upload 200 + ingest active 도달 + search hit > 0

# 시나리오 5: Multi-tenant 격리
pytest tests-integration/lucas_kms/test_multi_tenant_isolation.py -v
# 통과 기준: tenant A 의 document 가 tenant B 검색에서 0건

# 시나리오 6: 노션 노트 CRUD
pytest tests-integration/lucas_kms/test_notes_crud.py -v
```

### 12.3 통합 솔루션 회귀

```bash
# 통합 솔루션 기존 DB
docker compose -f docker-compose.full.yml up -d
pytest tests-integration/full/ -v --tb=short
# 통과 기준: 0 failures

# 기존 시나리오
pytest tests/integration/agent_delegate/ -v
pytest tests/integration/sop_inject/ -v
pytest tests/integration/persona/ -v
```

### 12.4 vLLM endpoint 운영 검증

```bash
# Circuit breaker
pytest tests-integration/lucas_kms/test_vllm_circuit_breaker.py -v
# Endpoint down 시 fallback 동작 + 30s open + half-open recovery

# Health check
pytest tests-integration/lucas_kms/test_vllm_health.py -v
```

### 12.5 운영 가이드

- [ ] Lucas-KMS 운영자 매뉴얼 published (`packages/lucas-kms/docs/admin-manual.md`)
- [ ] `docker compose up -d` 1-command 기동 검증
- [ ] Swagger 노출 정책 prod 환경 검증 (인증 없으면 401)
- [ ] vLLM endpoint 운영 가이드 published

---

## 13. Out-of-Scope (별도 spec)

- **E4B 모듈 분화** — [[project_e4b_migration_future_plan]]
- **Lucas-KMS SaaS 라이센스/billing 시스템** — 별도 product spec
- **다른 frontend** (Notion-clone full UI 등) — Phase 5+
- **i18n 전면 확장** — V1 기존 수준 유지
- **Mobile app**

---

## 14. Decisions (2026-05-19 사용자 승인)

1. **monorepo tool**: **uv workspace**
2. **Docker image registry**: **ghcr.io** (GitHub Container Registry)
3. **V1 frontend MVP fidelity**: 텍스트 블럭 + 표 + validity. drag-drop/slash/mention 은 Phase 5+
4. **Multi-tenant default**: 양쪽 지원, default multi-tenant. env `LUCAS_KMS_MODE=single-tenant` 시 on-prem.
5. **vLLM endpoint**: 외부 endpoint, Section 6.2 운영 정책 적용. 고객 자체 GPU vs Locus 운영은 계약 사안.
6. **Repo split**: **git subtree** (rev2 신설)

---

## 15. References

- 분석 보고서 (Explore agent 결과)
- 메모리 절칙: [[feedback_kms_lukas_separation]], [[feedback_no_backend_rewrite]], [[feedback_no_hardcoding_first_principle]], [[feedback_gpt55_review_mandatory]]
- 통합 솔루션 매뉴얼: `Doc/solution/2026-05-19-locus-solution-overview.md`, `Doc/solution/2026-05-19-locus-admin-manual.md`
- GPT-5.5 rev1 verdict: `Doc/research/2026-05-19-lucas-kms-spec.gpt55.txt`

---

## 16. 변경 이력

- 2026-05-19 (rev1): 초안. Option 3 monorepo + Gemma-4-31B 단일 + V1 patch + Brand=Lucas-KMS 확정.
- 2026-05-19 (rev4): 사용자 명시 — vLLM 은 *현 터미널링 gemma-4 deployment 그대로 유지*. Section 6.1 명시.
- 2026-05-19 (rev3): GPT-5.5 GO_WITH_CHANGES (rev2) 보강.
  - Section 8.1 RLS FORCE 정확 설명 (BYPASSRLS 금지) + write path 회귀
  - Section 7.4 Alembic multi-branch 구체 절차 (branch label, depends_on, env.py, stamp transition, rollback)
  - Section 9 Phase 3 의 T26 Docker build context 명시 + T28 multi-layer scan + T30.5 vLLM 정책 코드 Phase 4 이전
  - Section 9 Phase 5 의 T38 subtree push history audit 추가
  - Section 12.1 검증 static/dynamic/artifact/repo-history 4 층
- 2026-05-19 (rev2): GPT-5.5 FAIL_WITH_NOTES 보강.
  - Section 7 Alembic multi-branch 전면 재설계
  - Section 8 Multi-Store Tenant Isolation 신설 (Qdrant/ES/MinIO/Redis/Kafka/DLQ)
  - Section 6.2 외부 vLLM 운영 정책 신설
  - Section 9 Phase 0 (Inventory & Gates) 신설 + Phase 1-4 → 5 단계 재구성
  - Section 5.1 V1 frontend MVP 스코프 명시
  - Section 5.2 Swagger 운영 보안 정책
  - Section 4.3 god package 방지 — shared 에서 KMS/Agent 전용 telemetry 분리
  - Section 10 subtree 결정
  - Section 11 Risk Severity 재분류 (Critical/High/Medium)
  - Section 12 Success Criteria 구체 명령/threshold
