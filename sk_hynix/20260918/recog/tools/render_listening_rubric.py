#!/usr/bin/env python3
"""Render the manual listening rubric as JSON."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dataclasses import asdict

from testkit.listening_rubric import build_listening_rubric


def main() -> int:
    print(json.dumps([asdict(item) for item in build_listening_rubric()], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
