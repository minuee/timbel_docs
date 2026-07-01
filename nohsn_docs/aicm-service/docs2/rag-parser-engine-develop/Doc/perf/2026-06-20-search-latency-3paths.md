# 검색 Latency 측정·분석 — 3경로(콜봇/어드바이저/웹)

> 측정일 2026-06-20 · 환경 timbel_5fl(124.194.32.36) · 무인증 직접 호출 + aicm/KMS 로그 단계분해
> 선행: [2026-06-12-search-latency-analysis.md](2026-06-12-search-latency-analysis.md) (단일 경로 중심) — 본 문서는 3경로 비교 + 캐시 계층 모델로 확장

## 0. 환경 / 방법

| 항목 | 값 |
|---|---|
| aicm-service | `aicm_dev_service` :32012 |
| KMS api | `lucas-kms-api` :32020 (워커 large/small) |
| workspace / repository | `019bfe5d…` / `f7dc80c9…` (active 13건, **blocks 482개**, 벡터는 chunks 아닌 **blocks 테이블**) |
| tenant | `00000000-…-0001` |

**측정 경로(무인증)**: 콜봇 `POST /api/aicm/v1/search/internal/document`(완전 무인증), 어드바이저 `POST /api/aicm/v1/search/rag_assist`(X-auth-token 헤더 required지만 더미값 통과·검증없음→viewable=ALL), 웹동등 KMS `POST /api/v1/search`(무인증, 필수=`query`).
**계측**: curl `time_total`/`time_starttransfer` + aicm `[internal_search] search_latency total_ms/kms_ms/enrich_ms`(콜봇만) + KMS `SearchTraceStep`(step_name/latency_ms). 쿼리 5종(문서 내용 기반, 전부 결과 5건).

## 1. 핵심 결론 — 캐시 2단계 + intent_gate (정정됨)

> **[정정 2026-06-20, §9 측정]** 초판은 "3-tier(결과·임베딩 캐시)"로 봤으나 ① 측정에서 **임베딩은 병목 아님(~27ms)·검색경로 임베딩 캐시 부재**, 그리고 "~300ms 사각 = 임베딩"이 아니라 **Intent Gate LLM(~480ms)** 임이 밝혀졌다. 아래로 대체.

| 상태 | 콜봇 total(kms_ms) | 지배 요인 |
|---|---|---|
| 결과캐시 hit | **4~25ms** | KMS `search_cache_hit`→전 단계 skip |
| 결과캐시 miss (intent_gate OFF) | **130~216ms** | **rerank 116~138ms** (§2). 임베딩 27ms·retrieval 18~33ms는 작음 |
| intent_gate ON 경로 | **+~480ms** | intent 분류 LLM(병렬, max(480,200)≈480). **콜봇·웹은 off, 어드바이저만 on** |

**핵심 사실(§9)**: 순수 쿼리 임베딩 ~27ms(B200 :7125, cold=warm). 검색경로 임베딩 캐시 **없음**(있어도 이득 ≤27ms). 결과캐시 TTL **300초**라 대화형은 거의 매번 miss. **콜봇 실지연 = ~130~216ms, rerank 지배**(신규/반복 무관). 초판의 "신규쿼리 ~500ms"는 intent_gate ON 경로(콜봇 미사용)의 오귀속이었음.

## 2. KMS 파이프라인 단계 분해 (miss 대표)

`배당 지급 기준일 안내` (KMS 직접, 파이프라인 total=203ms) 원문:
```
query_decomposed         latency_ms=0
query_preprocessed(Okt)  latency_ms=0          (warm)
keyword_search(ES)       latency_ms=18  candidates=20
sparse_search(Qdrant)    latency_ms=21  candidates=20
dense_search(Qdrant)     latency_ms=23  candidates=20
rrf_fusion               latency_ms=0   total=43
reranking                latency_ms=138 input=20 output=5    ← 단일 최대(68%)
search_pipeline_completed total_latency_ms=203
```
다른 miss 샘플: rerank 116ms / total 198ms. → **rerank가 파이프라인 내 최대 고정비(116~138ms, ~60-68%)**. retrieval 3소스(18~33ms)는 병렬이라 벽시계 영향 작음. fusion/preprocess/decompose ≈ 0ms(warm).

**계측 사각**: 파이프라인 total(203ms) ≠ curl(504ms). 약 **300ms가 임베딩 생성+HTTP**로 SearchTraceStep에 안 잡힘 → 신규쿼리 실지연의 절반 이상이 미계측 구간.

