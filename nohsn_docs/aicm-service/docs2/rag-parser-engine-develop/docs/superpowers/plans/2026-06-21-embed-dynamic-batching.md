# 검색 쿼리 임베딩 동적 배칭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** B200 `unified_server.py`의 `/embed` legacy 단일텍스트 경로에 동적 마이크로배칭(`EmbedBatcher`)을 추가해 동시 검색 쿼리 임베딩의 단일 cuda:0 직렬경합을 완화한다.

**Architecture:** 신규 `EmbedBatcher`(검증된 `RerankBatcher`를 본뜬 별도 클래스)가 동시 단일텍스트 `/embed` 요청을 짧은 윈도로 모아 `_embedder.encode([t1..tN])` 1회로 처리하고 결과를 요청별 index로 분배한다. `/embed`의 legacy 분기만 배처 경유, batch(인제스트) 분기는 현행 유지. 외부 API·KMS 클라이언트 불변.

**Tech Stack:** Python(asyncio), FastAPI lifespan, FlagEmbedding BGEM3FlagModel(B200, sentence-transformers 5.x/py≥3.10), pytest+pytest-asyncio.

## Global Constraints

- 외부 `/embed` API(legacy `{"text"}`/batch `{"texts"}`, 응답 포맷) 불변. KMS `src/search/embedding_proxy.py`·인제스트 batch 경로 무수정.
- startup = lifespan(`@asynccontextmanager`)+`FastAPI(lifespan=)` — `@app.on_event` 아님. 배처 기동은 lifespan.
- **검증된 live `RerankBatcher`/`rerank_batcher.py` 절대 수정 금지.** EmbedBatcher는 신규 별도 파일.
- legacy 핸들러 보존: `await _load_embedder()` 선행, 빈 텍스트 가드, 변환 의미(`.tolist()`·`{str(k):float(v)}`). 배처는 raw 슬라이스(`dense_vec_i`, `lw_i`)만 반환.
- predict_fn의 `_embedder`는 호출시점 전역참조(lazy 호환). 핸들러가 submit 전 `await _load_embedder()` 호출.
- 신규 EmbedBatcher 바깥 except에 `logging.exception` + 미완료 future `set_exception`(hang 차단).
- 확정 파라미터(max_batch_texts/batch_wait_ms/max_queue)는 Phase 0(Task 1) 도출. 미통과 시 구현 보류.
- 배칭은 임베딩 벡터를 바꾸면 안 됨(텍스트별 독립 encode + index 분배 정확성).
- 배포·측정: B200 접근은 timbel(`ssh -p 17777 timbel@124.194.32.36`, 비번 `ha838131@`) 경유, B200 점프 `ssh -p 49910 -i /home/timbel/.ssh/DCTN-0523174639_key timbel_dhsh@59.150.35.1`. 단일 자격증명 1회(무차별 금지). **`aicm:embed:*` 절대 삭제 금지**(`aicm:search_cache:*`만). B200 의존성 재설치 금지(최소 재기동). B200 작업경로 `/NHNHOME/WORKSPACE/0426030034_A/kms_unified_server`.

---

### Task 1: Phase 0 검증 게이트 (B200-local, 기존 /embed 이중모드 활용)

**Files:** 없음(B200 측 측정). 결과는 spec 부록으로 기록.

**Interfaces:**
- Consumes: 현재 live `/embed`(legacy `{"text"}` 단일 + batch `{"texts"}` 1회 encode). batch 포맷 = "배칭 후 server-compute" 대리, 동시 single = "현 경합" 대리.
- Produces: PASS/FAIL + 확정 `max_batch_texts`(통과 시 Task 2/3 사용).

**핵심 통찰**: 기존 `/embed`의 batch 분기 `{"texts":[N]}`가 이미 `encode(texts, batch_size=16)` 1회 = "배칭 후" 그 자체다. 신규 코드/모델 로드 없이 현 서버로 전제 검증 가능(VRAM 리스크 0). **B200-local(localhost:35001)** 측정으로 터널 RTT 희석 회피.

- [ ] **Step 1: B200 접속 + 측정 스크립트 작성**

timbel 경유 B200 접속 후 `/NHNHOME/WORKSPACE/0426030034_A/kms_unified_server/phase0_embed.py` 작성:

