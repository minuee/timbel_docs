# Lucas-KMS — 성능 기준선

작성: 2026-05-19
대상: 운영자 / 인프라 / capacity planner
연계: `lucas-kms-public-saas-deployment.md`, spec rev4

> 본 문서는 *Lucas-KMS 단독 배포* 의 성능 기준선. 통합 Locus 솔루션 대비 차이는 §3 에 기록.

---

## 0. 환경 가정

| 항목 | 값 |
|---|---|
| API/Worker 호스트 | 16 vCPU / 64 GB RAM / NVMe |
| GPU (BGE-M3) | RTX 5090 1매 (sm_120, cu128) |
| 외부 vLLM | Gemma-4-31B (현 터미널링 deployment 그대로 유지) |
| Postgres | 동일 호스트, dedicated SSD volume |
| Qdrant | 동일 호스트, dedicated SSD volume |
| Elasticsearch | 동일 호스트, ES_JAVA_OPTS=-Xms2g -Xmx2g |
| Kafka | 단일 broker (KRaft) |
| Redis | 단일 인스턴스 |
| MinIO | 단일 인스턴스 |
| Network | 외부 vLLM 까지 RTT < 20ms (private link 또는 VPN) |

> 외부 매니지드 DB / 별도 vLLM 클러스터 환경은 별도 측정. 본 기준선은 표준 단일 호스트 배포 기준.

---

## 1. 단일 Tenant 시나리오

### 1.1 PDF ingest 처리 시간

| PDF 규모 | 처리 시간 (p50) | 처리 시간 (p95) | 주요 bottleneck |
|---|---|---|---|
| 5p (단순 텍스트) | 60-90초 | 120초 | vLLM segment + embed |
| 30p (일반 가이드) | 3-5분 | 7분 | vLLM segment (block 분할) |
| 150p (스캔 포함) | 13-17분 | 22분 | vision OCR + segment |
| 500p+ | 약 1시간 | 1.5시간 | 야간 처리 권장 |

세부 stage 분해 (30p PDF p50):

| stage | duration | 비고 |
|---|---|---|
| parsing | 20-30s | text/table/image 추출 (CPU bound) |
| segmenting | 90-150s | vLLM block segmenter (외부 vLLM 호출) |
| embedding | 30-50s | BGE-M3 GPU (cu128) |
| indexing (Qdrant + ES) | 10-20s | network + I/O |
| 검토 자동 승격 | 즉시 | `auto_approve=true` 시 |

### 1.2 검색 latency

| 시나리오 | p50 | p95 | p99 |
|---|---|---|---|
| `/search` (BGE-M3 dense+sparse+reranker, top_k=10) | 200-300ms | 700ms | 1.5s |
| `/search` (top_k=50) | 350-500ms | 1.2s | 2.5s |
| `/rag/assist-stream` (retrieval-only, 첫 토큰) | 400-600ms | 1.2s | 2.5s |
| `/rag/assist-stream` (E2E 완료) | 3-6s | 12s | 20s |
| `/rag` (full LLM 답변 + citation) | 4-8s | 15s | 25s |

> p95 의 *주요* contributor 는 vLLM round-trip (외부 endpoint 의존).

### 1.3 동시 처리

| 동시 작업 | 처리량 |
|---|---|
| 동시 ingest (small + large worker) | 5 doc 병렬 |
| 동시 search 요청 | 30 req/s (단일 호스트 GPU embed pipeline) |
| 동시 RAG 요청 | 8 req/s (vLLM 동시성 제한) |
| 동시 SSE stream | 50 connection (assist-stream) |

### 1.4 자원 사용량 (정상 부하)

| 자원 | 사용량 |
|---|---|
| API CPU | 평균 30%, peak 70% |
| Worker CPU | 평균 50%, peak 90% |
| GPU (BGE-M3) | 평균 40%, peak 80% |
| RAM | 28-40 GB (ES 2GB + Qdrant 4GB + 워커 4-6GB 등) |
| Disk write | 평균 30 MB/s (indexing) |
| Network outbound (vLLM) | 평균 5 Mbps, peak 30 Mbps |

---

## 2. Multi-Tenant 동시 시나리오

### 2.1 5 tenant 동시 ingest

5 tenant × 각 30p PDF 1건 동시 업로드:

| 지표 | 값 |
|---|---|
| 총 처리 시간 (5건 모두 active) | 8-12분 (vs 단일 5 × 3-5분 = 15-25분 — 병렬 효과) |
| 외부 vLLM 동시 호출 peak | 5-8 (LUCAS_VLLM_MAX_CONCURRENT=8 내) |
| Postgres connection peak | 60/200 |
| Kafka lag peak (split topic) | 5-10 |
| 격리 검증 결과 | 5 tenant 각자 자기 doc 만 search 가능 (cross-tenant 0 hit) |

