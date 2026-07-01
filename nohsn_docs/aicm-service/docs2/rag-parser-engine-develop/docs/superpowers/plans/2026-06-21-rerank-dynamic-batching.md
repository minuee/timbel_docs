# rerank 동적 배칭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** B200 `unified_server.py`의 `/rerank`에 동적 배칭(동시 요청을 짧은 윈도로 모아 1회 `CrossEncoder.predict`)을 도입해 콜봇 고동시성 rerank tail을 줄인다.

**Architecture:** 신규 `RerankBatcher`(asyncio.Queue + 단일 소비 루프)가 동시 `/rerank` 요청의 pairs를 모아 1회 predict 후 요청별 offset으로 score를 분배. `/rerank` 외부 API 불변. **단 Task 1(Phase 0 게이트) 통과 시에만 Task 2~6 진행.**

**Tech Stack:** Python asyncio, FastAPI/uvicorn, sentence-transformers `CrossEncoder`, pytest(+pytest-asyncio). 배포=NHN B200(`kms_unified_server/`) 직접 수정+재기동.

## Global Constraints

- 대상 = NHN **공유** B200 `kms_unified_server/unified_server.py`(:35001). vLLM(168GB)와 동일 단일 GPU(cuda:0) 공존. 변경은 전 KMS 검색 rerank에 영향.
- **rerank-only.** embedder/`/embed`·검색 파이프라인·KMS 클라이언트(`cross_encoder.py`)는 변경 금지(서버 API 불변).
- `/rerank` 요청/응답 스키마 불변(`{query, candidates:[{id,content}], top_k}` → `{results, latency_ms, model}`).
- predict 실패 시 그 배치 future 에러 전파 → KMS 클라이언트의 기존 **fusion 폴백**으로 무중단.
- 소스가 레포에 없음 → **변경 전 원본 백업 + 레포 미러(버전관리 시작)**.
- 배포 = B200 SSH(timbel 점프), `unified_server` 재기동(embed+rerank 재로드 수십초=검색 일시중단) → **저부하 시간대**.
- 파라미터 env: `RERANK_BATCH_WAIT_MS`(기본 5), `RERANK_MAX_BATCH_PAIRS`(기본 256), `RERANK_MAX_QUEUE`(기본 1000). Phase 0에서 확정.
- 접속: timbel `124.194.32.36:17777`(timbel/ha838131@) → B200 `59.150.35.1:49910`(timbel_dhsh, key `/home/timbel/.ssh/DCTN-0523174639_key`). 이모지 금지.

## 파일 구조

| 파일 | 책임 | 변경 |
|---|---|---|
| `kms_unified_server/unified_server.py` | embed+rerank FastAPI 서버(B200) | 미러 후 수정: 배처 배선 |
| `kms_unified_server/rerank_batcher.py` | 동적 배처(서버 독립, predict_fn 주입) | 신규 |
| `kms_unified_server/test_rerank_batcher.py` | 배처 단위테스트(GPU 불필요) | 신규 |
| `kms_unified_server/unified_deploy.sh` | 기동 스크립트 | 미러(참조용, 변경 없음 가능) |

---

### Task 1: Phase 0 — 배칭 전제 검증 게이트 (구현 전 필수)

**Files:** (없음 — B200 측정. 결과를 spec 부록·플랜에 기록)

**Interfaces:**
- Produces: go/no-go 판정 + 권장 `RERANK_BATCH_WAIT_MS`/`RERANK_MAX_BATCH_PAIRS`. **no-go면 Task 2~6 중단.**

- [ ] **Step 1: 배치 효율 측정 (vLLM idle)**

timbel→B200 경유로 `:7125/rerank`(=B200 :35001)에 측정:
- **단일 요청 candidates=160** 1건의 latency (curl time_total + 응답 latency_ms), n=10.
- **candidates=20 × 8 동시** 요청의 벽시계(8건 모두 완료까지) + 개별 latency, n=10 배치.
비교: 단일 160-batch p50 vs 8×20 동시 벽시계 p50.