```python
import json, time, urllib.request, statistics
from concurrent.futures import ThreadPoolExecutor
URL = "http://localhost:35001/embed"

def post(body):
    data = json.dumps(body).encode()
    r = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    resp = urllib.request.urlopen(r, timeout=60); resp.read()
    return (time.perf_counter() - t) * 1000.0

TEXTS = [f"적금 금리 펀드 청약 운용 보고서 안내 샘플 변형 {i}" for i in range(64)]

def concurrent_single_wall(n):
    # n개 단일텍스트 동시 호출 -> 전체 완료까지 wall = 가장 느린 호출
    with ThreadPoolExecutor(max_workers=n) as ex:
        lat = list(ex.map(lambda t: post({"text": t}), TEXTS[:n]))
    return max(lat)

def batched_once(n):
    return post({"texts": TEXTS[:n], "return_dense": True, "return_sparse": True})

post({"text": "warmup"}); batched_once(8)  # JIT 워밍업
for n in (8, 16, 32, 64):
    cs = sorted(concurrent_single_wall(n) for _ in range(5))
    bt = sorted(batched_once(n) for _ in range(5))
    cs_p50, bt_p50 = cs[len(cs)//2], bt[len(bt)//2]
    red = 100 * (1 - bt_p50 / cs_p50)
    print(f"N={n}: concurrent_single wall p50={cs_p50:.0f}ms  batched_once p50={bt_p50:.0f}ms  reduction={red:.0f}%")
```

- [ ] **Step 2: 실행**

Run (B200): `cd /NHNHOME/WORKSPACE/0426030034_A/kms_unified_server && venv/bin/python phase0_embed.py`
Expected: N=8/16/32/64 각 줄에 concurrent_single wall, batched_once, reduction% 출력.

- [ ] **Step 3: 게이트 판정 + 확정 파라미터**

게이트(둘 다 충족):
1. N=8에서 **reduction ≥ 30%**(배칭이 동시 대비 c=8 server-compute를 유의미 단축).
2. `max_batch_texts` = reduction이 유지되면서 batched_once 절대 latency가 과도하지 않은 최대 N(예: N=32에서 reduction 유지·batched p50가 콜봇 예산 내면 32; 후보 16/32/64 중 택). `batch_wait_ms`는 **6 이하**로 고정(c=1 회귀 ≤ ~9%: 67ms 기준). `max_queue=1000`.

미달 시: 구현 보류, 결과 보고 후 재설계. 통과 시 확정값 기록.

- [ ] **Step 4: 결과를 spec 부록으로 기록**

`docs/superpowers/specs/2026-06-21-embed-dynamic-batching-design.md` 끝에 `## Phase 0 결과` 추가: N별 수치표, PASS/FAIL, 확정 max_batch_texts/batch_wait_ms/max_queue. phase0_embed.py는 B200에서 삭제(임시).

```bash
git add docs/superpowers/specs/2026-06-21-embed-dynamic-batching-design.md
git commit -m "docs(embed-batching): Phase 0 게이트 결과 기록(확정 파라미터)"
```

---

### Task 2: EmbedBatcher 클래스 + 단위테스트

**Files:**
- Create: `kms_unified_server/embed_batcher.py`
- Test: `kms_unified_server/test_embed_batcher.py`

**Interfaces:**
- Consumes: Task 1 확정 파라미터(기본값에 반영; 미반영 시 32/5/1000).
- Produces: `EmbedBatcher(predict_fn, max_batch_texts=<P0>, batch_wait_ms=<P0>, max_queue=1000)`, `.start()`, `async submit(text: str) -> tuple[dense_vec, lexical_weights]`. predict_fn(texts: list[str]) -> dict(keys `dense_vecs`/`lexical_weights`).

- [ ] **Step 1: 실패 테스트 작성**

`kms_unified_server/test_embed_batcher.py`:

