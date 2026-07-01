# 검색 쿼리 임베딩 동적 배칭 — 설계 (spec)

> 2026-06-21 · 대상: NHN 공유 B200 `kms_unified_server/unified_server.py` `/embed`
> 선행: rerank 동적 배칭(`RerankBatcher`, 구현·배포·검증 완료, `2026-06-21-rerank-dynamic-batching-design.md`). 본 작업은 그 임베딩판.

## 목표
검색 쿼리 임베딩의 단일 cuda:0 동시경합을 동적 마이크로배칭으로 완화한다. 신규 `EmbedBatcher`가 동시 단일텍스트 `/embed` 요청을 짧은 윈도로 모아 `_embedder.encode([t1..tN])` 1회로 합산 추론하고 결과를 요청별 index로 분배한다.

## 근거 (측정, 2026-06-21 timbel, rerank 배칭 이후)
- `/embed` 직접 격리(authoritative): c=1 p50 **67ms** → c=8 p50 **~177ms (2.7x)**. 임베딩 자체 성능은 §12와 불변(c=1 67≈68ms).
- c=8 검색 total(273~370ms)에서 임베딩 잔차 ~151ms = **최대 단일 기여항목(~55%)**, rerank 104ms(38%). rerank 배칭 후 임베딩이 tail 1순위.
- 근본: 검색 쿼리 임베딩(`src/search/embedding_proxy.py`)이 **무배칭·무캐시 단일텍스트** `/embed`(legacy `{"text":...}`) → 동시 N개가 `encode([1 text])`를 단일 cuda:0에서 직렬 경합. (EMBEDDING_PROXY_URL=`host.docker.internal:7125`, rerank와 같은 unified_server.)
- 캐시(레버 B)는 distinct 쿼리·콜봇 reformulation으로 hit률 낮아 **범위 제외**(사용자 결정). 배칭만.

## Architecture
신규 `EmbedBatcher`(별도 클래스, RerankBatcher를 본뜸 — 검증된 live RerankBatcher는 불변). `/embed`의 **legacy 단일텍스트 분기만** 배처 경유. batch 분기(`{"texts":[...]}`, 인제스트)는 현행 코드 그대로(배처 미경유) — 인제스트는 latency 민감 X·대형 배치라 쿼리와 섞으면 쿼리 tail 악화.

외부 `/embed` 요청/응답 스키마 불변, KMS 클라이언트(`embedding_proxy.py`) 무수정, 인제스트 경로 무수정.

## Global Constraints (binding — 모든 태스크에 적용)
- 외부 `/embed` API(legacy `{"text"}`/batch `{"texts"}` 양식, 응답 포맷) 불변. KMS `embedding_proxy.py`·인제스트 batch 경로 무수정.
- startup = lifespan(`@asynccontextmanager`) + `FastAPI(lifespan=)` — `@app.on_event` 아님. 배처 기동은 lifespan.
- **검증된 live `RerankBatcher`·`rerank_batcher.py`는 절대 수정 금지**(surgical). EmbedBatcher는 신규 별도 파일/클래스.
- legacy 핸들러의 보존 필수: `await _load_embedder()` 선행, 빈 텍스트 가드, legacy 응답 양식. 변환 **의미**(`.tolist()`·`{str(k):float(v)}`)는 보존하되 plumbing은 `out["dense_vecs"]`/`out["lexical_weights"]` → 배처가 준 슬라이스(`dense_vec_i`, `lw_i`)로 조정. 배처는 **raw 슬라이스만 반환**(rerank의 `scores=[float(s)...]` 보존과 동형).
- predict_fn의 `_embedder`는 호출시점 전역참조(lazy 호환). 핸들러가 submit 전 `await _load_embedder()` 호출.
- 신규 EmbedBatcher엔 rerank M-3 후속 **선반영**: `_run_loop` 바깥 except에 `logging.exception` + 미완료 future `set_exception`(이론적 hang 차단).
- 확정 파라미터(max_batch_texts/batch_wait_ms/max_queue)는 Phase 0 측정으로 도출.
- 배칭은 임베딩 벡터를 바꾸면 안 됨(텍스트별 독립 인코딩 + index 분배 정확성).
- 배포·측정: B200 접근은 timbel(`timbel@124.194.32.36:17777`) 경유만, B200 점프 `timbel_dhsh@59.150.35.1:49910 -i DCTN-0523174639_key`. 단일 자격증명 1회(무차별 금지). 측정 중 **`aicm:embed:*` 절대 삭제 금지**(`aicm:search_cache:*`만). B200 의존성 재설치 금지(최소 재기동).

## EmbedBatcher (컴포넌트)
- `EmbedBatcher(predict_fn, max_batch_texts, batch_wait_ms, max_queue)`. `predict_fn(texts: list[str]) -> dict` (= `_embedder.encode(texts, batch_size=16, return_dense=True, return_sparse=True)` 결과 dict, keys `dense_vecs`/`lexical_weights`).
- `start()` — `_run_loop` task 생성.
- `async submit(text: str) -> tuple[list, dict]` — 요청당 1텍스트. qsize ≥ max_queue 시 overflow raise. `get_running_loop().create_future()`. (dense_vec_i, lexical_weights_i) raw 슬라이스 반환.
- `_run_loop` — 첫 항목 get(blocking) → batch_wait_ms 윈도/max_batch_texts 소프트캡까지 수집 → `texts=[t for ...]` → `out = await asyncio.to_thread(predict_fn, texts)` → 각 future에 `(out["dense_vecs"][i], out["lexical_weights"][i])` **index 분배**(요청=1텍스트라 offset 아님). 키 부재 시 빈값 graceful. predict 예외 → 배치 future set_exception 후 continue(루프 생존). 바깥 except → logging.exception + 미완료 future set_exception.