### 2.2 10 tenant 동시 search

10 tenant × 각 5 req/s sustained (총 50 req/s):

| 지표 | 값 |
|---|---|
| p95 latency | 800ms-1.2s (단일 tenant p95 대비 +15%) |
| GPU embed pipeline 큐 wait p95 | 50-100ms |
| Postgres connection peak | 80/200 |
| 격리 결과 | 매 query 가 자기 tenant 의 결과만 |

### 2.3 spike 시 동작

한 tenant 의 30 req/s spike (다른 tenant 5 req/s 일 때):

| 지표 | 값 |
|---|---|
| spike tenant p95 | 1.5-2.5s (자기 큐 wait 증가) |
| 다른 tenant p95 | 800ms (영향 미미) |
| GPU 동시성 | spike tenant 가 GPU 점유 우세 |
| 쿼터 enforcement | spike tenant 가 daily quota 도달 시 429 |

---

## 3. 통합 솔루션 (Locus) 대비 분리 시 예상 차이

### 3.1 분리 시점 (rev4)

| 항목 | 통합 Locus | Lucas-KMS 단독 | 차이 |
|---|---|---|---|
| API 메모리 | 1.8-2.4 GB (227+ routes) | 1.2-1.6 GB (KMS-only 라우터) | -30% |
| 컨테이너 이미지 크기 | 4.5-5.5 GB | 3.5-4.5 GB | -20% (Phase 3 packaging 완료 후 -40% 목표) |
| 첫 startup | 35-50s | 25-35s | -30% (KMS 라우터만 로드) |
| KMS search p95 | 700-900ms | 600-800ms | -10% (agent middleware 미경유) |
| KMS RAG p95 | 13-16s | 12-15s | -5-10% (agent runtime 미참여) |
| Ingest 처리 시간 | 동일 | 동일 | ~0% (KMS 파이프라인 동일) |
| GPU 사용량 | 동일 | 동일 | 0% (BGE-M3 동일) |
| vLLM 호출량 | 동일 | 동일 | 0% (LLM 사용처 동일 — segment/distill/intent) |

> 분리 시 *agent 미참여* 로 RAG p95 가 약간 감소. ingest 자체는 동일 KMS 파이프라인이므로 변화 없음.

### 3.2 향후 (Phase 3 packaging 완료 후)

- 컨테이너 이미지 -40% (agent_framework / frontend-v3 / tests/full 제외)
- API import 시간 -25% (lucas-kms wheel 만 install)
- DB schema 크기 -30% (agent table 미생성)
- 보안 surface 축소 (agent endpoint 0건)

---

## 4. 측정 도구

### 4.1 perf 디렉토리 구조 (신규 — 본 spec 일환)

```
tests/perf/                            # 신설 디렉토리
├── README.md
├── conftest.py
├── ingest/
│   ├── test_pdf_30p_baseline.py
│   ├── test_pdf_150p_baseline.py
│   └── fixtures/                      # 샘플 PDF (gitignored, scripts/perf/download.sh 로 받음)
├── search/
│   ├── test_search_latency.py
│   └── test_search_concurrent.py
├── rag/
│   ├── test_rag_assist_stream.py
│   └── test_rag_full.py
├── multi_tenant/
│   ├── test_5_tenant_ingest.py
│   ├── test_10_tenant_search.py
│   └── test_spike_tenant.py
└── reports/                           # 측정 결과 (gitignored — CI 가 artifact 로 보관)
```

> `tests/perf/` 는 본 spec rev4 의 §12.4 / §12.5 후속으로 신설. 현 시점 rev4 의 `tests-integration/lucas_kms/` 와 별도 — 후자는 *기능* 회귀, 전자는 *성능* 측정.

### 4.2 측정 실행

```bash
# 단일 시나리오
docker compose -f docker-compose.lucas-kms.yml exec lucas-kms-api \
  pytest tests/perf/ingest/test_pdf_30p_baseline.py -v --perf-report

# 전체 baseline 측정 (분기 1회 권장)
docker compose -f docker-compose.lucas-kms.yml exec lucas-kms-api \
  python -m scripts.loadtest.run_baseline \
    --output /tmp/perf-baseline-$(date +%Y%m%d).json

# locust 부하 테스트
docker compose -f docker-compose.lucas-kms.yml exec lucas-kms-api \
  locust -f scripts/loadtest/locustfile.py \
    --host https://kms.gov-tenant.example.kr \
    --users 50 --spawn-rate 5 --run-time 10m \
    --csv /tmp/locust-$(date +%Y%m%d) --headless
```

### 4.3 측정 항목 (자동)

`scripts/loadtest/run_baseline.py` 가 출력하는 JSON 예시:

