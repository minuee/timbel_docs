#!/usr/bin/env python3
"""CLI to generate the default synthetic corpus integration matrix."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from testkit.synthetic_corpus import generate_integration_matrix


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic synthetic fixtures for the audio sync merge MVP."
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="artifacts/synthetic",
        help="Directory where the session fixtures will be written.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    generated = generate_integration_matrix(output_dir)
    print(f"generated_sessions={len(generated)}")
    for session_dir in generated:
        print(session_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
