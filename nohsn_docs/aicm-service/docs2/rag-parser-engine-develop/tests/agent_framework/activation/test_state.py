import pytest
from src.agent_framework.activation.state import (
    ActivationState, can_transition, InvalidTransition,
)


def test_enum_values():
    assert {s.value for s in ActivationState} == {
        "draft","processing","pending_review","active","archived","rejected","failed"
    }


@pytest.mark.parametrize("src,dst,ok", [
    ("draft","processing",True),
    ("processing","pending_review",True),
    ("processing","active",True),        # auto-approve
    ("processing","failed",True),
    ("pending_review","active",True),
    ("pending_review","rejected",True),
    ("active","archived",True),
    ("archived","active",True),           # reactivate
    ("rejected","processing",True),       # retry
    ("draft","active",False),             # skip not allowed
    ("active","pending_review",False),
    ("archived","rejected",False),
])
def test_transitions(src, dst, ok):
    assert can_transition(ActivationState(src), ActivationState(dst)) is ok


def test_invalid_transition_raises():
    from src.agent_framework.activation.state import assert_transition
    with pytest.raises(InvalidTransition):
        assert_transition(ActivationState.draft, ActivationState.active)
