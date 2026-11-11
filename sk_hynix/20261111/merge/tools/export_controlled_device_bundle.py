#!/usr/bin/env python3
"""Export a standardized controlled-device evidence bundle from a completed room/session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from testkit.controlled_bundle import export_controlled_device_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a controlled-device evidence bundle.")
    parser.add_argument("room_id")
    parser.add_argument("output_dir")
    parser.add_argument("--data-root", default=".runtime")
    args = parser.parse_args()

    bundle = export_controlled_device_bundle(
        data_root=args.data_root,
        room_id=args.room_id,
        output_dir=args.output_dir,
    )
    print(json.dumps(bundle, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
