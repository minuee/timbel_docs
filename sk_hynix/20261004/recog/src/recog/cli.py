from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api import serve
from .pipeline import AudioSyncPipeline
from .store import SessionStore
from .synthetic import generate_fixture_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audio sync merge service MVP")
    parser.add_argument("--data-root", default=".runtime", help="data directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("serve", help="run the HTTP API")

    fixture = subparsers.add_parser("generate-fixture", help="generate synthetic session inputs")
    fixture.add_argument("--output", required=True)
    fixture.add_argument("--tracks", type=int, default=3)
    fixture.add_argument("--duration-seconds", type=float, default=6.0)

    process = subparsers.add_parser("process-fixture", help="create session, upload fixture, process it")
    process.add_argument("--input", required=True)

    args = parser.parse_args(argv)
    store = SessionStore(args.data_root)
    if args.command == "serve":
        serve(args.data_root)
        return 0
    if args.command == "generate-fixture":
        payload = generate_fixture_session(
            args.output,
            track_count=args.tracks,
            duration_seconds=args.duration_seconds,
        )
        print(json.dumps(payload, indent=2))
        return 0
    if args.command == "process-fixture":
        session = store.create_session()
        truth = json.loads((Path(args.input) / "ground_truth.json").read_text())
        for track in truth["tracks"]:
            store.add_file(
                session.session_id,
                participant_id=track["participant_id"],
                filename=track["filename"],
                payload=Path(track["path"]).read_bytes(),
            )
        result = AudioSyncPipeline(store).process_session(session.session_id)
        print(json.dumps(result, indent=2))
        return 0
    return 1
