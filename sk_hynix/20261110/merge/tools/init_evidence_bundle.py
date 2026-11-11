#!/usr/bin/env python3
"""Create a standardized evidence bundle scaffold for audio sync experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_BUNDLE_JSON = {
    "schema_version": "audio-sync-platform/evidence-bundle/v1",
    "bundle_id": "evidence_<timestamp>",
    "run_type": "controlled_device",
    "protocol_version": "recording-protocol/v1",
    "classification": "baseline-valid",
    "classification_reason": "pending operator review",
    "session": {
        "session_id": "fill",
        "room_id": "fill",
        "start_strategy": "server_authoritative_beep",
        "anchor_policy": "beep_required",
    },
    "participants": {"expected": 5, "received_files": 0},
    "metrics": {},
    "artifacts": {
        "manifest": "artifacts/manifest.json",
        "manifest_export": "artifacts/manifest.export.json",
        "bundle": "artifacts/aligned_tracks.zip",
        "mixdown": "artifacts/listening_mix.wav",
    },
    "residual_blockers": [],
}


DEFAULT_BUNDLE_MD = """# Evidence Bundle Summary

- Bundle ID:
- Run type:
- Classification:
- Classification reason:
- Session ID:
- Room ID:
- Start strategy:
- Anchor policy:

## Metrics
- alignment_confidence_mean:
- loudness_spread_db:
- clipped_samples_mix:

## Artifacts
- manifest:
- manifest_export:
- bundle:
- mixdown:

## Residual blockers
-
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a standard evidence bundle scaffold.")
    parser.add_argument("output_dir", help="Target evidence directory to create.")
    parser.add_argument("--run-type", default="controlled_device")
    parser.add_argument("--bundle-id", default=None)
    parser.add_argument("--protocol-version", default="recording-protocol/v1")
    parser.add_argument("--classification", default="baseline-valid")
    args = parser.parse_args()

    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    for subdir in [
        "synthetic/logs",
        "controlled-device/load-probe",
        "controlled-device/logs",
        "field/logs",
        "artifacts",
        "diagnostics/ffprobe",
        "diagnostics/scope-audit",
        "diagnostics/command-output",
    ]:
        (root / subdir).mkdir(parents=True, exist_ok=True)

    bundle_json = dict(DEFAULT_BUNDLE_JSON)
    bundle_json["bundle_id"] = args.bundle_id or root.name
    bundle_json["run_type"] = args.run_type
    bundle_json["protocol_version"] = args.protocol_version
    bundle_json["classification"] = args.classification

    (root / "summary.md").write_text(DEFAULT_BUNDLE_MD, encoding="utf-8")
    (root / "summary.json").write_text(json.dumps(bundle_json, indent=2), encoding="utf-8")
    (root / "session-metadata.json").write_text("{}\n", encoding="utf-8")
    (root / "room-state.json").write_text("{}\n", encoding="utf-8")
    (root / "protocol-events.ndjson").write_text("", encoding="utf-8")
    (root / "release-checklist.md").write_text("# Release Checklist\n\n- [ ] pending\n", encoding="utf-8")
    (root / "notes.md").write_text("# Notes\n\n", encoding="utf-8")

    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
