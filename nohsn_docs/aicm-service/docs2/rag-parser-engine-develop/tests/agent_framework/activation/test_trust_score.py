from datetime import datetime, timezone, timedelta
from src.agent_framework.activation.trust_score import compute_trust_score


def test_fresh_with_verified_boost():
    # 공식: 0.4*freshness + 0.3*usage + 0.3*stability + 0.15(verified boost)
    # age=10d → freshness=exp(-10/180)≈0.946
    # usage=8/20=0.4, stability=1.0 (supersede=0)
    # base = 0.4*0.946 + 0.3*0.4 + 0.3*1.0 = 0.798
    # + 0.15 boost = 0.948 (clamped ≤1.0)
    now = datetime(2026, 4, 25, tzinfo=timezone.utc)
    score = compute_trust_score(
        created_at=now - timedelta(days=10),
        verified_at=now - timedelta(days=5),
        hit_count_30d=8,
        supersede_count=0,
        now=now,
    )
    assert 0.92 < score < 0.97


def test_old_unverified():
    now = datetime(2026, 4, 25, tzinfo=timezone.utc)
    score = compute_trust_score(
        created_at=now - timedelta(days=720),
        verified_at=None,
        hit_count_30d=0,
        supersede_count=2,
        now=now,
    )
    assert 0.08 < score < 0.14


def test_clamped_to_unit_interval():
    now = datetime(2026, 4, 25, tzinfo=timezone.utc)
    s_hi = compute_trust_score(now, now, 1000, 0, now)
    s_lo = compute_trust_score(now - timedelta(days=9999), None, 0, 999, now)
    assert 0.0 <= s_lo <= 1.0
    assert 0.0 <= s_hi <= 1.0
