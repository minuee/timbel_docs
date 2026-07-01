# Locus-KMS — QUICKSTART (정직 체크리스트)

> 본 폴더만 가져가면 *대부분* 작동합니다. 단, 아래 사전 점검 + .env 값 설정 필수.

## 1. 사전 요구사항

| 항목 | 필수도 | 설명 |
|---|---|---|
| Docker + docker-compose v2 | **필수** | 컨테이너 구동 |
| NVIDIA Container Toolkit | mode B 필수 | 자체 GPU 사용 시 |
| 외부 vLLM endpoint 또는 GPU | **필수** | 둘 중 하나 |
| HuggingFace token | mode B 필수 | gemma-4-31b 모델 다운로드 |
| 디스크 공간 | 50GB+ | image (8GB) + 모델 cache + 데이터 |

## 2. 배포 모드 선택

### 모드 A — 외부 vLLM endpoint 사용 (예: 기존 SSH tunnel, 외부 GPU 서버)
- 가벼움 (자체 GPU 불필요)
- `.env` 의 `VLLM_URL` 을 외부 endpoint 로 설정
- 명령: `docker compose up -d`

### 모드 B — 자체 NVIDIA GPU 보유 (customer site)
- 컨테이너 내부에 vllm + reranker 동시 기동
- `HF_TOKEN` 필수 (HuggingFace 모델 다운로드)
- 명령: `docker compose --profile local-llm up -d`

## 3. 단계별 setup

### Step 1 — .env 작성

```bash
cp .env.example .env
```

**반드시 수정할 키** (비밀번호 강화 + endpoint):

```env
# 비밀번호 (강한 값으로 교체)
POSTGRES_PASSWORD=<openssl rand -hex 24>
KMS_APP_PASSWORD=<openssl rand -hex 24>
KMS_SUPERADMIN_PASSWORD=<openssl rand -hex 24>
MINIO_ROOT_PASSWORD=<openssl rand -hex 24>
JWT_SECRET_KEY=<openssl rand -hex 48>
CITATION_HMAC_SECRET=<openssl rand -hex 32>

# 운영 보안
LUCAS_AUTH_DISABLED=false   # 운영 시 false (인증 활성). 내부 테스트는 true.
ENV=prod
ENABLE_SWAGGER=false        # 운영 시 비활성. 또는 SWAGGER_AUTH_MODE=jwt + IP allowlist

# vLLM (모드 A 외부 endpoint)
VLLM_URL=http://<your-vllm-host>:<port>/v1   # 또는 default 유지 시 host.docker.internal:7120

# 모드 B 사용 시 추가
# VLLM_URL=http://vllm:8000/v1
# RERANKER_URL=http://reranker:8000/rerank
# HF_TOKEN=hf_xxxxx
```

### Step 2 — 기동

```bash
# 모드 A
docker compose up -d

# 모드 B (자체 GPU)
docker compose --profile local-llm up -d
```

### Step 3 — healthz 확인

```bash
sleep 30
curl http://localhost:5101/health
# {"status":"ok"}
```

### Step 4 — DB init + default tenant

migrate 컨테이너가 자동으로 `scripts/init_db.py` 호출해 schema + default tenant 생성.
실패 시 수동:

```bash
docker compose exec lucas-kms-api python3 scripts/init_db.py
docker compose exec lucas-kms-postgres psql -U kms -d kms_pipeline -c "
INSERT INTO tenants (id, name, slug, config, plan, tenant_type, context_config, feature_flags)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default', 'default', '{}', 'standard', 'personal', '{}', '{}')
ON CONFLICT (id) DO NOTHING;
"
```

### Step 5 — 사용 시작

- Swagger UI: http://localhost:5101/docs
- API 사용 가이드: `docs/api/lucas-kms-api-reference.md` (curl/Python/JS 예시 — §3a Repository Groups 포함)
- 운영자 매뉴얼: `docs/deployment/lucas-kms-operator-manual.md`

## 4. 알려진 한계 (정직 보고)

