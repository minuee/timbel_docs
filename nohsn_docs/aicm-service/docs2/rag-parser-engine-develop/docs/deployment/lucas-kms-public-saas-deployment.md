# Lucas-KMS — 공공 SaaS 배포 가이드

작성: 2026-05-19
대상: 공공기관 SaaS 도입 운영자 / 통합 파트너 / 인프라 담당
분리 모델: Lucas-KMS *KMS-only* 단독 product (Locus 통합 솔루션과 별개)
기준 spec: `docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md` (rev4)

> Lucas-KMS 는 Locus AI 의 KMS 영역만 분리한 *KMS-only* 단독 product 입니다.
> 기존 Locus 통합 솔루션은 동일 monorepo 에서 별도 빌드 — 본 문서는 공공 SaaS multi-tenant 배포 전용.

---

## 0. 한 줄 요약

```
docker compose -f docker-compose.lucas-kms.yml --env-file .env.lucas-kms up -d
```

- 단일 명령으로 KMS API + 워커 + Postgres + Qdrant + ES + Kafka + Redis + MinIO 기동
- 외부 vLLM endpoint (Gemma-4-31B, 현 터미널링 deployment 그대로 유지) 만 사전 준비
- multi-tenant 가 default. 단일 tenant on-prem 은 `LUCAS_KMS_MODE=single-tenant`

---

## 1. 사전 요구사항

### 1.1 호스트

| 항목 | 권장 | 최소 |
|---|---|---|
| CPU | 16 vCPU | 8 vCPU |
| RAM | 64 GB | 32 GB |
| Disk | NVMe 1TB+ | SSD 500GB |
| Docker | 24.0+ (Compose v2) | 20.10+ |
| OS | Ubuntu 22.04 LTS | Ubuntu 20.04+ |

> Postgres/Qdrant/ES 를 외부 매니지드로 분리하면 호스트 RAM 32 GB 로 충분.

### 1.2 GPU vLLM endpoint (외부)

Lucas-KMS 는 *외부 vLLM endpoint* 에 의존. 본 호스트에 GPU 불필요.

- **모델**: Gemma-4-31B (사용자 명명. 식별자는 현 운영 `VLLM_MODEL` 그대로 — 변경 금지)
- **권장 endpoint**: 현 Locus 운영의 tunneled deployment 를 그대로 재사용 가능. 변경 금지 (사용자 결정 2026-05-19)
- **요구**:
  - HTTPS endpoint (자체서명은 `LUCAS_VLLM_CA_CERT` 로 trust)
  - `/v1/models` health endpoint 응답
  - `/v1/chat/completions` 또는 `/v1/completions` 호환
  - throughput: 단일 tenant 기준 4 concurrent (small) + 1 concurrent (large) 처리 가능

> BGE-M3 임베딩 + reranker 는 본 호스트에서 GPU 로 가동 가능 (RTX 5090 sm_120 cu128) — `.env` 의 `EMBEDDING_DEVICE=cuda`. GPU 없으면 외부 embedding proxy (`EMBEDDING_PROXY_URL`) + reranker (`RERANKER_URL`) 별도 endpoint 필요.

### 1.3 도메인 / TLS

