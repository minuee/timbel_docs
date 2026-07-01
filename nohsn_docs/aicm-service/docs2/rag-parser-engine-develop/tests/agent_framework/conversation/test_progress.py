"""progress_emitter — 처리 시간 임계별 메시지 1회 발화."""

from __future__ import annotations

from src.agent_framework.conversation.progress_emitter import (
    DEFAULT_THRESHOLDS,
    ProgressEmitter,
)


class TestProgressEmitter:
    def test_below_first_threshold_no_message(self):
        e = ProgressEmitter()
        assert e.tick(500) is None
        assert e.tick(2999) is None

    def test_first_threshold_fires(self):
        e = ProgressEmitter()
        msg = e.tick(3500)
        assert msg is not None
        assert "검색" in msg

    def test_second_threshold_fires(self):
        e = ProgressEmitter()
        # 첫 임계 발화 후
        e.tick(3500)
        msg = e.tick(8000)
        assert msg is not None
        assert "분석" in msg

    def test_no_duplicate_fire(self):
        e = ProgressEmitter()
        first = e.tick(3500)
        second = e.tick(3600)
        assert first is not None
        assert second is None  # 같은 임계 다시 안 나감

    def test_skip_to_largest(self):
        # 한 번에 큰 임계로 점프 — 작은 미발화는 skip 처리.
        e = ProgressEmitter()
        msg = e.tick(20000)
        assert msg is not None
        assert "조금 더" in msg
        # 이후 작은 임계는 다시 안 발화
        assert e.tick(3500) is None
        assert e.tick(8000) is None

    def test_reset(self):
        e = ProgressEmitter()
        e.tick(3500)
        e.reset()
        msg = e.tick(3500)
        assert msg is not None  # 리셋 후 다시 발화

    def test_custom_thresholds(self):
        e = ProgressEmitter(thresholds=((1000, "곧 답변"),))
        assert e.tick(500) is None
        assert e.tick(1500) == "곧 답변"

    def test_default_thresholds_count(self):
        # 정렬된 형태 확인
        prev = -1
        for th, _ in DEFAULT_THRESHOLDS:
            assert th > prev
            prev = th
