import pytest
from src.agent_framework.runtime.sufficiency.kms_sufficiency import (
    extract_kms_features,
    is_sufficient,
    KmsFeatures,
    KmsHit,
    KMS_SCORE_THRESHOLD,
    KMS_GAP_THRESHOLD,
)


def _hit(score, title="t", snippet="s", source="kms_chunk"):
    return KmsHit(score=score, title=title, snippet=snippet, source=source)


def test_empty_hits():
    f = extract_kms_features([])
    assert f.n_hits == 0
    assert f.top_score is None
    assert f.rank_gap is None


def test_single_hit():
    f = extract_kms_features([_hit(0.92, "휴가 규정", "연차 15일")])
    assert f.n_hits == 1
    assert f.top_score == 0.92
    assert f.second_score is None
    assert f.rank_gap is None
    assert f.top_titles == ["휴가 규정"]


def test_strong_top_with_gap():
    """top 0.93 second 0.41 → rank_gap 0.52 (충분 신호)."""
    hits = [_hit(0.93, "정답"), _hit(0.41, "관련성 약함")]
    f = extract_kms_features(hits)
    assert f.rank_gap == pytest.approx(0.52, abs=0.001)


def test_ambiguous_two_close():
    """top 0.71 second 0.69 → 거의 동률 (애매 신호)."""
    f = extract_kms_features([_hit(0.71), _hit(0.69), _hit(0.40)])
    assert f.rank_gap == pytest.approx(0.02, abs=0.001)


def test_low_top_score():
    """모든 hit 가 낮은 score (부족 신호)."""
    f = extract_kms_features([_hit(0.18), _hit(0.15), _hit(0.10)])
    assert f.top_score == 0.18
    assert f.rank_gap == pytest.approx(0.03, abs=0.001)


def test_features_serializable():
    """SSE/JSONL 송출 위한 dict 변환."""
    f = extract_kms_features([_hit(0.5, "t", "s")])
    d = f.to_dict()
    assert d["top_score"] == 0.5
    assert d["top_titles"] == ["t"]


def test_is_sufficient_strong_signal():
    f = KmsFeatures(top_score=0.9, second_score=0.4, rank_gap=0.5, n_hits=2)
    assert is_sufficient(f) is True


def test_is_sufficient_low_score():
    f = KmsFeatures(top_score=0.5, n_hits=1)
    assert is_sufficient(f) is False


def test_is_sufficient_close_scores():
    f = KmsFeatures(top_score=0.71, second_score=0.69, rank_gap=0.02, n_hits=2)
    assert is_sufficient(f) is False


def test_is_sufficient_single_hit_passes():
    f = KmsFeatures(top_score=0.85, second_score=None, rank_gap=None, n_hits=1)
    assert is_sufficient(f) is True


def test_is_sufficient_empty():
    f = KmsFeatures()
    assert is_sufficient(f) is False


def test_threshold_constants_exposed():
    assert KMS_SCORE_THRESHOLD == 0.7
    assert KMS_GAP_THRESHOLD == 0.15
