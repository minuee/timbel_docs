# Locus-KMS v1.0 — 배포 준비 완료 (Final)

작성: 2026-05-19
세션: 35 commits, 모든 Phase 종료, 공정 perf 측정 완료

---

## 배포 산출물 — 최종 위치

| 자료 | 위치 |
|---|---|
| **GitHub Locus-KMS** | https://github.com/RickySonYH/Locus-KMS (deploy snapshot, `5548790`) |
| **GitHub Locas_1.0** | https://github.com/RickySonYH/Locas_1.0 (통합 솔루션 docs) |
| **gitlab Tag** | https://gitlab.timbel.dev/apps/langsa/rag-parser-engine/-/tags (`Locus-KMS1.0` → `e3c6d67`) |
| **gitlab Branch** | KMS-Plus branch (monorepo working) |
| **로컬 작업** | `/home/Ricky-Dev/Locus-KMS/` (clone + sync) |
| **운영 staging** | 가동 중 (port 5201, healthy) |

---

## 배포 절차 (3가지 시나리오)

### A. 외부 customer site 배포 — 자체 GPU 보유

```bash
git clone https://github.com/RickySonYH/Locus-KMS
cd Locus-KMS
cp .env.example .env
# .env 의 다음만 수정:
#   POSTGRES_PASSWORD, JWT_SECRET_KEY, CITATION_HMAC_SECRET, MINIO_ROOT_PASSWORD
#   LUCAS_AUTH_DISABLED=false (운영) + SWAGGER_AUTH_MODE=jwt
#   VLLM_URL=http://vllm:8000/v1 (mode B 사용 시)
#   HF_TOKEN=<hf token>

docker compose --profile local-llm up -d
```

### B. 통합 운영 환경에서 분리 배포 — 기존 SSH tunnel 사용

```bash
git clone https://github.com/RickySonYH/Locus-KMS
cd Locus-KMS
cp .env.example .env
# .env 의 다음만 수정:
#   비밀번호 + JWT_SECRET_KEY
#   VLLM_URL=http://host.docker.internal:7120/v1  (기본값 유지)

docker compose up -d  # mode A — 외부 vLLM endpoint 사용
```

### C. staging 테스트

```bash
git clone https://github.com/RickySonYH/Locus-KMS
cd Locus-KMS
cp .env.staging.example .env.staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml --env-file .env.staging up -d
curl http://localhost:5201/health  # {"status":"ok"}
```

---

## 검증 — 무엇이 입증 되었는가

### 1. 기능 (e2e ingest 동작)

| 단계 | 시간 | 결과 |
|---|---|---|
| upload | 0초 | 200 OK |
| parsing | ~9초 | block_count=9, page_count=4 |
| segmentation | ~9초 | 9 blocks |
| embedding (proxy) | 1.3초 | 9 vectors |
| Qdrant upsert | 0.2초 | 9 points |
| ES indexing | 0.4초 | 9 indexed |
| **total** | **14초** | active 가능 |

(통합 공공 SaaS 15분/doc 은 *대용량 PDF* 시나리오 — 4p 작은 자료는 staging 도 14초)

### 2. 성능 (실 데이터 환경 공정 비교)

| 지표 | 통합 (5101) | **분리 (5201)** | 변화 |
|---|---|---|---|
| Search p95 평균 | 10ms | **8ms** | **-20%** |
| RAG first_token (multi_turn) p95 | 163ms | **77ms** | **-53%** |
| RAG first_token (nara_register) p95 | 232ms | **103ms** | **-55%** |
| concurrent c=8 p99 | 1008ms | **~110ms** | **-89%** (tail spike 제거) |

### 3. 분리 정확성

- API routes: 통합 315 → 분리 192 (agent 123 정확 제외)
- agent service 0개 (compose config 검사)
- LUCAS_PRODUCT=kms env gate — runtime worker 등록 시 agent_framework 미import

### 4. 운영 보안

- 무인증 모드 (LUCAS_AUTH_DISABLED) — staging/dev 용
- JWT + Swagger auth policy (운영 모드)
- PostgreSQL RLS FORCE + lucas_kms_app role (migration 081 — staging 검증 후 적용)
- Multi-store tenant isolation (Postgres / Qdrant / ES / MinIO / Redis / Kafka)

---

## 문서 — 사용자 자료

