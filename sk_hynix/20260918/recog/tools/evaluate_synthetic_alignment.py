#!/usr/bin/env python3
"""CLI to evaluate predicted offsets/drift against synthetic ground truth."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from testkit.benchmark import TrackPrediction, evaluate_alignment, load_ground_truth


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare predicted offsets/drift values against a synthetic ground-truth fixture."
    )
    parser.add_argument("ground_truth", help="Path to ground_truth.json from a generated session.")
    parser.add_argument("predictions", help="Path to a JSON file containing prediction objects.")
    args = parser.parse_args()

    ground_truth = load_ground_truth(args.ground_truth)
    predictions_payload = json.loads(Path(args.predictions).read_text(encoding="utf-8"))
    predictions = [
        TrackPrediction(
            participant_id=item["participant_id"],
            predicted_offset_ms=item["predicted_offset_ms"],
            predicted_drift_ppm=item["predicted_drift_ppm"],
        )
        for item in predictions_payload
    ]

    result = evaluate_alignment(ground_truth, predictions)
    print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