- [ ] **Step 2: 판정 게이트**

Expected/Gate: 단일 160-batch가 8×20 동시 대비 **≥30% 빠르면 PASS**(overhead/경합-bound → 배칭 유효). 비슷하거나 느리면 **FAIL → 구현 중단**, 대안(조건부 rerank/후보축소/증설) 재논의로 에스컬레이션.

- [ ] **Step 3: vLLM 동반 부하 재측정**

vLLM(:8000)에 답변생성 부하를 동시에 건 상태에서 Step 1 반복. 배칭 이득이 vLLM 경합 하에서도 ≥20% 남는지 확인(실제 콜봇 조건).

- [ ] **Step 4: 큐 안정성 파라미터 도출**

단일 160-batch predict 시간 t_b로 sustained 처리량(pairs/s) 추정 → c=8+ 도착률 대비 `RERANK_MAX_BATCH_PAIRS`(throughput≥도착률) 범위·`RERANK_BATCH_WAIT_MS` 권장값 산출.

- [ ] **Step 5: 결과 기록 (커밋)**

Phase 0 측정표·판정·권장 파라미터를 spec 부록에 추가하고 커밋:
```bash
cd C:/Projects/AICC/working/aicm_old/rag-parser-engine
git add docs/superpowers/specs/2026-06-21-rerank-dynamic-batching-design.md
git commit -m "docs(rerank-batching): Phase 0 배칭 전제 검증 결과·권장 파라미터 기록"
```
**PASS 시에만 Task 2 진행. FAIL이면 여기서 중단·에스컬레이션.**

---

### Task 2: unified_server 소스 레포 미러 (버전관리 시작)

**Files:**
- Create: `kms_unified_server/unified_server.py`, `kms_unified_server/unified_deploy.sh` (B200에서 가져온 **원본 그대로**)

**Interfaces:**
- Produces: Task 3~4가 참조할 정확한 현재 소스. 이후 변경의 diff 기준선.

- [ ] **Step 1: B200에서 원본 회수**

timbel→B200 경유로 `/NHNHOME/WORKSPACE/0426030034_A/kms_unified_server/unified_server.py`와 `unified_deploy.sh`를 로컬 `rag-parser-engine/kms_unified_server/`로 복사(내용 변경 없이).

- [ ] **Step 2: 베이스라인 커밋**

```bash
cd C:/Projects/AICC/working/aicm_old/rag-parser-engine
git add kms_unified_server/unified_server.py kms_unified_server/unified_deploy.sh
git commit -m "chore(kms_unified_server): B200 라이브 소스 미러(베이스라인, 무변경)"
```
Expected: 이후 Task 4 변경이 이 베이스라인 대비 diff로 드러남.

---

### Task 3: RerankBatcher 클래스 + 단위테스트 (TDD, GPU 불필요)

**Files:**
- Create: `kms_unified_server/rerank_batcher.py`
- Test: `kms_unified_server/test_rerank_batcher.py`

**Interfaces:**
- Produces: `class RerankBatcher(predict_fn, max_batch_pairs=256, batch_wait_ms=5, max_queue=1000)` with `.start()` 및 `async submit(pairs: list[list[str]]) -> list[float]`. `predict_fn(all_pairs: list[list[str]]) -> list[float]`(동기) 주입. Task 4가 `predict_fn=lambda p: _reranker.predict(p, show_progress_bar=False)`로 사용.

- [ ] **Step 1: 실패 테스트 작성**

