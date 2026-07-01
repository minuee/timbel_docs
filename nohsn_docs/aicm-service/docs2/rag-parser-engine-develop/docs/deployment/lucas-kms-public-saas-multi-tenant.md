# Lucas-KMS — 공공 SaaS Multi-Tenant 운영

작성: 2026-05-19
대상: SaaS 운영자 (super admin) / tenant 관리자
연계: `lucas-kms-public-saas-deployment.md`, spec rev4 §8 (Multi-Store Tenant Isolation)

> Lucas-KMS 의 *default 운영 모드는 multi-tenant*. 본 문서는 tenant 생성, 격리 검증, 권한 분리, 쿼터 관리 절차.

---

## 0. 모델 — 격리는 어느 레이어에서 일어나는가

| 레이어 | 격리 메커니즘 |
|---|---|
| **PostgreSQL** | RLS `FORCE ROW LEVEL SECURITY` + `SET LOCAL app.current_tenant_id` |
| **Qdrant** | Collection naming `lucas_{tenant_id}_{repo_id}` + must filter `tenant_id` |
| **Elasticsearch** | Index naming `lucas-{tenant_id}-{repo_id}` + alias `lucas-{tenant_id}-*` |
| **MinIO** | Bucket naming `lucas-{tenant_id}` + IAM policy or prefix |
| **Redis** | Key namespace `lucas:{tenant_id}:*` (shared = `lucas:_shared:*`) |
| **Kafka** | Topic naming `aicm.document.*` 유지 + message body 의 `tenant_id` 필수 + consumer 가 RLS context 설정 |
| **DLQ** | 단일 `dlq_messages` table + `tenant_id` 컬럼 + RLS + scheduler 의 per-tenant isolation |

*다층 방어* — 한 레이어가 깨져도 다른 레이어가 막음. 그러나 *모두 적용 확인* 이 운영자 책임.

---

## 1. Tenant 생성

### 1.1 신규 tenant 절차

`scripts/seed/admin_inventory.py` 가 모든 레이어를 일괄 셋업.

```bash
docker compose -f docker-compose.lucas-kms.yml exec lucas-kms-api \
  python -m scripts.seed.admin_inventory \
    --tenant-slug gov-tenant-b \
    --tenant-name "공공기관 B" \
    --admin-email admin@gov-tenant-b.example.kr \
    --admin-password '<강력 임시 PW>' \
    --enable-rls \
    --create-default-repo \
    --minio-create-bucket \
    --qdrant-warmup
```

수행 내용 (순서):
1. Postgres `tenants` row insert + `tenant_id` UUID 생성
2. RLS context 검증 (`SET LOCAL app.current_tenant_id` 후 isolation 동작)
3. MinIO bucket `lucas-{tenant_id}` 생성 + policy 적용
4. Qdrant collection naming 예약 (실제 collection 은 첫 repo 생성 시 자동)
5. ES index naming 예약
6. Redis namespace 예약 (`lucas:{tenant_id}:_init` 키 1회 set/delete 로 권한 검증)
7. `users` admin row insert + 첫 JWT 발급 (24h, 첫 로그인 시 비번 변경 강제)
8. `audit_logs` 에 `tenant_created` event 기록

출력 (반드시 즉시 보관):

```
tenant_id: 7c4e2d1a-3f81-4f2b-9a6c-8e3d2f1a4b5c
admin_user_id: 9b8a7c6d-5e4f-3a2b-1c9d-8e7f6a5b4c3d
admin_jwt: eyJhbGc...
default_repo_id: f1e2d3c4-b5a6-9788-7f6e-5d4c3b2a1098
minio_bucket: lucas-7c4e2d1a-...
```

### 1.2 Tenant 삭제 (irreversible)

```bash
docker compose exec lucas-kms-api \
  python -m scripts.maintenance.tenant_delete \
    --tenant-id <uuid> \
    --confirm-tenant-slug gov-tenant-b \
    --dry-run

# 검토 후 --dry-run 제거
# 1. 모든 doc archive
# 2. Qdrant collection drop (lucas_{tenant_id}_*)
# 3. ES index delete (lucas-{tenant_id}-*)
# 4. MinIO bucket delete (lucas-{tenant_id})
# 5. Redis namespace flush (lucas:{tenant_id}:*)
# 6. Postgres soft delete (audit retention 위해 hard delete 금지)
# 7. audit_logs 에 tenant_deleted event
```

