"""Compare two perf reports (baseline vs candidate) → markdown table + verdict.

사용 예:
    python -m tests.perf.compare_reports \
        --baseline Doc/perf/2026-05-19-integrated/2026-05-19-search-latency.json \
        --candidate Doc/perf/2026-05-19-lucas-kms/2026-05-19-search-latency.json \
        --thresholds tests/perf/thresholds.yml \
        --out Doc/perf/2026-05-19-compare-search.md

회귀 임계값은 thresholds.yml 에서만 — magic number 금지.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Verdict:
    failures: list[str]
    warnings: list[str]

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_thresholds(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _index_results(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for block in report.get("results", []) or []:
        label = block.get("label")
        if label:
            out[label] = block
    return out


# ---------------------------------------------------------------------------
# Suite → threshold key mapping
# ---------------------------------------------------------------------------


def _ratio_keys_for_suite(suite: str) -> list[tuple[str, str]]:
    """Returns list of (metric_name, threshold_key)."""
    if suite.startswith("search"):
        return [
            ("p50_ms", "search_p50_ratio"),
            ("p95_ms", "search_p95_ratio"),
            ("p99_ms", "search_p99_ratio"),
        ]
    if suite.startswith("rag"):
        return [
            ("p50_ms", "rag_first_token_ratio"),
            ("p95_ms", "rag_first_token_ratio"),
            ("p99_ms", "rag_full_response_ratio"),
        ]
    if suite.startswith("ingest"):
        return [
            ("p50_ms", "ingest_total_time_ratio"),
            ("p95_ms", "ingest_total_time_ratio"),
        ]
    return [("p50_ms", "search_p50_ratio"), ("p95_ms", "search_p95_ratio")]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _format_delta(base: float, cand: float) -> str:
    if base <= 0:
        return "n/a"
    ratio = cand / base
    pct = (ratio - 1.0) * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{cand:.1f} ({sign}{pct:.1f}%)"


def compare(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    thresholds: dict[str, Any],
) -> tuple[str, Verdict]:
    """Returns (markdown_text, verdict)."""
    suite_base = baseline.get("suite", "unknown")
    suite_cand = candidate.get("suite", "unknown")
    base_idx = _index_results(baseline)
    cand_idx = _index_results(candidate)

    regression = thresholds.get("regression", {}) or {}
    slo = thresholds.get("slo_ms", {}) or {}
    min_samples = int(thresholds.get("minimum_samples", 5))

    metric_pairs = _ratio_keys_for_suite(suite_base)
    failures: list[str] = []
    warnings: list[str] = []

    lines: list[str] = []
    lines.append(f"# Perf Comparison: {suite_base}")
    lines.append("")
    lines.append(f"- baseline profile: `{baseline.get('profile', 'n/a')}`")
    lines.append(f"- candidate profile: `{candidate.get('profile', 'n/a')}`")
    lines.append(f"- baseline base_url: `{baseline.get('base_url', 'n/a')}`")
    lines.append(f"- candidate base_url: `{candidate.get('base_url', 'n/a')}`")
    lines.append("")
    lines.append("## Per-label latency (ms)")
    lines.append("")

    header = ["label", "metric", "baseline", "candidate (delta)", "ratio", "status"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    all_labels = sorted(set(base_idx) | set(cand_idx))
    for label in all_labels:
        b = base_idx.get(label, {})
        c = cand_idx.get(label, {})

        b_count = int(b.get("count", 0))
        c_count = int(c.get("count", 0))
        underpowered = b_count < min_samples or c_count < min_samples

        for metric, thresh_key in metric_pairs:
            b_val = float(b.get(metric, 0.0) or 0.0)
            c_val = float(c.get(metric, 0.0) or 0.0)
            ratio_limit = float(regression.get(thresh_key, 1.20))

            if b_val <= 0:
                status = "skip (no baseline)"
                ratio_str = "n/a"
            else:
                ratio = c_val / b_val
                ratio_str = f"{ratio:.2f}x"
                if underpowered:
                    status = "warn (samples<min)"
                    warnings.append(
                        f"{label}/{metric}: only {b_count}/{c_count} samples (need >={min_samples})"
                    )
                elif ratio >= ratio_limit:
                    status = f"FAIL (>={ratio_limit:.2f}x)"
                    failures.append(
                        f"{label}/{metric}: {ratio:.2f}x >= {ratio_limit:.2f}x"
                    )
                else:
                    status = "ok"

            row = [
                label,
                metric,
                f"{b_val:.1f}",
                _format_delta(b_val, c_val) if b_val > 0 else f"{c_val:.1f}",
                ratio_str,
                status,
            ]
            lines.append("| " + " | ".join(row) + " |")

    # SLO 표 — slo_breach 는 warning
    if slo:
        lines.append("")
        lines.append("## SLO check (candidate)")
        lines.append("")
        lines.append("| slo_key | limit_ms | observed_p95 | status |")
        lines.append("| --- | --- | --- | --- |")
        # search_p95_ms 등 키 매핑 — 단순화: 가장 큰 p95 비교
        max_p95 = max(
            (float(b.get("p95_ms", 0)) for b in cand_idx.values()),
            default=0.0,
        )
        for slo_key, limit in slo.items():
            status = "ok"
            if max_p95 > float(limit):
                status = f"warn (max p95 {max_p95:.1f} > {limit})"
                warnings.append(f"slo {slo_key}: max p95 {max_p95:.1f} > {limit}")
            lines.append(f"| {slo_key} | {limit} | {max_p95:.1f} | {status} |")

    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if failures:
        lines.append("**FAIL** — regressions detected:")
        for f in failures:
            lines.append(f"- {f}")
    elif warnings:
        lines.append("**WARN** — issues to review:")
        for w in warnings:
            lines.append(f"- {w}")
    else:
        lines.append("**PASS** — no regression above configured ratios.")

    return "\n".join(lines) + "\n", Verdict(failures=failures, warnings=warnings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two perf reports.")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path(__file__).resolve().parent / "thresholds.yml",
    )
    parser.add_argument("--out", type=Path, default=None, help="markdown 출력 경로")
    args = parser.parse_args(argv)

    baseline = _load_json(args.baseline)
    candidate = _load_json(args.candidate)
    thresholds = _load_thresholds(args.thresholds)

    md, verdict = compare(baseline, candidate, thresholds)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"[compare] wrote {args.out}")
    else:
        print(md)

    if verdict.failures:
        print(f"[compare] FAIL — {len(verdict.failures)} regression(s)", file=sys.stderr)
    elif verdict.warnings:
        print(f"[compare] WARN — {len(verdict.warnings)} warning(s)", file=sys.stderr)
    else:
        print("[compare] PASS", file=sys.stderr)

    return verdict.exit_code


if __name__ == "__main__":
    sys.exit(main())
