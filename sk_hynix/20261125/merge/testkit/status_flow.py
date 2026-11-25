"""Session status transition scaffold for integration/e2e verification."""

from __future__ import annotations


def build_status_flow() -> dict[str, tuple[str, ...]]:
    return {
        "happy_path": ("queued", "normalizing", "aligning", "mixing", "qa", "done"),
        "retry_path": (
            "queued",
            "normalizing",
            "aligning",
            "aligning_retry",
            "mixing",
            "qa",
            "done",
        ),
        "failure_path": ("queued", "normalizing", "failed"),
    }