```python
import asyncio
import os
import sys

import pytest

# B200 런타임은 cwd=kms_unified_server/ 라 flat import. 테스트도 동일하게 맞춤.
sys.path.insert(0, os.path.dirname(__file__))
from embed_batcher import EmbedBatcher  # noqa: E402


def _idx_predict(texts):
    # 텍스트 순서대로 인덱스를 dense/sparse에 — index 분배 검증용
    return {
        "dense_vecs": [[float(i)] for i in range(len(texts))],
        "lexical_weights": [{str(i): float(i)} for i in range(len(texts))],
    }


@pytest.mark.asyncio
async def test_single_request():
    b = EmbedBatcher(_idx_predict)
    b.start()
    dense, sparse = await b.submit("a")
    assert dense == [0.0]
    assert sparse == {"0": 0.0}


@pytest.mark.asyncio
async def test_concurrent_requests_single_encode_and_index():
    calls = []
    def predict(texts):
        calls.append(len(texts))
        return {
            "dense_vecs": [[float(i)] for i in range(len(texts))],
            "lexical_weights": [{str(i): float(i)} for i in range(len(texts))],
        }
    b = EmbedBatcher(predict, batch_wait_ms=20)
    b.start()
    r = await asyncio.gather(b.submit("a"), b.submit("b"), b.submit("c"))
    assert calls == [3]                       # 동시 도착 -> 1회 encode(3 texts)
    assert r[0] == ([0.0], {"0": 0.0})
    assert r[1] == ([1.0], {"1": 1.0})
    assert r[2] == ([2.0], {"2": 2.0})


@pytest.mark.asyncio
async def test_predict_exception_propagates():
    def predict(texts):
        raise RuntimeError("gpu boom")
    b = EmbedBatcher(predict)
    b.start()
    with pytest.raises(RuntimeError, match="gpu boom"):
        await b.submit("a")


@pytest.mark.asyncio
async def test_max_batch_texts_soft_cap_splits():
    calls = []
    def predict(texts):
        calls.append(len(texts))
        return {
            "dense_vecs": [[float(i)] for i in range(len(texts))],
            "lexical_weights": [{} for _ in range(len(texts))],
        }
    b = EmbedBatcher(predict, max_batch_texts=2, batch_wait_ms=20)
    b.start()
    await asyncio.gather(b.submit("a"), b.submit("b"), b.submit("c"))
    assert sum(calls) == 3            # 전 텍스트 처리
    assert len(calls) >= 2            # max_batch_texts=2로 2배치 이상 분할


@pytest.mark.asyncio
async def test_queue_overflow_raises():
    b = EmbedBatcher(_idx_predict, max_queue=0)  # 소비 전 큐검사
    with pytest.raises(RuntimeError, match="overflow"):
        await b.submit("a")


@pytest.mark.asyncio
async def test_queue_overflow_when_filled():
    import time as _t
    slow = asyncio.Event()

    def predict(texts):
        while not slow.is_set():
            _t.sleep(0.005)
        return {"dense_vecs": [[0.0]] * len(texts), "lexical_weights": [{}] * len(texts)}

    b = EmbedBatcher(predict, max_queue=2, batch_wait_ms=1)
    b.start()
    t1 = asyncio.create_task(b.submit("a"))
    await asyncio.sleep(0.05)         # 루프가 t1 소비 -> predict(블로킹) 진입, 큐 빔
    t2 = asyncio.create_task(b.submit("b"))
    t3 = asyncio.create_task(b.submit("c"))
    await asyncio.sleep(0.05)         # t2,t3 큐 적재(qsize=2)
    with pytest.raises(RuntimeError, match="overflow"):
        await b.submit("d")           # qsize(2) >= max_queue(2)
    slow.set()
    await asyncio.gather(t1, t2, t3, return_exceptions=True)


@pytest.mark.asyncio
async def test_sparse_dict_preserved():
    def predict(texts):
        return {
            "dense_vecs": [[1.0, 2.0] for _ in texts],
            "lexical_weights": [{"tok_a": 0.5, "tok_b": 0.25} for _ in texts],
        }
    b = EmbedBatcher(predict)
    b.start()
    dense, sparse = await b.submit("x")
    assert dense == [1.0, 2.0]
    assert sparse == {"tok_a": 0.5, "tok_b": 0.25}
```

- [ ] **Step 2: 실패 확인**

Run: `cd kms_unified_server && python -m pytest test_embed_batcher.py -q`
Expected: FAIL (`ModuleNotFoundError: embed_batcher` 또는 import 에러).

- [ ] **Step 3: EmbedBatcher 구현**

`kms_unified_server/embed_batcher.py`:

