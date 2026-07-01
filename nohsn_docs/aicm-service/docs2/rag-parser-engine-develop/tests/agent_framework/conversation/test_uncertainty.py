"""uncertainty_filter — confidence 임계 분류 + prepend."""

from __future__ import annotations

import pytest

from src.agent_framework.conversation.uncertainty_filter import UncertaintyFilter


class TestUncertaintyFilter:
    def test_high_label_no_prepend(self):
        f = UncertaintyFilter()
        d = f.evaluate(0.92)
        assert d.label == "high"
        assert d.prepend == ""
        assert "🟢" in d.badge

    def test_mid_label_no_prepend(self):
        f = UncertaintyFilter()
        d = f.evaluate(0.7)
        assert d.label == "mid"
        assert d.prepend == ""
        assert "🟡" in d.badge

    def test_low_label_has_prepend(self):
        f = UncertaintyFilter()
        d = f.evaluate(0.4)
        assert d.label == "low"
        assert d.prepend  # not empty
        assert "확실하지 않" in d.prepend
        assert "⚠" in d.badge

    def test_apply_low_prepends(self):
        f = UncertaintyFilter()
        out = f.apply("주식 결제일은 T+2 입니다.", confidence=0.3)
        assert out.startswith("확실하지 않")
        assert "주식 결제일" in out

    def test_apply_high_unchanged(self):
        f = UncertaintyFilter()
        out = f.apply("주식 결제일은 T+2 입니다.", confidence=0.9)
        assert out == "주식 결제일은 T+2 입니다."

    def test_clamps_out_of_range(self):
        f = UncertaintyFilter()
        # negative → low
        d = f.evaluate(-0.5)
        assert d.label == "low"
        # >1 → high
        d2 = f.evaluate(1.5)
        assert d2.label == "high"

    def test_invalid_thresholds_raise(self):
        with pytest.raises(ValueError):
            UncertaintyFilter(threshold_high=0.5, threshold_mid=0.5)
        with pytest.raises(ValueError):
            UncertaintyFilter(threshold_high=0.5, threshold_mid=0.6)
