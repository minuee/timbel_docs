"""Per-doc Lock — race 차단 + refcount cleanup."""

import asyncio
import pytest

from src.pipeline.workers.main import (
    _acquire_doc_lock,
    _release_doc_lock,
    _doc_locks,
    _doc_lock_refcount,
)


@pytest.fixture(autouse=True)
def _clear_locks():
    _doc_locks.clear()
    _doc_lock_refcount.clear()
    yield
    _doc_locks.clear()
    _doc_lock_refcount.clear()


@pytest.mark.asyncio
async def test_same_doc_serialized():
    """같은 doc 동시 진입 시 직렬 처리."""
    order = []

    async def worker(name, delay):
        lock = await _acquire_doc_lock("doc-a")
        try:
            async with lock:
                order.append(f"{name}_start")
                await asyncio.sleep(delay)
                order.append(f"{name}_end")
        finally:
            _release_doc_lock("doc-a")

    await asyncio.gather(worker("A", 0.1), worker("B", 0.05))
    # 직렬: A_start, A_end, B_start, B_end (또는 B 가 먼저)
    assert order in (
        ["A_start", "A_end", "B_start", "B_end"],
        ["B_start", "B_end", "A_start", "A_end"],
    )


@pytest.mark.asyncio
async def test_different_docs_parallel():
    """다른 doc 끼리는 병렬."""
    order = []

    async def worker(doc_id, name, delay):
        lock = await _acquire_doc_lock(doc_id)
        try:
            async with lock:
                order.append(f"{name}_start")
                await asyncio.sleep(delay)
                order.append(f"{name}_end")
        finally:
            _release_doc_lock(doc_id)

    await asyncio.gather(
        worker("doc-a", "A", 0.1),
        worker("doc-b", "B", 0.05),
    )
    # 병렬: A_start, B_start, B_end (먼저 끝), A_end
    assert order == ["A_start", "B_start", "B_end", "A_end"]


@pytest.mark.asyncio
async def test_refcount_cleanup():
    """처리 끝나면 _doc_locks 에서 제거됨."""
    lock = await _acquire_doc_lock("doc-x")
    assert "doc-x" in _doc_locks
    assert _doc_lock_refcount["doc-x"] == 1
    _release_doc_lock("doc-x")
    assert "doc-x" not in _doc_locks
    assert "doc-x" not in _doc_lock_refcount


@pytest.mark.asyncio
async def test_refcount_holds_during_inflight():
    """in-flight 동안 lock 유지, 마지막 release 에만 제거."""
    lock1 = await _acquire_doc_lock("doc-y")
    lock2 = await _acquire_doc_lock("doc-y")
    assert _doc_lock_refcount["doc-y"] == 2
    _release_doc_lock("doc-y")
    assert "doc-y" in _doc_locks
    assert _doc_lock_refcount["doc-y"] == 1
    _release_doc_lock("doc-y")
    assert "doc-y" not in _doc_locks
