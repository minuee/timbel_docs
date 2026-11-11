from __future__ import annotations


def build_drift_correction_filter(*, sample_rate: int, correction_factor: float) -> str:
    return f"asetrate={sample_rate * correction_factor},aresample={sample_rate}"


def build_alignment_filter(*, offset_seconds: float, duration_seconds: float) -> str:
    filters: list[str] = []
    if offset_seconds < 0:
        filters.append(f"atrim=start={abs(offset_seconds):.6f}")
        filters.append("asetpts=PTS-STARTPTS")
    if offset_seconds > 0:
        delay_ms = max(0, round(offset_seconds * 1000))
        filters.append(f"adelay={delay_ms}:all=1")
    filters.append("apad")
    filters.append(f"atrim=end={duration_seconds:.6f}")
    return ",".join(filters)