| 문서 | 위치 | 용도 |
|---|---|---|
| **API 사용 가이드** (2019 LOC) | `docs/api/lucas-kms-api-reference.md` | 외부 개발자 통합 매뉴얼 — 모든 endpoint curl/Python/JS |
| 솔루션 개요 | `docs/deployment/lucas-kms-public-saas-deployment.md` | 단계별 배포 |
| Multi-tenant 운영 | `docs/deployment/lucas-kms-public-saas-multi-tenant.md` | 격리 + tenant 운영 |
| 성능 기준선 | `docs/deployment/lucas-kms-public-saas-perf-baseline.md` | 성능 기준 + 측정 가이드 |
| 운영자 매뉴얼 | `docs/deployment/lucas-kms-operator-manual.md` | KMS-only 운영자 매뉴얼 |
| 분리 spec rev4 | `docs/design/2026-05-19-lucas-kms-separation-design.md` | 분리 설계 (GPT-5.5 검증) |
| 분리 plan | `docs/design/2026-05-19-lucas-kms-separation-plan.md` | Phase 0-5 task 분해 |

### Swagger UI

기동 후 즉시: http://your-host:5201/docs

192 endpoints, 42 tags, 모든 endpoint 에 summary/description/example/response_model 보강 완료.

---

## 무엇이 분리되었나 (정확)

**분리됨** (Lucas-KMS 미포함):
- agent 라우터 20개 (agents_v1, chat_v1, sop_samples_v1, external_agent_v1, schedule_v1, diary_v1, expense_v1, memo_v1, tools_v1, custom_tools_v1, skills_catalog_v1, manifest, context_v1, feed_v1, verification_v1, doc_draft_v1, agent_management, agent_documents_v1, activation, agent_chat_upload)
- agent runtime (engine.turn, delegate_router, sop_inject_builder)
- agent worker (reminder_worker)
- agent DB tables (agents, agent_channels, custom_tools 등 7개)

**분리되지 않음** (이미 KMS 코어):
- 문서 처리 파이프라인 (chunk_worker, embed_worker, block_worker, classify_worker)
- 검색 (search_proxy, hybrid, reranker)
- RAG (retrieve, answer, assist-stream)
- 파일 관리 (repositories, documents, blocks, notes, library_folders)

→ **파이프라인은 분리할 게 없음**. 통합 운영의 안정된 자료화 흐름 그대로 Lucas-KMS 에 들어있음.

---

## 다음 단계 (사용자 영역)

### 즉시 가능

- `git clone https://github.com/RickySonYH/Locus-KMS` → docker compose up
- staging 가동 중 (port 5201) — 추가 PDF 업로드 / 검색 즉시 테스트
- API 통합 — Swagger 보면서 클라이언트 작성

### 운영 배포 전 (사용자 확인 필요)

1. `.env` 의 비밀번호 모두 *강한 값* 으로 교체 (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `KMS_APP_PASSWORD`, `MINIO_ROOT_PASSWORD`, `CITATION_HMAC_SECRET`)
2. `LUCAS_AUTH_DISABLED=false` + `ENV=prod` + `SWAGGER_AUTH_MODE=jwt`
3. Alembic 081 (RLS FORCE) staging 회귀 후 적용
4. PAT (`ghp_L0Wb...`) revoke

### 후속 (v0.2)

- Phase 3 packages/ 본격 refactor (100K+ LOC, 별도 라운드)
- Cold-path 정밀 측정 (cache 우회 query 보강)
- 통합 데이터 다수 시드 후 csap_table 시나리오 등 추가 검증
- v0.2 image build + ghcr.io 자동 push CI 파이프라인

---

## 본 세션 종합 — 35 commits 누적

```
Phase 0 (5ff2e4d)          inventory tools
Phase 1 (6 commits)         boundary hardening
Phase 2 (3 commits)         Alembic / RLS / multi-store
Phase 3 (3 commits)         Dockerfile + compose + local-llm
Phase 4 (3 commits)         V1 MVP + Swagger + e2e
Phase 5 (2 commits)         vLLM tests + artifact scan + regression
Deploy/Perf (5 commits)     배포 가이드 + perf suite + baseline + staging + seeded
Tenant fix (2 commits)      default seed + path 검증
Docs (2 commits)            API guide + Swagger metadata
무인증 모드 (1 commit)      LUCAS_AUTH_DISABLED
Phase 4 integration (1)     e2e + DLQ + multi-tenant tests
gitlab/github push          모든 외부 repo 동기화
```

**Lucas-KMS v1.0 배포 준비 완료.**