- Lucas-KMS 공인 도메인 1개 (예: `kms.gov-tenant.example.kr`)
- TLS 인증서 (Let's Encrypt 또는 기관 CA)
- 외부 vLLM endpoint 도 HTTPS 필수

### 1.4 데이터 스토어 가용성

본 compose 가 기동하는 컴포넌트 — 외부 매니지드 사용 시 compose 에서 제외하고 endpoint env 만 가리킴:

| 스토어 | compose 기동 | 외부 매니지드 시 env |
|---|---|---|
| PostgreSQL 16 | `lucas-kms-postgres` | `DATABASE_URL` |
| Qdrant 1.12+ | `lucas-kms-qdrant` | `QDRANT_URL` |
| Elasticsearch 8.15 | `lucas-kms-es` | `ELASTICSEARCH_URL` |
| Kafka (KRaft) | `lucas-kms-kafka` | `KAFKA_BOOTSTRAP_SERVERS` |
| Redis 7 | `lucas-kms-redis` | `REDIS_URL` |
| MinIO | `lucas-kms-minio` | `MINIO_ENDPOINT` |

공공 SaaS production 권장: Postgres / ES / Redis 는 매니지드. Qdrant / MinIO / Kafka 는 호스트 또는 별도 클러스터.

---

## 2. 단계별 배포 절차

### 2.1 Repo clone + 환경 변수

```bash
git clone https://github.com/RickySonYH/Lucas-KMS.git
cd Lucas-KMS

# (또는 monorepo 에서 subtree pull 받은 분리 repo 사용)

cp .env.lucas-kms.example .env.lucas-kms
$EDITOR .env.lucas-kms
```

#### 2.1.1 `.env.lucas-kms` 작성 (핵심 항목)

```ini
# === 공통 ===
APP_ENV=production
LOG_LEVEL=INFO
LUCAS_PRODUCT=kms                       # KMS-only 식별 — 워커/팩토리 차단
LUCAS_KMS_MODE=multi-tenant             # multi-tenant | single-tenant

# === Secrets (반드시 신규 생성) ===
SECRET_KEY=<48-byte-random>             # python -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET=<48-byte-random>
CITATION_HMAC_SECRET=<48-byte-random>   # 32 byte+ 필수, startup fail-fast

# === PostgreSQL ===
DATABASE_URL=postgresql+asyncpg://lucas_kms_app:<PW>@lucas-kms-postgres:5432/lucas_kms_db
DATABASE_POOL_SIZE=20
LUCAS_KMS_DB_MIGRATE_USER=lucas_kms_migrate  # DDL/migration 전용 role (NOT app role)

# === Storage ===
QDRANT_URL=http://lucas-kms-qdrant:6333
ELASTICSEARCH_URL=http://lucas-kms-es:9200
KAFKA_BOOTSTRAP_SERVERS=lucas-kms-kafka:9092
REDIS_URL=redis://lucas-kms-redis:6379/0
MINIO_ENDPOINT=lucas-kms-minio:9000
MINIO_ACCESS_KEY=<신규 발급>
MINIO_SECRET_KEY=<신규 발급>

# === 외부 vLLM (Gemma-4-31B, 현 터미널링 그대로 유지) ===
LUCAS_VLLM_ENDPOINT=https://vllm.locus.internal/v1
LUCAS_VLLM_API_KEY=<bearer-token>
LUCAS_VLLM_MODEL_REVISION=<현 운영의 VLLM_MODEL 값 그대로>
LUCAS_VLLM_CA_CERT=                      # 자체서명 시 경로
LUCAS_VLLM_MAX_CONCURRENT=8
LUCAS_VLLM_TIMEOUT_TOTAL_MS=60000
LUCAS_VLLM_TIMEOUT_CONNECT_MS=5000
LUCAS_VLLM_RETRY_MAX=3
LUCAS_VLLM_CIRCUIT_FAILURE_RATE=0.5
LUCAS_VLLM_CIRCUIT_OPEN_SECS=30

# 기존 키 fallback (legacy 호환 — 미설정 시 위 LUCAS_VLLM_* 사용)
VLLM_URL=
VLLM_MODEL=

# === 임베딩 / Reranker (호스트 GPU 또는 외부 proxy) ===
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DEVICE=cuda                   # GPU 없으면 EMBEDDING_PROXY_URL 사용
EMBEDDING_PROXY_URL=                    # 외부 proxy 시 채움
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_URL=                           # 외부 reranker 시 채움

# === Swagger 보안 (Section 3.4) ===
ENABLE_SWAGGER=false                    # production default
SWAGGER_AUTH_MODE=jwt                   # none | basic | jwt
SWAGGER_IP_ALLOWLIST=                   # CIDR comma-sep — 공공 SaaS 는 명시

# === CORS ===
CORS_ORIGINS=https://kms.gov-tenant.example.kr

# === Upload ===
MAX_UPLOAD_SIZE_MB=100                  # nginx 와 동기화
UPLOAD_DIR=/data/uploads

# === Feature flags ===
FEATURE_LLM=true
FEATURE_SOP_RAG=false                   # KMS-only — SOP inject 비활성 (agent 없음)
ENABLE_INTENT_CLASSIFICATION=true
```

#### 2.1.2 비밀 생성 명령 (운영자용)

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"  # SECRET_KEY / JWT_SECRET / CITATION_HMAC_SECRET
openssl rand -base64 32                                       # API key / token
```

> `grep -E '(CHANGE_ME|<.+>|^$)' .env.lucas-kms` 결과 *비어 있어야* deploy 가능.

### 2.2 Docker 기동

```bash
docker compose -f docker-compose.lucas-kms.yml --env-file .env.lucas-kms up -d
docker compose -f docker-compose.lucas-kms.yml ps
```

기동 순서 (compose `depends_on` healthcheck 기반):
1. `lucas-kms-postgres` / `lucas-kms-qdrant` / `lucas-kms-es` / `lucas-kms-kafka` / `lucas-kms-redis` / `lucas-kms-minio`
2. `lucas-kms-api` (uvicorn + `src.api.main_kms:create_kms_app`)
3. `lucas-kms-pipeline-worker-large` (chunk/embed/block — 외부 vLLM 호출)
4. `lucas-kms-pipeline-worker-small` (DLQ scheduler + cleanup)
5. `lucas-kms-frontend` (nginx + frontend-v1 KMS patch)

### 2.3 Alembic migration 적용

> rev4 시점은 통합 Alembic history 사용 — Phase 2 multi-branch 도입 전. KMS-only 컨테이너의 `LUCAS_PRODUCT=kms` env 가 KMS 모델만 적용하도록 `tools/alembic_audit/` 가 검증.

```bash
# 첫 deploy 또는 schema upgrade
docker compose -f docker-compose.lucas-kms.yml run --rm \
  -e DATABASE_URL="<migrate role URL>" \
  lucas-kms-api alembic upgrade head

# Multi-branch 도입 후 (Phase 2 완료 시)
# docker compose ... alembic upgrade shared@head kms@head
```

검증:

```bash
docker compose exec lucas-kms-postgres \
  psql -U lucas_kms_app -d lucas_kms_db -c "\dt" \
  | tee /tmp/lucas_kms_tables.txt

# agent_* / chat_* / scheduled_actions 등 agent table 0건 확인
grep -cE "^public\.(agents|agent_channels|custom_tools|scheduled_actions|lifecycle_feedback)" /tmp/lucas_kms_tables.txt
# 기대: 0
```

### 2.4 시드 데이터 (tenant + admin user)

`scripts/seed/admin_inventory.py` 가 tenant + admin user + 기본 repo + JWT 발급 일괄 처리.

```bash
docker compose exec lucas-kms-api python -m scripts.seed.admin_inventory \
  --tenant-slug gov-tenant-a \
  --tenant-name "공공기관 A" \
  --admin-email admin@gov-tenant-a.example.kr \
  --admin-password '<강력한 임시 PW — 첫 로그인 시 변경>' \
  --enable-rls \
  --create-default-repo
```

출력:
- `tenant_id` (UUID)
- `admin_user_id`
- 첫 JWT token (24h)
- default repo UUID

> Output 은 *반드시* 운영자 비밀번호 보관소에 즉시 이관 후 터미널 scrollback 삭제.

### 2.5 healthz / readyz 확인

```bash
# 호스트에서 직접
curl -sf http://localhost:5101/healthz
# {"status":"ok","ts":"..."}

curl -sf http://localhost:5101/readyz
# {"db":"ok","qdrant":"ok","es":"ok","kafka":"ok","redis":"ok","minio":"ok","vllm":"ok"}

# 도메인 (nginx 경유)
curl -sf https://kms.gov-tenant.example.kr/healthz
```

`readyz` 의 *하나라도* `not_ok` 면 docker logs 로 해당 service 확인. vLLM `not_ok` 시 Section 6.3 참조.

### 2.6 첫 PDF 업로드 smoke

```bash
TOKEN="<2.4 단계의 JWT>"
curl -sf -X POST https://kms.gov-tenant.example.kr/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sample-30p.pdf" \
  -F "repository_id=<default repo UUID>"

# 처리 진행
curl -sf https://kms.gov-tenant.example.kr/api/v1/documents/<doc_id> \
  -H "Authorization: Bearer $TOKEN" \
  | jq .status
# 기대 전이: uploaded → parsing → segmenting → embedding → pending_review → active
```

30p PDF active 도달 기준: 3-5분 (외부 vLLM 정상 가용 시).

---

## 3. 네트워크 / TLS / 보안

### 3.1 nginx reverse proxy

`nginx.conf` (호스트 또는 ingress) — `MAX_UPLOAD_SIZE_MB` 와 `client_max_body_size` 동기화 필수.

```nginx
server {
  listen 443 ssl http2;
  server_name kms.gov-tenant.example.kr;

  ssl_certificate     /etc/letsencrypt/live/kms.gov-tenant.example.kr/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/kms.gov-tenant.example.kr/privkey.pem;
  ssl_protocols TLSv1.2 TLSv1.3;

  client_max_body_size 100m;            # MAX_UPLOAD_SIZE_MB 와 동일
  proxy_read_timeout 90s;
  proxy_send_timeout 90s;

  # API
  location /api/ {
    proxy_pass http://127.0.0.1:5101;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Real-IP $remote_addr;
  }

  # SSE — assist-stream 등
  location /api/v1/rag/assist-stream {
    proxy_pass http://127.0.0.1:5101;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding off;
  }

  # Frontend (V1 KMS patch)
  location / {
    proxy_pass http://127.0.0.1:5100;
  }

  # Swagger — production 은 차단 또는 IP allowlist
  location ~ ^/api/v1/(docs|openapi.json|redoc) {
    allow 10.0.0.0/8;                    # 사무망
    allow 192.168.0.0/16;                # 운영망
    deny all;
    proxy_pass http://127.0.0.1:5101;
  }
}

server {
  listen 80;
  server_name kms.gov-tenant.example.kr;
  return 301 https://$host$request_uri;
}
```

### 3.2 TLS 인증서 갱신

Let's Encrypt 사용 시:

```bash
certbot renew --quiet --post-hook "nginx -s reload"
# crontab: 0 3 * * * /usr/bin/certbot renew --quiet --post-hook "/usr/sbin/nginx -s reload"
```

기관 CA 인증서는 만료 30일 전 알람 (Prometheus blackbox exporter `probe_ssl_earliest_cert_expiry`).

### 3.3 IP allowlist (공공 SaaS)

- API: 사무망 + 모바일 VPN (가능 시)
- Swagger: 운영망만
- Admin UI: 사무망 + 운영 담당자 VPN
- 외부 vLLM endpoint: outbound 만, IP 고정

iptables / cloud security group 의 ingress rule 도 매뉴얼 보관.

### 3.4 Swagger 보안

`spec rev4 §5.2` 의 표 그대로 적용:

| 환경 | `ENABLE_SWAGGER` | `SWAGGER_AUTH_MODE` | `SWAGGER_IP_ALLOWLIST` |
|---|---|---|---|
| dev / staging | `true` | `none` | (비움) |
| public SaaS prod | `true` | `jwt` | 운영망 CIDR |
| single-tenant on-prem | `false` (default) | `basic` (활성 시) | 명시 |

JWT 모드는 `Authorization: Bearer <admin JWT>` 필요. `401` 시 docs 노출 안 됨.

### 3.5 JWT 정책

- 발급 주체: Lucas-KMS API `POST /api/v1/auth/login`
- 만료: `JWT_EXPIRE_MINUTES=60` (1h). refresh token 7일 (별도 endpoint)
- 권한: `super_admin` / `tenant_admin` / `operator` / `viewer`
- 모든 query 에 tenant_id 자동 적용 (RLS context)

### 3.6 RLS (Row-Level Security)

`spec rev4 §8.1` 적용:

- 모든 tenant-scoped table 에 `FORCE ROW LEVEL SECURITY`
- app role: `lucas_kms_app` (`NOSUPERUSER` + `NOBYPASSRLS` + non-owner)
- migration role: `lucas_kms_migrate` (owner) — runtime 사용 금지
- session 진입부에 `SET LOCAL app.current_tenant_id = '<tenant_uuid>'`
- default deny: tenant_id 미설정 시 0 행 반환

검증:

```bash
docker compose exec lucas-kms-postgres psql -U lucas_kms_app -d lucas_kms_db \
  -c "SELECT count(*) FROM documents;"
# tenant_id 미설정 → 0 (RLS 정상)
```

### 3.7 Audit log

- 모든 admin 변경 / LLM 호출 / 검색 → `audit_logs` 테이블
- `(tenant_id, actor_id, action, target, latency_ms, status, request_id, ts)`
- LLM 호출은 PII redact filter 적용 후 저장 (이메일/주민/카드 패턴)
- 보관: 1년 (압축 후 cold storage 이관 옵션)

---

## 4. 모니터링

### 4.1 Prometheus + Grafana

`docker-compose.lucas-kms.yml` 의 선택 service:

```yaml
  lucas-kms-prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./monitoring/prometheus.lucas-kms.yml:/etc/prometheus/prometheus.yml
    ports: ["9090:9090"]

  lucas-kms-grafana:
    image: grafana/grafana:latest
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PW}
    volumes:
      - grafana-data:/var/lib/grafana
    ports: ["3000:3000"]
