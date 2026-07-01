# rerank 동적 배칭 설계 (B200 unified_server)

> 작성일 2026-06-21 · 대상: NHN B200 `kms_unified_server/unified_server.py`(:35001, timbel 터널 :7125) · 단일 GPU(cuda:0) · embed/rerank/vLLM 공존
> 근거: [Doc/perf/2026-06-20-search-latency-3paths.md](../../../Doc/perf/2026-06-20-search-latency-3paths.md) §10/§12 — 콜봇 동시부하 tail(c=8 total p50 ~600ms)의 rerank 부분(p50 374ms)이 단일 GPU 경합 산물

## Goal

콜봇 고동시성(상시 c=8+) 검색의 rerank tail을, B200 reranker `/rerank`에 **동적 배칭**(짧은 윈도로 동시 요청을 모아 1회 batch predict)을 도입해 줄인다. **단, 전제(배칭이 실제로 rerank를 단축)가 측정으로 확인될 때만** 구현한다. embedder/`/embed`는 범위 외(rerank-only).

## 배경 / 현재 상태 (실측)

- B200 호스트 **GPU 1개**(B200 179GB). vLLM(gemma 답변LLM) 168GB + `unified_server`(embed+rerank) 9GB, free ~4.6GB. 셋 다 cuda:0.
- `/rerank`(`unified_server.py`): 요청마다 `pairs=[[query,c.content]...]` → `scores = await asyncio.to_thread(lambda: _reranker.predict(pairs))`. **교차요청 배칭/큐 없음**(§11 확정). `_lock`은 모델 로드 전용.
- KMS 클라이언트(`cross_encoder.py _remote_score`): 검색 1건 = `/rerank` POST 1회, 후보 20개 한 payload. 동시 검색 = 동시 POST N개.
- 측정(§10/§12): c=1 rerank p50 ~104ms / c=8 p50 374ms(3.6x). 동시 predict가 단일 GPU에서 경합·직렬화.

## Phase 0 — 배칭 전제 검증 게이트 (구현 전 필수)

구현 전 **배칭이 실제로 rerank를 단축하는지** B200에서 측정한다. 통과 못 하면 구현 중단.

1. **배치 효율 측정**: `/rerank`에 후보 **160개를 담은 단일 요청**의 predict latency vs **20개×8 동시 요청의 벽시계(8건 모두 비우는 시간)**. 단일 160-batch가 8×20 동시보다 **유의미하게 빠른지**(예: ≥30%).
   - 빠르면(overhead/경합-bound) → 배칭 유효, 구현 진행.
   - 비슷하면(compute-bound) → 배칭 무효 → **구현 중단**, 대안(조건부 rerank·후보축소·증설) 재논의.
2. **vLLM 동반 부하 측정**: vLLM(:8000)에 답변 생성 부하를 동시에 건 상태에서 위 1을 반복. 실제 콜봇(검색+답변 동시)에 가까운 조건. 배칭 이득이 vLLM 경합 하에서도 남는지.
3. **GPU throughput vs 도착률**: 단일 160-batch predict 시간으로 sustained c=8+ 처리량 추정 → 큐 안정(throughput ≥ 도착률) 가능한 max_batch 범위 도출.

**산출**: 배칭 유효성 판정 + 권장 `BATCH_WAIT_MS`/`MAX_BATCH_PAIRS`. (Phase 0 결과를 본 spec에 부록으로 추가.)

## Architecture (Phase 0 통과 시)

`/rerank` 핸들러의 "요청별 즉시 predict"를 **단일 배처 경유**로 변경. 배처가 동시 요청을 모아 1회 batch predict 후 요청별로 score를 분배. `/rerank` 외부 API(요청/응답 스키마)는 불변 — KMS 클라이언트 무수정.

## Components

### 1. `RerankBatcher` (신규, `unified_server.py` 내)

**Interfaces:**
- `submit(query: str, candidates: list[Candidate]) -> Future[list[float]]` — 요청을 큐에 넣고 결과 future 반환.
- 내부: `asyncio.Queue`에 `(pairs, offset_meta, future)` 적재. 단일 백그라운드 `_run_loop()`가 소비.
- `_run_loop()`:
  1. 큐에서 최소 1건 await(블로킹 get).
  2. 이미 큐에 쌓인 것을 즉시 추가 수집(non-blocking drain), 부족하면 `BATCH_WAIT_MS`만큼만 추가 대기(동시성 높으면 즉시 참).
  3. 누적 pairs가 `MAX_BATCH_PAIRS` 도달 시 중단(초과분은 다음 배치).
  4. 전 요청 pairs 연결 → `await asyncio.to_thread(lambda: _reranker.predict(all_pairs))` **1회**.
  5. offset_meta로 요청별 score 슬라이스 → 각 future `set_result`.
  6. predict 예외 시 그 배치 future들 `set_exception`.

