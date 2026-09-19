from __future__ import annotations

import base64
import hashlib
import hmac
import io
import itertools
import json
import os
import threading
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from .contracts import (
    validate_create_room_payload,
    validate_join_room_payload,
    validate_preflight_payload,
    validate_ready_payload,
    validate_start_room_payload,
    validate_upload_metadata,
)
from .events import summarize_room_readiness
from .merge_job import MergeJobManager, MergeValidationError
from .openapi import document_json, read_asset, swagger_page
from .pipeline import AudioSyncPipeline
from .protocol_models import RecordingEnvelope, classify_baseline
from .rooms import CapturePolicyError, MetadataValidationError, RoomStateError
from .store import SessionStore


def _json_response(start_response, payload: dict, status: HTTPStatus = HTTPStatus.OK):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    start_response(
        f"{status.value} {status.phrase}",
        [("Content-Type", "application/json"), ("Content-Length", str(len(body)))],
    )
    return [body]



def _evidence_payload(session: dict) -> dict:
    return {
        "classification": session.get("classification"),
        "classification_reason": session.get("classification_reason"),
        "failed_rules": session.get("failed_rules", []),
        "degraded_rules": session.get("degraded_rules", []),
        "evidence_ready": session.get("evidence_ready", False),
        "recommended_run_type": session.get("recommended_run_type"),
        "evidence_export_hint": session.get("evidence_export_hint"),
        "evidence_bundle_path": session.get("evidence_bundle_path"),
        "evidence_exported_at": session.get("evidence_exported_at"),
        "evidence_run_type": session.get("evidence_run_type"),
        "artifacts_index_path": session.get("artifacts_index_path"),
    }


def _session_response_payload(session: dict) -> dict:
    payload = dict(session)
    payload["evidence"] = _evidence_payload(session)
    return payload


def _augment_artifact(artifact: dict) -> dict:
    """Add size_bytes and duration_ms to an artifact record.

    size_bytes: on-disk file size from stat()
    duration_ms: from artifact metadata['duration_ms'] if present, else 0 or None
    """
    augmented = dict(artifact)

    # Add size_bytes from file stat
    artifact_path = artifact.get("path")
    if artifact_path and Path(artifact_path).exists():
        try:
            augmented["size_bytes"] = Path(artifact_path).stat().st_size
        except OSError:
            augmented["size_bytes"] = 0
    else:
        augmented["size_bytes"] = 0

    # Add duration_ms from metadata or default
    metadata = artifact.get("metadata", {})
    augmented["duration_ms"] = metadata.get("duration_ms", 0 if artifact.get("kind") == "mixdown" else None)

    return augmented

def _read_json_body(environ) -> dict:  # noqa: ANN001
    length = int(environ.get("CONTENT_LENGTH", "0") or 0)
    raw = environ["wsgi.input"].read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _read_raw_body(environ) -> bytes:  # noqa: ANN001
    length = int(environ.get("CONTENT_LENGTH", "0") or 0)
    return environ["wsgi.input"].read(length)


def _read_multipart_body(environ) -> dict[str, object]:  # noqa: ANN001
    content_type = environ.get("CONTENT_TYPE", "")
    raw = _read_raw_body(environ)
    if not raw:
        return {}
    parser_input = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw
    )
    message = BytesParser(policy=policy.default).parsebytes(parser_input)
    if not message.is_multipart():
        raise ValueError("multipart body expected")

    payload: dict[str, object] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        body = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if name == "metadata":
            payload["metadata"] = json.loads(body.decode("utf-8"))
        elif name == "file":
            payload["file"] = body
            payload["filename"] = filename
    return payload


def _read_multipart_upload(environ) -> tuple[dict[str, str], list[tuple[str, bytes]]]:  # noqa: ANN001
    """Parse a multi-file multipart body into (text fields, [(filename, bytes)]).

    The existing _read_multipart_body handles the single-file recording upload;
    the merge test path needs several files under one field name.
    """
    content_type = environ.get("CONTENT_TYPE", "")
    raw = _read_raw_body(environ)
    if not raw:
        return {}, []
    parser_input = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw
    )
    message = BytesParser(policy=policy.default).parsebytes(parser_input)
    if not message.is_multipart():
        raise ValueError("multipart body expected")

    fields: dict[str, str] = {}
    files: list[tuple[str, bytes]] = []
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        body = part.get_payload(decode=True) or b""
        if filename:
            files.append((filename, body))
        else:
            fields[name] = body.decode("utf-8", errors="replace").strip()
    return fields, files


def _require_fields(payload: dict, fields: list[str]) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise KeyError(", ".join(missing))


#: Swagger UI and the OpenAPI document sit behind HTTP Basic auth. The merge
#: endpoints themselves stay open -- they are reached only from inside the
#: docker network, while /docs is the one surface a person opens in a browser.
#: The default is a placeholder, not a secret: set SWAGGER_PASSWORD in
#: .env.recog (which is gitignored) on each deployment. An empty value
#: turns the prompt off entirely.
DOCS_AUTH_REALM = "recog API docs"


