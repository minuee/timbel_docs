# 검색 쿼리 임베딩 동적 배칭 — before/after 검증

> 측정 2026-06-21 · timbel_5fl(호스트 내부) · /embed 직접 격리 authoritative(검색경로 embedding step 로그 미노출)
> 배포: develop a7e3d94(EmbedBatcher + /embed legacy 배선), B200 런타임 cp(백업 `unified_server.py.bak.20260621T034123Z`). drift=영구화 별도.
> 확정 파라미터: max_batch_texts=32, batch_wait_ms=6, max_queue=1000. 매 조건 `aicm:search_cache:*` flush, `aicm:embed:*`(4379) 불변.

## /embed 직접 격리 (authoritative, 단일텍스트 동시, 2런)
| conc | before p50 | after p50 | after p95 | 비고 |
|------|-----------|-----------|-----------|------|
| c=1 | 67ms | **71ms** | 73 | batch_wait_ms=6 세금 +6.6%(≤10% 게이트 통과) |
| c=4 | ~86~121ms | **33~40ms** | ~45 | 대폭 단축 |
| c=8 | **177ms (2.7x)** | **38~41ms** | ~44~73 | **4.4~4.7x 단축** |

**c=8/c=1 배수: before 2.7x → after 0.53~0.57(<1.0).** 8개 동시 단일텍스트가 1회 encode로 합쳐져 c=8이 c=1보다 빠름 — 배칭 정상 동작의 명확한 signature. (Phase 0: 8텍스트 batched encode = 16ms server-compute와 정합.)

## 콜봇 total (보조 — 권위값은 위 §직접격리)
| conc | before total p50 | after p50 | after p95 |
|------|-----------|-----------|-----------|
| c=1 | — | 185 | 237 |
| c=4 | — | 124 | 275 |
| c=8 | **~317ms** | **134ms** | 367 |
콜봇 c=8 total ~317→134(p50 -58%). p95 tail은 검색경로 retrieval/rerank 변동성.

## 품질 — 벡터 동일성 (index 분배 정확성)
- 동일 텍스트 2회: dense+sparse **bit-identical**(5/5 결정적 재현).
- 배치경유 vs 단독: self-cosine **0.99999840~0.99999916**, max|diff| 1.5e-4~4.9e-4(fp16 라운딩 수준), **swap 0건**(모든 배치 벡터가 자기 단독벡터에 최근접). → index 분배/매핑 정확, 차이는 GPU 부동소수 비결정성(배치 구성 변동)일 뿐.
- 서로 다른 5텍스트 → 5 distinct dense(1024차원, L2 norm≈1.0, bge-m3 정규화).

## vLLM 동반부하 + VRAM (gemma-4-31B-it 4-worker 70s 동반)
- /embed c=8 p50 **61ms**(idle 38 → 동반 61, before 177 대비 여전히 대폭 우위), c=8/c=1=0.84(배칭 유지).
- 콜봇 c=8 p50 36ms / **p95~1.9s·max~2.0s** — tail 급증은 단일 cuda:0를 vLLM 생성과 공유하는 기존 GPU-공유 경합 산물(p50은 건전).
- ΔVRAM: embedder idle 2958 → 부하 peak **4012 MiB(Δ~1.05GB)**, 전체 ~10.4GB 여유. **OOM 로그 없음**.

## 판정: 회귀 없음 — 게이트 통과
c=1 세금 +6.6%(≤10%) · c=8 p50 177→38ms(**4.7x**, c=8/c=1<1.0) · 벡터 매핑 정확(swap 0, cos~1.0) · vLLM 동반부하 OOM無·ΔVRAM~1GB(헤드룸 내). rerank 배칭(c=8 1.5x)보다 임베딩 배칭 이득이 큼(동시 encode가 단일 GPU서 심하게 직렬화하던 것을 1회 합산으로 해소).

## 한계
- 런타임 cp drift(unified_deploy.sh 재실행 시 덮임) — 영구화 별도 결정.
- 콜봇 total은 검색경로 다단계라 임베딩 배칭 효과 일부만 반영 — 권위값은 /embed 직접격리.
- 1차 배포는 `embed_batcher.py`의 `or []`가 numpy ndarray서 ValueError(단일 /embed 500) → None 가드로 수정(a7e3d94)·ndarray 회귀테스트 추가 후 재배포. 단위테스트 fake가 plain list라 못 잡은 케이스(교훈).
