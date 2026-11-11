#!/usr/bin/env python3
"""Create a timestamped runtime-device evidence directory with note templates copied in."""

from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Prepare a runtime-device evidence directory')
    parser.add_argument('--platform', required=True, choices=['ios', 'android'])
    parser.add_argument('--label', default='smoke')
    parser.add_argument('--root', default='verification/evidence')
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    out_dir = Path(args.root) / f'{stamp}-{args.platform}-{args.label}'
    out_dir.mkdir(parents=True, exist_ok=True)

    review_dir = out_dir / 'review'
    review_dir.mkdir(parents=True, exist_ok=True)

    template = Path('apps/recorder-mobile/docs/runtime-device-run-note-template.md')
    target = review_dir / 'runtime-device-run-note.md'
    shutil.copy2(template, target)

    print(out_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
