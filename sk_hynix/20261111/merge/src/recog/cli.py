from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import sync_scan
from .api import serve
from .beep import BEEP_SOURCE_DEFAULT, BEEP_SOURCES
from .pipeline import AudioSyncPipeline
from .store import SessionStore
from .sync_sound import SYNC_SOUNDS
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

    scan = subparsers.add_parser(
        "sync-scan", help="diagnose sync-sound detection and alignment on recordings (read-only)"
    )
    scan.add_argument("files", nargs="+", help="recordings, any format ffmpeg reads")
    scan.add_argument("--sound", default="all", choices=["all", *SYNC_SOUNDS])
    scan.add_argument("--source", default=BEEP_SOURCE_DEFAULT, choices=list(BEEP_SOURCES))
    scan.add_argument("--json", action="store_true", help="machine-readable output")

    args = parser.parse_args(argv)
    if args.command == "sync-scan":
        # Before the store: a diagnostic must not create a data directory.
        return sync_scan.main(args.files, args.sound, args.source, args.json)
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