```python
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

log = logging.getLogger(__name__)


class EmbedBatcher:
    """동시 단일텍스트 /embed 요청을 짧은 윈도로 모아 1회 encode로 처리하는 동적 배처.

    predict_fn(texts: list[str]) -> dict (동기; BGEM3FlagModel.encode 래핑,
    keys dense_vecs/lexical_weights). submit(text)로 텍스트 등록 후 그 요청 몫의
    (dense_vec, lexical_weights)를 await. encode는 단일 소비 루프에서 1개씩 직렬
    실행 -> 동시 encode 경합 제거(단일 GPU 유리).
    """

    def __init__(
        self,
        predict_fn: Callable[[list], dict],
        max_batch_texts: int = 32,
        batch_wait_ms: int = 5,
        max_queue: int = 1000,
    ) -> None:
        self._predict_fn = predict_fn
        self._max_batch_texts = max_batch_texts
        self._batch_wait_s = batch_wait_ms / 1000.0
        self._max_queue = max_queue
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def submit(self, text: str) -> tuple:
        if self._queue.qsize() >= self._max_queue:
            raise RuntimeError("embed batcher queue overflow")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._queue.put((text, fut))
        return await fut

    async def _run_loop(self) -> None:
        while True:
            batch: list = []
            try:
                text0, fut0 = await self._queue.get()
                batch = [(text0, fut0)]
                deadline = time.monotonic() + self._batch_wait_s
                # 윈도 내 추가 수집(큐에 있으면 즉시, 없으면 잠깐 대기). soft cap.
                while len(batch) < self._max_batch_texts:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        text_i, fut_i = await asyncio.wait_for(
                            self._queue.get(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        break
                    batch.append((text_i, fut_i))

                texts = [t for t, _ in batch]
                try:
                    out = await asyncio.to_thread(self._predict_fn, texts)
                except Exception as exc:  # noqa: BLE001 -- 배치 실패는 future로 전파(폴백)
                    for _, fut in batch:
                        if not fut.done():
                            fut.set_exception(exc)
                    continue

                dense_vecs = out.get("dense_vecs") or []
                lexical_weights = out.get("lexical_weights") or []
                for i, (_, fut) in enumerate(batch):
                    if not fut.done():
                        dv = dense_vecs[i] if i < len(dense_vecs) else None
                        lw = lexical_weights[i] if i < len(lexical_weights) else {}
                        fut.set_result((dv, lw))
            except Exception:  # noqa: BLE001 -- 루프 보호 + 미완료 future 전파(hang 차단)
                log.exception("embed batcher run loop error")
                for _, fut in batch:
                    if not fut.done():
                        fut.set_exception(RuntimeError("embed batcher internal error"))
                continue
```

(Task 1 확정 파라미터를 `__init__` 기본값 `max_batch_texts`/`batch_wait_ms`에 반영. 미도출 시 32/5.)

- [ ] **Step 4: 통과 확인**

Run: `cd kms_unified_server && python -m pytest test_embed_batcher.py -q -W error::DeprecationWarning`
Expected: 7 passed.

- [ ] **Step 5: 커밋**

```bash
git add kms_unified_server/embed_batcher.py kms_unified_server/test_embed_batcher.py
git commit -m "feat(embed-batching): EmbedBatcher 동적 배처 + 단위테스트 7건"
```

---

### Task 3: unified_server.py에 EmbedBatcher 배선

**Files:**
- Modify: `kms_unified_server/unified_server.py`(import + 전역 + lifespan + /embed legacy 분기)
- Test: AST 확인(B200 의존성으로 전체 import 로컬 불가)

**Interfaces:**
- Consumes: `EmbedBatcher`(Task 2). 현재 `unified_server.py`(rerank 배칭 배포본 abb8e28 = B200 live와 동일).

**현재 관련 코드**:
- import 영역: `from rerank_batcher import RerankBatcher`(존재). 전역: `_rerank_batcher = None`(존재).
- lifespan(rerank 배처 기동부 존재) — 그 뒤에 embed 배처 기동 추가.
- `/embed` 핸들러(legacy 분기): `await _load_embedder()` → `is_legacy` 분기 → `texts=[text]` → 공통 `_encode`/`out`.

- [ ] **Step 1: import + 전역 추가**

`kms_unified_server/unified_server.py` import 영역(`from rerank_batcher import RerankBatcher` 다음 줄)에 추가:
```python
from embed_batcher import EmbedBatcher
```
전역 `_rerank_batcher = None` 다음 줄에 추가:
```python
_embed_batcher = None
```

- [ ] **Step 2: lifespan에 embed 배처 기동 추가**

lifespan에서 rerank 배처 `.start()` 다음, `yield` 앞에 추가:
```python
    global _embed_batcher
    _embed_batcher = EmbedBatcher(
        predict_fn=lambda texts: _embedder.encode(
            texts, batch_size=16, return_dense=True, return_sparse=True
        ),
        max_batch_texts=int(os.environ.get("EMBED_MAX_BATCH_TEXTS", "<P0>")),
        batch_wait_ms=int(os.environ.get("EMBED_BATCH_WAIT_MS", "<P0>")),
        max_queue=int(os.environ.get("EMBED_MAX_QUEUE", "1000")),
    )
    _embed_batcher.start()
```
(`<P0>` = Task 1 확정값으로 치환, 예 `"32"`/`"5"`. 코드 기본값과 동일하게.)

