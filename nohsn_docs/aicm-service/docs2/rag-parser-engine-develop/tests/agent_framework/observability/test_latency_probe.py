import json
import pytest
from src.agent_framework.observability.latency_probe import (
    LatencyProbe,
    PlanStepEvent,
    Phase,
)


def test_record_phase_basic():
    p = LatencyProbe()
    p.record_phase("intent_classifier", started_at=0.0, ended_at=1.96)
    assert len(p.phases) == 1
    assert p.phases[0].name == "intent_classifier"
    assert p.phases[0].wall_ms == pytest.approx(1960, abs=1)


def test_record_phase_meta():
    p = LatencyProbe()
    p.record_phase("plan_generator", 0.0, 13.5,
                   prompt_tokens=8123, output_tokens=412, cached_tokens=0)
    assert p.phases[0].meta["prompt_tokens"] == 8123
    assert p.phases[0].meta["cached_tokens"] == 0


def test_consume_step_event_dupe_count():
    """trace A 의 6 step 입력 → 중복 signature 카운트 검증."""
    p = LatencyProbe()
    events = [
        PlanStepEvent(step=1, kind="tool", tool="kms_rag.search",
                      args={"query": "주식 매도 대금 입금일"}, ts=15.6, ok=True),
        PlanStepEvent(step=2, kind="tool", tool="web.search",
                      args={"query": "주식 매도 대금 입금일"}, ts=15.9, ok=True),
        PlanStepEvent(step=3, kind="reasoning", tool=None,
                      args={"expr": "kms 결과 확인"}, ts=17.0, ok=True),
        PlanStepEvent(step=4, kind="tool", tool="kms_rag.search",
                      args={"query": "주식 매도 대금 입금일"}, ts=17.0, ok=True),
        PlanStepEvent(step=5, kind="tool", tool="web.search",
                      args={"query": "삼성전자 주식 매도 대금 입금일"}, ts=17.4, ok=True),
        PlanStepEvent(step=6, kind="reasoning", tool=None,
                      args={"expr": "최종 합성"}, ts=18.5, ok=True),
    ]
    for e in events:
        p.consume_step_event(e)
    assert p.compute_signature_dupe_count() == 1  # kms_rag 동일 query 2회 = 1 dupe


def test_consume_step_event_no_dupes():
    p = LatencyProbe()
    p.consume_step_event(PlanStepEvent(1, "tool", "kms_rag.search",
                                       {"query": "회사 휴가"}, 0.5, True))
    p.consume_step_event(PlanStepEvent(2, "tool", "web.search",
                                       {"query": "회사 휴가"}, 0.7, True))
    assert p.compute_signature_dupe_count() == 0


def test_to_sse_payload_shape():
    p = LatencyProbe()
    p.record_phase("intent_classifier", 0.0, 1.96)
    p.record_phase("plan_generator", 1.96, 8.50, prompt_tokens=8123)
    payload = p.to_sse_payload()
    assert "phases" in payload
    assert "dupes" in payload
    assert payload["phases"][0]["name"] == "intent_classifier"
    assert payload["phases"][1]["meta"]["prompt_tokens"] == 8123


def test_normalize_args_for_signature():
    """args 정규화 — 공백/대소문자/key 순서 무관."""
    from src.agent_framework.observability.latency_probe import _args_signature
    a = _args_signature("kms_rag.search", {"query": " 회사 휴가 "})
    b = _args_signature("kms_rag.search", {"query": "회사 휴가"})
    assert a == b


def test_record_phase_accepts_negative_wall_ms():
    """record_phase 가 음수 wall_ms (started > ended) 를 raise 없이 기록.

    실제 예외 격리 (record_phase 내부에서 raise 시 caller 영향 X) 는
    별도 시나리오 — 이 테스트는 입력 정합성 한정."""
    p = LatencyProbe()
    p.record_phase("bad", started_at=10.0, ended_at=5.0)
    assert p.phases[0].wall_ms == -5000


def test_args_signature_handles_non_json_types():
    """UUID/datetime/dict 같은 non-trivial 값도 raise 없이 signature 생성."""
    from src.agent_framework.observability.latency_probe import _args_signature
    import uuid
    import datetime as dt
    sig = _args_signature("schedule.create",
                          {"id": uuid.uuid4(), "when": dt.datetime.now()})
    # raise 안 나면 OK. 결과는 str 표현 포함.
    assert sig.startswith("schedule.create|")