## 3. 경로별 프로파일

동일 쿼리 `주문 결제 방법`:

| 경로 | total | first-byte | 구성 |
|---|---|---|---|
| 웹동등(KMS직접) | 12~20ms(hit) / ~500ms(신규miss) | ≈total | 순수 검색. history 없음→캐시키 안정→**hit율 최고** |
| 콜봇 | 6~36ms(hit) / 130~216ms(miss) | ≈total(논스트림) | 검색만. context_weighted(가중융합), **llm_rewrite off**(reformulate 비용 없음) |
| 어드바이저(SSE) | **2.7s** | **8~25ms** | intent_gate **476ms** + 검색 204ms + LLM답변 ~2s |

**어드바이저 SSE 이벤트 분해**(원문): `intent latency_ms=476` → `sources search_latency_ms=204, candidates=5` → `token×N`(답변 ~2s). first-byte는 즉시(SSE open). 즉 **검색 자체(204ms)는 콜봇 miss와 동급**, 추가비는 ①intent_gate LLM 476ms ②답변 생성 LLM ~2s.

## 4. 갑작/상시 지연 구분

**상시(persistent) 지연** — 매 miss마다 발생:
- **rerank 116~138ms** (Cross-encoder, B200 :7125). 파이프라인 내 최대.
- **임베딩+HTTP ~300ms** (신규쿼리 한정, 계측 밖). T3의 주범.
- **어드바이저 intent_gate 476ms + 답변 LLM ~2s** (경로 고유, 매 요청).

**상시화되는 캐시 미스** — 구조적:
- 캐시키 = `sha256(query + params + ctx)`, `ctx = context_fingerprint(conversation_history)`.
- **콜봇·어드바이저는 history 포함 → 대화 턴마다 ctx 변화 → 매 턴 miss**(T2/T3). 웹은 질문만 → 동일질문 반복 hit(T1).
- 즉 대화형 경로는 본질적으로 캐시 이득이 적어 "항시 T2(130~216ms) 이상".

**갑작(sudden) 지연**:
- **Okt JIT 재현·확정**(§8): cold 시 `query_preprocessed`(Okt)가 **워커당 ~6초**(4워커=6104/5591/6103/6193ms). 단 **startup warmup이 흡수**(`_common.py:154` 워커별 더미쿼리) → 사용자 첫 검색은 대부분 warm. **잔여 누출**: 더미가 단일패턴이라 일부 형태소 경로 미예열 → burst #7에서 preprocess **545ms 1회** 사용자 경로 노출.
- 완전 신규 쿼리의 임베딩 miss(+300ms)가 "가끔 느림"으로 체감될 수 있음.

**특이 관찰(단일 샘플, 확인필요)**: 콜봇 history 케이스 b2가 kms_ms=7인데 **enrich_ms=62**로 급증(질문만 b1은 enrich=4). history 텍스트가 enrich(AICM DB 보강) 경로 비용을 올리는지 §5에서 확인 필요.

## 5. 미확정 / 추가 측정 필요

1. **임베딩 캐시 가설**: T2(130~216) vs T3(~500)의 차이가 임베딩 캐시 유무인지 — 검색결과캐시·임베딩캐시(`aicm:embed:bge-m3:*`)를 모두 비운 완전 cold 1회 + 임베딩만 워밍 후 1회 비교로 확정.
2. **임베딩+HTTP 300ms 분해**: 임베딩 서버(B200 터널) 단독 latency vs HTTP. KMS에 embedding 단계 latency 로깅 추가(현재 trace에 embedding step ms 미노출).
3. **콜봇 enrich 62ms 급증**: history 케이스 재현 N회 — 노이즈 vs 실제.
4. **rerank 부하 의존성**: 동시 검색 부하(c=8 등)에서 rerank가 GPU 큐잉으로 급증하는지(선행문서 c=8 tail 언급).

## 6. 개선 후보 (우선순위·영향·리스크)