**핵심 효과**: predict가 배처에서 **1개씩 직렬 실행** → 현재의 동시 predict 경합 제거(단일 GPU 유리). 동시 요청은 큐에서 모여 한 번에.

### 2. `/rerank` 핸들러 변경

```python
@app.post("/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest):
    await _load_reranker()
    if not req.candidates:
        return RerankResponse(results=[], latency_ms=0, model=RERANKER_MODEL)
    t0 = time.perf_counter()
    scores = await _batcher.submit(req.query, req.candidates)   # ← 직접 predict 대신 배처
    # 이하 기존 응답 조립(results/latency_ms/model) 동일
```

### 3. startup

`@app.on_event("startup")`에서 `_batcher = RerankBatcher(); _batcher.start()`(소비 루프 task 생성). reranker 로드(`_load_reranker`)는 기존대로.

## Parameters (Phase 0에서 확정, 잠정 기본값)

- `RERANK_BATCH_WAIT_MS`(env, 기본 5): 추가 수집 대기 상한. 고동시성선 즉시 참, 저동시성 ≤5ms 추가.
- `RERANK_MAX_BATCH_PAIRS`(env, 기본 256): 1 predict 최대 pair 수(VRAM 4.6GB·latency 상한). 초과분 다음 배치.
- env로 노출 → 무재배포 튜닝.

## Data Flow

```
8 동시 /rerank → 각 submit(query,20 pairs)→future → _run_loop가 윈도 내 8건 수집
  → predict(160 pairs) 1회 → offset으로 [0:20],[20:40]... score 분배 → 8 future 동시 resolve
  → 각 /rerank 응답 반환(스키마 불변)
```

## Error Handling

- **predict 실패**: 그 배치 모든 future `set_exception` → `/rerank`가 5xx → **KMS 클라이언트 `cross_encoder.py`가 fusion 순서 폴백**(기존, 검색 무중단).
- **빈 candidates**: 핸들러에서 즉시 빈 응답(배처 미경유).
- **배처 루프 예외**: 루프는 try/except로 감싸 개별 배치 실패가 루프를 죽이지 않게(다음 배치 계속).
- **과부하**: 큐 길이 상한(예: 1000) — 초과 시 즉시 에러(폴백) 하여 무한 적체 방지. (Phase 0 throughput 결과로 상한 조정.)

## Testing

- **단위(GPU 불필요)**: `RerankBatcher`의 수집/분배 로직을 fake predict(입력 pairs 수만큼 더미 score 반환)로 테스트 — ① 요청별 score offset 정확 분배 ② max_batch 분할(초과분 다음 배치) ③ 빈 candidates ④ predict 예외 시 future 전파. (predict를 주입 가능하게 설계.)
- **통합(timbel→B200)**: 배포 후 c=1/4/8 **before/after 분포 재측정** — rerank p50/p95 감소 확인 + **품질 top-5 동일**(배칭이 score를 안 바꿈) + **vLLM 동반 부하** 시에도 이득 + 지속 부하 큐 안정.
- 프론트 테스트 러너 없음과 무관(서버측 Python) — 배처 단위테스트는 pytest 가능.

## Deployment (NHN 공유 B200 — 신중)

- 소스 `unified_server.py`는 **레포에 없음**(B200 Lustre `kms_unified_server/`만). 절차:
  1. **백업**: B200에서 `unified_server.py` → `unified_server.py.bak.<ts>`.
  2. **레포 미러**(버전관리 부재 해소): 변경 전 원본 + 변경본을 rag-parser-engine `kms_unified_server/`에 커밋(추적 시작).
  3. 변경 적용 → `python -c "import ast; ast.parse(...)"` 문법확인.
  4. 재기동: `unified_deploy.sh`(nohup) 또는 기존 기동방식으로 unified_server 재시작. **embed/rerank 둘 다 재로드되므로(~수십초) 검색 일시 중단** — 저부하 시간대 권장.
  5. 검증(통합 테스트). 실패 시 `.bak` 복원+재기동.
