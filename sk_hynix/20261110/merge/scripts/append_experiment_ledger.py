#!/usr/bin/env python3
"""Append an evidence bundle summary into the experiment ledger markdown table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HEADER = "| Run ID | Date | Track | Protocol | Classification | Evidence bundle | Key outcome | Promotion relevant? |\n|---|---|---|---|---|---|---|---|\n"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> int:
    parser = argparse.ArgumentParser(description='Append an evidence bundle to the experiment ledger')
    parser.add_argument('--bundle', required=True, help='Path to bundle.json')
    parser.add_argument('--ledger', default='.omx/plans/experiment-ledger-audio-sync-platform.md')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--key-outcome', required=True)
    parser.add_argument('--notes', default='')
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    bundle = load_json(bundle_path)
    classification = bundle.get('classification', 'unknown')
    run_type = bundle.get('run_type', 'unknown')
    protocol = bundle.get('protocol_version', 'unknown')
    promotion_relevant = 'yes' if classification == 'baseline-valid' and run_type == 'controlled_device' else 'no'

    ledger_path = Path(args.ledger)
    text = ledger_path.read_text(encoding='utf-8') if ledger_path.exists() else '# Experiment Ledger\n\n' + HEADER
    row = f"| `{args.run_id}` | {args.date} | {run_type} | {protocol} | {classification} | `{bundle_path}` | {args.key_outcome} | {promotion_relevant} |\n"
    if row in text:
        print('row already present')
        return 0
    if HEADER not in text:
        text += '\n' + HEADER
    text += row
    if args.notes:
        text += f"\n- `{args.run_id}` notes: {args.notes}\n"
    ledger_path.write_text(text, encoding='utf-8')
    print(str(ledger_path))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
