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
    assert calls == [6]                # 동시 도착 -> 1회 predict(6 pairs)
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

@pytest.mark.asyncio
async def test_queue_overflow_when_filled():
    # 소비를 막아 큐를 채운 뒤 추가 submit이 overflow로 raise하는지(일반 경로).
    import time as _t
    slow = asyncio.Event()

    def predict(pairs):
        # to_thread에서 실행 — slow까지 블로킹해 큐 적체 유도
        while not slow.is_set():
            _t.sleep(0.005)
        return [0.0] * len(pairs)

    b = RerankBatcher(predict, max_queue=2, batch_wait_ms=1)
    b.start()
    # 첫 submit은 루프가 즉시 집어가 predict(블로킹)에 들어감 -> 큐 비워짐
    t1 = asyncio.create_task(b.submit([["q", "a"]]))
    await asyncio.sleep(0.05)  # 루프가 t1을 소비해 predict 진입
    # 이제 큐에 2건 채움(소비 루프는 predict에 묶여 있음)
    t2 = asyncio.create_task(b.submit([["q", "b"]]))
    t3 = asyncio.create_task(b.submit([["q", "c"]]))
    await asyncio.sleep(0.05)  # t2,t3가 큐에 적재(qsize=2)
    # 3번째 적재 시도는 qsize(2) >= max_queue(2) -> overflow
    with pytest.raises(RuntimeError, match="overflow"):
        await b.submit([["q", "d"]])
    slow.set()  # 정리: predict 풀어 t1~t3 완료
    await asyncio.gather(t1, t2, t3, return_exceptions=True)