## 데이터 흐름 (/embed legacy 분기)
변경 전:
```python
texts = [text]; ...
out = await asyncio.to_thread(_encode)   # _encode = _embedder.encode(texts, ...)
# 이후 dense_list=[v.tolist()...], single_dense, single_sparse_dict 조립
```
변경 후(legacy 분기에서 encode 호출만 교체):
```python
if _embed_batcher is None: raise RuntimeError("embed batcher not initialized")
dense_vec_i, lw_i = await _embed_batcher.submit(text)
# 이후 변환·조립은 기존과 동일: single_dense = dense_vec_i.tolist() if hasattr... ;
#   single_sparse_dict = {str(k): float(v) for k,v in lw_i.items()}
```
batch 분기·embed 응답 포맷·sparse 변환 규칙 전부 보존.

## 에러 처리
- predict 예외 → future set_exception → `embedding_proxy.embed`가 RuntimeError 수신 → KMS 빈 벡터 graceful degradation(기존 동작). 루프 생존.
- `_embed_batcher is None`(lifespan 미기동) 가드 → RuntimeError.
- max_queue overflow → 즉시 거부.
- `_run_loop` 바깥 except → logging.exception + 미완료 future set_exception(hang 차단).

## Phase 0 검증 게이트 (구현 전 필수)
배칭이 실제 경합을 줄이는지 **B200-local**에서 실측(터널 RTT 희석 회피 — rerank 교훈):
- `encode([N texts])` 1회 vs `N×encode([1])` 동시(현행) 의 server-compute latency 비교(c=8 상당, N=8).
- max_batch_texts 후보(16/32/64; encode 내부 batch_size=16 고려)별 측정 → 확정 파라미터 도출.
- **게이트**: 배칭이 c=8 server-compute를 ≥30% 단축(rerank 동일 기준). **그리고 c=1 회귀 점검**: batch_wait_ms 가산이 단일 쿼리(67ms)에 과도하지 않은지(wait_ms 작게 — c=1 회귀 목표 ≤ +10%). 미달 시 구현 보류·재설계.

## 테스트 (`test_embed_batcher.py`, 신규)
predict_fn은 가짜(index 식별 가능한 더미 dense/sparse) 주입. ①단일 submit ②동시 N + **index 분배 정확성**(각 요청이 자기 dense/sparse 수신) ③predict 예외 전파 ④소프트캡 분할 ⑤queue overflow 2종(max_queue=0, 적체) ⑥sparse dict 보존(키/값 매핑). DeprecationWarning=error로 실행.

## 배포 (rerank와 동일 절차)
로컬 develop 구현·테스트 → B200 `unified_server.py` 백업(타임스탬프) → 파일 반영(`embed_batcher.py` 신규 + 수정 `unified_server.py`)·md5·AST → **최소 재기동**(uvicorn, 의존성 재설치 X) → health(ready) + `/embed` 스모크(단일텍스트 200, dense 1024차원·sparse 정상) → 실패 시 `.bak` 복원.

## 통합 검증 (배포 후)
- before/after: **`/embed` 직접 격리를 authoritative**(검색경로 embedding step은 로그 미노출). c=1/4/8 {p50,p95,max} + c=8/c=1 배수. 콜봇 c=1/4/8 total도 보조.
- 품질: 동일 텍스트 임베딩이 배칭 전후 **동일 벡터**(dense·sparse). index 분배 버그 회귀 검출.
- vLLM 동반부하 c=8: 실 콜봇 조건서 tail 개선 유지.
- VRAM: encode 내부 batch_size=16라 GPU forward는 ≤16텍스트(누적 max_batch_texts 무관). 부하 중 ΔVRAM·OOM 로그 확인(9GB 헤드룸).

## 한계
- 런타임 cp drift(unified_deploy.sh 재실행 시 덮임) — rerank와 동일, 영구화 별도 결정.
- 현 GPU 부하 가벼워 무부하 절대개선폭 작을 수 있음(고경합·vLLM 부하서 이득 큼).
- c=1 batch_wait_ms 세금은 구조적 — Phase 0에서 허용범위 확인.

## Phase 0 결과 (2026-06-21, PASS)
B200-local localhost:35001, 기존 /embed 이중모드(batch `{"texts":N}`=배칭후 / 단일 `{"text"}` N동시=현경합), 각 N 5회 p50 2런.

| N | concurrent_single wall p50 | batched_once p50 | reduction |
|---|---|---|---|
| 8 | 171~173ms | 16ms | **90~91%** |
| 16 | 359~368ms | 22~23ms | 94% |
| 32 | 767~769ms | 37ms | 95% |
| 64 | 1434~1548ms | 66ms | 95~96% |

**게이트 PASS**: N=8 reduction 90%(≥30% 큰 마진). **확정 파라미터: max_batch_texts=32**(reduction 95% 포화, batched 37ms 콜봇예산 내, N=64는 한계이득뿐인데 배치 compute 2배→HoL blocking↑라 32 채택), **batch_wait_ms=6**, **max_queue=1000**. rerank(66~77%)보다 임베딩 배칭 이득이 큼(동시 encode가 단일 GPU서 심하게 직렬화).