`kms_unified_server/test_rerank_batcher.py`:
```python
import asyncio
import os
import sys

import pytest

# B200 런타임은 cwd=kms_unified_server/ 라 flat import. 테스트도 동일하게 맞춤.
sys.path.insert(0, os.path.dirname(__file__))
from rerank_batcher import RerankBatcher  # noqa: E402

def _idx_predict(pairs):
    # pair 순서대로 인덱스를 score로 — offset 분배 검증용
    return [float(i) for i in range(len(pairs))]

@pytest.mark.asyncio
async def test_single_request_scores():
    b = RerankBatcher(_idx_predict)
    b.start()
    scores = await b.submit([["q", "a"], ["q", "b"], ["q", "c"]])
    assert scores == [0.0, 1.0, 2.0]

@pytest.mark.asyncio
async def test_concurrent_requests_single_predict_and_offsets():
    calls = []
    def predict(pairs):
        calls.append(len(pairs))
        return [float(i) for i in range(len(pairs))]
    b = RerankBatcher(predict, batch_wait_ms=20)
    b.start()
    r = await asyncio.gather(
        b.submit([["q", "a1"], ["q", "a2"]]),              # 2 pairs
        b.submit([["q", "b1"]]),                            # 1 pair
        b.submit([["q", "c1"], ["q", "c2"], ["q", "c3"]]),  # 3 pairs
    )
    assert calls == [6]                # 동시 도착 → 1회 predict(6 pairs)
    assert r[0] == [0.0, 1.0]
    assert r[1] == [2.0]
    assert r[2] == [3.0, 4.0, 5.0]

@pytest.mark.asyncio
async def test_predict_exception_propagates_to_futures():
    def predict(pairs):
        raise RuntimeError("gpu boom")
    b = RerankBatcher(predict)
    b.start()
    with pytest.raises(RuntimeError, match="gpu boom"):
        await b.submit([["q", "a"]])

@pytest.mark.asyncio
async def test_max_batch_pairs_soft_cap_splits():
    calls = []
    def predict(pairs):
        calls.append(len(pairs))
        return [0.0] * len(pairs)
    b = RerankBatcher(predict, max_batch_pairs=4, batch_wait_ms=20)
    b.start()
    await asyncio.gather(
        b.submit([["q", "a"], ["q", "b"]]),
        b.submit([["q", "c"], ["q", "d"]]),
        b.submit([["q", "e"], ["q", "f"]]),
    )
    assert sum(calls) == 6            # 전 pair 처리
    assert len(calls) >= 2            # max_batch_pairs로 2배치 이상 분할

@pytest.mark.asyncio
async def test_queue_overflow_raises():
    b = RerankBatcher(lambda p: [0.0] * len(p), max_queue=0)  # 소비 전 큐검사
    with pytest.raises(RuntimeError, match="overflow"):
        await b.submit([["q", "a"]])
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:/Projects/AICC/working/aicm_old/rag-parser-engine && python -m pytest kms_unified_server/test_rerank_batcher.py -q`
Expected: FAIL (ModuleNotFoundError: rerank_batcher 없음)

- [ ] **Step 3: 최소 구현**

`kms_unified_server/rerank_batcher.py`:
```python
from __future__ import annotations

import asyncio
import time
from typing import Callable


class RerankBatcher:
    """동시 /rerank 요청을 짧은 윈도로 모아 1회 predict로 처리하는 동적 배처.

    predict_fn(all_pairs: list[list[str]]) -> list[float] (동기; CrossEncoder.predict 래핑).
    submit(pairs)로 요청별 pairs 등록 후 그 요청 몫의 score 리스트를 await.
    predict는 단일 소비 루프에서 1개씩 직렬 실행 → 동시 predict 경합 제거(단일 GPU 유리).
    """

    def __init__(
        self,
        predict_fn: Callable[[list], list],
        max_batch_pairs: int = 256,
        batch_wait_ms: int = 5,
        max_queue: int = 1000,
    ) -> None:
        self._predict_fn = predict_fn
        self._max_batch_pairs = max_batch_pairs
        self._batch_wait_s = batch_wait_ms / 1000.0
        self._max_queue = max_queue
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def submit(self, pairs: list) -> list:
        if self._queue.qsize() >= self._max_queue:
            raise RuntimeError("rerank batcher queue overflow")
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        await self._queue.put((pairs, fut))
        return await fut

    async def _run_loop(self) -> None:
        while True:
            try:
                pairs0, fut0 = await self._queue.get()
                batch = [(pairs0, fut0)]
                total = len(pairs0)
                deadline = time.monotonic() + self._batch_wait_s
                # 윈도 내 추가 수집(큐에 있으면 즉시, 없으면 잠깐 대기). soft cap.
                while total < self._max_batch_pairs:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        pairs_i, fut_i = await asyncio.wait_for(
                            self._queue.get(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        break
                    batch.append((pairs_i, fut_i))
                    total += len(pairs_i)  # 마지막 항목이 max를 약간 넘을 수 있음(soft cap)

                all_pairs = [p for pairs, _ in batch for p in pairs]
                try:
                    scores = await asyncio.to_thread(self._predict_fn, all_pairs)
                except Exception as exc:  # noqa: BLE001 — 배치 실패는 future로 전파(폴백)
                    for _, fut in batch:
                        if not fut.done():
                            fut.set_exception(exc)
                    continue

                off = 0
                for pairs, fut in batch:
                    n = len(pairs)
                    if not fut.done():
                        fut.set_result(list(scores[off:off + n]))
                    off += n
            except Exception:  # noqa: BLE001 — 루프 보호(개별 배치 실패가 루프를 죽이지 않게)
                continue
```

