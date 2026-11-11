#!/usr/bin/env python3
"""Export a processed session into the standardized evidence bundle layout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from recog.evidence import export_session_to_evidence_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Export session artifacts into an evidence bundle")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--run-type", default=None)
    parser.add_argument("--reviewer", default="operator")
    args = parser.parse_args()

    evidence_root = export_session_to_evidence_bundle(
        args.data_root,
        args.session_id,
        args.evidence_root,
        run_type=args.run_type,
        reviewer=args.reviewer,
    )
    print(str(evidence_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
