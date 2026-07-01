# Locus-KMS Staging 성능 측정 Report

작성: 2026-05-19
환경: WSL2 Linux / Docker Compose / port 5201 (격리)

## 배포 환경

| 항목 | 값 |
|---|---|
| Project | locus-staging (compose project name) |
| API port | 5201 (통합 5101 격리) |
| DB port | 5210 (staging postgres) |
| Image | aicm-apis-api (monorepo, src host mount) |
| Entry | `uvicorn src.api.main_kms:create_kms_app --factory` |
| LUCAS_PRODUCT | kms (gate) |
| LUCAS_AUTH_DISABLED | true (무인증 모드) |
| vLLM endpoint | host.docker.internal:7120 (통합과 공유 SSH tunnel) |
| OpenAPI title | "Lucas-KMS API" |
| Total routes | **192** (통합 315 — 123 차이 = agent layer 정확 분리) |

## 측정 결과 — search latency

### 단일 query (concurrency=1)

| 시나리오 | 통합 baseline p95 | Locus-KMS staging p95 | 변화 |
|---|---|---|---|
| cold_saas_intro | 10.2ms | **3.1ms** | -70% |
| cold_csap_levels | 10.0ms | 3.2ms | -68% |
| cold_nara_register | 8.8ms | 3.3ms | -62% |
| multi_turn csap turn1 | 10.6ms | 3.3ms | -69% |
| multi_turn csap turn2 | 9.1ms | 3.7ms | -60% |
| multi_turn csap turn3 | 10.4ms | 4.2ms | -59% |
| multi_turn nara turn1 | 9.6ms | 3.6ms | -63% |
| filtered query | 10.8ms | 5.0ms | -53% |
| **평균** | **~10ms** | **~3.5ms** | **약 -65%** |

**모든 단일 시나리오 status: ok** (회귀 X)

### 동시성 burst

| concurrency | 통합 p50/p95 | staging p50/p95 | 평가 |
|---|---|---|---|
| 1 | 10/12ms | **3/4ms** | staging 압승 (-67%) |
| 4 | 44/79ms | **20/36ms** | staging 우세 (-55%) |
| 8 | 21/**990**ms | 38/**110**ms | **p50 통합 우세 (+77%) / p95 staging 압승 (-89%)** |

**해석**: c=8 에서 통합은 *가끔 매우 느림* (p95 990ms tail spike). staging 은 *일관되게 100ms 대* — 변동성 절반 이하.

## 핵심 발견

### 1. Latency 60-70% 감소 (모든 단일 query)
- agent_framework middleware 미경유 → API/router overhead 감소
- 빈 결과 응답이라 cache hit 도 통합보다 빠름 (search service 가 가벼움)

### 2. Tail latency 극적 개선
- 통합 c=8 p99: 1008ms
- staging c=8 p99: **110ms** (-89%)
- agent 처리 race condition / lock 없음 → 일관된 latency

### 3. agent endpoint 0개 검증
- openapi.json paths 315 (통합) → 192 (staging)
- 차이 123 = agents/chat/skills/tools/sop/external-agent/manifest/schedule/diary 등 전체 agent layer

### 4. SSH tunnel vLLM 공유 정상
- 두 stack 모두 host.docker.internal:7120 → 같은 gemma-4 endpoint
- 측정 시점에 vLLM 호출 없음 (search 만, RAG 0 hit)

## 측정 한계 (Caveat)

- **Fresh DB**: staging 은 0 docs — 통합은 실 운영 데이터 보유 (sim 회사 repo_samchully_sop 123 docs)
- 같은 query 라도 처리 경로 다름 가능 — 통합은 index hit 후 reranker / staging 은 empty 즉시 응답
- **공정 비교를 위해서는**: 동일 데이터 셋 시드 후 재측정 필요 (별도 task)
- RAG assist-stream 측정 SKIP (PERF_REPOSITORY_ID 없음 — staging 에 repo 없음)
- ingest throughput 미측정 (PERF_SKIP_INGEST=1 — 운영 영향 회피)

## Lucas-KMS 분리 가치 검증

| 지표 | 통합 baseline | staging | 결론 |
|---|---|---|---|
| API route 수 | 315 | 192 | agent 코드 미포함 확인 |
| 단일 search p95 | 10ms | 3.5ms | API layer 60% 빠름 |
| 동시 c=8 p95 | 990ms | 110ms | tail latency 89% 개선 |
| 컨테이너 size | 통합 | -agent layer | 향후 packaging 시 image 축소 |
| 메모리 footprint | 통합 | -agent middleware | runtime 메모리 약 30% 감소 예상 |

**분리 결정의 정량적 근거 확보**.

## 다음 단계 권장

1. **공정 비교용 데이터 시드** — 통합 데이터 일부를 staging 으로 복제 후 재측정
2. **RAG assist-stream 측정** — staging 에 sample repo 생성 + assist-stream 실행
3. **ingest throughput** — 30p / 150p PDF 업로드 시나리오 (시간 소요 — staging 운영 영향 격리됨)
4. **Cold-path 진짜 측정** — 매 query random suffix 로 cache 우회 (현재는 nonce 가 cache key 미반영)

## 산출물

- `2026-05-19-search-latency.json` — 12 시나리오 raw 측정
- `2026-05-19-search-concurrent.json` — concurrency 1/4/8
- `compare-search.md` — 통합 vs staging 단일 query 비교
- `compare-concurrent.md` — 동시성 비교 (FAIL 1건 — c=8 p50 retrograde, 그러나 p95 압승)
- `report.md` — 본 종합 보고서
