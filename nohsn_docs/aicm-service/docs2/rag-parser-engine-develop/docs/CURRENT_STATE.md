# Locus-KMS — 현재 상태 매뉴얼 (KMS-only)

작성: 2026-05-19
대상: 운영자 / 검토자 / 도입 파트너 (현 시점 live 환경 점검·운용)
모태: README.md + QUICKSTART.md + docs/deployment/* 의 *현재 시점* 스냅샷

> 본 문서는 *시점 의존*. 환경/이미지/태그가 바뀌면 README + docs/deployment/ 의 원본을 신뢰. 기준 시점: 2026-05-19, gitlab tag `Locus-KMS1.0` 직후.

---

## 0. 한눈에

| 항목 | 값 |
|---|---|
| Repo | `https://gitlab.timbel.dev/apps/langsa/rag-parser-engine` (branch `locus-kms-release-1.0`, tag `Locus-KMS1.0` / `Locus-KMS1.0.1`) |
| Mirror | `https://github.com/RickySonYH/Locus-KMS` |
| 분리 모델 | KMS-only standalone — Agent / Chat / SOP-inject 기능 *없음* (통합본 Locus 와 별개) |
| API factory | `src/api/main_kms.py` → `create_kms_app()` |
| 기본 포트 | API `5101` (default compose) / staging API `5201` (staging compose) |
| 기본 인증 모드 | `LUCAS_AUTH_DISABLED=true` (default, 무인증) |
| 외부 LLM | vLLM + Gemma-4-31B (외부 endpoint 또는 self-GPU profile) |

---

## 1. 현재 떠있는 staging 환경

본 시점 docker compose 의 `lucas-kms-*` 컨테이너 (staging 전용 prefix) — `docker ps` 기준.

| 컨테이너 | 이미지 | 포트 (host) | 상태 |
|---|---|---|---|
| `lucas-kms-api` | `aicm-apis-api` | 5201 → 8000 | healthy |
| `lucas-kms-worker-large` | `lucas-kms:latest` | (internal) | healthy |
| `lucas-kms-worker-small` | `lucas-kms:latest` | (internal) | healthy |
| `lucas-kms-postgres` | `postgres:16-alpine` | 5210 → 5432 | healthy |
| `lucas-kms-qdrant` | `qdrant/qdrant:v1.12.1` | 5211/5212 → 6333/6334 | healthy |
| `lucas-kms-elasticsearch` | `elasticsearch:8.15.0` | 5213 → 9200 | healthy |
| `lucas-kms-kafka` | `apache/kafka:latest` | 5214 → 9094 | healthy |
| `lucas-kms-redis` | `redis:7-alpine` | 5215 → 6379 | healthy |
| `lucas-kms-minio` | `minio/minio:latest` | 5216/5217 → 9000/9001 | healthy |

healthz 확인:

```bash
curl -s http://localhost:5201/health
# {"status":"ok"}
```

> Frontend (5252) — 본 시점에는 docker listen 으로 잡히지 않음. WSL Windows 측 dev server 또는 별도 호스트 정적 서버에서 띄우는 구조. frontend 정적 자원은 `frontend/` 폴더에 포함.

## 2. staging compose 마운트 구조 (중요)

`docker-compose.staging.yml` 는 4 services 모두에 다음과 같이 mount:

```yaml
volumes:
  - /home/Ricky-Dev/Locus-KMS/src:/app/src:ro
  - /home/Ricky-Dev/AICM-APIs/packages/lucas-shared/src/lucas_shared:/app/lucas_shared:ro
  - /home/Ricky-Dev/Locus-KMS/alembic:/app/alembic:ro
  - /home/Ricky-Dev/Locus-KMS/alembic.ini:/app/alembic.ini:ro
```

즉 staging runtime 코드 = **본 repo (`Locus-KMS`) 의 src + AICM-APIs 의 packages/lucas-shared**.

**self-contained 주의** — staging compose 는 외부 절대경로 (`/home/Ricky-Dev/AICM-APIs/...`) 에 의존. 단순히 본 repo 만 가져간 외부 환경에서는 staging compose 가 그대로 작동하지 않음. 운영 `docker-compose.yml` 는 별개 (image 내부 코드 사용 — self-contained).

## 3. 운영 모드 (현재 staging)

`docker-compose.staging.yml` 의 `lucas-kms-api` env:

```yaml
PYTHONPATH: /app
CORS_ORIGINS: "http://localhost:5252,http://localhost:5251,http://localhost:5101,http://localhost:5102,http://localhost:3000,http://localhost:8080,http://localhost:5173"
ENABLE_SWAGGER: "true"
ENV: dev
SWAGGER_AUTH_MODE: none
LUCAS_AUTH_DISABLED: "true"
```

- 무인증 모드 (`LUCAS_AUTH_DISABLED=true`) — JWT 없이 호출 가능
- Swagger 공개 (`ENABLE_SWAGGER=true`, `SWAGGER_AUTH_MODE=none`)
- CORS — 5252/5251/5101/5102/3000/8080/5173 허용

> 운영 (prod) 시 위 4 항목 모두 변경 필요. README §보안 명시 / QUICKSTART §3 Step1·§7 운영 체크리스트 참조.

## 4. 매뉴얼 / API 진입점 (현 시점)

| 주제 | 진입점 |
|---|---|
| 문서 인덱스 | [`docs/INDEX.md`](INDEX.md) |
| API 사용 | [`docs/api/lucas-kms-api-reference.md`](api/lucas-kms-api-reference.md) (2019 LOC, 14 섹션) |
| 배포 (공공 SaaS) | [`docs/deployment/lucas-kms-public-saas-deployment.md`](deployment/lucas-kms-public-saas-deployment.md) |
| Multi-tenant 운영 | [`docs/deployment/lucas-kms-public-saas-multi-tenant.md`](deployment/lucas-kms-public-saas-multi-tenant.md) |
| 성능 기준선 | [`docs/deployment/lucas-kms-public-saas-perf-baseline.md`](deployment/lucas-kms-public-saas-perf-baseline.md) |
| 운영자 매뉴얼 | [`docs/deployment/lucas-kms-operator-manual.md`](deployment/lucas-kms-operator-manual.md) |
| 분리 디자인 | [`docs/design/2026-05-19-lucas-kms-separation-design.md`](design/2026-05-19-lucas-kms-separation-design.md) |
| 배포 준비 종합 보고 | [`Doc/solution/2026-05-19-locus-kms-deployment-ready.md`](../Doc/solution/2026-05-19-locus-kms-deployment-ready.md) |
| Staging seeded perf | [`Doc/perf/2026-05-19-lucas-kms-staging-seeded/report.md`](../Doc/perf/2026-05-19-lucas-kms-staging-seeded/report.md) |

라이브 (실행 중):

| URL | 내용 |
|---|---|
| `http://localhost:5201/health` | liveness |
| `http://localhost:5201/api/v1/openapi.json` | OpenAPI schema |
| `http://localhost:5201/docs` | Swagger UI (staging 공개) |
| `http://localhost:5201/redoc` | Redoc |

## 5. 기본 자료 (default tenant)

- tenant_id: `00000000-0000-0000-0000-000000000001` (배포 시 migrate 서비스가 `scripts/init_db.py` 로 시드 — `settings.LUCAS_DEFAULT_TENANT_ID` 에서 읽음. alembic `082_seed_default_lucas_tenant` 도 동일 ID. **주의: migrate 는 alembic 이 아니라 init_db.py 를 호출**)
- 무인증 모드에서 모든 호출이 이 tenant 로 귀속

API 헤더 (무인증 모드):
- 필수 헤더 없음
- 선택: `X-Tenant-Id: 00000000-0000-0000-0000-000000000001` (multi-tenant 시 명시)

인증 모드 전환 시 — `Authorization: Bearer <jwt>` 필수, JWT payload 의 `tenant_id` 와 path 의 `{tenant_id}` 일치 강제.

## 6. 자주 쓰는 호출 (staging 5201 기준)

### 6.1 Repository 목록

```bash
curl -s http://localhost:5201/api/v1/repositories | jq .
```

### 6.2 Search (하이브리드)

```bash
curl -s -X POST http://localhost:5201/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "결제 정책 환불", "tenant_id": "00000000-0000-0000-0000-000000000001", "top_k": 5}' | jq .
```

### 6.3 RAG (SSE 스트리밍)

```bash
curl -N -X POST http://localhost:5201/api/v1/rag/assist-stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"query": "...", "tenant_id": "00000000-0000-0000-0000-000000000001"}'
```

자세한 schema / 예시 / 에러 코드는 `docs/api/lucas-kms-api-reference.md`.

## 7. 검증된 동작 (배포 준비 종합 보고 §검증 완료)

- e2e ingest: 14초 / 4p PDF, 9 blocks (정상)
- 공정 perf 비교 (실 데이터 환경, integrated vs Locus-KMS): API −20% / RAG −53% / c=8 tail −89%
- 분리 정확성: integrated 315 routes → Locus-KMS 192 routes (agent 0)
- 인프라 fix 적용 (schema dump + kms_app role + 권한)

자세한 수치 + 산출 방식: `Doc/perf/2026-05-19-lucas-kms-staging-seeded/report.md`.

## 8. 알려진 한계 (QUICKSTART §4 발췌)

| 한계 | 영향 | 대응 |
|---|---|---|
| alembic fresh DB enum 이중 생성 | DB init 실패 | migrate 가 `scripts/init_db.py` (SQLAlchemy `create_all`) 로 자동 우회 |
| `host.docker.internal` Linux 미해석 | mode A default endpoint 실패 | docker-compose `extra_hosts: ["host.docker.internal:host-gateway"]` 적용됨 |
| `kms_app` role 권한 부족 (RLS) | API permission denied | `init_db.py` 가 role 생성 + GRANT. fresh DB 면 수동 GRANT |
| packages/ 전면 refactor 미진행 | image 에 agent_framework 코드 *물리 존재* (런타임 미사용) | `.dockerignore` 로 build context 제외 / import-linter 가 0 import 보장 |
| csap_table 시나리오 +63% | 특정 query latency 증가 (data 부족 시) | 운영 데이터 충분 시드되면 해소 |

## 9. 운영 전 마지막 체크리스트 (재정리)

- [ ] `.env` 의 모든 비밀번호 강한 값 (default 제거)
- [ ] `LUCAS_AUTH_DISABLED=false` + `ENV=prod`
- [ ] `ENABLE_SWAGGER=false` 또는 `SWAGGER_AUTH_MODE=jwt` + IP allowlist
- [ ] TLS + reverse proxy (nginx)
- [ ] PostgreSQL / Qdrant / MinIO / Kafka 영속화 + 백업 정책
- [ ] vLLM endpoint 가용성 (mode A) 또는 GPU + `HF_TOKEN` (mode B)
- [ ] `/metrics` Prometheus 수집 + Grafana 대시보드
- [ ] Locus-KMS staging compose 의 절대경로 마운트는 *로컬 dev 전용* — 운영은 `docker-compose.yml` 사용

---

> 본 문서가 stale 되면 `docs/INDEX.md` 의 *현재 상태 매뉴얼* 항목을 갱신하거나 본 파일을 갱신.
