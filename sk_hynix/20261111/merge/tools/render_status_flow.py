#!/usr/bin/env python3
"""Render the lane-4 status transition scaffold as JSON."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from testkit.status_flow import build_status_flow


def main() -> int:
    print(json.dumps(build_status_flow(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
