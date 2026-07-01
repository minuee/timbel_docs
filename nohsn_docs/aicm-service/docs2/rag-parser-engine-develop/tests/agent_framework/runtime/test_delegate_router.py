"""delegate_router — LLM 후보 선택 + 위임 turn 호출."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from src.agent_framework.runtime.delegate_router import (
    _load_delegate_candidates,
    _select_delegate_target,
)


@pytest.mark.asyncio
async def test_select_with_valid_llm_response():
    """LLM 이 best_agent_id + confidence>=0.6 반환 → 그 agent_id 반환."""
    target_id = uuid4()
    candidates = [
        MagicMock(id=target_id, name="주식봇",
                  description="주식 매매제도 안내",
                  guidelines_md="주식 매매 절차..."),
        MagicMock(id=uuid4(), name="다른봇",
                  description="other", guidelines_md="other"),
    ]
    fake_llm_response = MagicMock(
        text=f'{{"best_agent_id": "{target_id}", "confidence": 0.85, "reason": "주식"}}'
    )
    with patch("src.agent_framework.runtime.delegate_router.llm_router") as m:
        m.route = AsyncMock(return_value=fake_llm_response)
        result = await _select_delegate_target(
            user_query="주식 매매 수수료",
            current_agent=MagicMock(name="SaaS봇", description="SaaS"),
            candidates=candidates,
        )
    assert result is not None
    assert result.target_agent_id == target_id
    assert result.confidence == 0.85


@pytest.mark.asyncio
async def test_select_low_confidence_returns_none():
    """confidence < 0.6 → None 반환."""
    candidates = [MagicMock(id=uuid4(), name="x", description="", guidelines_md="")]
    fake_llm_response = MagicMock(text='{"best_agent_id": "11111111-2222-3333-4444-555555555555", "confidence": 0.3, "reason": "low"}')
    with patch("src.agent_framework.runtime.delegate_router.llm_router") as m:
        m.route = AsyncMock(return_value=fake_llm_response)
        result = await _select_delegate_target(
            user_query="q", current_agent=MagicMock(name="c", description=""),
            candidates=candidates,
        )
    assert result is None


@pytest.mark.asyncio
async def test_select_empty_candidates_returns_none():
    """candidates empty → LLM 호출 X, None 반환."""
    result = await _select_delegate_target(
        user_query="q", current_agent=MagicMock(name="c", description=""),
        candidates=[],
    )
    assert result is None


@pytest.mark.asyncio
async def test_select_invalid_uuid_returns_none():
    """LLM 이 잘못된 UUID 반환 → None."""
    candidates = [MagicMock(id=uuid4(), name="x", description="", guidelines_md="")]
    fake_llm_response = MagicMock(text='{"best_agent_id": "not-a-uuid", "confidence": 0.9, "reason": "x"}')
    with patch("src.agent_framework.runtime.delegate_router.llm_router") as m:
        m.route = AsyncMock(return_value=fake_llm_response)
        result = await _select_delegate_target(
            user_query="q", current_agent=MagicMock(name="c", description=""),
            candidates=candidates,
        )
    assert result is None


@pytest.mark.asyncio
async def test_select_llm_invalid_json_returns_none():
    """LLM JSON 파싱 실패 → None."""
    candidates = [MagicMock(id=uuid4(), name="x", description="", guidelines_md="")]
    fake_llm_response = MagicMock(text="not json at all")
    with patch("src.agent_framework.runtime.delegate_router.llm_router") as m:
        m.route = AsyncMock(return_value=fake_llm_response)
        result = await _select_delegate_target(
            user_query="q", current_agent=MagicMock(name="c", description=""),
            candidates=candidates,
        )
    assert result is None


@pytest.mark.asyncio
async def test_load_candidates_empty_list():
    """delegate_ids empty → 빈 list 반환 (DB 조회 X)."""
    db = MagicMock()
    db.execute = AsyncMock()
    result = await _load_delegate_candidates(
        db=db,
        delegate_ids=[],
        tenant_id=uuid4(),
    )
    assert result == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_load_candidates_filters_by_tenant_and_active():
    """SQL stmt 에 tenant_id + is_active filter 포함 확인."""
    captured = {}

    async def fake_execute(stmt):
        captured["stmt"] = stmt
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        return result_mock

    db = MagicMock()
    db.execute = fake_execute

    tenant = uuid4()
    delegate_ids = [uuid4(), uuid4()]
    await _load_delegate_candidates(
        db=db, delegate_ids=delegate_ids, tenant_id=tenant,
    )
    # stmt SQL 에 tenant_id 와 is_active 포함 확인 — compile()
    stmt = captured["stmt"]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "tenant_id" in compiled
    assert "is_active" in compiled


@pytest.mark.asyncio
async def test_try_delegate_emits_prefix_then_target_stream():
    """spec §4 — delegate event + prefix token + target turn 의 token/sources/done 통과."""
    from src.agent_framework.runtime.delegate_router import _try_delegate

    async def fake_engine_turn(*args, **kwargs):
        # target turn 이 start, intent, token, sources, done emit
        yield {"event": "start"}
        yield {"event": "intent"}
        yield {"event": "token", "data": {"text": "주식 답"}}
        yield {"event": "sources", "data": [{}]}
        yield {"event": "done"}

    selection = MagicMock(
        target_agent_id=uuid4(),
        target_agent_name="주식봇",
        confidence=0.9,
        reason="주식",
    )
    target_ctx = MagicMock()
    events = []
    with patch("src.agent_framework.runtime.delegate_router.engine_turn",
               side_effect=lambda *a, **kw: fake_engine_turn()):
        async for ev in _try_delegate(
            selection=selection,
            user_query="q",
            session_id="s",
            delegation_depth=0,
            target_agent=target_ctx,
        ):
            events.append(ev)

    # 첫 event = delegate metadata
    assert events[0]["event"] == "delegate"
    assert events[0]["data"]["to_agent_name"] == "주식봇"
    # 두번째 = prefix token
    assert events[1]["event"] == "token"
    assert "주식봇" in events[1]["data"]["text"]
    # start, intent 는 suppress — 그 후 token / sources / done 통과
    event_names = [e["event"] for e in events]
    assert "start" not in event_names
    assert "intent" not in event_names
    assert event_names.count("done") == 1


@pytest.mark.asyncio
async def test_try_delegate_target_exception_after_prefix():
    """target turn 중 exception → error event + done emit."""
    from src.agent_framework.runtime.delegate_router import _try_delegate

    async def fake_engine_turn_crash(*args, **kwargs):
        yield {"event": "token", "data": {"text": "partial"}}
        raise RuntimeError("boom")

    selection = MagicMock(
        target_agent_id=uuid4(),
        target_agent_name="X",
        confidence=0.9, reason="r",
    )
    events = []
    with patch("src.agent_framework.runtime.delegate_router.engine_turn",
               side_effect=lambda *a, **kw: fake_engine_turn_crash()):
        async for ev in _try_delegate(
            selection=selection, user_query="q", session_id="s",
            delegation_depth=0, target_agent=MagicMock(),
        ):
            events.append(ev)

    # 마지막 두 event = error + done
    assert events[-2]["event"] == "error"
    assert events[-1]["event"] == "done"
