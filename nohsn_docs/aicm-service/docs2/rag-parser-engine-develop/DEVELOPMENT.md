# Locus-KMS — 개발자 가이드 (수정·디버그·테스트)

작성: 2026-05-19
대상: Locus-KMS 폴더에서 코드 *수정 / 디버그 / 테스트* 진행하는 개발자 (사람 + AI)

> 운영 배포 단계별 가이드는 `QUICKSTART.md`, 운영자 매뉴얼은 `docs/deployment/lucas-kms-operator-manual.md`. 본 문서는 **개발 워크플로우 전용**.

---

## 0. 개발 환경 한눈에

| 항목 | 값 |
|---|---|
| 언어 / runtime | Python 3.11, FastAPI, SQLAlchemy 2, Alembic |
| Package manager | uv (pyproject.toml) |
| DB | PostgreSQL 16 (RLS), Qdrant 1.12, Elasticsearch 8.15 |
| Cache / queue | Redis 7, Kafka |
| Storage | MinIO (S3 호환) |
| LLM | 외부 vLLM endpoint (Gemma-4-31B) — 기본 SSH tunnel `host.docker.internal:7120` |
| Frontend | vanilla JS (`frontend/`), PDF.js, no build step |
| 배포 | Docker Compose (`docker-compose.yml` 운영 / `docker-compose.staging.yml` dev) |

## 1. 첫 setup (clone 후)

```bash
# 1. clone (gitlab 또는 github)
git clone https://github.com/RickySonYH/Locus-KMS
cd Locus-KMS

# 2. 환경 변수
cp .env.example .env
# .env 편집 — VLLM_URL 만 본인 환경에 맞게 (default 는 host.docker.internal:7120)

# 3. 기동
docker compose up -d

# 4. healthz
sleep 30
curl http://localhost:5101/health
# {"status":"ok"}
```

### Staging (host volume mount 로 hot-reload 흉내)

본 호스트 (`/home/Ricky-Dev/`) 에서만 작동 — staging compose 가 절대경로 의존.

```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d
# lucas-kms-api 가 5201 port 로 뜸. src/ alembic/ 이 read-only mount → 코드 변경 시 컨테이너 재시작 (uvicorn reload 미사용)
docker restart lucas-kms-api
```

## 2. 디렉토리 빠른 지도

```
.
├── CLAUDE.md                 # AI 어시스턴트 컨텍스트 (자동 로드)
├── README.md                 # 솔루션 개요 + 빠른 시작
├── QUICKSTART.md             # 단계별 setup + 알려진 한계
├── DEVELOPMENT.md            # 본 문서 — 수정·디버그·테스트
├── HANDOFF.md                # 현 시점 핸드오프 (미진행 / 다음 단계)
├── docs/
│   ├── INDEX.md              # 문서 navigation hub
│   ├── CURRENT_STATE.md      # 본 시점 staging 환경 매뉴얼
│   ├── api/                  # API ref (curl/Python/JS 예시 2019 LOC)
│   ├── deployment/           # 배포·운영·multi-tenant·perf 매뉴얼 4종
│   └── design/               # 분리 spec / plan
├── Doc/
│   ├── solution/             # 배포 준비 완료 종합 보고
│   ├── perf/                 # staging 성능 측정 결과
│   └── scan/                 # 이미지 artifact scan
├── src/
│   ├── api/                  # FastAPI app + routers + auth + schemas + services
│   ├── pipeline/             # ingest workers (vision / OCR / chunk / embed / index)
│   ├── search/               # 하이브리드 검색 + reranker
│   ├── common/               # config / storage_tenant / time_utils / agent_hook
│   └── core/                 # DB models (SQLAlchemy)
├── frontend/                 # V1 MVP UI (vanilla JS + PDF.js)
├── alembic/                  # DB migration (multi-branch)
├── alembic_kms/              # KMS-only env.py wrapper
├── tests/                    # pytest (api / db / pipeline / perf / regression 등)
├── scripts/                  # init_db / perf / regression / eval / seed
├── tools/                    # import_audit / alembic_audit / docker_scan
├── docker-compose.yml        # 운영 (self-contained)
├── docker-compose.staging.yml# dev (host volume mount, 본 호스트 전용)
├── Dockerfile                # KMS API + worker image
├── pyproject.toml            # 의존성 정의
└── .dockerignore             # agent_framework 빌드 컨텍스트 차단
```

## 3. 자주 하는 수정 패턴

### 3.1 새 API endpoint 추가

```python
# 1. src/api/routers/<area>.py 에 endpoint 추가
@router.get("/api/v1/foo/{foo_id}")
async def get_foo(foo_id: UUID, ...) -> ApiResponse[FooOut]:
    ...

# 2. (필요 시) src/api/schemas/<area>.py 에 Pydantic 모델 추가
class FooOut(BaseModel):
    id: UUID
    name: str

# 3. src/api/main_kms.py 의 RouterSpec 리스트에 등록 (이미 등록되어 있으면 skip)

# 4. 재시작
docker restart lucas-kms-api

# 5. Swagger 확인
open http://localhost:5101/docs
```