- **영향 범위**: 라이브 변경은 전 KMS 검색 rerank에 적용. fallback(fusion)으로 hard fail은 graceful하나, 배포 직후 품질/지연 즉시 확인 필수.

## Out of Scope / Non-Goals

- **embedder/`/embed` 배칭**(범위 외, rerank-only). embed 경합(~tail 30%)은 잔존 — 본 작업으로 rerank 부분만 개선(부분 해결).
- GPU 분리/증설(하드웨어, 1 GPU 확정).
- 조건부 rerank·후보축소(별도 KMS측 보완책).
- KMS 클라이언트(`cross_encoder.py`)·검색 파이프라인 변경 없음(서버 API 불변).
- vLLM 설정 변경 없음.

## 리뷰 반영(설계 리스크 → 완화)

| 리스크 | 완화 |
|---|---|
| 배칭 전제 미검증(compute-bound면 무효) | **Phase 0 게이트** — 통과해야만 구현 |
| vLLM 동시부하서 이득 불확실 | Phase 0·통합테스트에 **vLLM 부하 동반** |
| 큐 무한증가(throughput<도착률) | max_batch 사이징 + 큐 상한+폴백 |
| 공유 B200 라이브 변경 위험 | 백업·fallback·단계검증·저부하 배포 |
| 버전관리 부재 | 레포 미러(원본+변경본 커밋) |

## 부록: Phase 0 검증 결과 (2026-06-21) — PASS

B200 reranker(:7125, timbel 터널) 측정. health 전부 가동.

**M1 (vLLM idle)**: 단일 160-batch vs 20×8 동시.
- wall(터널): 단일160 p50 177ms / 8×20동시 벽시계 p50 202ms → 12.2%(터널 RTT 희석).
- **서버 compute(latency_ms)**: 단일160 **45ms** vs 8×20 per-req **144ms** = **3.2배**.

**M2 (vLLM generate 4동시 부하)**:
- wall: 단일160 181ms vs 8×20 446ms → **59.5%**.
- 서버 compute: 단일160 **80ms** vs 8×20 per-req **298ms** = **3.7배**.

**throughput sweep(서버 compute p50)**: 고정 floor ~7ms/콜(batch 1~16 동일), GPU forward는 batch≈64부터 선형. **포화 ≈ batch 128(~5,200 pairs/s)**, 160=5,161, 200↓. t_b(160)=38~45ms.

**판정 = PASS**: 게이트 metric(wall ≥30%)은 M1서 미달이나, 이는 **터널 RTT가 단일요청 compute(45ms)를 희석한 측정 아티팩트**. 게이트 **의도(배칭이 경합-bound라 유효한가)는 서버 compute 3.2~3.7배로 명확 충족**. 운영도 KMS→reranker 동일 터널 경유라 서버측 절감(요청당 144→45ms, c=8)이 실현됨. M2(vLLM 부하=실제 콜봇 조건)는 wall로도 59.5% PASS.

**확정 파라미터**: `RERANK_MAX_BATCH_PAIRS=160`(c=8 윈도 흡수+포화점), `RERANK_BATCH_WAIT_MS=8`(floor 7ms 직상), `RERANK_MAX_QUEUE=1000`. throughput ~5,000 pairs/s ≫ c=8 도착률(~48 rerank/s) → 큐 안정.

**한계**: 측정이 터널 경유라 wall 절대치는 RTT 포함. candidate는 실문서 형태 한국어 청크(테넌트0 데이터 부재로 실 KMS content 미사용) — latency는 pair 토큰길이로 결정되므로 측정 목적엔 충분. zero_score 0건(품질 sanity OK).

### 부록 보강: 터널 없이 B200 로컬 재측정 (2026-06-21) — wall 게이트도 PASS

B200 쉘 내 `localhost:35001/rerank` 직접 호출(터널 RTT 제거), n=15.
| 측정 | single cand160 wall p50 | 8×cand20 동시 wall p50 | ratio(single faster) | compute p50(single/per-req) |
|---|---|---|---|---|
| M1(idle) | 0.0449s | 0.1355s | **66.8%** | 43ms / 122ms |
| M2(vLLM 4×generate) | 0.0931s | 0.4096s | **77.3%** | 91ms / 306ms |

→ 터널 제거 시 **wall 게이트(M1 ≥30%, M2 ≥20%) 모두 넉넉히 통과**(66.8%/77.3%). 이전 터널 wall 12.2%는 고정 RTT가 단건 43ms compute를 부풀린 아티팩트로 확정. **Phase 0 최종 = PASS, 구현 진행.**