def _docs_credentials() -> tuple[str, str]:
    return (
        os.environ.get("SWAGGER_USER", "admin"),
        os.environ.get("SWAGGER_PASSWORD", "change-me"),
    )


def _docs_authorized(environ) -> bool:  # noqa: ANN001
    expected_user, expected_password = _docs_credentials()
    if not expected_password:
        return True

    header = environ.get("HTTP_AUTHORIZATION", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False

    user, separator, password = decoded.partition(":")
    if not separator:
        return False
    # compare_digest on both halves so a wrong username costs the same as a
    # wrong password.
    user_ok = hmac.compare_digest(user, expected_user)
    password_ok = hmac.compare_digest(password, expected_password)
    return user_ok and password_ok


def _docs_unauthorized(start_response):  # noqa: ANN001
    body = json.dumps({"error": "authentication required"}).encode("utf-8")
    start_response(
        f"{HTTPStatus.UNAUTHORIZED.value} {HTTPStatus.UNAUTHORIZED.phrase}",
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("WWW-Authenticate", f'Basic realm="{DOCS_AUTH_REALM}"'),
        ],
    )
    return [body]


def _asset_response(start_response, body: bytes, content_type: str):  # noqa: ANN001
    """Serve a static doc asset. Cached briefly so the UI is not re-fetched
    on every reload, but stays short enough for redeploys to take effect."""
    start_response(
        f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "public, max-age=300"),
        ],
    )
    return [body]


def _merge_error(start_response, code: str, message: str, status: HTTPStatus):  # noqa: ANN001
    return _json_response(start_response, {"error": {"code": code, "message": message}}, status)


#: /v1/merge validation codes that are not plain 400s.
_MERGE_ERROR_STATUS = {
    "E4040": HTTPStatus.NOT_FOUND,
    "E4090": HTTPStatus.CONFLICT,
    "E4091": HTTPStatus.CONFLICT,
    "E4092": HTTPStatus.CONFLICT,
}


# Module-level counter for proxy requests (thread-safe)
_proxy_requests_count = 0
_proxy_counter_lock = threading.Lock()


