#!/usr/bin/env python3
"""Render the machine-readable regression scaffold for lane 4."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from testkit.regression_plan import build_regression_plan


def main() -> int:
    print(json.dumps(build_regression_plan(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