| # | 개선 | 영향 | 리스크/비고 |
|---|---|---|---|
| ~~1~~ | ~~임베딩 캐시~~ | **폐기(§9)** — 임베딩 27ms로 병목 아님, 검색경로 캐시 부재·이득 ≤27ms | — |
| 2 | **동시부하 tail = 단일 B200 GPU 경합 해소** (§10/§11/§12) | 단일요청 OK(~165ms), **c=8 total p50 ~600ms(3.9배)**. 원인=**embedder+reranker가 cuda:0 공유**→둘 다 3.4~3.6x 열화(§12). retrieval·api큐 무관 | (a)embedder/reranker **GPU·스트림 분리**(근본) (b)embed·rerank **둘다 배칭** (c)증설. **rerank 배칭 단독=tail ~44%만**(embedding 경합 잔존). 단순off 불가(품질−40%)·후보축소 config고정·동시제한은 큐지연. 모두 NHN 공유 B200 `unified_server.py` 변경 |
| 4 | **intent_gate 정책** | ON 경로 ~480ms. 콜봇·웹은 이미 off(정상), 어드바이저만 on | 어드바이저는 잡담 조기차단에 의도적. 끄면 false-empty 리스크([[project_search_intent_gate]]). 부수: 정상도메인 오분류 관측 |
| 5 | **대화형 캐시 키/TTL** | hit율↑(현 TTL 300s+history ctx로 거의 매번 miss) | ctx 약화는 context-weighting 손상. TTL연장/현발화 부분캐시 설계 필요 |
| 6 | **Okt warmup 다양화** (§8) | 잔여 JIT 누출(#7 545ms) 제거 | `_common.py:160` 더미 단일→다양 패턴. 저위험·소변경 |

**즉효·저위험 순(정정)**: ②rerank(콜봇 핵심) → ⑥warmup다양화 → ⑤대화캐시TTL → ④intent_gate(어드바이저 정책). **①임베딩 폐기.**

## 8. Okt JIT cold-start 재현 (2026-06-20)

`lucas-kms-api`(uvicorn `--workers 4`) 재시작으로 cold 강제 후 즉시 burst 15회 측정.

**스파이크 위치 = `query_preprocessed`(Okt 형태소분석), 명확.** 다른 단계(embedding/rerank) 아님.

**startup warmup 4건(워커당 1회) — 진짜 JIT는 여기서 흡수** (원문):
```
query_preprocessed latency_ms=6104  original='검색 워밍업 더미' → okt_warmup_done
query_preprocessed latency_ms=5591  ...
query_preprocessed latency_ms=6103  ...
query_preprocessed latency_ms=6193  ...
```
워커 4 = warmup 4 = JIT 4회(5.6~6.2초/워커). `/health/ready` 200까지 ~11.4초 = 이 비용. 메커니즘: `src/api/_common.py:154-161` lifespan에서 워커별 `QueryPreprocessor().preprocess("검색 워밍업 더미")` 1회.

**사용자 burst preprocess(=Okt) ms**: 대부분 2~23ms(warm). 예외 **#7 `해외 주식 입고 가능 수량` = 545ms**(2차 JIT 누출), 이후 #8부터 23→5→4→2ms 정착. total_latency도 400→130ms대 수렴.

**결론**: JIT(~6s/워커)는 실재하나 startup warmup이 대부분 흡수 → 사용자 첫 검색 보호됨. 잔여 545ms 1회는 더미가 단일패턴이라 특정 형태소 경로 미예열 탓 → **warmup 다양화(개선 #6)** 로 제거 가능. (부수 확인: KMS `/api/v1/search`는 `X-Tenant-Id` 헤더 필요; blocks 482→832로 증가.)

## 7. 한 줄 요약 (정정)

검색 자체는 **캐시 hit이면 ~10ms**. 콜봇 단일요청 ~165ms(rerank ~100ms가 절반). **진짜 문제는 동시부하 tail**: c=8서 total p50 ~600ms(3.9배). **원인은 rerank 단독이 아니라 embedder와 reranker가 같은 단일 B200 GPU(cuda:0)를 공유해 둘 다 ~3.4~3.6x 동반 열화**(§12 확정). retrieval(Qdrant/ES)·api큐잉 무관. **콜봇 tail의 진짜 레버 = 공유 GPU 경합 해소**(embedder/reranker GPU분리·둘다 배칭·증설); rerank 배칭 단독은 tail의 ~44%. 어드바이저는 intent_gate(480ms)+답변LLM(2s)이 별개. 임베딩캐시·Okt JIT는 부차.

## 9. 임베딩 캐시/비용 측정 (2026-06-20) — 가설 반증

| 측정 | 결과 |
|---|---|
| 순수 쿼리 임베딩(B200 :7125/embed 직접) | **~25~29ms, cold=warm** (프록시 자체 캐시 없음) |
| 검색경로 임베딩 캐시 | **없음** — `search/embedding_proxy.py EmbeddingProxyClient.embed()` 무캐시. `EmbeddingCache`(`pipeline/embedders/bge_m3.py`, 키 `aicm:embed:bge-m3:{sha}`, TTL 30일, 4379키)는 **인제스트 전용** |
| 격리측정 A(둘다 cold) vs B(result-miss+embed-hit) | A−B ≈ **−8ms(노이즈)** → 임베딩 캐시 이득 0 |
| "~300ms 사각" 정체 | **Intent Gate LLM** — 라우터가 `classify_intent`(LLM)+검색을 `asyncio.gather` 병렬. gate ON시 curl 515ms(intent latency_ms=486), OFF시 내부 170ms. 초판의 504−203=301ms가 정확히 이 구간 |
| 결과캐시 TTL | **300초**(짧음). `aicm:search_cache:{hash}` |

**결론**: 임베딩은 병목이 아니며(개선 ① 폐기), 큰 비용은 (ON일 때) intent_gate. **콜봇/웹은 intent_gate off가 정상**이라 그 비용을 안 물고, 남는 지배요인은 **rerank**. 부수: intent 분류기가 정상 도메인 쿼리("해외주식 양도소득세")를 도메인외로 오분류해 gate ON시 빈 결과 → 분류 정확도 별도 점검 필요.

## 10. rerank 비용/품질/동시부하 측정 (2026-06-20, 재측정 n=396)

intent_gate OFF 고정(콜봇 조건). 캐시미스 실측. 후보수=20(전 요청 input_count=20). **재측정으로 조건당 n 강화(A n=20×2, B n=20/48/96), 시간대 2패스 검증.**

**비용 격리(ON vs OFF, n=20 each, 분포)**: ON total p50 153.5 / OFF p50 54.0 → **rerank 순비용 p50 ≈99.5ms**(rerank step 직접 p50 94ms와 일치). p95: ON total 203 / rerank step 143. (초판 "≈61ms"는 저샘플 저부하 하단치, 분포로 p50 95~100ms·p95 140ms로 정정.)

**후보수**: `src/search/models.py:137` `candidate_pool_size: int = 20`(SearchConfig). `_resolve_config`(service.py:130-169)가 candidate_pool_size를 **안 읽음**, SearchRequest에 필드 **없음** → **per-request 불가, config 고정**. 20→10/5 축소는 **KMS 코드 수정 필요**(API 측정 불가). (이력: 50→20은 이미 적용.)

**품질(rerank ON vs OFF, top-5 chunk_id 5쿼리)**: 평균 overlap **3.0/5(60%)**, top-1 변동 **4/5**, 순서변동 5/5 → **단순 off는 상위결과 40% 교체·1위 대부분 변경 = 품질 손상 명백**.

**동시부하 분포(c=1/4/8, distinct 쿼리, n=20/48/96)**:
| 동시도 | total p50 | total p95 | total max | rerank p50 | rerank p95 |
|---|---|---|---|---|---|
| c=1 | 165.5 | 196.9 | 214 | 83.0 | 123.1 |
| c=4 | 311.0 | 358.0 | 362 | 150.5 | 193.0 |
| **c=8** | **593.5** | **652.8** | **716** | **300.0** | **399.2** |
→ **c=8서 total p95가 c=1 대비 3.3배(197→653ms), rerank 동일비율 증가 = B200 reranker 직렬화/큐잉 tail.** 시간대 2패스(3분 간격) p50 차 4% = 분포 안정. **"61~138ms 흔들림" = c=1 단일호출 rerank의 정상 분포**(p50 83/p95 123/max 144), 이상 아님. 부하 시 3배+ 확대.

**결론**: 콜봇 rerank 이슈는 평속(~61ms)이 아니라 **동시부하 tail(rerank 155ms·total 400ms대)**. 안전 절감: (a) 결과캐시 hit(1~3ms로 전부 우회)+빈출쿼리 TTL연장, (b) **reranker 동시호출 제한/배칭**(off보다 무손상으로 tail 절감), (c) 조건부 rerank(fusion 상위 점수차 충분시 생략, 코드변경). **단순 off·후보축소(코드없이)는 부적합.** 파일: `src/search/reranker/cross_encoder.py:135-210`(원격 GPU rerank), `src/search/cache.py:79-115`(캐시키).

## 11. reranker 서버 배칭 확정 (B200 소스, 2026-06-20)

접근: 로컬→timbel(SSH)→B200 점프(방화벽으로 B200 직접 불가). timbel systemd `aicm-b200-tunnel.service`가 `:7125(timbel)→localhost:35001(B200)` 터널. B200 = `59.150.35.1:49910`, user `timbel_dhsh`, key `/home/timbel/.ssh/DCTN-0523174639_key`.

**구동 서버**: `/NHNHOME/WORKSPACE/0426030034_A/kms_unified_server/unified_server.py` (embed+rerank 통합, `uvicorn unified_server:app --port 35001`, **단일 워커**). reranker=bge-reranker-v2-m3, sentence-transformers `CrossEncoder`, fp16, cuda:0.

**/rerank 핸들러(인용)**:
```python
_lock = asyncio.Lock()   # 모델 로드 전용(추론 아님)
@app.post("/rerank")
async def rerank(req):
    pairs = [[req.query, c.content] for c in req.candidates]
    scores = await asyncio.to_thread(lambda: _reranker.predict(pairs, show_progress_bar=False))
```

**판정: 교차요청 동적 배칭 없음.** 배치 큐/수집윈도/max_batch_size/배처 라이브러리 전무. 요청마다 자기 candidates만 독립 `predict` 1회(요청 내부 배치는 ST 자동, 교차요청 합산 없음). 추론은 `asyncio.to_thread`(기본 ThreadPoolExecutor)로 오프로드, 명시적 직렬화 lock 없음 → 동시 요청은 단일 CUDA에서 경합/순차. → **§10의 c=8 tail 원인 확정.**

**개선 방향**: 마이크로 배칭은 **부재 → 도입 여지 명확**("있는데 한계"가 아님). 동적 배칭 큐(짧은 윈도로 동시 `/rerank`를 모아 max_batch_size까지 합쳐 1 predict) 도입 시 GPU 활용↑·tail↓, 배치 내 요청 함께 완료(동시제한의 큐지연 없음). **단 수정 대상이 NHN 공유 B200의 `unified_server.py`라 신중**(공유 GPU·embed와 동일 프로세스·단일워커). 도입 전 배치 윈도/최대크기·embed 영향·동시성 안전성 설계 필요.

## 12. c=8 단계별 분해 — tail 정체 확정 (2026-06-20, §6리뷰 결함2 규명)

§10 c=8 tail을 "rerank 주동인"으로 본 것은 **과귀속**이었음. 단계별 분해 결과 정정:

| 단계 | c1 p50 | c8 p50 | 배율 |
|---|--:|--:|--:|
| dense/sparse/keyword | 18~22 | 14~19 | **~1x (스케일 안 함)** |
| rerank | 104 | 374.5 | **3.6x** |
| gap(total−pre−max(retr)−fusion−rerank) | 30.5 | 218.5 | **7.2x** |
| total | 158.5 | 613 | 3.9x |
| **/embed 직접 (B200 :7125)** | 68.3 | 231.8 | **3.4x** |

**확정**:
- **retrieval(Qdrant/ES)은 동시부하서 불변 → 병목 아님.** api 큐잉 단독 기여 ≤24ms.
- gap(=embedding+오버헤드)이 7.2x 폭증, gap 증가분 +188ms의 **~87%(163ms)가 embedding 경합**(/embed 직접 c=8 3.4x로 확증).
- **근본 = embedder와 reranker가 동일 cuda:0(단일 B200 GPU) 공유** → 동시부하서 둘 다 ~3.4~3.6x 동반 열화. rerank tail과 비-rerank(embedding) tail은 **같은 GPU 경합의 두 얼굴**.

**개선 함의(시정)**:
- **rerank 배칭만 = tail의 ~44%**(rerank 374→104 복원 시 total 613→~342). **embedding 경합(+188ms)은 잔존** → rerank 배칭 단독 불충분.
- 진짜 레버: (a) **embedder/reranker 별도 GPU·스트림 분리**(교차경합 제거, 가장 근본) (b) embed·rerank **둘 다 배칭** (c) B200 증설. 단 모두 **NHN 공유 B200 `unified_server.py`/배포** 변경이라 신중.

**측정 주의**: c=1 gap(30.5) < /embed직접(68)은 검색 파이프라인 embedding이 일부 overlap(HyDE/병렬)됨을 시사 → gap 절대치는 근사. 단 **스케일 배율(embedding 3.4x, gap 7.2x, retrieval 1x)은 견고**해 "비-rerank tail=GPU경합" 결론은 확정.
