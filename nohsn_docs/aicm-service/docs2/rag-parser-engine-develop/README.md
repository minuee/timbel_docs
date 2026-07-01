# Locus-KMS

> **Locus-KMS** — Knowledge Management System (KMS-only standalone).
> Locus AI 플랫폼의 KMS 영역만 분리한 단독 배포 product.

## 핵심 기능

- 파일 업로드 + 자료화 (PDF/DOCX/MD/HTML/TXT, 500MB 까지)
- 풀옵션 ingest pipeline (vision + noise_filter + ontology + semantic_chunk)
- 노션 스타일 노트 + 블럭 단위 편집 (텍스트 / 표 / validity 토글)
- 일반 검색 (keyword)
- RAG 검색 (semantic + SSE 스트리밍)
- 하이브리드 검색 (BGE-M3 dense+sparse + reranker)
- Multi-repo 검색 scope (RepositoryGroup) — default / tenant_all / specified / group
- 파일 관리 UI (V1 frontend MVP)
- Multi-tenant 격리 (Postgres RLS + Qdrant/ES/MinIO/Redis/Kafka tenant scope)

## 빠른 시작 (1-command 기동)

```bash
git clone https://github.com/RickySonYH/Locus-KMS
cd Locus-KMS
cp .env.example .env
# .env 값 확인 (default 는 무인증 모드)
docker compose up -d
sleep 30
curl http://localhost:5101/health
# {"status":"ok"}
```

## 배포 모드

### 모드 A — 외부 vLLM endpoint (default)
- 기존 운영 환경의 SSH tunneled vLLM 사용 (host.docker.internal:7120)
- 본 컨테이너 stack 에 vllm/reranker *미포함*
- 명령: `docker compose up -d`

### 모드 B — 자체 GPU (customer site)
- 컨테이너 내부에 vllm + reranker 추가 기동 (NVIDIA GPU 필요)
- `.env` 의 `VLLM_URL=http://vllm:8000/v1`, `RERANKER_URL=http://reranker:8000/rerank`
- `HF_TOKEN` 추가 필요
- 명령: `docker compose --profile local-llm up -d`

## 인증 모드

### 무인증 (LUCAS_AUTH_DISABLED=true, default)
- 헤더 없이 호출 가능 — 내부 테스트 / 시연 / staging
- 기본 tenant_id = `00000000-0000-0000-0000-000000000001` (migrate 서비스의 `scripts/init_db.py` 가 `settings.LUCAS_DEFAULT_TENANT_ID` 로 시드. alembic `082_seed_default_lucas_tenant` 도 동일 ID 시드 — 두 경로 동기)

### 인증 (LUCAS_AUTH_DISABLED=false, 운영)
- JWT Bearer 필수 — `POST /api/v1/auth/v2/signup` 또는 `/login`
- X-Tenant-Id 헤더 + RBAC 적용

## API 문서

- **Swagger UI**: http://localhost:5101/api/v1/docs (기동 후)
- **OpenAPI schema**: http://localhost:5101/api/v1/openapi.json
- **API 사용 가이드**: [docs/api/lucas-kms-api-reference.md](./docs/api/lucas-kms-api-reference.md) — 14 섹션, 모든 endpoint 의 curl/Python/JS 예시

## 디렉토리 구조