```

Prometheus scrape targets:
- `lucas-kms-api:8000/metrics`
- `lucas-kms-pipeline-worker-large:9000/metrics`
- `lucas-kms-pipeline-worker-small:9000/metrics`
- 외부 vLLM 의 `/metrics` (옵션)

### 4.2 핵심 alert (Locus 매뉴얼과 동일 — KMS 영역만)

| Alert | 조건 | 심각도 |
|---|---|---|
| `lucas_kms_api_down` | up == 0 for 1m | critical |
| `lucas_kms_kafka_consumer_lag_high` | split topic lag > 30 for 5m | warning |
| `lucas_kms_dlq_depth_high` | dlq_messages > 10 | warning |
| `lucas_kms_vllm_failure_rate_high` | rate(vllm_errors_total[5m]) > 0.05 | critical |
| `lucas_kms_vllm_circuit_open` | circuit_state == open for 1m | critical |
| `lucas_kms_doc_stuck_parsing` | docs in parsing > 60m | warning |
| `lucas_kms_db_connections_high` | pg_stat_activity.count > 80% pool | warning |
| `lucas_kms_disk_usage_high` | disk_free < 20% | critical |

### 4.3 대시보드

기존 `monitoring/grafana/dashboards/` 의 KMS 패널 재활용. Lucas-KMS 전용 dashboard:
- API latency p50/p95/p99
- Pipeline duration per stage (parsing/segmenting/embedding)
- Kafka lag per topic
- vLLM call latency + failure rate + circuit state
- Tenant 별 활성 doc 수 / search QPS

---

## 5. 사고 회복

### 5.1 DLQ 회복

```bash
# DLQ 적재 확인
docker compose exec lucas-kms-api python -m scripts.maintenance.dlq_inspect

