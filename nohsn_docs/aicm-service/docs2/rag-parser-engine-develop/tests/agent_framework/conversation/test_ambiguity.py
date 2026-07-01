"""ambiguity_resolver — 다중 의도 시 짧은 확인 질문 합성."""

from __future__ import annotations

from src.agent_framework.conversation.ambiguity_resolver import (
    AmbiguityResolver,
    IntentCandidate,
)


def _ic(label: str, desc: str, conf: float) -> IntentCandidate:
    return IntentCandidate(label=label, description=desc, confidence=conf)


class TestAmbiguityResolver:
    def test_single_intent_no_resolve(self):
        r = AmbiguityResolver()
        out = r.resolve([_ic("a", "일정 조회", 0.8)])
        assert out.needs_confirm is False

    def test_clear_top_no_resolve(self):
        r = AmbiguityResolver()
        # top 0.85, second 0.4 → gap 매우 크고 top 신뢰 → 모호 아님
        out = r.resolve(
            [
                _ic("a", "일정 조회", 0.85),
                _ic("b", "메모 작성", 0.4),
            ]
        )
        assert out.needs_confirm is False

    def test_two_close_candidates(self):
        r = AmbiguityResolver()
        out = r.resolve(
            [
                _ic("a", "일정 조회", 0.55),
                _ic("b", "회의 예약", 0.52),
            ]
        )
        assert out.needs_confirm is True
        assert "일정 조회" in out.question
        assert "회의 예약" in out.question
        assert len(out.options) == 2

    def test_three_candidates_listed(self):
        r = AmbiguityResolver()
        out = r.resolve(
            [
                _ic("a", "일정 조회", 0.5),
                _ic("b", "회의 예약", 0.45),
                _ic("c", "메모 작성", 0.4),
                _ic("d", "검색", 0.3),
            ]
        )
        assert out.needs_confirm is True
        # 상위 3개만
        assert len(out.options) == 3
        assert "일정 조회" in out.question
        assert "회의 예약" in out.question
        assert "메모 작성" in out.question
        assert "검색" not in out.question

    def test_no_descriptions_no_resolve(self):
        r = AmbiguityResolver()
        out = r.resolve(
            [
                _ic("a", "", 0.5),
                _ic("b", "", 0.49),
            ]
        )
        # 모호하긴 한데 보여 줄 라벨이 없음
        assert out.needs_confirm is False

    def test_empty_input(self):
        r = AmbiguityResolver()
        out = r.resolve([])
        assert out.needs_confirm is False
