import asyncio
import pytest
from src.api.routers.chat_v1 import _sse_mirror_tee


async def gen_sample():
    yield {"event": "plan_step", "data": {"step": 1, "kind": "tool",
                                          "tool": "kms_rag.search",
                                          "args": {"query": "test"}, "ts": 1.0,
                                          "ok": True}}
    yield {"event": "plan_step", "data": {"step": 2, "kind": "tool",
                                          "tool": "web.search",
                                          "args": {"query": "test"}, "ts": 1.5,
                                          "ok": True}}
    yield {"event": "done", "data": {}}


@pytest.mark.asyncio
async def test_mirror_tee_preserves_order():
    consumed = []
    async def consumer(ev):
        consumed.append(ev)

    yielded = []
    async for ev in _sse_mirror_tee(gen_sample(), consumer):
        yielded.append(ev)

    assert [e["event"] for e in yielded] == ["plan_step", "plan_step", "done"]
    assert len(consumed) == 3


@pytest.mark.asyncio
async def test_mirror_tee_consumer_exception_isolated():
    """mirror consumer 가 raise 해도 사용자 yield 는 영향 X."""
    async def bad_consumer(ev):
        raise RuntimeError("mirror failed")

    async def gen():
        yield {"event": "a", "data": {}}
        yield {"event": "b", "data": {}}
        yield {"event": "c", "data": {}}

    yielded = []
    async for ev in _sse_mirror_tee(gen(), bad_consumer):
        yielded.append(ev)
    assert len(yielded) == 3


@pytest.mark.asyncio
async def test_mirror_tee_no_consumer_extra_calls():
    """consumer 가 yielded events 와 정확히 일치 (extra/missed call 없음)."""
    consumed = []
    async def consumer(ev):
        consumed.append(ev)

    async def gen():
        for i in range(5):
            yield {"event": f"evt-{i}", "data": {"i": i}}

    yielded = []
    async for ev in _sse_mirror_tee(gen(), consumer):
        yielded.append(ev)

    assert yielded == consumed
    assert len(yielded) == 5


@pytest.mark.asyncio
async def test_mirror_tee_empty_source():
    consumed = []
    async def consumer(ev):
        consumed.append(ev)

    async def gen():
        if False:
            yield  # empty generator

    yielded = []
    async for ev in _sse_mirror_tee(gen(), consumer):
        yielded.append(ev)

    assert yielded == []
    assert consumed == []
