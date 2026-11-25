from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from .models import (
    ArtifactRecord,
    FileRecord,
    ParticipantRecord,
    RecordingRecord,
    RoomEventRecord,
    RoomRecord,
    SessionRecord,
    new_id,
    utc_now,
)
from .evidence import build_evidence_summary
from .events import classify_session
from .rooms import (
    RoomStateError,
    can_ready,
    can_stop,
    can_start,
    next_room_state_after_join,
    next_room_state_after_ready,
)


class SessionStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.sessions_root = self.root / "sessions"
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self.rooms_root = self.root / "rooms"
        self.rooms_root.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> SessionRecord:
        session = SessionRecord(session_id=new_id("session"))
        session_dir = self.session_dir(session.session_id)
        for child in ("uploads", "canonical", "aligned", "artifacts", "work"):
            (session_dir / child).mkdir(parents=True, exist_ok=True)
        self.save_session(session)
        return session

    def create_session_from_room(self, room: RoomRecord) -> SessionRecord:
        session = SessionRecord(
            session_id=room.session_id or new_id("session"),
            room_id=room.room_id,
            host_id=room.host_participant_id,
            mode=room.mode,
            protocol_version=room.protocol_version,
            start_strategy=room.start_strategy,
            anchor_policy=room.anchor_policy,
            join_code=room.join_code,
            evidence_auto_export=room.evidence_auto_export,
            evidence_default_run_type=room.evidence_default_run_type,
            start_command_id=room.start_command_id,
            server_start_issued_at=room.server_start_issued_at,
            anchor_type=room.anchor_type,
            participant_ids=[participant.participant_id for participant in room.participants],
        )
        session_dir = self.session_dir(session.session_id)
        for child in ("uploads", "canonical", "aligned", "artifacts", "work"):
            (session_dir / child).mkdir(parents=True, exist_ok=True)
        self.save_session(session)
        return session

    def list_sessions(self) -> list[str]:
        return sorted(path.name for path in self.sessions_root.iterdir() if path.is_dir())

    def session_dir(self, session_id: str) -> Path:
        return self.sessions_root / session_id

    def session_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def save_session(self, session: SessionRecord) -> None:
        session.updated_at = utc_now()
        session.classification = classify_session(session)
        evidence_summary = build_evidence_summary(session)
        session.classification_reason = evidence_summary["classification_reason"]
        session.failed_rules = evidence_summary["failed_rules"]
        session.degraded_rules = evidence_summary["degraded_rules"]
        session.evidence_ready = evidence_summary["evidence_ready"]
        session.recommended_run_type = evidence_summary["recommended_run_type"]
        session.evidence_export_hint = evidence_summary["evidence_export_hint"]
        path = self.session_path(session.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(session.to_dict(), indent=2, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def get_session(self, session_id: str) -> SessionRecord:
        payload = json.loads(self.session_path(session_id).read_text())
        return SessionRecord.from_dict(payload)

    def room_dir(self, room_id: str) -> Path:
        return self.rooms_root / room_id

    def room_path(self, room_id: str) -> Path:
        return self.room_dir(room_id) / "room.json"

    def save_room(self, room: RoomRecord) -> None:
        room.updated_at = utc_now()
        path = self.room_path(room.room_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(room.to_dict(), indent=2, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def get_room(self, room_id: str) -> RoomRecord:
        payload = json.loads(self.room_path(room_id).read_text())
        return RoomRecord.from_dict(payload)

    def create_room(
        self,
        *,
        host_participant_id: str,
        expected_participant_count: int = 5,
        minimum_ready_participants: int = 1,
        mode: str = "research",
        protocol_version: str = "recording-protocol/v1",
        start_strategy: str = "server_authoritative_beep",
        anchor_policy: str = "beep_required",
        evidence_auto_export: bool = False,
        evidence_default_run_type: str | None = None,
    ) -> RoomRecord:
        session = self.create_session()
        room = RoomRecord(
            room_id=new_id("room"),
            host_participant_id=host_participant_id,
            protocol_version=protocol_version,
            start_strategy=start_strategy,
            anchor_policy=anchor_policy,
            expected_participant_count=expected_participant_count,
            minimum_ready_participants=minimum_ready_participants,
            mode=mode,
            session_id=session.session_id,
            join_code=new_id("join")[-6:].upper(),
            evidence_auto_export=evidence_auto_export,
            evidence_default_run_type=evidence_default_run_type,
        )
        session.room_id = room.room_id
        session.host_id = room.host_participant_id
        session.mode = room.mode
        session.protocol_version = room.protocol_version
        session.start_strategy = room.start_strategy
        session.anchor_policy = room.anchor_policy
        session.join_code = room.join_code
        session.evidence_auto_export = room.evidence_auto_export
        session.evidence_default_run_type = room.evidence_default_run_type
        self.save_session(session)
        self.save_room(room)
        return room

    def append_room_event(
        self,
        room_id: str,
        *,
        event_type: str,
        participant_id: str | None = None,
        payload: dict | None = None,
    ) -> RoomEventRecord:
        room = self.get_room(room_id)
        event = RoomEventRecord(
            event_id=new_id("event"),
            room_id=room_id,
            event_type=event_type,
            participant_id=participant_id,
            payload=payload or {},
        )
        room.events.append(event)
        self.save_room(room)
        return event

    def join_room(self, room_id: str, **participant_fields: object) -> ParticipantRecord:
        room = self.get_room(room_id)
        participant = ParticipantRecord(**participant_fields)
        room.participants.append(participant)
        room.state = next_room_state_after_join(room)
        self.save_room(room)
        self.append_room_event(
            room_id,
            event_type="participant_joined",
            participant_id=participant.participant_id,
        )
        return participant

    def update_participant(
        self, room_id: str, participant_id: str, **changes: object
    ) -> ParticipantRecord:
        room = self.get_room(room_id)
        for participant in room.participants:
            if participant.participant_id == participant_id:
                for key, value in changes.items():
                    setattr(participant, key, value)
                participant.updated_at = utc_now()
                self.save_room(room)
                return participant
        raise KeyError(participant_id)

    def record_preflight(
        self,
        room_id: str,
        participant_id: str,
        *,
        recorder_engine: str,
        mic_route: str,
        audio_processing_flags: dict[str, bool],
        permission_state: dict[str, object],
        time_sync: dict[str, object],
        warnings: list[str] | None = None,
    ) -> ParticipantRecord:
        room = self.get_room(room_id)
        for participant in room.participants:
            if participant.participant_id == participant_id:
                participant.recorder_engine = recorder_engine
                participant.mic_route = mic_route
                participant.audio_processing_flags = audio_processing_flags
                participant.preflight_snapshot = {
                    "permission_state": permission_state,
                    "time_sync": time_sync,
                    "warnings": warnings or [],
                }
                participant.preflight_passed_at = utc_now()
                participant.state = "preflight_passed"
                participant.updated_at = utc_now()
                self.save_room(room)
                self.append_room_event(
                    room_id,
                    event_type="participant_preflight_passed",
                    participant_id=participant_id,
                    payload={"warnings": warnings or []},
                )
                return participant
        raise KeyError(participant_id)

    def mark_ready(self, room_id: str, participant_id: str) -> ParticipantRecord:
        room = self.get_room(room_id)
        for participant in room.participants:
            if participant.participant_id == participant_id:
                ok, reason = can_ready(participant)
                if not ok:
                    raise RoomStateError(reason or "cannot_ready")
                participant.state = "ready"
                participant.updated_at = utc_now()
                room.state = next_room_state_after_ready(room)
                self.save_room(room)
                self.append_room_event(
                    room_id,
                    event_type="participant_ready",
                    participant_id=participant_id,
                )
                return participant
        raise KeyError(participant_id)

    def start_room(self, room_id: str, *, participant_id: str, anchor_type: str) -> RoomRecord:
        room = self.get_room(room_id)
        ok, reason = can_start(room, participant_id)
        if not ok:
            raise RoomStateError(reason or "cannot_start")
        room.session_id = new_id("session")
        room.start_command_id = new_id("start_cmd")
        room.server_start_issued_at = utc_now()
        room.anchor_type = anchor_type
        room.state = "recording"
        for participant in room.participants:
            if participant.state == "ready":
                participant.state = "recording"
                participant.updated_at = utc_now()
        self.save_room(room)
        self.append_room_event(
            room_id,
            event_type="recording_started",
            participant_id=participant_id,
            payload={
                "session_id": room.session_id,
                "start_command_id": room.start_command_id,
                "server_start_issued_at": room.server_start_issued_at,
                "anchor_type": anchor_type,
            },
        )
        session = self.create_session_from_room(room)
        self.append_session_event(
            session.session_id,
            event_type="room_recording_started",
            participant_id=participant_id,
            payload={
                "room_id": room.room_id,
                "start_command_id": room.start_command_id,
                "server_start_issued_at": room.server_start_issued_at,
                "anchor_type": anchor_type,
            },
        )
        return self.get_room(room_id)

    def stop_room(self, room_id: str, *, participant_id: str) -> RoomRecord:
        room = self.get_room(room_id)
        ok, reason = can_stop(room, participant_id)
        if not ok:
            raise RoomStateError(reason or "cannot_stop")
        room.state = "stopped"
        stopped_at = utc_now()
        for participant in room.participants:
            if participant.state in {"recording", "ready", "preflight_passed"}:
                participant.state = "stopped"
                participant.updated_at = stopped_at
        self.save_room(room)
        self.append_room_event(
            room_id,
            event_type="recording_stopped",
            participant_id=participant_id,
            payload={"stopped_at": stopped_at},
        )
        if room.session_id:
            self.append_session_event(
                room.session_id,
                event_type="room_recording_stopped",
                participant_id=participant_id,
                payload={"room_id": room.room_id, "stopped_at": stopped_at},
            )
        return self.get_room(room_id)

    def add_file(
        self,
        session_id: str,
        *,
        participant_id: str,
        filename: str,
        payload: bytes,
    ) -> FileRecord:
        session = self.get_session(session_id)
        if len(session.files) >= session.limits["max_participants"]:
            raise ValueError("session participant limit exceeded")
        file_id = new_id("file")
        upload_path = self.session_dir(session_id) / "uploads" / f"{file_id}_{filename}"
        upload_path.write_bytes(payload)
        record = FileRecord(
            file_id=file_id,
            participant_id=participant_id,
            filename=filename,
            uploaded_path=str(upload_path),
            format_name=Path(filename).suffix.lstrip(".").lower() or "unknown",
            container=Path(filename).suffix.lstrip(".").lower() or "unknown",
            sha256=self.sha256(upload_path),
            filesize_bytes=len(payload),
            session_id=session_id,
            room_id=session.room_id,
        )
        session.files.append(record)
        self.save_session(session)
        return record

    def register_recording_metadata(
        self,
        session_id: str,
        *,
        participant_id: str,
        recording_id: str | None,
        control_metadata: dict[str, object],
        audio_file_metadata: dict[str, object],
    ) -> RecordingRecord:
        session = self.get_session(session_id)
        if recording_id:
            for record in session.recordings:
                if record.recording_id == recording_id:
                    raise ValueError("recording_id already exists")
        record = RecordingRecord(
            recording_id=recording_id or new_id("rec"),
            session_id=session_id,
            participant_id=participant_id,
            metadata_status="registered",
            binary_status="missing",
            validation_status="pending",
            control_metadata=dict(control_metadata),
            audio_file=dict(audio_file_metadata),
        )
        session.recordings.append(record)
        self.save_session(session)
        return record

    def get_recording(self, session_id: str, recording_id: str) -> RecordingRecord:
        session = self.get_session(session_id)
        for record in session.recordings:
            if record.recording_id == recording_id:
                return record
        raise KeyError(recording_id)

    def attach_recording_binary(
        self,
        session_id: str,
        recording_id: str,
        *,
        payload: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> RecordingRecord:
        session = self.get_session(session_id)
        for index, record in enumerate(session.recordings):
            if record.recording_id != recording_id:
                continue
            if record.metadata_status != "registered":
                raise ValueError("recording metadata must be registered first")
            if record.binary_status == "uploaded":
                raise ValueError("recording binary already uploaded")
            audio_file = dict(record.audio_file)
            final_filename = filename or audio_file.get("filename") or f"{recording_id}.bin"
            upload_path = self.session_dir(session_id) / "uploads" / f"{recording_id}_{final_filename}"
            upload_path.write_bytes(payload)
            audio_file["size_bytes"] = len(payload)
            audio_file["content_type"] = content_type or "application/octet-stream"
            record.audio_file = audio_file
            record.uploaded_path = str(upload_path)
            record.binary_status = "uploaded"
            record.updated_at = utc_now()

            file_record = FileRecord(
                file_id=new_id("file"),
                participant_id=record.participant_id,
                filename=str(audio_file.get("filename") or final_filename),
                uploaded_path=str(upload_path),
                recording_id=recording_id,
                session_id=session_id,
                room_id=session.room_id,
                format_name=str(audio_file.get("container") or Path(final_filename).suffix.lstrip(".").lower() or "unknown"),
                container=str(audio_file.get("container") or Path(final_filename).suffix.lstrip(".").lower() or "unknown"),
                codec=str(audio_file.get("codec") or "unknown"),
                sample_rate_hz=audio_file.get("sample_rate_hz"),
                channels=audio_file.get("channels"),
                duration_seconds=audio_file.get("duration_seconds"),
                sha256=self.sha256(upload_path),
                mic_route=str(record.control_metadata.get("mic_route") or "unknown"),
                audio_processing_flags=dict(record.control_metadata.get("audio_processing_flags") or {}),
                start_command_received_at=record.control_metadata.get("start_command_received_at"),
                recording_started_at=record.control_metadata.get("recording_started_at"),
                anchor_type=record.control_metadata.get("anchor_type"),
                anchor_expected_at=record.control_metadata.get("anchor_expected_at"),
                metadata={"recording_id": recording_id, "content_type": audio_file["content_type"]},
            )
            session.recordings[index] = record
            session.files.append(file_record)
            self.save_session(session)
            self._maybe_close_room_after_uploads(session)
            return record
        raise KeyError(recording_id)

    def append_session_event(
        self,
        session_id: str,
        *,
        event_type: str,
        participant_id: str | None = None,
        payload: dict | None = None,
    ) -> dict[str, object]:
        session = self.get_session(session_id)
        event = {
            "event_id": new_id("sess_evt"),
            "session_id": session_id,
            "room_id": session.room_id,
            "participant_id": participant_id,
            "event_type": event_type,
            "payload": payload or {},
            "created_at": utc_now(),
        }
        session.events.append(event)
        self.save_session(session)
        return event

    def is_recording_processing_ready(self, recording: RecordingRecord) -> bool:
        return (
            recording.metadata_status == "registered"
            and recording.binary_status == "uploaded"
            and recording.validation_status in {"pending", "accepted", "warn"}
        )

    def is_session_processing_ready(self, session_id: str) -> bool:
        session = self.get_session(session_id)
        if session.recordings:
            return all(self.is_recording_processing_ready(recording) for recording in session.recordings)
        return bool(session.files)

    def _maybe_close_room_after_uploads(self, session: SessionRecord) -> None:
        if not session.room_id:
            return
        room = self.get_room(session.room_id)
        uploaded_participants = {recording.participant_id for recording in session.recordings if recording.binary_status == "uploaded"}
        if room.state == "stopped" and room.expected_participant_count > 0 and len(uploaded_participants) >= room.expected_participant_count:
            room.state = "closed"
            self.save_room(room)
            self.append_room_event(
                room.room_id,
                event_type="room_closed",
                payload={"uploaded_participant_count": len(uploaded_participants)},
            )

    def update_file(self, session_id: str, file_id: str, **changes: object) -> FileRecord:
        session = self.get_session(session_id)
        for entry in session.files:
            if entry.file_id == file_id:
                for key, value in changes.items():
                    setattr(entry, key, value)
                entry.updated_at = utc_now()
                self.save_session(session)
                return entry
        raise KeyError(file_id)

    def add_artifact(
        self,
        session_id: str,
        *,
        kind: str,
        name: str,
        source_path: str | Path,
        mime_type: str,
        metadata: dict | None = None,
    ) -> ArtifactRecord:
        source = Path(source_path)
        destination = self.session_dir(session_id) / "artifacts" / name
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        session = self.get_session(session_id)
        artifact = ArtifactRecord(
            artifact_id=new_id("artifact"),
            kind=kind,
            name=name,
            path=str(destination),
            mime_type=mime_type,
            sha256=self.sha256(destination),
            metadata=metadata or {},
        )
        session.artifacts.append(artifact)
        self.save_session(session)
        return artifact

    def set_session_state(
        self,
        session_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        qa_summary: dict | None = None,
    ) -> SessionRecord:
        session = self.get_session(session_id)
        if status is not None:
            session.status = status
        if stage is not None:
            session.stage = stage
        if qa_summary is not None:
            session.qa_summary = qa_summary
        self.save_session(session)
        return session

    def mark_evidence_exported(
        self,
        session_id: str,
        *,
        evidence_bundle_path: str,
        evidence_run_type: str,
        artifacts_index_path: str | None = None,
    ) -> SessionRecord:
        session = self.get_session(session_id)
        session.evidence_bundle_path = evidence_bundle_path
        session.evidence_run_type = evidence_run_type
        session.evidence_exported_at = utc_now()
        session.artifacts_index_path = artifacts_index_path
        self.save_session(session)
        bundle_json = Path(evidence_bundle_path) / "bundle.json"
        classification_json = Path(evidence_bundle_path) / "classification.json"
        artifacts_index = Path(artifacts_index_path) if artifacts_index_path else Path(evidence_bundle_path) / "artifacts-index.json"
        if bundle_json.exists():
            self.add_artifact(
                session_id,
                kind="evidence_bundle",
                name="bundle.json",
                source_path=bundle_json,
                mime_type="application/json",
                metadata={"evidence_run_type": evidence_run_type},
            )
        if classification_json.exists():
            self.add_artifact(
                session_id,
                kind="classification",
                name="classification.json",
                source_path=classification_json,
                mime_type="application/json",
                metadata={"evidence_run_type": evidence_run_type},
            )
        if artifacts_index.exists():
            self.add_artifact(
                session_id,
                kind="artifacts_index",
                name="artifacts-index.json",
                source_path=artifacts_index,
                mime_type="application/json",
                metadata={"evidence_run_type": evidence_run_type},
            )
        return session

    def append_error(self, session_id: str, payload: dict) -> None:
        session = self.get_session(session_id)
        session.errors.append(payload)
        self.save_session(session)

    def close_session(self, session_id: str) -> SessionRecord:
        """Close a session: mark as closing, move artifacts to archive, cleanup work directories.

        Implements the state machine from §5:
        1. Write state=closing with fsync before I/O
        2. Move artifacts to archive/ and cleanup work dirs
        3. Write state=closed with fsync after I/O succeeds

        If I/O fails, state remains 'closing' for cron reconciliation.
        """
        session = self.get_session(session_id)

        # Step 1: Write state=closing before any I/O
        session.state = "closing"
        session.closed_at = utc_now()
        self.save_session(session)

        # Step 2: Move artifacts to archive and cleanup work dirs
        archive_root = self.root / "archive" / "sessions" / session_id
        archive_root.mkdir(parents=True, exist_ok=True)
        session_dir = self.session_dir(session_id)

        try:
            # Move artifacts directory to archive
            artifacts_src = session_dir / "artifacts"
            artifacts_dst = archive_root / "artifacts"
            if artifacts_src.exists():
                if artifacts_dst.exists():
                    shutil.rmtree(artifacts_dst)
                shutil.move(str(artifacts_src), str(artifacts_dst))

            # Remove temporary work directories
            for subdir in ("work", "canonical", "aligned", "uploads"):
                subdir_path = session_dir / subdir
                if subdir_path.exists():
                    shutil.rmtree(subdir_path)

            # Step 3: Write state=closed with fsync
            session.state = "closed"
            session.archive_dir = str(archive_root)
            self.save_session(session)

            return session
        except Exception as exc:
            # If I/O fails, leave state as 'closing' for cron to retry
            session.errors.append({
                "error_type": "close_session_io_failure",
                "message": str(exc),
                "timestamp": utc_now(),
            })
            self.save_session(session)
            raise

    @staticmethod
    def sha256(path: str | Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