법적 보관 의무 만료 후 별도 hard delete 절차 (cold storage 포함).

---

## 2. 격리 검증

### 2.1 cross-tenant 0 hit — 회귀 시나리오

운영 중 분기 1회 + 신규 tenant 추가 시 매번:

```bash
# tenant A 에 doc 업로드 + active
TENANT_A_TOKEN="<A admin JWT>"
DOC_A_ID=$(curl -sf -X POST .../api/v1/documents/upload \
  -H "Authorization: Bearer $TENANT_A_TOKEN" \
  -F "file=@sample.pdf" -F "repository_id=<A repo>" | jq -r .id)

# active 대기 (max 10분)
until curl -sf .../api/v1/documents/$DOC_A_ID -H "Authorization: Bearer $TENANT_A_TOKEN" | jq -e '.status == "active"'; do
  sleep 30
done

# tenant B 의 검색에 hit 0 검증
TENANT_B_TOKEN="<B admin JWT>"
curl -sf -X POST .../api/v1/search \
  -H "Authorization: Bearer $TENANT_B_TOKEN" \
  -d '{"query":"<A doc 의 고유 문구>","top_k":10}' \
  | jq '.results | length'
# 기대: 0
```

### 2.2 자동 회귀 테스트

```bash
pytest tests-integration/lucas_kms/test_multi_tenant_isolation.py -v
```

테스트 케이스 (현 spec rev4 §12.2 시나리오 5):
- A 의 doc → B 의 `/search` 0 hit
- A 의 doc → B 의 `/rag` 0 hit
- A 의 chunk_id → B 의 `/chunks/{id}` 403/404
- A 의 citation HMAC token → B 의 viewer 403
- A 의 MinIO presigned URL → B 의 fetch 403
- Kafka message 의 `tenant_id` 위조 시 worker reject

매 PR CI gate. local 회귀:

```bash
docker compose -f docker-compose.lucas-kms.yml exec lucas-kms-api \
  pytest tests-integration/lucas_kms/test_multi_tenant_isolation.py -v --tb=short
```

### 2.3 레이어별 isolation 점검

| 레이어 | 명령 | 기대 |
|---|---|---|
| Postgres RLS | `SELECT count(*) FROM documents;` (tenant_id 미설정) | 0 |
| Postgres RLS | `SET LOCAL app.current_tenant_id='<A>'; SELECT count(*) FROM documents WHERE tenant_id='<B>';` | 0 |
| Qdrant | `curl http://qdrant:6333/collections` 의 naming | `lucas_<tenant>_<repo>` 만 |
| ES | `curl http://es:9200/_cat/indices?v` | `lucas-<tenant>-*` 만 |
| MinIO | `mc ls lucas-kms-minio/` | `lucas-<tenant>` 만 |
| Redis | `redis-cli --scan --pattern 'lucas:*'` 의 prefix | `lucas:<tenant>:*` 또는 `lucas:_shared:*` |
| Kafka | 임의 consumer 가 `aicm.document.*` 의 message 1건 peek 후 `tenant_id` field 존재 | 모든 message 에 `tenant_id` |
| DLQ | `SELECT tenant_id, count(*) FROM dlq_messages GROUP BY tenant_id` | 각 tenant 별 별도 row |

### 2.4 write path 회귀 (rev4 §8.1 명시)

read-only RLS 만으로는 부족 — write 도 회귀.

```bash
pytest tests-integration/lucas_kms/test_rls_write_path.py -v
```

테스트:
- tenant A context 에서 `INSERT documents (tenant_id=B)` → policy violation
- tenant A context 에서 `UPDATE documents SET title='x' WHERE tenant_id=B` → 0 rows affected (RLS hide)
- tenant A context 에서 `DELETE FROM chunks WHERE document_id IN (B 의 doc)` → 0 rows affected

---

## 3. 운영자 권한 분리

### 3.1 역할 매트릭스

| 역할 | 범위 | 권한 |
|---|---|---|
| **super_admin** | 모든 tenant + 시스템 | tenant CRUD, vLLM config, 글로벌 alert, audit_logs 전체 조회 |
| **tenant_admin** | 단일 tenant | tenant 내 user/repo/doc CRUD, tenant audit_logs 조회 |
| **operator** | 단일 tenant | repo 내 doc upload/review/archive, search 사용 |
| **viewer** | 단일 tenant | search 만 사용 (등록/수정 불가) |