# 단일 doc 재시도
curl -X POST https://kms.gov-tenant.example.kr/api/v1/documents/<doc_id>/retry \
  -H "Authorization: Bearer $TOKEN"

# 전체 tenant DLQ flush (운영자 명시 결정 후만)
docker compose exec lucas-kms-api python -m scripts.maintenance.dlq_flush \
  --tenant-id <uuid> --dry-run
# 검토 후 --dry-run 제거
```

### 5.2 consumer 재시작

```bash
# 단일 worker 재시작 (partition rebalance — split topic 점유 바뀜)
docker compose restart lucas-kms-pipeline-worker-large

# 전체 재시작 (최후)
docker compose -f docker-compose.lucas-kms.yml restart
```

`consumer_supervisor_restart` 가 시간당 3회 이상이면 root cause 조사 (vLLM timeout / DB connection saturation).

### 5.3 vLLM endpoint 변경

운영 중 vLLM endpoint 교체 (예: B200 tunnel 변경):

```bash
# 1. circuit breaker 강제 open (현 endpoint 트래픽 차단)
curl -X POST https://kms.gov-tenant.example.kr/api/v1/admin/vllm/circuit \
  -H "Authorization: Bearer $SUPER_ADMIN_TOKEN" \
  -d '{"action":"open"}'

