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


@pytest.mark.asyncio
async def test_numpy_ndarray_dense_vecs():
    # BGEM3FlagModel.encode는 dense_vecs를 numpy ndarray로 반환 -> `or []`가 ValueError 내던 회귀
    np = pytest.importorskip("numpy")
    def predict(texts):
        return {
            "dense_vecs": np.array([[float(i), float(i)] for i in range(len(texts))]),
            "lexical_weights": [{str(i): float(i)} for i in range(len(texts))],
        }
    b = EmbedBatcher(predict, batch_wait_ms=20)
    b.start()
    r = await asyncio.gather(b.submit("a"), b.submit("b"))
    assert list(r[0][0]) == [0.0, 0.0]
    assert r[0][1] == {"0": 0.0}
    assert list(r[1][0]) == [1.0, 1.0]
    assert r[1][1] == {"1": 1.0}