**KMS-only 원칙 주의**: 새 endpoint 가 `src.agent_framework.*` 를 import 하면 안 됨. import 시 `tools/import_audit/` 에서 violation 검출.

### 3.2 새 DB migration

```bash
# alembic.kms.ini 사용 (KMS branch)
docker compose exec lucas-kms-api alembic -c alembic.kms.ini revision --autogenerate -m "add foo table"
# migrations/versions/ 에 새 파일 생성 → 검토 후 commit
docker compose exec lucas-kms-api alembic -c alembic.kms.ini upgrade head
```

**Fresh DB caveat**: alembic 의 `user_role_enum` 이중 생성 버그가 있어, *완전 fresh DB* 에서는 alembic 대신 `scripts/init_db.py` (SQLAlchemy `create_all`) 가 자동 호출됨. 기존 DB 에 incremental migration 만 alembic 사용 권장.

### 3.3 새 pipeline worker

```python
# 1. src/pipeline/<worker_name>.py 작성
# 2. Kafka consumer group 정의 (config 에서 topic + group_id)
# 3. docker-compose.yml 에 service 추가 (or 기존 worker-large/small 에 포함)
# 4. 재빌드: docker compose build && docker compose up -d
```

### 3.4 Frontend (V1 MVP) 수정

```bash
# 정적 HTML / JS — build step 없음
# 컨테이너에 mount 안 되어 있으면 (default), nginx 서빙 컨테이너 재시작 또는
# 호스트에서 직접 file:// 또는 별도 http server (e.g., python -m http.server 5252)
cd frontend && python3 -m http.server 5252
# CORS 는 docker-compose.staging.yml 의 CORS_ORIGINS 에 5252 이미 포함
```

## 4. 디버그 가이드

### 4.1 로그 보기

```bash
# 실시간 (api)
docker compose logs -f lucas-kms-api

# 최근 200 줄
docker compose logs --tail=200 lucas-kms-api

# 여러 컨테이너 동시
docker compose logs -f lucas-kms-api lucas-kms-worker-large

# 특정 키워드 grep
docker compose logs lucas-kms-api 2>&1 | grep -i "error\|exception"
```

### 4.2 컨테이너 내부 진입

```bash
docker compose exec lucas-kms-api bash
# 안에서 Python REPL
python3 -c "from src.api.main_kms import create_kms_app; app = create_kms_app(); print(len(app.routes))"

# DB 직접 (psql)
docker compose exec lucas-kms-postgres psql -U kms -d kms_pipeline
```

### 4.3 DB 직접 점검

```sql
-- tenant 목록
SELECT id, name, slug, plan FROM tenants;

-- 특정 tenant 의 문서 수
SELECT COUNT(*) FROM documents WHERE tenant_id = '00000000-0000-0000-0000-000000000001';

-- 최근 ingest 실패
SELECT id, status, error_message, created_at FROM documents
WHERE status IN ('failed', 'partially_failed') ORDER BY created_at DESC LIMIT 20;

-- RLS 상태 (운영 시)
SELECT relname, relrowsecurity, relforcerowsecurity
FROM pg_class WHERE relkind = 'r' AND relname IN ('documents', 'blocks', 'chunks');
```

### 4.4 Qdrant 점검

```bash
# collections 목록
curl http://localhost:5111/collections

# 특정 collection 정보
curl http://localhost:5111/collections/kms_chunks | jq .

# scroll (샘플 데이터 확인)
curl -X POST http://localhost:5111/collections/kms_chunks/points/scroll \
  -H "Content-Type: application/json" \
  -d '{"limit": 5, "with_payload": true, "with_vector": false}' | jq .
```

### 4.5 Elasticsearch 점검

```bash
# 인덱스 목록
curl http://localhost:5113/_cat/indices?v

# 특정 인덱스 매핑
curl http://localhost:5113/kms_blocks/_mapping | jq .

# 샘플 검색
curl -X POST http://localhost:5113/kms_blocks/_search \
  -H "Content-Type: application/json" \
  -d '{"query": {"match": {"content": "결제"}}, "size": 3}' | jq .
```

### 4.6 흔한 traceback / 원인