```
.
├── Dockerfile                            # KMS API + worker (main_kms factory)
├── docker-compose.yml                    # 11 services (default) / 13 (local-llm)
├── .env.example                          # 환경 변수 템플릿
├── README.md                             # 본 문서
├── alembic/                              # DB migration (multi-branch shared/kms/agent)
├── alembic_kms/                          # KMS-only env.py wrapper
├── src/                                  # 소스 (monorepo snapshot)
│   ├── api/                              # FastAPI routers (KMS only)
│   ├── pipeline/                         # ingest workers
│   ├── search/                           # 하이브리드 검색 + tenant wrapper
│   ├── common/                           # 공통 유틸 (config, auth, storage_tenant 등)
│   └── core/                             # DB models
├── frontend/                             # V1 KMS frontend + MVP 컴포넌트
│   ├── components/                       # block_editor, table_editor, citation_viewer
│   ├── lib/                              # api.js (JWT wrapper)
│   └── doc-detail-mvp.html               # V1 MVP detail 페이지
├── docs/
│   ├── api/                              # API 사용 가이드 (2019 LOC)
│   ├── deployment/                       # 4 운영 가이드
│   └── design/                           # spec + plan
├── tests/
│   ├── perf/                             # 성능 측정 suite
│   ├── db/                               # RLS + migration 테스트
│   └── frontend/v1/                      # MVP UI E2E 테스트
├── scripts/
│   ├── perf/                             # benchmark 실행
│   ├── regression/                       # Locus smoke
│   └── eval/                             # GPT-5.5 검증
└── tools/
    ├── import_audit/                     # 의존성 그래프
    ├── alembic_audit/                    # branch 분류
    └── docker_scan/                      # 4-layer artifact scan
```

## 성능 측정

```bash
# 기본 시나리오 — 공공 SaaS 시나리오 (단일/multi-turn/OOD/노이즈/표 인용)
PERF_BASE_URL=http://localhost:5101 ./scripts/perf/run_benchmark.sh lucas-kms

# 결과: Doc/perf/YYYY-MM-DD-HH-MM/compare.md
```

회귀 임계값 (`tests/perf/thresholds.yml`):
- p95 latency +20% 이상 증가 → warning
- p99 latency +50% 이상 증가 → fail

## 운영 매뉴얼

- [docs/deployment/lucas-kms-public-saas-deployment.md](./docs/deployment/lucas-kms-public-saas-deployment.md) — 단계별 배포
- [docs/deployment/lucas-kms-public-saas-multi-tenant.md](./docs/deployment/lucas-kms-public-saas-multi-tenant.md) — Multi-tenant 운영
- [docs/deployment/lucas-kms-public-saas-perf-baseline.md](./docs/deployment/lucas-kms-public-saas-perf-baseline.md) — 성능 기준선
- [docs/deployment/lucas-kms-operator-manual.md](./docs/deployment/lucas-kms-operator-manual.md) — 운영자 매뉴얼

## 기술 스택

- LLM: vLLM + Gemma-4-31B (외부 SSH tunnel 또는 local-llm profile)
- Embedding: BGE-M3 (multilingual)
- Reranker: BGE-reranker-v2-m3
- Vector DB: Qdrant
- Search: Elasticsearch
- Event Bus: Apache Kafka
- Cache: Redis
- Storage: PostgreSQL (RLS) + MinIO
- Backend: Python 3.11, FastAPI, SQLAlchemy 2, Alembic
- Frontend: vanilla JS + PDF.js (V1 MVP)
- Deploy: Docker Compose

## 보안 명시

운영 외부 노출 환경 전환 절차:
```bash
# .env 의 다음 값 수정
LUCAS_AUTH_DISABLED=false
ENV=prod
ENABLE_SWAGGER=false
SWAGGER_AUTH_MODE=jwt
JWT_SECRET_KEY=<openssl rand -hex 32>
POSTGRES_PASSWORD=<strong>
KMS_APP_PASSWORD=<strong>
KMS_SUPERADMIN_PASSWORD=<strong>
MINIO_ROOT_PASSWORD=<strong>
CITATION_HMAC_SECRET=<strong>
```

자세한 보안 정책: `docs/deployment/lucas-kms-public-saas-deployment.md` Section 7.

## 라이센스

TBD — 운영팀 확정 필요.

## 통합 솔루션

KMS + Agent 통합 버전은 [Locas_1.0](https://github.com/RickySonYH/Locas_1.0) (private) 참조.

---

작성: 2026-05-19