**안전성 근거(변경 금지 사유)**: predict_fn의 `_embedder`는 호출 시점 전역 참조. `/embed` 핸들러가 submit 전 `await _load_embedder()`를 호출하므로(아래 유지), 배처 `_run_loop`가 항목 처리 시 `_embedder`는 이미 로드됨(기존 lazy 동작 보존).

- [ ] **Step 3: /embed legacy 분기를 배처 경유로 변경**

현재 legacy 분기(빈 텍스트 가드 직후 `texts = [text]` 등으로 공통 `_encode`/`out`로 흐르는 부분)를 **배처 경유 조기반환**으로 교체. 빈 텍스트 가드는 보존:
```python
    is_legacy = "text" in payload and "texts" not in payload
    if is_legacy:
        text = str(payload.get("text") or "")
        if not text:
            return {"dense": [], "sparse": {}}
        if _embed_batcher is None:
            raise RuntimeError("embed batcher not initialized")
        dense_vec, lw = await _embed_batcher.submit(text)
        single_dense = (
            dense_vec.tolist() if hasattr(dense_vec, "tolist")
            else (list(dense_vec) if dense_vec is not None else [])
        )
        single_sparse = {str(k): float(v) for k, v in (lw or {}).items()}
        return {"dense": single_dense, "sparse": single_sparse}
```
**불변(건드리지 말 것)**: `await _load_embedder()`(legacy 분기 앞 유지), batch 분기(`else`) 전체·공통 `_encode`/`out`/dense_list/배치 응답 조립. legacy가 위에서 조기반환하므로 batch 경로는 변형 없음. (변환 의미 `.tolist()`·`{str(k):float(v)}`는 기존 단일 응답 로직과 동일.)

- [ ] **Step 4: 문법 확인**

Run: `cd /c/Projects/AICC/working/aicm_old/rag-parser-engine && PYTHONUTF8=1 python -c "import ast; ast.parse(open('kms_unified_server/unified_server.py',encoding='utf-8').read()); print('AST OK')"`
Expected: AST OK. (B200 의존성으로 전체 import 로컬 불가 — AST+diff 리뷰로 확인. flat import는 B200 cwd=kms_unified_server/ 기준 정상.)

- [ ] **Step 5: 커밋**

```bash
git add kms_unified_server/unified_server.py
git commit -m "feat(embed-batching): /embed legacy 경로를 EmbedBatcher 경유로 배선(lifespan 기동)"
```

---

### Task 4: B200 배포 (백업·최소 재기동)

**Files:** B200 측 배포 — 로컬 변경 없음.

**Interfaces:**
- Consumes: Task 2·3 산출 `embed_batcher.py`(신규), 수정 `unified_server.py`.

- [ ] **Step 1: 백업**

timbel→B200 경유로 B200 `kms_unified_server/unified_server.py`를 `unified_server.py.bak.<UTC타임스탬프>`로 백업. 백업 경로 기록.

- [ ] **Step 2: 드리프트 확인 + 파일 반영**

B200 현재 `unified_server.py`가 예상 base(rerank 배칭 배포본, `_rerank_batcher` 있고 `_embed_batcher` **없음**)인지 확인. 다르면 중단·보고. 로컬 `embed_batcher.py`(신규)·수정 `unified_server.py`를 B200 `/NHNHOME/WORKSPACE/0426030034_A/kms_unified_server/`에 전송, md5 대조. B200에서 양 파일 AST 확인: `venv/bin/python -c "import ast; ast.parse(open('unified_server.py').read()); ast.parse(open('embed_batcher.py').read()); print('AST OK')"`.

- [ ] **Step 3: 최소 재기동(의존성 재설치 없음)**

```bash
cd /NHNHOME/WORKSPACE/0426030034_A/kms_unified_server
pkill -f 'uvicorn unified_server' || true
export RERANKER_MODEL=BAAI/bge-reranker-v2-m3 EMBED_MODEL=BAAI/bge-m3 DEVICE=cuda:0 USE_FP16=1
export PYTORCH_ALLOC_CONF=expandable_segments:True PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
setsid nohup venv/bin/python -m uvicorn unified_server:app --host 0.0.0.0 --port 35001 > logs/unified.log 2>&1 < /dev/null &
```
기동 로그(`tail logs/unified.log`)에서 import 오류(특히 `ModuleNotFoundError: embed_batcher`)·배처 기동 오류 없는지 확인.

