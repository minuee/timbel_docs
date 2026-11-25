"""Helpers for producing prefilled AC7 listening-review artifacts."""

from __future__ import annotations

from datetime import UTC, datetime


def build_prefilled_listening_review(
    *,
    session_id: str,
    recommended_stt_input: str,
    fixture_type: str = "synthetic",
    review_date: str | None = None,
) -> str:
    date_value = review_date or datetime.now(UTC).date().isoformat()
    return f"""# Audio Sync Merge Listening Review

## Session metadata
- Session ID: {session_id}
- Fixture type: {fixture_type}
- Reviewer:
- Review date: {date_value}
- Recommended STT input from manifest: {recommended_stt_input}

## Scoring rubric
Score each item from 1 (poor) to 5 (excellent).

| Category | Score | Notes |
|---|---:|---|
| No howling / flanging |  |  |
| No overlap / smearing artifacts |  |  |
| Loudness consistency across speakers |  |  |
| Overall listening naturalness |  |  |
| Clarity for downstream STT |  |  |

## Pass thresholds
- `No howling / flanging` average >= 4.5
- `No overlap / smearing artifacts` average >= 4.5
- Overall average >= 4.0

## Reviewer decision
- Result: `BLOCKED`
- Notes:
- Follow-up actions:
"""