# 2. .env.lucas-kms 의 LUCAS_VLLM_ENDPOINT 수정

# 3. API + 워커 재기동 (rolling 권장)
docker compose -f docker-compose.lucas-kms.yml up -d --no-deps --build lucas-kms-api
docker compose -f docker-compose.lucas-kms.yml restart lucas-kms-pipeline-worker-large

# 4. health 확인
curl -sf https://kms.gov-tenant.example.kr/readyz | jq .vllm
# {"vllm":"ok"}

# 5. circuit breaker 자동 half-open (30s) → closed
```

> 모델 식별자 (`LUCAS_VLLM_MODEL_REVISION`) mismatch 시 startup fail. 변경 시 함께 update.

### 5.4 Postgres 장애

- replica 가용 시 자동 failover. `DATABASE_URL` host 가 endpoint (DNS / pgbouncer)
- 단일 노드 장애: snapshot 복구 (Section 6 백업)
- 복구 후 Alembic head 확인: `alembic current` == 기대 revision

### 5.5 전체 stack 재시작

```bash
# 최후 절차 — 데이터 손실 없음 (volume 보존)
docker compose -f docker-compose.lucas-kms.yml down
docker compose -f docker-compose.lucas-kms.yml --env-file .env.lucas-kms up -d
```

기동 후 readyz 모두 `ok` 까지 평균 60-90초.

---

## 6. 백업 / 복구

### 6.1 백업 주기

| 자원 | 주기 | 보관 | 도구 |
|---|---|---|---|
| PostgreSQL | 1h rolling + 일 단위 7일 | 30일 | `pg_dump` / `pgBackRest` |
| Qdrant | 12h | 14일 | snapshot REST API |
| Elasticsearch | 12h | 14일 | snapshot repository |
| MinIO (documents bucket) | 6h | 90일 | `mc mirror` 또는 S3 versioning |
| MinIO (intermediate bucket) | 보관 X | — | 색인 후 cleanup |
| Redis | 백업 X (cache only) | — | — |
| Kafka | 백업 X (event stream) | — | retention 7일 |

### 6.2 백업 스크립트

```bash
# Postgres
docker compose exec lucas-kms-postgres pg_dump -U lucas_kms_app lucas_kms_db \
  | gzip > /backup/postgres/lucas-kms-$(date +%Y%m%d-%H%M).sql.gz