- [ ] **Step 4: 통과 확인**

Run: `cd C:/Projects/AICC/working/aicm_old/rag-parser-engine && python -m pytest kms_unified_server/test_rerank_batcher.py -q`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add kms_unified_server/rerank_batcher.py kms_unified_server/test_rerank_batcher.py
git commit -m "feat(rerank-batching): RerankBatcher 동적 배처 + 단위테스트"
```

---

### Task 4: unified_server.py에 배처 배선

**Files:**
- Modify: `kms_unified_server/unified_server.py` (Task 2 미러본)

**Interfaces:**
- Consumes: `RerankBatcher`(Task 3).
- 미러본의 실제 코드에 맞춰 적용하되, 알려진 현재 형태는 아래와 같다(B200 실측):
  - `_lock = asyncio.Lock()`(모델 로드용), `_reranker`(전역), `_load_reranker()`(lazy).
  - `/rerank`: `pairs = [[req.query, c.content] for c in req.candidates]; scores = await asyncio.to_thread(lambda: _reranker.predict(pairs, show_progress_bar=False))`.
  - startup: `@app.on_event("startup")` 존재(embedder warmup 등).

- [ ] **Step 1: import + 전역 배처**

파일 상단 import에 추가(B200 런타임 cwd=kms_unified_server/ 이므로 **flat import**):
```python
from rerank_batcher import RerankBatcher
```
전역 선언부(`_reranker` 근처)에 추가:
```python
import os
_rerank_batcher: RerankBatcher | None = None
```

- [ ] **Step 2: startup에서 reranker 로드 + 배처 기동**

`@app.on_event("startup")` 본문에 추가(reranker를 startup에 미리 로드해 배처 predict_fn이 즉시 유효하도록):
```python
    await _load_reranker()
    global _rerank_batcher
    _rerank_batcher = RerankBatcher(
        predict_fn=lambda pairs: _reranker.predict(pairs, show_progress_bar=False),
        max_batch_pairs=int(os.environ.get("RERANK_MAX_BATCH_PAIRS", "256")),
        batch_wait_ms=int(os.environ.get("RERANK_BATCH_WAIT_MS", "5")),
        max_queue=int(os.environ.get("RERANK_MAX_QUEUE", "1000")),
    )
    _rerank_batcher.start()
```

- [ ] **Step 3: /rerank 핸들러를 배처 경유로 변경**

`/rerank` 핸들러의 predict 호출부를 교체:

변경 전:
```python
    pairs = [[req.query, c.content] for c in req.candidates]
    scores = await asyncio.to_thread(lambda: _reranker.predict(pairs, show_progress_bar=False))
```
변경 후:
```python
    pairs = [[req.query, c.content] for c in req.candidates]
    scores = await _rerank_batcher.submit(pairs)