def test_to_sse_payload_sanitizes_non_json_meta():
    """meta 에 non-JSON 값이 들어와도 SSE payload 가 json.dumps 가능."""
    import uuid
    p = LatencyProbe()
    p.record_phase("plan_generator", 0.0, 1.0, request_id=uuid.uuid4())
    payload = p.to_sse_payload()
    # 검증: dispatcher 가 SSE 송출 시 json.dumps 가능
    json.dumps(payload)  # raise 안 나면 OK


# ---------------------------------------------------------------------------
# P3-1: consume_event + finalize_derived_phases 단위 테스트
# ---------------------------------------------------------------------------

def test_consume_event_delegates_plan_step_to_step_event():
    """consume_event 가 plan_step event 를 consume_step_event 로 위임."""
    p = LatencyProbe()
    p.consume_event({
        "event": "plan_step",
        "data": {
            "step": 1, "kind": "tool", "tool": "kms_rag.search",
            "args": {"query": "test"}, "ts": 10.0, "ok": True,
        },
    })
    # _step_events 에 1건 누적, _event_timeline 에는 없어야 함
    assert len(p._step_events) == 1
    assert p._step_events[0].tool == "kms_rag.search"
    assert p._event_timeline == []


def test_consume_event_records_non_plan_step_to_timeline():
    """consume_event 가 plan_step 외 event 를 _event_timeline 에 누적."""
    p = LatencyProbe()
    p.consume_event({"event": "intent", "data": {"ts": 1.0}})
    p.consume_event({"event": "plan_generated", "data": {"ts": 2.5}})
    p.consume_event({"event": "citations_finalized", "data": {"ts": 5.0}})
    p.consume_event({"event": "done", "data": {"ts": 5.1}})
    assert len(p._event_timeline) == 4
    assert p._event_timeline[0] == ("intent", 1.0)
    assert p._event_timeline[2] == ("citations_finalized", 5.0)


def test_finalize_derived_phases_generates_correct_phases():
    """finalize_derived_phases 가 ts 기반으로 sub-phase wall_ms 를 올바르게 도출."""
    p = LatencyProbe()
    turn_started = 0.0
    # intent 완료 ts=1.0, plan_generated ts=3.0, citations_finalized ts=5.0
    p.consume_event({"event": "intent", "data": {"ts": 1.0}})
    p.consume_event({"event": "plan_generated", "data": {"ts": 3.0}})
    p.consume_event({"event": "citations_finalized", "data": {"ts": 5.0}})
    p.finalize_derived_phases(turn_started)

    phase_names = [ph.name for ph in p.phases]
    assert "intent_classifier" in phase_names
    assert "plan_generator" in phase_names
    assert "answer_compose_finalize" in phase_names

    intent_ph = next(ph for ph in p.phases if ph.name == "intent_classifier")
    assert intent_ph.wall_ms == pytest.approx(1000.0, abs=1)

    plan_ph = next(ph for ph in p.phases if ph.name == "plan_generator")
    assert plan_ph.wall_ms == pytest.approx(2000.0, abs=1)

    compose_ph = next(ph for ph in p.phases if ph.name == "answer_compose_finalize")
    assert compose_ph.wall_ms == pytest.approx(2000.0, abs=1)


def test_finalize_derived_phases_no_duplicate_phases():
    """동일 event 가 두 번 와도 phase 는 첫 발생만 기록."""
    p = LatencyProbe()
    p.consume_event({"event": "intent", "data": {"ts": 1.0}})
    p.consume_event({"event": "intent", "data": {"ts": 2.0}})  # 중복
    p.finalize_derived_phases(0.0)
    intent_phases = [ph for ph in p.phases if ph.name == "intent_classifier"]
    assert len(intent_phases) == 1
    assert intent_phases[0].wall_ms == pytest.approx(1000.0, abs=1)


def test_finalize_derived_phases_empty_timeline_is_noop():
    """timeline 이 비어있으면 phases 에 아무것도 추가하지 않음."""
    p = LatencyProbe()
    p.record_phase("engine_turn", 0.0, 10.0)
    p.finalize_derived_phases(0.0)
    # engine_turn 만 남아야 함
    assert len(p.phases) == 1
    assert p.phases[0].name == "engine_turn"