# Qdrant snapshot
curl -X POST http://localhost:5111/collections/<collection>/snapshots

# ES snapshot (repository 사전 등록 필요)
curl -X PUT "http://localhost:5113/_snapshot/lucas-kms/snap-$(date +%Y%m%d-%H%M)?wait_for_completion=true"

# MinIO
mc mirror lucas-kms-minio/lucas-<tenant_id>-documents /backup/minio/<tenant_id>/
```

`scripts/backup.sh` 가 모두 자동 — cron 으로 호스트에 설치:

```cron
0 * * * *  /opt/lucas-kms/scripts/backup.sh postgres-hourly
0 */12 * * *  /opt/lucas-kms/scripts/backup.sh qdrant es
0 */6 * * *  /opt/lucas-kms/scripts/backup.sh minio
```

### 6.3 복구

```bash
# Postgres 시점 복구
gunzip < /backup/postgres/lucas-kms-20260519-0300.sql.gz \
  | docker compose exec -T lucas-kms-postgres psql -U lucas_kms_migrate -d lucas_kms_db_restore

# Qdrant snapshot 복구
curl -X PUT http://localhost:5111/collections/<collection>/snapshots/upload \
  -F "snapshot=@/backup/qdrant/snap-20260519-0300.snapshot"

# 색인 재구축 (Postgres 만 복구 시)
docker compose exec lucas-kms-api python -m scripts.maintenance.reindex_all \
  --tenant-id <uuid>