| Traceback / 증상 | 원인 | 해결 |
|---|---|---|
| `permission denied for table X` | RLS 환경에서 `kms_app` role 권한 부족 | `init_db.py` 가 자동 GRANT. fresh fresh DB 면 수동: `GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO kms_app;` |
| `user_role_enum already exists` | alembic 이 enum 이중 생성 | migrate 컨테이너가 `init_db.py` (`create_all`) 사용하도록 docker-compose `command` 확인 |
| `host.docker.internal: Name or service not known` | Linux 환경 (`extra_hosts` 미설정) | `docker-compose.yml` 의 api 서비스에 `extra_hosts: ["host.docker.internal:host-gateway"]` 추가 또는 `.env` 의 `VLLM_URL` 직접 IP 명시 |
| `tenant_id mismatch (403)` | 인증 모드에서 JWT `tenant_id` 와 path `{tenant_id}` 불일치 | JWT 발급 시 올바른 tenant 로 / 또는 `LUCAS_AUTH_DISABLED=true` 로 무인증 모드 |
| RAG 응답 무한 hang | 외부 vLLM endpoint 응답 없음 | `curl http://<VLLM_URL>/v1/models` 확인. SSH tunnel 끊김이면 재연결 |
| Swagger 비공개 (`/docs` 401) | 운영 모드 `SWAGGER_AUTH_MODE=jwt` | `.env` 에 `ENABLE_SWAGGER=true SWAGGER_AUTH_MODE=none` 으로 dev 전환 |

### 4.7 디버거 (pdb / breakpoint)

uvicorn 이 `--reload` 안 켜져 있으므로 (workers=1+ 환경에서는 reload 불가) 직접 디버그하려면:

```bash
# 컨테이너에서 외부로 노출된 디버그 포트 설정 후, debugpy 사용
docker compose exec lucas-kms-api pip install debugpy
docker compose exec lucas-kms-api python -m debugpy --listen 0.0.0.0:5678 --wait-for-client -m uvicorn src.api.main_kms:create_kms_app --factory --host 0.0.0.0 --port 8000
# VS Code attach: localhost:5678
```

또는 빠르게: 코드에 `breakpoint()` 삽입 후 `docker compose run --rm --service-ports lucas-kms-api ...` 로 interactive 기동.

## 5. 테스트

```bash
# 전체 (운영 환경에서 추천 안 됨 — DB 영향)
docker compose exec lucas-kms-api pytest tests/ -v

# 특정 영역
docker compose exec lucas-kms-api pytest tests/api/ -v
docker compose exec lucas-kms-api pytest tests/db/ -v
docker compose exec lucas-kms-api pytest tests/integration/lucas_kms/ -v

# perf
docker compose exec lucas-kms-api pytest tests/perf/ -v

# 회귀 (Locus smoke — KMS-only 의 영향 검증)
./scripts/regression/run_smoke.sh
```

또는 호스트에서 (의존성 설치 후):

```bash
uv sync  # pyproject.toml 기준
uv run pytest tests/api/ -v
```

## 6. 성능 측정

```bash
# 기본 시나리오 (5201 staging)
PERF_BASE_URL=http://localhost:5201 \
PERF_TENANT_ID=00000000-0000-0000-0000-000000000001 \
PERF_REPOSITORY_ID=<repo-uuid> \
./scripts/perf/run_benchmark.sh lucas-kms

# 결과: Doc/perf/<timestamp>/compare.md
```

회귀 임계값 — `tests/perf/thresholds.yml`:
- p95 latency +20% 이상 증가 → warning
- p99 latency +50% 이상 증가 → fail

## 7. import 격리 검증 (KMS-only 보장)

```bash
# agent_framework 가 import 되는지 검사
python3 tools/import_audit/audit.py src/api/main_kms.py
# 0 violations 가 정상

# 4-layer artifact scan (운영 이미지 빌드 시)
./tools/docker_scan/scan.sh lucas-kms:latest
```

## 8. Git workflow

| 흐름 | 명령 |
|---|---|
| 일반 commit | `git add ...` → `git commit -m "..."` (이모지 X) |
| github push | `git push origin main` |
| gitlab push (release) | `git push gitlab main:locus-kms-release-1.0` |
| 새 release tag | `git tag -a Locus-KMS<ver> -m "..."` → `git push gitlab Locus-KMS<ver>` |

**금지**:
- `gitlab/main` 으로 force push (별도 langsa 프로젝트 흐름)
- 이모지 commit 메시지
- agent_framework 코드를 본 repo 에 추가
- 두 repo 동시 수정 (AICM-APIs + 본 repo) — *각각 별도 commit*

## 9. AICM-APIs (Locus 본체) 와의 관계

본 repo 와 무관하지만 알아둘 점:
- AICM-APIs 의 `packages/lucas-shared/` 가 본 repo 의 `src/common/` 와 일부 동일 (storage_tenant / time_utils / agent_hook). Phase 3 packaging 완료 후 두 repo 가 동일 패키지 사용 예정.
- 본 repo 에서 `src/common/*.py` 수정 시 AICM-APIs 의 `packages/lucas-shared/src/lucas_shared/*.py` 도 함께 갱신 필요 (수동 sync, 자동 X).
- staging compose 가 AICM-APIs 의 lucas-shared 마운트 — *호스트 전용*.

---

> 추가 디버그 시나리오 발생 시 본 문서 §4.6 에 추가.
