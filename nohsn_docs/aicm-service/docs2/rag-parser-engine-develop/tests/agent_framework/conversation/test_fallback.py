"""fallback_composer — 외부 호출 실패 시 대안 안내 합성."""

from __future__ import annotations

from src.agent_framework.conversation.fallback_composer import (
    FallbackComposer,
    FallbackContext,
)


class TestFallbackComposer:
    def test_timeout_with_alternatives(self):
        c = FallbackComposer()
        out = c.compose(
            FallbackContext(
                failed_action="뉴스 조회",
                error_kind="timeout",
                alternatives=["일정 조회", "메모 저장"],
            )
        )
        assert "뉴스 조회" in out
        assert "응답이 늦" in out or "늦어" in out
        assert "일정 조회" in out
        assert "메모 저장" in out

    def test_unauthorized_no_alternatives(self):
        c = FallbackComposer()
        out = c.compose(
            FallbackContext(failed_action="결제 요청", error_kind="unauthorized")
        )
        assert "결제 요청" in out
        assert "권한" in out
        assert "잠시 후" in out  # 추후 시도 안내

    def test_rate_limited(self):
        c = FallbackComposer()
        out = c.compose(
            FallbackContext(failed_action="외부 API", error_kind="rate_limited")
        )
        assert "한도" in out

    def test_unknown_kind_falls_back_to_default_template(self):
        c = FallbackComposer()
        out = c.compose(
            FallbackContext(failed_action="작업", error_kind="weird_kind")
        )
        # weird_kind 는 템플릿에 없음 → unknown 템플릿 사용
        assert "작업" in out
        assert "진행하지 못했" in out

    def test_3_alternatives_listed(self):
        c = FallbackComposer()
        out = c.compose(
            FallbackContext(
                failed_action="검색",
                error_kind="service_down",
                alternatives=["A", "B", "C", "D"],  # 4 개 중 상위 3 개만
            )
        )
        assert "A" in out
        assert "B" in out
        assert "C" in out
        # 4 번째는 cut
        assert "D" not in out

    def test_empty_action_uses_default_label(self):
        c = FallbackComposer()
        out = c.compose(FallbackContext(failed_action="", error_kind="timeout"))
        assert "요청한 작업" in out
