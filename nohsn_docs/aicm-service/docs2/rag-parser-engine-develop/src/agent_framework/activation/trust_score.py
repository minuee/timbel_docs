"""Trust score (델타 #4) — Guru 패턴."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from math import exp


def compute_trust_score(
    created_at: datetime,
    verified_at: datetime | None,
    hit_count_30d: int,
    supersede_count: int,
    now: datetime | None = None,
) -> float:
    n = now or datetime.now(timezone.utc)
    age_days = max(0.0, (n - created_at).total_seconds() / 86400.0)
    freshness = exp(-age_days / 180.0)
    usage = min(1.0, hit_count_30d / 20.0)
    stability = max(0.0, 1.0 - min(1.0, supersede_count / 3.0))
    base = 0.4 * freshness + 0.3 * usage + 0.3 * stability
    if verified_at and (n - verified_at) < timedelta(days=90):
        base += 0.15
    return max(0.0, min(1.0, base))