```

복구 리허설은 분기 1회 (`docs/operations/dr-rehearsal-2026-04-25.md` 양식 활용).

---

## 7. 보안 체크리스트

- [ ] `.env.lucas-kms` 의 모든 secret 신규 발급 (CHANGE_ME 0건)
- [ ] `.env.lucas-kms` 가 `.gitignore` 에 포함
- [ ] Postgres app role 이 `NOBYPASSRLS` (`SELECT rolbypassrls FROM pg_roles` → false)
- [ ] migration role 과 app role 분리 (runtime 은 app role 만)
- [ ] Swagger production 미노출 또는 JWT + IP allowlist
- [ ] TLS 인증서 만료 30일 전 알람 설정
- [ ] 외부 vLLM endpoint HTTPS (또는 사설 VPN 내)
- [ ] `CITATION_HMAC_SECRET` 32 byte 이상 + startup 검증 통과
- [ ] audit_logs 의 PII redact filter 동작 확인 (이메일/주민/카드 패턴)
- [ ] 모든 admin 권한 사용자 2FA (외부 SSO 연동 시)
- [ ] backup 무결성 분기 1회 복구 리허설 통과
- [ ] DR runbook 운영팀 공유 (이 문서 + multi-tenant + perf-baseline)

---

## 8. 운영자 일일 체크리스트

- [ ] `curl /readyz` 모든 컴포넌트 `ok`
- [ ] DLQ depth < 10
- [ ] consumer lag < 30 (split / part_ready / embed topic)
- [ ] failed status doc 없음 (또는 운영자 확인 완료)
- [ ] vLLM heartbeat OK + 외부 endpoint 응답
- [ ] 디스크 사용률 < 70%
- [ ] 백업 cron 마지막 성공 시각 확인

---

## 9. References

- 분리 spec: `docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md` (rev4)
- 통합 솔루션 운영 매뉴얼: `Doc/solution/2026-05-19-locus-admin-manual.md`
- multi-tenant 운영: `docs/deployment/lucas-kms-public-saas-multi-tenant.md`
- 성능 기준선: `docs/deployment/lucas-kms-public-saas-perf-baseline.md`
- KMS-only 운영자 매뉴얼: `docs/deployment/lucas-kms-operator-manual.md`
- 통합 솔루션 release-checklist (참고): `docs/operations/release-checklist.md`
- 통합 솔루션 secrets-setup (참고): `docs/operations/secrets-setup.md`
- 통합 솔루션 TLS/nginx (참고): `docs/operations/tls-nginx.md`
- DR 리허설 양식: `docs/operations/dr-rehearsal-2026-04-25.md`
