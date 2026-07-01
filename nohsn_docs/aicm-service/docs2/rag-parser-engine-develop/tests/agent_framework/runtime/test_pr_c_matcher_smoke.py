"""Smoke — engine 미의존 단위. matcher / session_store / schedule_store 만 검증.

worktree 환경에서 engine.py 가 없는 상태로도 작은 모듈 변경이
syntactically valid + 기본 contract 를 만족하는지 확인한다.
"""
from __future__ import annotations


def test_matcher_slots_filled_AND_smoke():
    from src.agent_framework.runtime.matcher import MatcherContext, evaluate_when

    full = MatcherContext(
        user_message="",
        detected_intents=[],
        slots={"title": "x", "when": "2026-04-28T18:00", "where": "엔타워"},
        tool_result=None,
        user_intent=None,
    )
    partial = MatcherContext(
        user_message="",
        detected_intents=[],
        slots={"title": "x", "when": None},
        tool_result=None,
        user_intent=None,
    )
    empty_str = MatcherContext(
        user_message="",
        detected_intents=[],
        slots={"title": "x", "when": ""},
        tool_result=None,
        user_intent=None,
    )

    assert evaluate_when("slots_filled(title, when)", full) is True
    assert evaluate_when("slots_filled(title, when)", partial) is False
    assert evaluate_when("slots_filled(title, when)", empty_str) is False

    # 단일 slot_filled 도 backward-compat
    assert evaluate_when("slot_filled(title)", full) is True
    assert evaluate_when("slot_filled(when)", partial) is False


def test_session_state_effective_personal_tenant_id_smoke():
    from src.agent_framework.runtime.session_store import SessionState

    a = SessionState(
        session_id="x",
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id="tenant-A",
        identity=None,
        personal_tenant_id="ptid-X",
    )
    assert a.effective_personal_tenant_id == "ptid-X"

    b = SessionState(
        session_id="y",
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id="tenant-B",
        identity=None,
        personal_tenant_id=None,  # account_bind_failed 시뮬
    )
    # fallback 으로 tenant_id 를 사용
    assert b.effective_personal_tenant_id == "tenant-B"

    c = SessionState(
        session_id="z",
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id="",
        identity=None,
        personal_tenant_id=None,
    )
    # 둘 다 비어 있으면 None
    assert c.effective_personal_tenant_id is None


def test_schedule_store_dedup_signature_smoke():
    from src.agent_framework.tools.schedule_store import _dedup_signature

    s1 = _dedup_signature("2026-04-28T18:00", "윤찬우 만남")
    s2 = _dedup_signature("2026-04-28T18:00", "  윤찬우 만남  ")  # 공백
    s3 = _dedup_signature("2026-04-28T18:00", "윤수석 만남")  # 다른 title
    s4 = _dedup_signature("2026-04-28T19:00", "윤찬우 만남")  # 다른 시각

    assert s1 == s2, "공백 차이로 dedup 분실되면 안 됨"
    assert s1 != s3
    assert s1 != s4
    assert len(s1) == 16  # sha256 16자 prefix
