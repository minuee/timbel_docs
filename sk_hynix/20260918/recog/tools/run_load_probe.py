#!/usr/bin/env python3
"""Run a repeatable synthetic load probe and emit a prefilled listening-review sheet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recog.pipeline import AudioSyncPipeline
from recog.store import SessionStore
from recog.synthetic import generate_fixture_session
from testkit.listening_review import build_prefilled_listening_review


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic multi-track session, process it, and emit load-probe artifacts."
    )
    parser.add_argument("output_dir", nargs="?", default="artifacts/load-probe")
    parser.add_argument("--tracks", type=int, default=5)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    fixture_dir = output_dir / "fixture"
    runtime_dir = output_dir / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    truth = generate_fixture_session(
        fixture_dir,
        track_count=args.tracks,
        duration_seconds=args.duration_seconds,
    )

    store = SessionStore(runtime_dir)
    session = store.create_session()
    for track in truth["tracks"]:
        store.add_file(
            session.session_id,
            participant_id=track["participant_id"],
            filename=track["filename"],
            payload=Path(track["path"]).read_bytes(),
        )

    started = time.perf_counter()
    result = AudioSyncPipeline(store).process_session(session.session_id)
    elapsed_seconds = round(time.perf_counter() - started, 3)

    manifest_path = store.session_dir(session.session_id) / "artifacts" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    listening_review_path = output_dir / "listening-review.md"
    listening_review_path.write_text(
        build_prefilled_listening_review(
            session_id=session.session_id,
            recommended_stt_input=manifest["recommended_stt_input"],
            fixture_type="synthetic",
        )
    )

    summary = {
        "session_id": session.session_id,
        "tracks": args.tracks,
        "duration_seconds": args.duration_seconds,
        "elapsed_seconds": elapsed_seconds,
        "qa_summary": result["qa_summary"],
        "artifacts": result["artifacts"],
        "manifest_path": str(manifest_path),
        "listening_review_path": str(listening_review_path),
    }
    summary_path = output_dir / "probe-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
