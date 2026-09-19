#!/usr/bin/env python3
"""Summarize recorder PoC baseline-check JSON files into one decision report.

Usage:
  python3 tools/summarize_recorder_poc.py verification/evidence/<timestamp>/recorder-poc
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


def load_reports(directory: Path) -> list[dict]:
    reports: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text())
        payload["_report_path"] = str(path)
        reports.append(payload)
    return reports


def classify(reports: list[dict]) -> tuple[str, list[str]]:
    notes: list[str] = []
    if not reports:
        return "no_reports", ["No recorder PoC reports were found."]

    valid_count = sum(1 for item in reports if item.get("baseline_valid"))
    total = len(reports)
    if valid_count == total:
        notes.append("All provided reports satisfy the research baseline.")
        return "keep_flutter_recorder_strategy", notes
    if valid_count > 0:
        notes.append("Some reports satisfy the baseline, but at least one does not.")
        return "keep_flutter_plus_native_bridge", notes
    notes.append("No provided report satisfies the research baseline.")
    return "revisit_recorder_strategy", notes


def summarize(directory: Path) -> dict:
    reports = load_reports(directory)
    decision, notes = classify(reports)
    return {
        "input_directory": str(directory),
        "report_count": len(reports),
        "valid_count": sum(1 for item in reports if item.get("baseline_valid")),
        "decision": decision,
        "reports": [
            {
                "path": item.get("_report_path"),
                "baseline_valid": item.get("baseline_valid"),
                "container": item.get("container"),
                "codec": item.get("codec"),
                "sample_rate_hz": item.get("sample_rate_hz"),
                "channels": item.get("channels"),
                "violations": item.get("violations", []),
            }
            for item in reports
        ],
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Usage: python3 tools/summarize_recorder_poc.py <recorder-poc-dir>", file=sys.stderr)
        return 1
    directory = Path(args[0])
    summary = summarize(directory)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