### 3.2 권한 부여

```bash
# super_admin → tenant_admin 발급
docker compose exec lucas-kms-api \
  python -m scripts.seed.user_create \
    --tenant-id <uuid> \
    --email ops@gov-tenant-a.example.kr \
    --role tenant_admin

# tenant_admin → operator/viewer 발급 (Admin UI 사용 권장)
# Admin UI → Users → "+ Add" → 역할 선택
```

### 3.3 권한 검증

```bash
# viewer 가 upload 시도 → 403
curl -X POST .../api/v1/documents/upload \
  -H "Authorization: Bearer $VIEWER_TOKEN" \
  -F "file=@x.pdf"
# {"detail":"forbidden","required_role":"operator"}

# tenant_admin 이 다른 tenant audit_logs 조회 → 403
curl .../api/v1/audit/logs?tenant_id=<other> \
  -H "Authorization: Bearer $TENANT_ADMIN_TOKEN"
# 403
```

### 3.4 super_admin 보호

- super_admin 발급은 *시스템 콘솔* 에서만 (Admin UI 비노출)
- super_admin JWT 는 별도 시크릿 저장소 보관
- super_admin 활동은 모든 audit_logs 에 별도 indicator (`actor_role=super_admin`)
- 2FA 의무 (외부 SSO 연동 권장)

---

## 4. 쿼터 / Billing (선택)

> Lucas-KMS rev4 는 *billing 시스템 미포함* (out-of-scope). 본 섹션은 쿼터 enforcement 기반만.

### 4.1 쿼터 항목

| 항목 | 단위 | 기본 |
|---|---|---|
| 활성 doc 수 | per tenant | 1000 |
| 월 ingest 페이지 | per tenant | 50000 |
| 일 search 요청 | per tenant | 10000 |
| 일 RAG 요청 | per tenant | 1000 |
| MinIO 용량 | per tenant | 50 GB |
| Qdrant vector 수 | per tenant | 500000 |
| 동시 ingest job | per tenant | 5 |
| vLLM 동시 호출 | per tenant | `LUCAS_VLLM_MAX_CONCURRENT` / N |

### 4.2 enforcement

- Redis counter 기반 (`lucas:{tenant}:quota:{metric}:{period}`)
- API middleware 에서 검사 → 초과 시 429
- 일/월 단위 rolling window

### 4.3 운영자 조회

```bash
docker compose exec lucas-kms-api \
  python -m scripts.maintenance.tenant_usage \
    --tenant-id <uuid> \
    --period 2026-05
```

출력 예:

```
tenant: gov-tenant-a
  active_docs: 423 / 1000
  ingest_pages_this_month: 12340 / 50000
  search_today: 1820 / 10000
  rag_today: 145 / 1000
  minio_bytes: 12.3 GB / 50 GB
  qdrant_vectors: 184200 / 500000
```

### 4.4 쿼터 증액

```bash
docker compose exec lucas-kms-api \
  python -m scripts.maintenance.tenant_quota_set \
    --tenant-id <uuid> \
    --metric active_docs --value 5000
```

audit_logs 에 `quota_changed` event 기록.

---

## 5. Tenant 별 alert / 모니터링

- Prometheus metric label `tenant_id` 포함
- Grafana 의 tenant 별 dashboard (variable 로 tenant 선택)
- alert 라우팅 — 일부 alert 은 tenant_admin 에게도 발송 (예: doc 처리 stuck, 쿼터 80% 도달)

| Alert | 대상 |
|---|---|
| `lucas_kms_tenant_quota_warning` (사용량 80%+) | super_admin + tenant_admin |
| `lucas_kms_tenant_doc_stuck` (60m+) | super_admin + tenant_admin |
| `lucas_kms_tenant_dlq_high` (5건+) | super_admin + tenant_admin |
| `lucas_kms_api_down` | super_admin |
| `lucas_kms_vllm_circuit_open` | super_admin |

---

## 6. Tenant 마이그레이션 / 이관

### 6.1 export

```bash
docker compose exec lucas-kms-api \
  python -m scripts.maintenance.tenant_export \
    --tenant-id <uuid> \
    --output /backup/tenant-export/<uuid>/
```