| 한계 | 영향 | 대응 |
|---|---|---|
| **alembic upgrade head — fresh DB 에서 user_role_enum 이중 생성 버그** | DB init 실패 | migrate 가 init_db.py (SQLAlchemy create_all) 사용 — 자동 우회 |
| **fresh 배포 시 테넌트 에러 (구 결함, 2026-05-21 fix)** | 무인증 모드 write 가 FK 위반(테넌트 에러). 과거엔 DB 수동 INSERT 로 우회 | ① `init_db.py` 가 `settings.LUCAS_DEFAULT_TENANT_ID`(`...0001`) 로 시드 (구: `...0000` 하드코딩) ② `models/__init__` 이 `Agent` 모델 등록 → `create_all` dangling FK 해소 (구: `agent_documents→agents` NoReferencedTableError). 회귀: `tests/db/test_default_tenant_seed_consistency.py` |
| **host.docker.internal** Linux 일반 환경에서 미해석 가능 | mode A 의 default endpoint 작동 X | docker-compose.yml 의 api 서비스에 `extra_hosts: ["host.docker.internal:host-gateway"]` 추가됨 OR `VLLM_URL=http://<실 IP>:port/v1` 직접 명시 |
| **kms_app role 권한 미설정 시 (RLS 환경)** | API 호출 시 permission denied | init_db.py 가 role 생성 + GRANT 수행. 만약 fresh fresh DB 면 수동 GRANT 필요 |
| **packages/ 전면 refactor 미진행** | agent_framework 코드가 image 에 *물리적으로 존재* (단, runtime 미사용) | .dockerignore 로 build context 에서 제외됨. import-linter 가 0 import 보장 |
| **csap_table 시나리오 측정 시 +63%** | 특정 query 의 latency 증가 (data 부족 시) | 운영 데이터 충분히 시드되면 해소 |

## 5. 트러블슈팅

### "permission denied for table X"
→ kms_app role 권한 부족. staging fix 절차 참조:
```bash
docker compose exec lucas-kms-postgres psql -U <pg_user> -d <db> -c "
ALTER ROLE kms_app BYPASSRLS;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO kms_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO kms_app;"
```

### "user_role_enum already exists"
→ alembic 이 enum 이중 생성. **migrate 가 init_db.py 사용 중인지 확인**.

### fresh 배포 후 테넌트 에러 / "tenant ... not found" / FK 위반 (write 시)
→ default tenant(`...0001`) 미시드. 2026-05-21 이후 빌드는 `init_db.py` 가 자동 시드하므로 발생 안 함. 구버전 DB 거나 수동 schema dump 로 만든 경우 다음으로 확인·복구:
```bash
# 1) default tenant 존재 확인
docker compose exec lucas-kms-postgres psql -U <pg_user> -d <db> -c \
  "SELECT id, name FROM tenants WHERE id = '00000000-0000-0000-0000-000000000001';"
# 2) 없으면 init_db.py 재실행 (idempotent)
docker compose exec lucas-kms-api python3 scripts/init_db.py
```
→ `create_all` 단계에서 `NoReferencedTableError: ... agent_documents.agent_id ... agents` 가 뜨면, `src/core/models/__init__` 이 `Agent` 모델을 import 하는지 확인 (KMS-only 스키마 정합성).

### "host.docker.internal: Name or service not known"
→ Linux 환경. docker-compose 의 api 서비스에 추가:
```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```
또는 .env 의 VLLM_URL 을 실 IP 로 변경.

### vLLM 응답 없음 (mode A)
→ SSH tunnel 또는 외부 endpoint 가 살아있는지 확인:
```bash
curl http://<VLLM_URL host:port>/v1/models
```

### Swagger 가 안 보임
→ `.env` 의 `ENABLE_SWAGGER=true` 또는 `LUCAS_AUTH_DISABLED=true` 확인. 운영 모드면 의도된 동작.

## 6. 성능 측정 (선택)

```bash
# benchmark
PERF_BASE_URL=http://localhost:5101 \
PERF_TENANT_ID=00000000-0000-0000-0000-000000000001 \
PERF_REPOSITORY_ID=<your-repo-uuid> \
./scripts/perf/run_benchmark.sh lucas-kms

# 결과: Doc/perf/<timestamp>/compare.md
```

## 7. 운영 전 마지막 체크리스트

- [ ] `.env` 의 모든 비밀번호 강한 값 (`change-me`, `kms_dev_password` 등 default 제거)
- [ ] `LUCAS_AUTH_DISABLED=false` + `ENV=prod`
- [ ] `ENABLE_SWAGGER=false` (또는 SWAGGER_AUTH_MODE=jwt)
- [ ] TLS / reverse proxy (nginx) 설정
- [ ] PostgreSQL backup 정책
- [ ] Qdrant snapshot 정책
- [ ] MinIO bucket 영속화 확인
- [ ] Kafka topic retention
- [ ] vLLM endpoint 가용성 (mode A) 또는 GPU/HF_TOKEN (mode B)
- [ ] 모니터링 (Prometheus 메트릭 `/metrics` 노출 — 운영 시 추가)

---

**결론**: 본 폴더 + .env 작성 + Step 1-5 따라가면 작동. 알려진 한계 (#4) 와 트러블슈팅 (#5) 참조.

문제 발생 시 staging 환경 (port 5201, 가동 중) 의 fix 절차를 참조 가능.
