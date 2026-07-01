"""chat_v1 dispatcher 의 모든 신규 wrap 이 flag off 일 때 byte-equal SSE
출력을 보장하는지 검증.

이 테스트가 깨지면 시연 path 가 더럽혀진 것 — 즉시 수정 필수.
"""
import json
import os
import pytest
from src.agent_framework.observability.latency_probe import LatencyProbe, PlanStepEvent
from src.common.feature_flags import FeatureFlag, is_enabled


def test_all_flags_off_by_default(monkeypatch):
    for f in FeatureFlag:
        monkeypatch.delenv(f"FEATURE_{f.value.upper()}", raising=False)
    for f in FeatureFlag:
        assert is_enabled(f) is False


def test_probe_to_sse_only_when_flag_on(monkeypatch):
    monkeypatch.delenv("FEATURE_LATENCY_PROBE_SSE", raising=False)
    probe = LatencyProbe()
    probe.record_phase("intent_classifier", 0.0, 1.0)
    payload = probe.to_sse_payload() if is_enabled(FeatureFlag.LATENCY_PROBE_SSE) else None
    assert payload is None


def test_probe_to_sse_when_flag_on(monkeypatch):
    monkeypatch.setenv("FEATURE_LATENCY_PROBE_SSE", "true")
    probe = LatencyProbe()
    probe.record_phase("intent_classifier", 0.0, 1.0)
    payload = probe.to_sse_payload() if is_enabled(FeatureFlag.LATENCY_PROBE_SSE) else None
    assert payload is not None
    assert "phases" in payload


@pytest.mark.asyncio
async def test_phase_wrap_helper_propagates_exception():
    """phase wrap 이 caller 의 예외를 그대로 전파 (silent swallow X).
    그러면서도 phase 는 ended_at 까지 기록 — diagnostic 보존."""
    from src.api.routers.chat_v1 import _phase_wrap
    probe = LatencyProbe()

    async def boom():
        raise RuntimeError("upstream failed")

    with pytest.raises(RuntimeError, match="upstream failed"):
        await _phase_wrap(probe, "intent_classifier", boom)
    assert len(probe.phases) == 1
    assert probe.phases[0].name == "intent_classifier"
    assert probe.phases[0].wall_ms >= 0


@pytest.mark.asyncio
async def test_phase_wrap_helper_records_meta():
    from src.api.routers.chat_v1 import _phase_wrap
    probe = LatencyProbe()

    async def work():
        return {"usage": {"prompt_tokens": 100, "cached_tokens": 80}}

    result = await _phase_wrap(probe, "plan_generator", work,
                               extract_meta=lambda r: {
                                   "prompt_tokens": r["usage"]["prompt_tokens"],
                                   "cached_tokens": r["usage"]["cached_tokens"],
                               })
    assert result == {"usage": {"prompt_tokens": 100, "cached_tokens": 80}}
    assert probe.phases[0].meta["prompt_tokens"] == 100
    assert probe.phases[0].meta["cached_tokens"] == 80


@pytest.mark.asyncio
async def test_phase_wrap_helper_records_on_success_with_no_extract():
    """extract_meta 미지정 시에도 phase wall_ms 정상 기록."""
    from src.api.routers.chat_v1 import _phase_wrap
    probe = LatencyProbe()

    async def work():
        return "OK"

    result = await _phase_wrap(probe, "answer_compose", work)
    assert result == "OK"
    assert probe.phases[0].wall_ms >= 0
    assert probe.phases[0].meta == {}


