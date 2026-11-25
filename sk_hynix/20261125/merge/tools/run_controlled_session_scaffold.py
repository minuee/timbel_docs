#!/usr/bin/env python3
"""Run a thin-client controlled session scaffold and export an evidence bundle."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from recog.pipeline import AudioSyncPipeline
from recog.store import SessionStore
from recog.synthetic import generate_fixture_session
from testkit.controlled_bundle import export_controlled_device_bundle


def _run_helper(script: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / script), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a controlled-session evidence bundle using the current backend scaffold."
    )
    parser.add_argument("output_dir", help="Evidence bundle output directory.")
    parser.add_argument("--tracks", type=int, default=3)
    parser.add_argument("--duration-seconds", type=float, default=6.0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    runtime_dir = output_dir / "runtime"
    fixture_dir = output_dir / "controlled-device" / "fixture"

    _run_helper("init_evidence_bundle.py", str(output_dir), "--run-type", "controlled_device")
    _run_helper("generate_sync_beep.py", str(output_dir / "controlled-device" / "beep.wav"))

    truth = generate_fixture_session(fixture_dir, track_count=args.tracks, duration_seconds=args.duration_seconds)

    store = SessionStore(runtime_dir)
    room = store.create_room(
        host_participant_id="p1",
        expected_participant_count=args.tracks,
        minimum_ready_participants=args.tracks,
        mode="research",
    )

    for index, track in enumerate(truth["tracks"], start=1):
        participant_id = track["participant_id"]
        store.join_room(
            room.room_id,
            participant_id=participant_id,
            device_id=f"device_{index}",
            os_type="ios" if index % 2 else "android",
            os_version="test",
            app_version="0.1.0",
        )
        store.record_preflight(
            room.room_id,
            participant_id,
            recorder_engine="controlled_session_scaffold",
            mic_route="built_in_mic",
            audio_processing_flags={"agc": False, "noise_suppression": False, "echo_cancellation": False},
            permission_state={"microphone": "granted"},
            time_sync={"server_time_offset_ms": 0.0, "round_trip_ms": 10.0 + index, "sync_quality_bucket": "good"},
        )
        store.mark_ready(room.room_id, participant_id)

    started = store.start_room(room.room_id, participant_id="p1", anchor_type="beep")
    session_id = started.session_id
    assert session_id is not None
    store.stop_room(room.room_id, participant_id="p1")

    for index, track in enumerate(truth["tracks"], start=1):
        participant_id = track["participant_id"]
        payload = Path(track["path"]).read_bytes()
        metadata = {
            "schema_version": "audio-sync-platform/v1",
            "session": {
                "session_id": session_id,
                "room_id": started.room_id,
                "host_id": "p1",
                "protocol_version": started.protocol_version,
                "start_strategy": started.start_strategy,
                "anchor_policy": started.anchor_policy,
                "created_at": started.created_at,
            },
            "participant": {
                "participant_id": participant_id,
                "display_name": participant_id,
                "role": "host" if participant_id == "p1" else "member",
            },
            "recording": {
                "recording_id": f"rec_{participant_id}",
                "filename": track["filename"],
                "container": track["format"],
                "codec": "pcm_s16le" if track["format"] == "wav" else "compressed",
                "duration_seconds": truth["duration_seconds"] + track["offset_seconds"],
                "pause_resume_events": [],
            },
            "device": {
                "device_id": f"device_{index}",
                "device_model": f"simulated-device-{index}",
                "os_type": "ios" if index % 2 else "android",
                "os_version": "test",
                "app_version": "0.1.0",
                "mic_route": "built_in_mic",
                "audio_processing_flags": {"agc": False, "noise_suppression": False, "echo_cancellation": False},
            },
            "timing": {
                "start_command_issued_at": started.server_start_issued_at,
                "start_command_received_at": started.server_start_issued_at,
                "recording_started_at": started.server_start_issued_at,
                "recording_stopped_at": store.get_room(room.room_id).updated_at,
                "server_time_offset_ms": 0.0,
                "round_trip_ms": 10.0 + index,
                "sync_quality_bucket": "good",
            },
            "audio": {
                "sample_rate": truth["sample_rate"],
                "channels": 1,
                "bit_depth": 16,
                "format_profile": "research_baseline_wav_mono_48k",
            },
            "anchor": {
                "anchor_type": "beep",
                "anchor_expected_at": started.server_start_issued_at,
                "anchor_expected_offset_ms_from_start_command": 100,
                "anchor_repeat_policy": "start_only",
                "anchor_spec_version": "sync-beep/v1",
            },
            "upload": {
                "sha256": "",
                "filesize_bytes": len(payload),
            },
        }
        record = store.register_recording_metadata(
            session_id,
            participant_id=participant_id,
            recording_id=f"rec_{participant_id}",
            control_metadata={
                "start_command_id": started.start_command_id,
                "server_start_issued_at": started.server_start_issued_at,
                "start_command_received_at": started.server_start_issued_at,
                "recording_started_at": started.server_start_issued_at,
                "recording_stopped_at": store.get_room(room.room_id).updated_at,
                "mic_route": "built_in_mic",
                "audio_processing_flags": {"agc": False, "noise_suppression": False, "echo_cancellation": False},
                "anchor_type": "beep",
                "anchor_expected_at": started.server_start_issued_at,
                "pause_resume_events": [],
                "schema_version": metadata["schema_version"],
                "envelope": metadata,
            },
            audio_file_metadata={
                "filename": track["filename"],
                "container": track["format"],
                "codec": "pcm_s16le" if track["format"] == "wav" else "compressed",
                "sample_rate_hz": truth["sample_rate"],
                "channels": 1,
                "duration_seconds": truth["duration_seconds"] + track["offset_seconds"],
            },
        )
        store.attach_recording_binary(
            session_id,
            record.recording_id,
            payload=payload,
            content_type="audio/wav" if track["format"] == "wav" else "application/octet-stream",
        )
        store.append_session_event(
            session_id,
            event_type="recording_uploaded",
            participant_id=participant_id,
            payload={"filename": track["filename"], "classification": "baseline_valid"},
        )

    result = AudioSyncPipeline(store).process_session(session_id)

    session = store.get_session(session_id)
    room_state = store.get_room(room.room_id)
    recording_envelopes = [record.control_metadata.get("envelope", {}) for record in session.recordings]
    (output_dir / "session-metadata.json").write_text(json.dumps({"recordings": recording_envelopes, "session": session.to_dict()}, indent=2))
    (output_dir / "room-state.json").write_text(json.dumps(room_state.to_dict(), indent=2))
    with (output_dir / "protocol-events.ndjson").open("w", encoding="utf-8") as handle:
        for event in session.events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    export_controlled_device_bundle(data_root=runtime_dir, room_id=room.room_id, output_dir=output_dir)

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    summary["session_id"] = session_id
    summary["room_id"] = room.room_id
    summary["protocol_version"] = room_state.protocol_version
    summary["classification"] = session.classification
    summary["participants"]["expected"] = args.tracks
    summary["participants"]["received_files"] = len(session.files)
    summary["metrics"] = session.qa_summary
    summary["residual_blockers"] = []
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "summary.md").write_text(
        "# Evidence Bundle Summary\n\n"
        f"- Session ID: {session_id}\n"
        f"- Room ID: {room.room_id}\n"
        f"- Protocol Version: {room_state.protocol_version}\n"
        f"- Start Strategy: {room_state.start_strategy}\n"
        f"- Anchor Policy: {room_state.anchor_policy}\n"
        f"- Participant Count: {len(session.files)}\n"
        f"- Classification: {session.classification}\n\n"
        "## Key Results\n"
        f"- Controlled-device scaffold run complete\n"
        f"- QA summary: {json.dumps(session.qa_summary, ensure_ascii=False)}\n",
        encoding="utf-8",
    )

    print(json.dumps({"session_id": session_id, "room_id": room.room_id, "qa_summary": result["qa_summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
