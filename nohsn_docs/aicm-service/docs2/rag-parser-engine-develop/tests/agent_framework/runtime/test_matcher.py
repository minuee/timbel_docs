from src.agent_framework.runtime.matcher import evaluate_when, MatcherContext


def _ctx(**kw):
    defaults = dict(
        user_message="",
        detected_intents=[],
        slots={},
        tool_result=None,
        user_intent=None,
    )
    defaults.update(kw)
    return MatcherContext(**defaults)


def test_has_intent():
    ctx = _ctx(detected_intents=["book_appointment"])
    assert evaluate_when("has_intent(book_appointment)", ctx) is True
    assert evaluate_when("has_intent(cancel)", ctx) is False


def test_slot_filled():
    ctx = _ctx(slots={"date": "2026-04-25", "svc": None})
    assert evaluate_when("slot_filled(date)", ctx) is True
    assert evaluate_when("slot_filled(svc)", ctx) is False


def test_tool_result_positive():
    ctx = _ctx(tool_result={"available": True})
    assert evaluate_when("tool_result.available", ctx) is True
    ctx2 = _ctx(tool_result={"available": False})
    assert evaluate_when("tool_result.available", ctx2) is False


def test_tool_result_negation():
    ctx = _ctx(tool_result={"available": False})
    assert evaluate_when("not tool_result.available", ctx) is True


def test_user_intent():
    ctx = _ctx(user_intent="yes")
    assert evaluate_when("user_intent(yes)", ctx) is True
    assert evaluate_when("user_intent(no)", ctx) is False


def test_unknown_expression_returns_false():
    ctx = _ctx()
    assert evaluate_when("totally_unknown()", ctx) is False