```json
{
  "version": "2026-05-19",
  "git_sha": "f6b8812",
  "lucas_product": "kms",
  "vllm_model_revision": "<운영 값>",
  "scenarios": {
    "ingest_30p": {
      "p50_seconds": 220, "p95_seconds": 380, "p99_seconds": 450,
      "stages": {"parsing": 25, "segmenting": 130, "embedding": 40, "indexing": 15}
    },
    "search_top10": {
      "p50_ms": 240, "p95_ms": 720, "p99_ms": 1450,
      "throughput_rps": 28
    },
    "rag_assist_stream_first_token": {
      "p50_ms": 480, "p95_ms": 1180, "p99_ms": 2400
    },
    "rag_assist_stream_total": {
      "p50_seconds": 4.2, "p95_seconds": 11.5, "p99_seconds": 18.7
    },
    "multi_tenant_5_ingest": {
      "total_seconds": 540,
      "vllm_concurrent_peak": 7,
      "cross_tenant_hits": 0
    }
  }
}
```

### 4.4 regression 게이트 (CI)

`scripts/loadtest/check_regression.py` 가 매 PR 의 perf JSON 을 main 의 baseline 과 비교:

| 항목 | 회귀 임계 | 동작 |
|---|---|---|
| search p95 | +30% | warn (review 요구) |
| search p95 | +50% | fail |
| RAG p95 | +30% | warn |
| RAG p95 | +50% | fail |
| ingest 30p p95 | +25% | warn |
| ingest 30p p95 | +50% | fail |
| cross-tenant hit | 1건 이상 | fail (격리 깨짐 — critical) |
| vLLM circuit open during baseline | true | fail |

### 4.5 측정 주의사항

- *cold cache* 와 *warm cache* 분리 측정 (`--warmup` 옵션)
- 외부 vLLM endpoint 가 변경되면 baseline 재측정 필수
- B200 tunnel network jitter 가 p99 에 큰 영향 — 측정 시 tunnel 안정성 확인
- Postgres autovacuum / ES segment merge 가 spike 유발 — 측정 전 idle 5분
- 단일 호스트에서 측정과 부하를 동시에 돌리면 측정 부정확 — 부하는 외부 호스트에서

---

## 5. capacity planning

### 5.1 호스트 1대 (RAM 64GB, GPU 1매) 권장 한도

| 항목 | 한도 |
|---|---|
| 총 tenant 수 | 20-30 |
| 총 활성 doc 수 | 10000 |
| 총 vector 수 (Qdrant) | 5M |
| 일 ingest 페이지 | 50000 |
| sustained search QPS | 30 |
| sustained RAG QPS | 5 |

### 5.2 scale-out 방향

이 수치를 초과하면:

| 단계 | 조치 |
|---|---|
| GPU saturation | 외부 embedding proxy + reranker 클러스터 (RTX 5090 2매+ 또는 B200) |
| Qdrant 부하 | 별도 Qdrant 클러스터 (sharding) |
| ES 부하 | ES 노드 추가 + replica |
| Postgres 부하 | pgbouncer + read replica + writes 만 primary |
| Kafka 부하 | broker 추가 + partition 증가 |
| 외부 vLLM 부하 | vLLM 인스턴스 추가 (load balancer) — *모델은 Gemma-4-31B 유지* |

호스트 1대 → 다중 호스트 전환 시 spec 의 §10 (Repo split) 와 함께 *별도 plan* 필요.

---

## 6. 운영자 활용

### 6.1 분기 baseline 측정

```bash
# 운영 트래픽이 낮은 시간 (예: 일 04:00)
scripts/perf/baseline.sh --output /backup/perf/$(date +%Y%m%d).json

# 이전 분기와 비교
python scripts/perf/compare.py \
  --baseline /backup/perf/20260219.json \
  --current /backup/perf/20260519.json
```

trend 가 회귀 임계 초과 시 root cause 조사 (vLLM endpoint 변경 / GPU 노후 / DB index bloat 등).

### 6.2 신규 vLLM endpoint 교체 후

교체 *전* + *후* baseline 측정. 후가 전보다 +20% 이상 회귀하면 endpoint 재검토.

### 6.3 신규 tenant 추가 영향 분석

신규 tenant 추가 *전* 의 5분 baseline (search/RAG p95) 와 *후* 1시간 후 동일 측정. p95 +15% 이상이면 capacity 임계 도달 — scale-out 검토.

---

## 7. References

- spec rev4 §12 (Success Criteria — 구체 측정 명령): `docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md`
- 배포 가이드: `docs/deployment/lucas-kms-public-saas-deployment.md`
- multi-tenant 운영: `docs/deployment/lucas-kms-public-saas-multi-tenant.md`
- 운영자 매뉴얼: `docs/deployment/lucas-kms-operator-manual.md`
- 통합 솔루션 loadtest: `scripts/loadtest/locustfile.py`, `docs/loadtest/`