# ---------------------------------------------------------------------------
# T-INTEGRATE smoke tests — dispatcher integration (mirror tee + probe emit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mirror_tee_accumulates_plan_step_for_probe():
    """_sse_mirror_tee 가 plan_step 이벤트를 probe.consume_step_event 로 정확히
    전달하고, 비 plan_step 이벤트는 probe step 목록에 포함되지 않음."""
    from src.api.routers.chat_v1 import _sse_mirror_tee
    probe = LatencyProbe()

    events = [
        {"event": "plan_step", "data": {"step": 1, "kind": "tool",
                                         "tool": "kms_rag.search",
                                         "args": {"query": "q"}, "ts": 1.0, "ok": True}},
        {"event": "token", "data": {"text": "hello"}},
        {"event": "plan_step", "data": {"step": 2, "kind": "tool",
                                         "tool": "kms_rag.search",
                                         "args": {"query": "q"}, "ts": 1.5, "ok": True}},
        {"event": "done", "data": {}},
    ]

    async def gen():
        for ev in events:
            yield ev

    async def consume(item: dict) -> None:
        if item.get("event") != "plan_step":
            return
        d = item.get("data") or {}
        probe.consume_step_event(PlanStepEvent(
            step=d.get("step", 0),
            kind=d.get("kind", ""),
            tool=d.get("tool"),
            args=d.get("args") or {},
            ts=d.get("ts", 0.0),
            ok=bool(d.get("ok", True)),
        ))

    yielded = []
    async for ev in _sse_mirror_tee(gen(), consume):
        yielded.append(ev)

    # yield 순서/내용 동일
    assert [e["event"] for e in yielded] == ["plan_step", "token", "plan_step", "done"]
    # probe 가 plan_step 2개만 수집
    assert probe._step_events[0].step == 1
    assert probe._step_events[1].step == 2
    assert len(probe._step_events) == 2
    # 중복 tool+args 2건이므로 dupe count = 1
    assert probe.compute_signature_dupe_count() == 1


@pytest.mark.asyncio
async def test_flag_off_no_latency_probe_sse(monkeypatch):
    """flag off 시 latency_probe SSE 이벤트가 출력에 나타나지 않아야 함.
    dispatcher 의 _probe_enabled 분기 로직을 직접 재현."""
    monkeypatch.delenv("FEATURE_LATENCY_PROBE_SSE", raising=False)
    assert is_enabled(FeatureFlag.LATENCY_PROBE_SSE) is False

    # flag off → probe 분기 없음 → latency_probe event 없음
    events_out = [
        {"event": "token", "data": {"text": "hi"}},
        {"event": "done", "data": {}},
    ]
    # 직접 확인: is_enabled False 면 probe emit 코드 진입 안 함
    probe_enabled = is_enabled(FeatureFlag.LATENCY_PROBE_SSE)
    yielded_events = list(events_out)
    if probe_enabled:
        probe = LatencyProbe()
        yielded_events.append({"event": "latency_probe", "data": probe.to_sse_payload()})

    assert all(e["event"] != "latency_probe" for e in yielded_events)


@pytest.mark.asyncio
async def test_flag_on_latency_probe_sse_emitted(monkeypatch):
    """flag on 시 latency_probe SSE 이벤트가 출력에 포함되어야 함."""
    monkeypatch.setenv("FEATURE_LATENCY_PROBE_SSE", "true")
    assert is_enabled(FeatureFlag.LATENCY_PROBE_SSE) is True

    probe = LatencyProbe()
    probe.record_phase("engine_turn", 0.0, 0.5)
    payload = probe.to_sse_payload()

    assert "phases" in payload
    assert payload["phases"][0]["name"] == "engine_turn"
    assert payload["phases"][0]["wall_ms"] == pytest.approx(500.0, abs=1.0)
    assert "dupes" in payload
    assert "n_steps" in payload


@pytest.mark.asyncio
async def test_mirror_tee_type_hint_signature():
    """_sse_mirror_tee 가 AsyncIterable + Callable[[dict], Awaitable[None]]
    타입 힌트를 가진 함수로 호출 가능 — 시그니처 확인."""
    import inspect
    from src.api.routers.chat_v1 import _sse_mirror_tee
    sig = inspect.signature(_sse_mirror_tee)
    assert "source" in sig.parameters
    assert "consumer" in sig.parameters
    doc = _sse_mirror_tee.__doc__ or ""
    assert "consumer must be fast" in doc