- [ ] **Step 4: 스모크**

B200 `curl -s localhost:35001/health` → ready=true. `/embed` 단일텍스트 스모크:
```bash
curl -s -X POST localhost:35001/embed -H 'Content-Type: application/json' -d '{"text":"적금 금리 안내"}'
```
→ 200 + `dense`(1024개 float) + `sparse`(dict) 정상. batch 포맷도 1건 확인(`{"texts":["a","b"]}` → dense 2개·latency_ms). 단일·배치 모두 정상.

- [ ] **Step 5: 상태 보고 + 실패 시 롤백**

백업 경로·md5·health·스모크 기록. 실패 시 `.bak` 복원+재기동. (커밋 불요 — B200측.)

---

### Task 5: 통합 검증 (before/after) + 문서화

**Files:** `Doc/perf/2026-06-21-embed-batching-before-after.md`(신규)

**Interfaces:**
- Consumes: 배포된 배칭 버전.

- [ ] **Step 1: before/after — /embed 직접 격리(authoritative)**

검색경로 embedding step은 로그 미노출이므로 `/embed` 직접을 권위값으로. B200-local(localhost:35001) 또는 timbel(localhost:7125)에서 **단일텍스트** `{"text":"<distinct>"}` c=1/4/8 동시(각 distinct, n=20/48/96) {p50,p95,max} + **c=8/c=1 배수**. before 기준 = 측정 기록(현 세션 §B: c=1 67ms / c=8 ~177ms, 2.7x). after가 c=8 단축됐는지.

- [ ] **Step 2: before/after — 콜봇 total(보조)**

콜봇 `localhost:32012/api/aicm/v1/search/internal/document`(body utf-8) c=1/4/8 total {p50,p95}. before(현 세션 콜봇 c=8 total ~317·검색경로 embedding 잔차 ~151) 대비 total 단축 확인. 매 조건 `aicm:search_cache:*` flush, **`aicm:embed:*` 불변**.

- [ ] **Step 3: 품질 — 벡터 동일성**

동일 텍스트 5개를 `/embed` 단일로 호출 → dense·sparse가 **배칭 경유에도 결정적·합리적**(같은 텍스트 2회 호출 시 동일 벡터). index 분배 버그면 텍스트-벡터 매핑이 어긋남 → 검출. (배칭은 텍스트별 독립 encode라 벡터 불변이어야.)

- [ ] **Step 4: vLLM 동반부하 + VRAM**

vLLM 부하(어드바이저 rag_assist 또는 vLLM 직접) 동반 c=8 `/embed`·콜봇 측정 → 실 조건서 tail 개선 유지. B200 `nvidia-smi`로 임베딩 부하 중 cuda:0 used ΔVRAM·OOM 로그 확인(encode 내부 batch_size=16라 GPU forward ≤16텍스트, 9GB 헤드룸 잠식 여부).

- [ ] **Step 5: 문서화·커밋**

`Doc/perf/2026-06-21-embed-batching-before-after.md`에 before/after 표·개선폭·벡터동일성·vLLM부하·VRAM 기록:
```bash
git add Doc/perf/2026-06-21-embed-batching-before-after.md
git commit -m "docs(embed-batching): 배칭 배포 후 before/after /embed 격리 검증 결과"
```

---

## Self-Review

**Spec coverage:** 목표/근거→Task1·5, EmbedBatcher→Task2, /embed 배선·legacy전용·보존·None가드→Task3, Phase0 게이트→Task1, 배포(백업·최소재기동·스모크)→Task4, before/after(/embed 격리 authoritative)·품질(벡터동일)·vLLM·VRAM→Task5, M-3 선반영→Task2 코드, RerankBatcher 불변→전 태스크 배선만. 커버 완료.

**Placeholder scan:** `<P0>`는 Task 1 산출 의존 의도적 치환점(Task 2/3 Interfaces·Step에 명시). 그 외 TBD/TODO 없음.

**Type consistency:** `EmbedBatcher(predict_fn, max_batch_texts, batch_wait_ms, max_queue)`·`submit(text)->tuple(dense,lw)`·predict_fn `texts->dict(dense_vecs/lexical_weights)`가 Task 2 정의 = Task 3 lifespan/handler 사용과 일치. 핸들러 변환(`.tolist()`/`{str:float}`)은 spec 보존 규칙과 일치.