class RecogApplication:
    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self.pipeline = AudioSyncPipeline(store)
        # /v1/merge runs independently of the /rooms and /sessions paths and
        # keeps its scratch space beside the session data.
        self.merge_jobs = MergeJobManager(Path(store.root) / "merge")

    def __call__(self, environ, start_response):  # noqa: ANN001
        global _proxy_requests_count

        method = environ["REQUEST_METHOD"].upper()
        path = environ.get("PATH_INFO", "")

        # P1-5: X-Forwarded-For detection and logging
        if "HTTP_X_FORWARDED_FOR" in environ:
            xff_value = environ["HTTP_X_FORWARDED_FOR"]
            # Log WARN and increment counter
            with _proxy_counter_lock:
                _proxy_requests_count += 1
            print(f"WARN proxy_detected xff={xff_value} path={path}", flush=True)

        try:
            if method == "GET" and path == "/health":
                return _json_response(
                    start_response,
                    {"status": "ok", "service": "recog"},
                    HTTPStatus.OK,
                )

            if method == "GET" and path == "/metrics":
                # P1-5: Expose proxy request counter as Prometheus text metric
                with _proxy_counter_lock:
                    counter_value = _proxy_requests_count
                body = f"recog_proxy_requests_total {counter_value}\n".encode("utf-8")
                start_response(
                    f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
                    [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))],
                )
                return [body]

            # ---- API docs --------------------------------------------------
            # Swagger UI assets are vendored under static/ so the page works
            # with no network -- the deploy target is air-gapped.
            if method == "GET" and (path in ("/docs", "/docs/") or path.startswith("/docs/") or path == "/openapi.json"):
                if not _docs_authorized(environ):
                    return _docs_unauthorized(start_response)

            if method == "GET" and path in ("/docs", "/docs/"):
                return _asset_response(start_response, swagger_page(), "text/html; charset=utf-8")

            if method == "GET" and path.startswith("/docs/"):
                asset = read_asset(path[len("/docs/") :])
                if asset is None:
                    return _json_response(start_response, {"error": "not found"}, HTTPStatus.NOT_FOUND)
                body, content_type = asset
                return _asset_response(start_response, body, content_type)

            if method == "GET" and path == "/openapi.json":
                return _asset_response(
                    start_response, document_json(), "application/json; charset=utf-8"
                )

            # ---- /v1/merge -------------------------------------------------
            # Audio merge for master-api: presigned download -> overlay -> presigned
            # upload, tracked by job id. No auth (same docker network).
            if method == "POST" and path == "/v1/merge":
                payload = _read_json_body(environ)
                try:
                    accepted = self.merge_jobs.submit(payload)
                except MergeValidationError as exc:
                    status = _MERGE_ERROR_STATUS.get(exc.code, HTTPStatus.BAD_REQUEST)
                    return _merge_error(start_response, exc.code, exc.message, status)
                return _json_response(start_response, accepted, HTTPStatus.ACCEPTED)

            # Test path: files posted directly, no storage involved. Runs the
            # same queue, worker and mixing code as the presigned path.
            if method == "POST" and path == "/v1/merge/upload":
                fields, uploads = _read_multipart_upload(environ)
                try:
                    accepted = self.merge_jobs.submit_upload(
                        uploads,
                        room_no=fields.get("roomNo"),
                        align=fields.get("align") or "none",
                        started_at_raw=fields.get("startedAt"),
                        output_format=fields.get("format") or "flac",
                    )
                except MergeValidationError as exc:
                    status = _MERGE_ERROR_STATUS.get(exc.code, HTTPStatus.BAD_REQUEST)
                    return _merge_error(start_response, exc.code, exc.message, status)
                return _json_response(start_response, accepted, HTTPStatus.ACCEPTED)

            # Re-run a finished job from its stored request. Fresh presigned URLs
            # can be supplied in the body; everything else is reused verbatim.
            if method == "POST" and path.startswith("/v1/merge/") and path.endswith("/retry"):
                job_id = path[len("/v1/merge/") : -len("/retry")].strip("/")
                if not job_id or "/" in job_id:
                    return _merge_error(
                        start_response, "E4040", "jobId not found", HTTPStatus.NOT_FOUND
                    )
                overrides = _read_json_body(environ)
                try:
                    accepted = self.merge_jobs.retry(job_id, overrides)
                except MergeValidationError as exc:
                    status = _MERGE_ERROR_STATUS.get(exc.code, HTTPStatus.BAD_REQUEST)
                    return _merge_error(start_response, exc.code, exc.message, status)
                return _json_response(start_response, accepted, HTTPStatus.ACCEPTED)

            if method == "GET" and path == "/v1/merge":
                query = parse_qs(environ.get("QUERY_STRING", ""))
                room_no = query.get("roomNo", [None])[0]
                try:
                    limit = int(query.get("limit", ["50"])[0])
                except ValueError:
                    limit = 50
                records = self.merge_jobs.history(room_no=room_no, limit=limit)
                return _json_response(
                    start_response, {"count": len(records), "jobs": records}
                )

            if method in ("GET", "HEAD") and path.startswith("/v1/merge/") and path.endswith("/download"):
                job_id = path[len("/v1/merge/") : -len("/download")].strip("/")
                result = self.merge_jobs.result_path(job_id) if job_id and "/" not in job_id else None
                if result is None:
                    return _merge_error(
                        start_response,
                        "E4040",
                        "no downloadable result for this jobId "
                        "(not finished, failed, or uploaded to storage instead)",
                        HTTPStatus.NOT_FOUND,
                    )
                return self._serve_file(environ, start_response, str(result), result.name)

            if method == "GET" and path.startswith("/v1/merge/"):
                job_id = path[len("/v1/merge/") :].strip("/")
                if not job_id or "/" in job_id:
                    return _merge_error(
                        start_response, "E4040", "jobId not found", HTTPStatus.NOT_FOUND
                    )
                job_payload = self.merge_jobs.get(job_id)
                if job_payload is None:
                    return _merge_error(
                        start_response, "E4040", "jobId not found", HTTPStatus.NOT_FOUND
                    )
                # A failed job still answers 200: the lookup itself succeeded.
                # master-api decides on the `status` field, not the HTTP code.
                return _json_response(start_response, job_payload)

            if method == "POST" and path == "/rooms":
                payload = _read_json_body(environ)
                validate_create_room_payload(payload)
                room = self.store.create_room(
                    host_participant_id=payload["host_participant_id"],
                    expected_participant_count=payload.get("expected_participant_count", 5),
                    minimum_ready_participants=payload.get("minimum_ready_participants", 1),
                    mode=payload.get("mode", "research"),
                    protocol_version=payload.get("protocol_version", "recording-protocol/v1"),
                    start_strategy=payload.get("start_strategy", "server_authoritative_beep"),
                    anchor_policy=payload.get("anchor_policy", "beep_required"),
                    evidence_auto_export=payload.get("evidence_auto_export", False),
                    evidence_default_run_type=payload.get("evidence_default_run_type"),
                )
                return _json_response(
                    start_response,
                    {
                        "room_id": room.room_id,
                        "session_id": room.session_id,
                        "join_code": room.join_code,
                        "host_participant_id": room.host_participant_id,
                        "state": room.state,
                        "mode": room.mode,
                        "protocol_version": room.protocol_version,
                        "start_strategy": room.start_strategy,
                        "anchor_policy": room.anchor_policy,
                        "minimum_ready_participants": room.minimum_ready_participants,
                        "evidence_auto_export": room.evidence_auto_export,
                        "evidence_default_run_type": room.evidence_default_run_type,
                    },
                    HTTPStatus.CREATED,
                )

            if path.startswith("/rooms/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) >= 2:
                    room_id = parts[1]
                else:
                    raise KeyError("missing room id")
                if method == "POST" and len(parts) == 3 and parts[2] == "join":
                    payload = _read_json_body(environ)
                    validate_join_room_payload(payload)
                    participant = self.store.join_room(room_id, **payload)
                    room = self.store.get_room(room_id)
                    return _json_response(
                        start_response,
                        {
                            "room_id": room_id,
                            "participant_id": participant.participant_id,
                            "participant_state": participant.state,
                            "room_state": room.state,
                        },
                    )
                if method == "POST" and len(parts) == 3 and parts[2] == "preflight":
                    payload = _read_json_body(environ)
                    room = self.store.get_room(room_id)
                    warnings = validate_preflight_payload(payload, mode=room.mode)
                    participant = self.store.record_preflight(
                        room_id,
                        payload["participant_id"],
                        recorder_engine=payload["recorder_engine"],
                        mic_route=payload["mic_route"],
                        audio_processing_flags=payload["audio_processing_flags"],
                        permission_state=payload["permission_state"],
                        time_sync=payload["time_sync"],
                        warnings=warnings,
                    )
                    return _json_response(
                        start_response,
                        {
                            "room_id": room_id,
                            "participant_id": participant.participant_id,
                            "participant_state": participant.state,
                            "room_state": self.store.get_room(room_id).state,
                            "research_mode_blockers": [],
                            "research_mode_warnings": warnings,
                        },
                    )
                if method == "POST" and len(parts) == 3 and parts[2] == "ready":
                    payload = _read_json_body(environ)
                    room = self.store.get_room(room_id)
                    validate_ready_payload(payload, mode=room.mode)
                    participant = self.store.update_participant(
                        room_id,
                        payload["participant_id"],
                        recorder_engine=payload["recorder_engine"],
                        mic_route=payload["mic_route"],
                        audio_processing_flags=payload["audio_processing_flags"],
                    )
                    participant = self.store.mark_ready(room_id, participant.participant_id)
                    room = self.store.get_room(room_id)
                    return _json_response(
                        start_response,
                        {
                            "room_id": room_id,
                            "participant_id": participant.participant_id,
                            "participant_state": participant.state,
                            "room_state": room.state,
                        },
                    )
                if method == "POST" and len(parts) == 3 and parts[2] == "start":
                    payload = _read_json_body(environ)
                    room = self.store.get_room(room_id)
                    validate_start_room_payload(payload, mode=room.mode)
                    room = self.store.start_room(
                        room_id,
                        participant_id=payload["participant_id"],
                        anchor_type=payload["anchor_type"],
                    )
                    return _json_response(
                        start_response,
                        {
                            "room_id": room.room_id,
                            "session_id": room.session_id,
                            "start_command_id": room.start_command_id,
                            "server_start_issued_at": room.server_start_issued_at,
                            "protocol_version": room.protocol_version,
                            "start_strategy": room.start_strategy,
                            "anchor_policy": room.anchor_policy,
                            "anchor_type": room.anchor_type,
                            "room_state": room.state,
                        },
                    )
                if method == "POST" and len(parts) == 3 and parts[2] == "stop":
                    payload = _read_json_body(environ)
                    room = self.store.stop_room(
                        room_id,
                        participant_id=payload["participant_id"],
                    )
                    return _json_response(
                        start_response,
                        {
                            "room_id": room.room_id,
                            "session_id": room.session_id,
                            "room_state": room.state,
                        },
                    )
                if method == "GET" and len(parts) == 2:
                    room = self.store.get_room(room_id)
                    readiness = summarize_room_readiness(room)
                    return _json_response(
                        start_response,
                        {
                            "room_id": room.room_id,
                            "session_id": room.session_id,
                            "host_participant_id": room.host_participant_id,
                            "state": room.state,
                            "mode": room.mode,
                            "protocol_version": room.protocol_version,
                            "start_strategy": room.start_strategy,
                            "anchor_policy": room.anchor_policy,
                            "join_code": room.join_code,
                            "participants": [entry.to_dict() for entry in room.participants],
                            "events": [entry.to_dict() for entry in room.events],
                            "readiness": readiness,
                        },
                    )

            if method == "POST" and path == "/sessions":
                session = self.store.create_session()
                return _json_response(start_response, session.to_dict(), HTTPStatus.CREATED)

            if path.startswith("/sessions/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) >= 2:
                    session_id = parts[1]
                else:
                    raise KeyError("missing session id")
                if method == "GET" and len(parts) == 2:
                    session_payload = self.store.get_session(session_id).to_dict()
                    return _json_response(start_response, _session_response_payload(session_payload))
                if method == "POST" and len(parts) == 3 and parts[2] == "events":
                    payload = _read_json_body(environ)
                    _require_fields(payload, ["event"])
                    event = self.store.append_session_event(
                        session_id,
                        event_type=payload["event"],
                        participant_id=payload.get("participant_id"),
                        payload=payload.get("payload"),
                    )
                    return _json_response(start_response, event, HTTPStatus.CREATED)
                if method == "POST" and len(parts) == 3 and parts[2] == "process":
                    payload = _read_json_body(environ)
                    session = self.store.get_session(session_id)
                    if session.room_id:
                        room = self.store.get_room(session.room_id)
                        if room.state not in {"stopped", "closed"}:
                            return _json_response(
                                start_response,
                                {"error": "session_not_ready_for_processing"},
                                HTTPStatus.CONFLICT,
                            )
                    if not self.store.is_session_processing_ready(session_id):
                        return _json_response(
                            start_response,
                            {"error": "session_not_ready_for_processing"},
                            HTTPStatus.CONFLICT,
                        )
                    effective_export_root = payload.get("evidence_export_root")
                    effective_run_type = payload.get("evidence_run_type")
                    if session.evidence_auto_export and effective_export_root is None:
                        effective_export_root = str(Path(self.store.root) / "evidence-auto")
                    if effective_run_type is None:
                        effective_run_type = session.evidence_default_run_type
                    result = self.pipeline.process_session(
                        session_id,
                        evidence_export_root=effective_export_root,
                        evidence_run_type=effective_run_type,
                        evidence_reviewer=payload.get("evidence_reviewer", "backend_auto_export"),
                    )
                    return _json_response(start_response, _session_response_payload(result), HTTPStatus.ACCEPTED)
                if method == "POST" and len(parts) == 3 and parts[2] == "recordings":
                    content_type = (environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
                    if content_type == "multipart/form-data":
                        multipart = _read_multipart_body(environ)
                        metadata = multipart.get("metadata")
                        binary = multipart.get("file")
                        if not isinstance(metadata, dict):
                            return _json_response(
                                start_response,
                                {"error": "multipart metadata part is required"},
                                HTTPStatus.BAD_REQUEST,
                            )
                        if not isinstance(binary, (bytes, bytearray)):
                            return _json_response(
                                start_response,
                                {"error": "multipart file part is required"},
                                HTTPStatus.BAD_REQUEST,
                            )
                        session = self.store.get_session(session_id)
                        if "schema_version" in metadata:
                            envelope = RecordingEnvelope.from_dict(metadata)
                            baseline_valid, violations, classification = classify_baseline(envelope)
                            participant_id = envelope.participant.participant_id
                            filename = str(multipart.get("filename") or envelope.recording.filename)
                            room_id = envelope.session.room_id
                            device_id = envelope.device.device_id
                            format_name = envelope.recording.container
                            container = envelope.recording.container
                            codec = envelope.recording.codec
                            sample_rate_hz = envelope.audio.sample_rate
                            channels = envelope.audio.channels
                            duration_seconds = envelope.recording.duration_seconds
                            mic_route = envelope.device.mic_route
                            audio_processing_flags = envelope.device.audio_processing_flags
                            start_command_id = None
                            server_start_issued_at = envelope.timing.start_command_issued_at
                            start_command_received_at = envelope.timing.start_command_received_at
                            client_record_invoked_at = None
                            recording_started_at = envelope.timing.recording_started_at
                            local_monotonic_start_tick = envelope.timing.local_monotonic_started_at_ms
                            anchor_type = envelope.anchor.anchor_type
                            anchor_expected_at = envelope.anchor.anchor_expected_at
                            pause_resume_events = envelope.recording.pause_resume_events
                            raw_metadata = envelope.to_dict()
                        else:
                            validate_upload_metadata(metadata, mode=session.mode)
                            baseline_valid = True
                            violations = []
                            classification = "baseline_valid"
                            participant_id = metadata["participant_id"]
                            filename = str(multipart.get("filename") or metadata["filename"])
                            room_id = metadata.get("room_id")
                            device_id = metadata.get("device_id", "")
                            format_name = metadata.get("container", "unknown")
                            container = metadata.get("container", "unknown")
                            codec = metadata.get("codec", "unknown")
                            sample_rate_hz = metadata.get("sample_rate_hz")
                            channels = metadata.get("channels")
                            duration_seconds = metadata.get("duration_seconds")
                            mic_route = metadata.get("mic_route", "unknown")
                            audio_processing_flags = metadata.get("audio_processing_flags", {})
                            start_command_id = metadata.get("start_command_id")
                            server_start_issued_at = metadata.get("server_start_issued_at")
                            start_command_received_at = metadata.get("start_command_received_at")
                            client_record_invoked_at = metadata.get("client_record_invoked_at")
                            recording_started_at = metadata.get("recording_started_at")
                            local_monotonic_start_tick = metadata.get("local_monotonic_start_tick")
                            anchor_type = metadata.get("anchor_type")
                            anchor_expected_at = metadata.get("anchor_expected_at")
                            pause_resume_events = metadata.get("pause_resume_events", [])
                            raw_metadata = metadata

                        file_record = self.store.add_file(
                            session_id,
                            participant_id=participant_id,
                            filename=filename,
                            payload=bytes(binary),
                        )
                        file_record = self.store.update_file(
                            session_id,
                            file_record.file_id,
                            room_id=room_id,
                            device_id=device_id,
                            format_name=format_name or file_record.format_name,
                            container=container or file_record.container,
                            codec=codec,
                            sample_rate_hz=sample_rate_hz,
                            channels=channels,
                            duration_seconds=duration_seconds,
                            filesize_bytes=len(binary),
                            classification=classification,
                            baseline_valid=baseline_valid,
                            violations=violations,
                            mic_route=mic_route,
                            audio_processing_flags=audio_processing_flags,
                            start_command_id=start_command_id,
                            server_start_issued_at=server_start_issued_at,
                            start_command_received_at=start_command_received_at,
                            client_record_invoked_at=client_record_invoked_at,
                            recording_started_at=recording_started_at,
                            local_monotonic_start_tick=local_monotonic_start_tick,
                            anchor_type=anchor_type,
                            anchor_expected_at=anchor_expected_at,
                            pause_resume_events=pause_resume_events,
                            metadata=raw_metadata,
                            recording_metadata=raw_metadata,
                        )
                        self.store.append_session_event(
                            session_id,
                            event_type="recording_uploaded",
                            participant_id=participant_id,
                            payload={
                                "file_id": file_record.file_id,
                                "classification": file_record.classification,
                            "classification_reason": session.classification_reason if (session := self.store.get_session(session_id)) else None,
                                "baseline_valid": file_record.baseline_valid,
                            },
                        )
                        return _json_response(start_response, file_record.to_dict(), HTTPStatus.CREATED)

                    payload = _read_json_body(environ)
                    participant = payload.get("participant") or {}
                    recording_event = payload.get("recording_event") or {}
                    audio_file = payload.get("audio_file") or {}
                    _require_fields(participant, ["participant_id"])
                    _require_fields(
                        recording_event,
                        [
                            "recording_started_at",
                            "recording_stopped_at",
                            "mic_route",
                            "audio_processing_flags",
                            "anchor_type",
                        ],
                    )
                    _require_fields(
                        audio_file,
                        [
                            "filename",
                            "container",
                            "codec",
                            "sample_rate_hz",
                            "channels",
                            "duration_seconds",
                        ],
                    )
                    record = self.store.register_recording_metadata(
                        session_id,
                        participant_id=participant["participant_id"],
                        recording_id=recording_event.get("recording_id"),
                        control_metadata=(payload.get("time_sync") or {}) | recording_event,
                        audio_file_metadata=audio_file,
                    )
                    self.store.append_session_event(
                        session_id,
                        event_type="recording_metadata_registered",
                        participant_id=participant["participant_id"],
                        payload={"recording_id": record.recording_id},
                    )
                    return _json_response(start_response, record.to_dict(), HTTPStatus.CREATED)
                if method == "POST" and len(parts) == 5 and parts[2] == "recordings" and parts[4] == "file":
                    recording_id = parts[3]
                    length = int(environ.get("CONTENT_LENGTH", "0") or 0)
                    payload = environ["wsgi.input"].read(length)
                    if not payload:
                        return _json_response(
                            start_response,
                            {"error": "binary payload is required"},
                            HTTPStatus.BAD_REQUEST,
                        )
                    record = self.store.attach_recording_binary(
                        session_id,
                        recording_id,
                        payload=payload,
                        content_type=(environ.get("CONTENT_TYPE") or None),
                    )
                    self.store.append_session_event(
                        session_id,
                        event_type="recording_binary_uploaded",
                        participant_id=record.participant_id,
                        payload={"recording_id": record.recording_id},
                    )
                    return _json_response(start_response, record.to_dict(), HTTPStatus.CREATED)
                if method == "GET" and len(parts) == 3 and parts[2] == "artifacts":
                    session = self.store.get_session(session_id)
                    augmented_artifacts = [_augment_artifact(entry.to_dict()) for entry in session.artifacts]
                    return _json_response(
                        start_response,
                        {"session_id": session_id, "artifacts": augmented_artifacts, "evidence": _evidence_payload(session.to_dict())},
                    )
                if method == "POST" and len(parts) == 3 and parts[2] == "close":
                    payload = _read_json_body(environ)
                    session = self.store.get_session(session_id)
                    join_code = payload.get("join_code")
                    if not join_code:
                        return _json_response(
                            start_response,
                            {"error": "join_code is required"},
                            HTTPStatus.BAD_REQUEST,
                        )
                    if join_code != session.join_code:
                        return _json_response(
                            start_response,
                            {"error": "invalid join_code"},
                            HTTPStatus.FORBIDDEN,
                        )
                    # Idempotency: if already closed, return 200 with existing payload
                    if session.state == "closed":
                        return _json_response(
                            start_response,
                            _session_response_payload(session.to_dict()),
                            HTTPStatus.OK,
                        )
                    try:
                        closed_session = self.store.close_session(session_id)
                        return _json_response(
                            start_response,
                            _session_response_payload(closed_session.to_dict()),
                            HTTPStatus.OK,
                        )
                    except Exception as exc:
                        return _json_response(
                            start_response,
                            {"error": f"close_failed: {str(exc)}"},
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                if method in ("GET", "HEAD") and len(parts) == 4 and parts[2] == "artifacts":
                    kind = parts[3]
                    query = parse_qs(environ.get("QUERY_STRING", ""))
                    token = query.get("token", [None])[0]

                    session = self.store.get_session(session_id)
                    if not token or token != session.join_code:
                        return _json_response(
                            start_response,
                            {"error": "invalid or missing token"},
                            HTTPStatus.FORBIDDEN,
                        )

                    # Map kind to filename
                    kind_to_filename = {
                        "listening_mix": "listening_mix.wav",
                        "aligned_tracks": "aligned_tracks.zip",
                        "manifest": "manifest.json",
                        "manifest_export": "manifest.export.json",
                    }
                    filename = kind_to_filename.get(kind)
                    if not filename:
                        return _json_response(
                            start_response,
                            {"error": "unknown artifact kind"},
                            HTTPStatus.NOT_FOUND,
                        )

                    # Find artifact path (prefer active, fall back to archive)
                    artifact_path = None
                    for artifact in session.artifacts:
                        if artifact.name == filename:
                            artifact_path = artifact.path
                            break

                    if not artifact_path or not Path(artifact_path).exists():
                        # Try archive directory
                        archive_dir_path = Path(session.archive_dir) if session.archive_dir else (self.store.root / "archive" / "sessions" / session_id)
                        archive_path = archive_dir_path / "artifacts" / filename
                        if archive_path.exists():
                            artifact_path = str(archive_path)
                        else:
                            return _json_response(
                                start_response,
                                {"error": "artifact not found"},
                                HTTPStatus.NOT_FOUND,
                            )

                    # Serve the file
                    return self._serve_file(environ, start_response, artifact_path, filename)
                if method == "POST" and len(parts) == 3 and parts[2] == "files":
                    content_type = (environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
                    if content_type == "application/json":
                        payload = _read_json_body(environ)
                        metadata = payload.get("metadata", {})
                        session = self.store.get_session(session_id)
                        validate_upload_metadata(metadata, mode=session.mode)
                        file_bytes = base64.b64decode(payload["contentBase64"])
                        file_record = self.store.add_file(
                            session_id,
                            participant_id=metadata["participant_id"],
                            filename=metadata["filename"],
                            payload=file_bytes,
                        )
                        file_record = self.store.update_file(
                            session_id,
                            file_record.file_id,
                            room_id=metadata.get("room_id"),
                            device_id=metadata.get("device_id", ""),
                            container=metadata.get("container", file_record.container),
                            codec=metadata.get("codec", "unknown"),
                            sample_rate_hz=metadata.get("sample_rate_hz"),
                            channels=metadata.get("channels"),
                            duration_seconds=metadata.get("duration_seconds"),
                            classification="degraded",
                            baseline_valid=False,
                            violations=["control_metadata_missing"],
                            mic_route=metadata.get("mic_route", "unknown"),
                            audio_processing_flags=metadata.get("audio_processing_flags", {}),
                            start_command_id=metadata.get("start_command_id"),
                            server_start_issued_at=metadata.get("server_start_issued_at"),
                            start_command_received_at=metadata.get("start_command_received_at"),
                            client_record_invoked_at=metadata.get("client_record_invoked_at"),
                            recording_started_at=metadata.get("recording_started_at"),
                            local_monotonic_start_tick=metadata.get("local_monotonic_start_tick"),
                            anchor_type=metadata.get("anchor_type"),
                            anchor_expected_at=metadata.get("anchor_expected_at"),
                            pause_resume_events=metadata.get("pause_resume_events", []),
                            metadata=metadata,
                        )
                        self.store.append_session_event(
                            session_id,
                            event_type="legacy_file_uploaded",
                            participant_id=metadata["participant_id"],
                            payload={
                                "file_id": file_record.file_id,
                                "classification": file_record.classification,
                            "classification_reason": session.classification_reason if (session := self.store.get_session(session_id)) else None,
                            },
                        )
                        return _json_response(start_response, file_record.to_dict(), HTTPStatus.CREATED)

                    query = parse_qs(environ.get("QUERY_STRING", ""))
                    participant_id = query.get("participant_id", [None])[0]
                    filename = query.get("filename", [None])[0]
                    if not participant_id or not filename:
                        return _json_response(
                            start_response,
                            {"error": "participant_id and filename are required"},
                            HTTPStatus.BAD_REQUEST,
                        )
                    length = int(environ.get("CONTENT_LENGTH", "0") or 0)
                    payload = environ["wsgi.input"].read(length)
                    file_record = self.store.add_file(
                        session_id, participant_id=participant_id, filename=filename, payload=payload
                    )
                    return _json_response(start_response, file_record.to_dict(), HTTPStatus.CREATED)
            return _json_response(start_response, {"error": "not found"}, HTTPStatus.NOT_FOUND)
        except FileNotFoundError:
            return _json_response(start_response, {"error": "not found"}, HTTPStatus.NOT_FOUND)
        except RoomStateError as exc:
            return _json_response(start_response, {"error": str(exc)}, HTTPStatus.CONFLICT)
        except (CapturePolicyError, MetadataValidationError) as exc:
            return _json_response(start_response, {"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
        except Exception as exc:  # noqa: BLE001
            return _json_response(start_response, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _serve_file(self, environ, start_response, file_path: str, filename: str):  # noqa: ANN001
        """Serve a file with Range request support (206), HEAD, and streaming."""
        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            return _json_response(
                start_response,
                {"error": "file not found"},
                HTTPStatus.NOT_FOUND,
            )

        try:
            file_size = file_path_obj.stat().st_size
        except OSError:
            return _json_response(
                start_response,
                {"error": "cannot stat file"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        # Compute weak ETag from file_size and mtime_ns (memory-bounded)
        try:
            stat = file_path_obj.stat()
            etag = f"W/\"{stat.st_size:x}-{stat.st_mtime_ns:x}\""
        except OSError:
            etag = "unknown"

        # Determine MIME type
        mime_type_map = {
            ".wav": "audio/wav",
            ".zip": "application/zip",
            ".json": "application/json",
        }
        suffix = file_path_obj.suffix.lower()
        mime_type = mime_type_map.get(suffix, "application/octet-stream")

        method = environ["REQUEST_METHOD"].upper()
        range_header = environ.get("HTTP_RANGE", "")

        # Parse Range header
        range_start = None
        range_end = None
        if range_header:
            if not range_header.startswith("bytes="):
                return self._range_not_satisfiable(start_response, file_size)
            range_spec = range_header[6:]
            try:
                if range_spec.startswith("-"):
                    # Suffix range: bytes=-1024
                    suffix_length = int(range_spec[1:])
                    range_start = max(0, file_size - suffix_length)
                    range_end = file_size - 1
                elif "-" in range_spec:
                    parts = range_spec.split("-")
                    if parts[0]:
                        range_start = int(parts[0])
                    if parts[1]:
                        range_end = int(parts[1])
                    else:
                        range_end = file_size - 1
                    # Validate
                    if range_start > range_end:
                        return self._range_not_satisfiable(start_response, file_size)
                    if range_start >= file_size:
                        return self._range_not_satisfiable(start_response, file_size)
                else:
                    return self._range_not_satisfiable(start_response, file_size)
            except (ValueError, IndexError):
                return self._range_not_satisfiable(start_response, file_size)

        # Prepare response headers
        headers = [
            ("Content-Type", mime_type),
            ("Accept-Ranges", "bytes"),
            ("ETag", etag),
        ]

        if range_start is not None and range_end is not None:
            # 206 Partial Content
            content_length = range_end - range_start + 1
            headers.extend([
                ("Content-Range", f"bytes {range_start}-{range_end}/{file_size}"),
                ("Content-Length", str(content_length)),
            ])
            status = HTTPStatus.PARTIAL_CONTENT
        else:
            # 200 OK (full file)
            headers.append(("Content-Length", str(file_size)))
            status = HTTPStatus.OK
            range_start = 0
            range_end = file_size - 1

        if method == "HEAD":
            start_response(f"{status.value} {status.phrase}", headers)
            return []

        start_response(f"{status.value} {status.phrase}", headers)

        # Stream file in 64 KB chunks
        if method == "GET":
            try:
                with open(file_path_obj, "rb") as f:
                    f.seek(range_start)
                    bytes_remaining = range_end - range_start + 1
                    chunk_size = 65536
                    while bytes_remaining > 0:
                        to_read = min(chunk_size, bytes_remaining)
                        chunk = f.read(to_read)
                        if not chunk:
                            break
                        yield chunk
                        bytes_remaining -= len(chunk)
            except OSError:
                pass

    def _range_not_satisfiable(self, start_response, file_size: int):  # noqa: ANN001
        """Return 416 Range Not Satisfiable response."""
        status = HTTPStatus.RANGE_NOT_SATISFIABLE
        headers = [
            ("Content-Range", f"bytes */{file_size}"),
            ("Content-Length", "0"),
        ]
        start_response(f"{status.value} {status.phrase}", headers)
        return []


def _resolve_bind(host_arg: str | None, port_arg: int | None) -> tuple[str, int]:
    """Resolve bind host and port, with env var override support.

    Args:
        host_arg: explicit host argument (None to use env var or default)
        port_arg: explicit port argument (None to use env var or default)

    Returns:
        (resolved_host, resolved_port) tuple
    """
    resolved_host = host_arg
    if resolved_host is None:
        resolved_host = os.environ.get("RECOG_HOST", "127.0.0.1")

    resolved_port = port_arg
    if resolved_port is None:
        port_env = os.environ.get("RECOG_PORT")
        resolved_port = int(port_env) if port_env else 8080

    return resolved_host, resolved_port


def create_app(data_root: str | Path) -> RecogApplication:
    return RecogApplication(SessionStore(data_root))


def serve(data_root: str | Path, host: str | None = None, port: int | None = None) -> None:
    resolved_host, resolved_port = _resolve_bind(host, port)
    app = create_app(data_root)
    with make_server(resolved_host, resolved_port, app) as server:
        print(f"serving audio sync merge service on http://{resolved_host}:{resolved_port}")
        server.serve_forever()