산출물:
- `postgres.sql.gz` (tenant_id filtered dump)
- `qdrant/` (collection snapshots)
- `es/` (index snapshots)
- `minio/` (bucket mirror)
- `manifest.json` (메타)

### 6.2 import (다른 stack)

```bash
docker compose -f <target-stack>/docker-compose.lucas-kms.yml exec lucas-kms-api \
  python -m scripts.maintenance.tenant_import \
    --input /backup/tenant-export/<uuid>/ \
    --new-tenant-slug gov-tenant-a-migrated \
    --remap-uuids
```

import 시 UUID remap 옵션 — 동일 target 에 import 시 충돌 방지.

### 6.3 검증

- import 후 `test_multi_tenant_isolation.py` 회귀
- doc 수 / chunk 수 / vector 수 일치 확인
- 샘플 검색 결과 동일 확인

---

## 7. 운영자 체크리스트

### 7.1 신규 tenant 추가 시

- [ ] `scripts/seed/admin_inventory.py` 실행 + 출력 비밀번호 즉시 이관
- [ ] 첫 로그인 비밀번호 변경 강제 확인
- [ ] tenant_admin 에게 운영자 매뉴얼 (`lucas-kms-operator-manual.md`) 전달
- [ ] 격리 검증 (cross-tenant 0 hit) 1회 실행
- [ ] 쿼터 정책 협의 후 설정
- [ ] Grafana dashboard 의 tenant filter 정상 동작
- [ ] alert 라우팅에 tenant_admin contact 추가

### 7.2 주기 (월 1회)

- [ ] 모든 tenant 의 쿼터 사용량 점검
- [ ] cross-tenant 0 hit 회귀 1회
- [ ] inactive tenant (30일 이상 활동 없음) 식별 + 정책 확인
- [ ] audit_logs 압축 (90일+) → cold storage

### 7.3 주기 (분기 1회)

- [ ] write path RLS 회귀
- [ ] tenant 1개 backup → 다른 stack 복원 → 격리 검증 (DR 리허설 일환)
- [ ] super_admin 활동 audit 검토
- [ ] 권한 정책 최신화 (퇴직/이동 반영)

---

## 8. FAQ

**Q. 한 tenant 의 ingest 폭주가 다른 tenant 의 처리에 영향?**
A. (1) per-tenant vLLM 동시 호출 제한 (`LUCAS_VLLM_MAX_CONCURRENT` / N), (2) DLQ scheduler 가 per-tenant isolation (한 tenant 의 storm 차단), (3) Kafka consumer 의 partition 분포가 tenant 별 균등 — 그래도 spike 시 대기 시간 증가는 발생. 격리는 *정확성*, 성능 격리는 *완화*.

**Q. Cross-tenant 검색이 정말 0 hit?**
A. 다층 방어 — Postgres RLS / Qdrant filter / ES filter / MinIO bucket / Redis namespace / Kafka tenant_id. *어느 한 레이어 무력화* 시 다음 레이어에서 0. `test_multi_tenant_isolation.py` 가 모든 레이어 회귀.

**Q. super_admin 이 모든 tenant data 보임?**
A. 기본 *no*. super_admin 도 `SET LOCAL app.current_tenant_id` 가 필요. 별도 `bypass_rls=true` flag 가 있는 explicit endpoint 만 (audit 필수). 사고 조사 시에만 사용.

**Q. tenant 별 backup 주기 다르게?**
A. 가능 — `scripts/backup.sh` 에 `--tenant-id` 옵션 추가. critical tenant 는 1h, 일반 tenant 는 6h 등.

**Q. vLLM 호출 비용을 tenant 별로 분리?**
A. `audit_logs` + `llm_usage` 테이블에 `tenant_id` 기록. `scripts.maintenance.tenant_usage` 가 집계 — billing 연동은 별도 product.

**Q. 다른 LLM 모델을 tenant 별로?**
A. rev4 시점 *Gemma-4-31B 단일 권장* (현 터미널링 deployment 유지). tenant 별 모델 분리는 향후 검토 (out-of-scope).

---

## 9. References

- spec rev4 §8 (Multi-Store Tenant Isolation): `docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md`
- 배포 가이드: `docs/deployment/lucas-kms-public-saas-deployment.md`
- 성능 기준선: `docs/deployment/lucas-kms-public-saas-perf-baseline.md`
- 운영자 매뉴얼 (KMS-only): `docs/deployment/lucas-kms-operator-manual.md`