```
(나머지 응답 조립 `results/latency_ms/model` 불변. 빈 candidates 조기반환 가드 유지.)

- [ ] **Step 4: 문법·import 확인**

Run: `cd C:/Projects/AICC/working/aicm_old/rag-parser-engine && python -c "import ast; ast.parse(open('kms_unified_server/unified_server.py').read()); print('AST OK')"`
Expected: AST OK. (전체 import는 B200 의존성 필요라 로컬 실행 불가 — 문법·diff 리뷰로 확인.)

- [ ] **Step 5: 커밋**

```bash
git add kms_unified_server/unified_server.py
git commit -m "feat(rerank-batching): /rerank를 RerankBatcher 경유로 배선(startup 기동)"
```

---

### Task 5: B200 배포 (백업·재기동)

**Files:** (B200 측 배포 — 로컬 변경 없음)

**Interfaces:**
- Consumes: Task 3·4 산출 `rerank_batcher.py`, 수정된 `unified_server.py`.

- [ ] **Step 1: 백업**

timbel→B200 경유로 B200 `kms_unified_server/unified_server.py`를 `unified_server.py.bak.<ts>`로 백업. 백업 경로 확인.

- [ ] **Step 2: 파일 반영**

로컬 `kms_unified_server/rerank_batcher.py`(신규)와 수정된 `unified_server.py`를 B200 `/NHNHOME/WORKSPACE/0426030034_A/kms_unified_server/`에 전송. `python -c "import ast; ast.parse(...)"` 양 파일 문법확인. unified_server.py가 `from rerank_batcher import RerankBatcher`(flat)로 import하고, 기동이 cwd=kms_unified_server/(`unified_deploy.sh` 확인)라 같은 디렉터리의 rerank_batcher.py가 해석됨. cwd가 다르면 `unified_deploy.sh`의 실행 디렉터리 기준에 맞춰 조정.

- [ ] **Step 3: 재기동**

`unified_deploy.sh`(또는 기존 기동방식)으로 unified_server 재시작. 기동 로그에서 reranker 로드 완료 + 배처 기동 확인. `:7125/health` ready=true, reranker/embedder loaded 확인.

- [ ] **Step 4: 스모크 확인**

`:7125/rerank`에 candidates 20개 1건 호출 → 200 + results 정상(score 순). 단일 요청이 배처 경유로도 정상 동작 확인.

- [ ] **Step 5: 상태 보고(커밋 불요 — B200측)**

백업 경로·반영 파일·health·스모크 결과 기록. 실패 시 `.bak` 복원+재기동.

---

### Task 6: 통합 검증 (before/after 측정)

**Files:** (없음 — timbel→B200 측정)

**Interfaces:**
- Consumes: 배포된 배칭 버전.

- [ ] **Step 1: after 분포 측정**

§10/§12 동일 프로토콜로 c=1/4/8 재측정(intent_gate off, repo f7dc80c9, distinct 쿼리, n=20/48/96): rerank step·total {p50,p95,max}.

- [ ] **Step 2: before/after 비교 + 게이트**

Expected: **c=8 rerank/total tail이 유의미 감소**(목표: rerank p50 374→배칭 후 단축, total p50 593↓). 큐 안정(지속 c=8서 적체 없음).

- [ ] **Step 3: 품질 회귀 확인**

동일 쿼리 5개 top-5 결과를 **배칭 전(.bak 또는 기록값) vs 후** 비교 → **동일**(배칭은 score를 안 바꿔야 함 — predict 입력/순서 보존). 불일치면 offset 분배 버그 → 회귀.

- [ ] **Step 4: vLLM 동반 부하 확인**

vLLM 답변생성 부하 동반 c=8 측정 → 실제 콜봇 조건서도 tail 개선 유지.

- [ ] **Step 5: 결과 문서화·커밋**

after 분포·개선폭·품질동일·큐안정성을 `Doc/perf/2026-06-20-search-latency-3paths.md`에 추가(또는 신규 perf 노트) 후 커밋:
```bash
git add Doc/perf/2026-06-20-search-latency-3paths.md
git commit -m "docs(rerank-batching): 배칭 배포 후 c=8 tail 개선 검증 결과"
```
