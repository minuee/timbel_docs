"""Job queue and worker for POST /v1/merge.

Participant recordings are downloaded from presigned URLs, normalized to the
16 kHz mono working format, overlaid on one timeline, and pushed back through a
presigned PUT. master-api learns the outcome by polling GET /v1/merge/{jobId}.

See newDocs/MERGE_API_SPEC.md.
"""

from __future__ import annotations

import os
import queue
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import audio
from .merge_store import MergeRecordStore
from .s3_transfer import TransferError, download, upload

ALIGN_NONE = "none"
ALIGN_TIMESTAMP = "timestamp"
ALIGN_MODES = (ALIGN_NONE, ALIGN_TIMESTAMP)

OUTPUT_FORMATS = ("flac", "wav")

STATUS_WAITING = "WAITING"
STATUS_RUNNING = "RUNNING"
STATUS_DONE = "DONE"
STATUS_ERROR = "ERROR"

STAGE_DOWNLOADING = "DOWNLOADING"
STAGE_NORMALIZING = "NORMALIZING"
STAGE_MIXING = "MIXING"
STAGE_UPLOADING = "UPLOADING"

# Progress ceiling per stage; within a stage we interpolate by files completed.
_STAGE_SPAN = {
    STAGE_DOWNLOADING: (0, 40),
    STAGE_NORMALIZING: (40, 60),
    STAGE_MIXING: (60, 85),
    STAGE_UPLOADING: (85, 99),
}

# Polling hints handed back to master-api so it need not hard-code an interval.
_RETRY_AFTER_MS = {
    STATUS_WAITING: 10_000,
    STAGE_UPLOADING: 2_000,
    "default": 5_000,
}

WORKING_SAMPLE_RATE = 16_000


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


#: Where a job's sources come from. "upload" is the Postman/Swagger test path:
#: files arrive in the request body and the result is kept for download instead
#: of being pushed to storage. Everything between those ends is shared.
SOURCE_PRESIGNED = "presigned"
SOURCE_UPLOAD = "upload"

MAX_FILES = _env_int("MERGE_MAX_FILES", 5)
MAX_FILE_BYTES = _env_int("MERGE_MAX_FILE_BYTES", 2 * 1024 * 1024 * 1024)
#: Upload-path bodies are buffered in memory, so this stays well below the
#: presigned limit.
UPLOAD_MAX_BYTES = _env_int("MERGE_UPLOAD_MAX_BYTES", 512 * 1024 * 1024)
WORKERS = _env_int("MERGE_WORKERS", 3)
JOB_TIMEOUT_SEC = _env_int("MERGE_JOB_TIMEOUT_SEC", 30 * 60)
MAX_OFFSET_MS = _env_int("MERGE_MAX_OFFSET_MS", 60_000)
JOB_TTL_SEC = _env_int("MERGE_JOB_TTL_SEC", 24 * 60 * 60)
#: How long the SQLite history is kept. Independent of JOB_TTL_SEC, which
#: only bounds how many jobs stay cached in memory -- a status query for an
#: older job falls back to the database.
RECORD_TTL_DAYS = _env_int("MERGE_RECORD_TTL_DAYS", 90)


#: Raised against a job that cannot be resumed after a restart because its
#: uploaded source files are gone.
ERROR_SOURCES_GONE = "E5002"


class MergeValidationError(ValueError):
    """Request body rejected before the job is queued (E40xx)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_started_at(raw: object, participant_id: str) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise MergeValidationError(
            "E4005", f"startedAt is required for participantId={participant_id} when align=timestamp"
        )
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MergeValidationError(
            "E4006", f"startedAt is not a valid ISO8601 timestamp for participantId={participant_id}"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def request_to_json(request: dict) -> dict:
    """Make a validated request JSON-safe (startedAt is a datetime)."""
    payload = dict(request)
    payload["files"] = [
        {**entry, "startedAt": _iso(entry.get("startedAt"))} for entry in request["files"]
    ]
    return payload


def request_from_json(payload: dict) -> dict:
    """Inverse of request_to_json, used when reloading a row from SQLite."""
    request = dict(payload)
    files = []
    for entry in payload["files"]:
        restored = dict(entry)
        raw = restored.get("startedAt")
        restored["startedAt"] = (
            _parse_started_at(raw, restored.get("participantId", "?")) if raw else None
        )
        files.append(restored)
    request["files"] = files
    return request


def validate_merge_payload(payload: dict) -> dict:
    """Normalize and validate a POST /v1/merge body.

    Raises MergeValidationError with the spec error code on the first problem.
    """
    if not isinstance(payload, dict):
        raise MergeValidationError("E4001", "request body must be a JSON object")

    room_no = payload.get("roomNo")
    if not isinstance(room_no, str) or not room_no.strip():
        raise MergeValidationError("E4001", "roomNo is required")

    raw_files = payload.get("files")
    if raw_files is None:
        raise MergeValidationError("E4001", "files is required")
    if not isinstance(raw_files, list):
        raise MergeValidationError("E4001", "files must be an array")
    if len(raw_files) == 0:
        raise MergeValidationError("E4002", "files must contain at least 1 entry")
    if len(raw_files) > MAX_FILES:
        raise MergeValidationError("E4003", f"files must contain at most {MAX_FILES} entries")

    raw_output = payload.get("output")
    if not isinstance(raw_output, dict):
        raise MergeValidationError("E4001", "output is required")
    put_url = raw_output.get("putUrl")
    if not isinstance(put_url, str) or not put_url.strip():
        raise MergeValidationError("E4001", "output.putUrl is required")
    originalname = raw_output.get("originalname")
    if not isinstance(originalname, str) or not originalname.strip():
        raise MergeValidationError("E4001", "output.originalname is required")
    # The value travels as an HTTP header, which is latin-1 only, and it has to
    # match master-api's PUT signature byte for byte -- so we reject anything we
    # would otherwise have to reshape. master-api already stores this
    # percent-encoded (`encodeURIComponent` in drive.util.js createPutParams).
    try:
        originalname.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise MergeValidationError(
            "E4007",
            "output.originalname must be percent-encoded ASCII "
            "(use encodeURIComponent, matching the value signed into putUrl)",
        ) from exc
    output_format = raw_output.get("format", "flac")
    if output_format not in OUTPUT_FORMATS:
        raise MergeValidationError("E4001", f"output.format must be one of {', '.join(OUTPUT_FORMATS)}")

    raw_options = payload.get("options") or {}
    if not isinstance(raw_options, dict):
        raise MergeValidationError("E4001", "options must be an object")
    align = raw_options.get("align", ALIGN_NONE)
    if align not in ALIGN_MODES:
        raise MergeValidationError("E4001", f"options.align must be one of {', '.join(ALIGN_MODES)}")

    files: list[dict] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw_files):
        if not isinstance(entry, dict):
            raise MergeValidationError("E4001", f"files[{index}] must be an object")
        participant_id = entry.get("participantId")
        if not isinstance(participant_id, str) or not participant_id.strip():
            raise MergeValidationError("E4001", f"files[{index}].participantId is required")
        if participant_id in seen:
            raise MergeValidationError("E4004", f"duplicate participantId: {participant_id}")
        seen.add(participant_id)

        get_url = entry.get("getUrl")
        if not isinstance(get_url, str) or not get_url.strip():
            raise MergeValidationError("E4001", f"files[{index}].getUrl is required")

        normalized = {
            "participantId": participant_id,
            "getUrl": get_url,
            "fileName": entry.get("fileName"),
            "startedAt": None,
        }
        if align == ALIGN_TIMESTAMP:
            normalized["startedAt"] = _parse_started_at(entry.get("startedAt"), participant_id)
        files.append(normalized)

    return {
        "roomNo": room_no,
        "files": files,
        "output": {
            "putUrl": put_url,
            "originalname": originalname,
            "format": output_format,
        },
        "options": {"align": align},
        "source": SOURCE_PRESIGNED,
    }


def validate_upload_request(
    uploads: list[tuple[str, bytes]],
    *,
    room_no: str | None = None,
    align: str = ALIGN_NONE,
    started_at_raw: str | None = None,
    output_format: str = "flac",
) -> dict:
    """Validate the multipart test path (POST /v1/merge/upload).

    Mirrors validate_merge_payload's rules so the two entry points cannot
    drift apart, minus the presigned-URL fields.
    """
    if not uploads:
        raise MergeValidationError("E4002", "at least 1 file is required")
    if len(uploads) > MAX_FILES:
        raise MergeValidationError("E4003", f"at most {MAX_FILES} files are allowed")
    if output_format not in OUTPUT_FORMATS:
        raise MergeValidationError("E4001", f"format must be one of {', '.join(OUTPUT_FORMATS)}")
    if align not in ALIGN_MODES:
        raise MergeValidationError("E4001", f"align must be one of {', '.join(ALIGN_MODES)}")

    total = sum(len(payload) for _, payload in uploads)
    if total > UPLOAD_MAX_BYTES:
        raise MergeValidationError(
            "E4003", f"uploaded bytes exceed the {UPLOAD_MAX_BYTES} byte limit for this path"
        )

    started_values: list[str] = []
    if align == ALIGN_TIMESTAMP:
        if not started_at_raw or not started_at_raw.strip():
            raise MergeValidationError("E4005", "startedAt is required when align=timestamp")
        started_values = [item.strip() for item in started_at_raw.split(",") if item.strip()]
        if len(started_values) != len(uploads):
            raise MergeValidationError(
                "E4005",
                f"startedAt must list {len(uploads)} timestamps (one per file, in upload order)",
            )

    files: list[dict] = []
    for index, (filename, _payload) in enumerate(uploads):
        participant_id = f"f{index + 1}"
        files.append(
            {
                "participantId": participant_id,
                "getUrl": None,
                "fileName": filename or f"upload_{index + 1}",
                "startedAt": (
                    _parse_started_at(started_values[index], participant_id)
                    if align == ALIGN_TIMESTAMP
                    else None
                ),
            }
        )

    return {
        "roomNo": room_no.strip() if isinstance(room_no, str) and room_no.strip() else f"upload-{uuid.uuid4().hex[:8]}",
        "files": files,
        "output": {"putUrl": None, "originalname": None, "format": output_format},
        "options": {"align": align},
        "source": SOURCE_UPLOAD,
    }


def compute_offsets_ms(files: list[dict], *, max_offset_ms: int = MAX_OFFSET_MS) -> tuple[str, list[dict]]:
    """Turn startedAt values into per-track delays relative to the earliest start.

    A track whose computed offset exceeds ``max_offset_ms`` is treated as a bad
    clock rather than a real delay: it falls back to 0 and is flagged, so one
    misconfigured device cannot push everyone else out of alignment.
    """
    reference_entry = min(files, key=lambda item: item["startedAt"])
    reference_started = reference_entry["startedAt"]

    tracks: list[dict] = []
    for entry in files:
        delta_ms = int(round((entry["startedAt"] - reference_started).total_seconds() * 1000))
        fallback = delta_ms > max_offset_ms
        tracks.append(
            {
                "participantId": entry["participantId"],
                "offsetMs": 0 if fallback else max(0, delta_ms),
                "fallback": fallback,
            }
        )
    return reference_entry["participantId"], tracks


def _apply_retry_overrides(request: dict, overrides: dict) -> dict:
    """Merge fresh URLs into a stored request for a retry.

    Only the fields that go stale are replaceable: the presigned URLs. Anything
    else (participants, alignment mode, output name) stays as originally
    accepted, so a retry re-runs the same job rather than quietly becoming a
    different one.
    """
    updated = dict(request)
    updated["files"] = [dict(entry) for entry in request["files"]]
    updated["output"] = dict(request["output"])

    for entry in overrides.get("files") or []:
        if not isinstance(entry, dict):
            raise MergeValidationError("E4001", "files[] entries must be objects")
        participant_id = entry.get("participantId")
        get_url = entry.get("getUrl")
        if not participant_id or not get_url:
            raise MergeValidationError(
                "E4001", "each files[] override needs participantId and getUrl"
            )
        target = next(
            (item for item in updated["files"] if item["participantId"] == participant_id), None
        )
        if target is None:
            raise MergeValidationError(
                "E4001", f"unknown participantId in override: {participant_id}"
            )
        target["getUrl"] = get_url

    output_override = overrides.get("output") or {}
    if not isinstance(output_override, dict):
        raise MergeValidationError("E4001", "output override must be an object")
    if "putUrl" in output_override:
        put_url = output_override["putUrl"]
        if not isinstance(put_url, str) or not put_url.strip():
            raise MergeValidationError("E4001", "output.putUrl override must be a non-empty string")
        updated["output"]["putUrl"] = put_url

    return updated


class MergeJob:
    """Mutable job state. Guarded by MergeJobManager._lock."""

    def __init__(self, job_id: str, request: dict, *, retried_from: str | None = None) -> None:
        self.job_id = job_id
        self.request = request
        self.room_no = request["roomNo"]
        self.source = request.get("source", SOURCE_PRESIGNED)
        self.result_path: Path | None = None
        self.status = STATUS_WAITING
        self.stage: str | None = None
        self.progress = 0
        self.accepted_at = _now()
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.output: dict | None = None
        self.alignment: dict | None = None
        self.timing: dict | None = None
        self.error: dict | None = None
        #: Set when this job was created by POST /v1/merge/{jobId}/retry, so the
        #: 90-day history keeps the lineage instead of overwriting the original.
        self.retried_from = retried_from
        #: Bumped each time a restart re-queued this job. A climbing number is a
        #: sign the server is crash-looping on this input.
        self.requeue_count = 0

    def to_record(self) -> dict:
        """Row shape for MergeRecordStore.save()."""
        return {
            "job_id": self.job_id,
            "room_no": self.room_no,
            "source": self.source,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "request": request_to_json(self.request),
            "output": self.output,
            "alignment": self.alignment,
            "timing": self.timing,
            "error": self.error,
            "result_path": str(self.result_path) if self.result_path else None,
            "retried_from": self.retried_from,
            "requeue_count": self.requeue_count,
            "accepted_at": _iso(self.accepted_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
        }

    @classmethod
    def from_record(cls, record: dict) -> "MergeJob":
        job = cls(
            record["job_id"],
            request_from_json(record["request"]),
            retried_from=record.get("retried_from"),
        )
        job.status = record["status"]
        job.stage = record.get("stage")
        job.progress = record.get("progress", 0)
        job.output = record.get("output")
        job.alignment = record.get("alignment")
        job.timing = record.get("timing")
        job.error = record.get("error")
        job.requeue_count = record.get("requeue_count", 0)
        job.result_path = Path(record["result_path"]) if record.get("result_path") else None
        job.accepted_at = _parse_started_at(record["accepted_at"], job.job_id)
        job.started_at = (
            _parse_started_at(record["started_at"], job.job_id) if record.get("started_at") else None
        )
        job.finished_at = (
            _parse_started_at(record["finished_at"], job.job_id) if record.get("finished_at") else None
        )
        return job

    @property
    def is_active(self) -> bool:
        return self.status in (STATUS_WAITING, STATUS_RUNNING)

    def retry_after_ms(self) -> int | None:
        if not self.is_active:
            return None
        if self.status == STATUS_WAITING:
            return _RETRY_AFTER_MS[STATUS_WAITING]
        return _RETRY_AFTER_MS.get(self.stage, _RETRY_AFTER_MS["default"])

    def accepted_payload(self) -> dict:
        return {
            "jobId": self.job_id,
            "roomNo": self.room_no,
            "status": self.status,
            "fileCount": len(self.request["files"]),
            "acceptedAt": _iso(self.accepted_at),
            "retryAfterMs": self.retry_after_ms(),
        }

    def status_payload(self) -> dict:
        payload = {
            "jobId": self.job_id,
            "roomNo": self.room_no,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "acceptedAt": _iso(self.accepted_at),
            "startedAt": _iso(self.started_at),
            "finishedAt": _iso(self.finished_at),
        }
        retry_after = self.retry_after_ms()
        if retry_after is not None:
            payload["retryAfterMs"] = retry_after
        if self.output is not None:
            payload["output"] = self.output
        if self.alignment is not None:
            payload["alignment"] = self.alignment
        if self.timing is not None:
            payload["timing"] = self.timing
        if self.error is not None:
            payload["error"] = self.error
        if self.source == SOURCE_UPLOAD:
            payload["source"] = SOURCE_UPLOAD
            if self.status == STATUS_DONE:
                payload["downloadUrl"] = f"/v1/merge/{self.job_id}/download"
        if self.retried_from:
            payload["retriedFrom"] = self.retried_from
        if self.requeue_count:
            payload["requeueCount"] = self.requeue_count
        return payload


class MergeJobError(RuntimeError):
    """Failure inside the worker (E41xx), surfaced through the status endpoint."""

    def __init__(self, code: str, message: str, participant_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.participant_id = participant_id


class MergeJobManager:
    """Bounded worker pool over an unbounded queue.

    MERGE_WORKERS caps concurrent merges, not intake: request number N+1 is
    still accepted with 202 and waits its turn (spec section 8).
    """

    def __init__(
        self,
        work_root: str | Path,
        *,
        workers: int = WORKERS,
        job_timeout_sec: int = JOB_TIMEOUT_SEC,
        job_ttl_sec: int = JOB_TTL_SEC,
        max_offset_ms: int = MAX_OFFSET_MS,
        record_ttl_days: int = RECORD_TTL_DAYS,
        db_path: str | Path | None = None,
    ) -> None:
        self.work_root = Path(work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        # Upload-path results outlive their scratch dir so they can be fetched.
        self.results_root = self.work_root.parent / f"{self.work_root.name}_results"
        self.results_root.mkdir(parents=True, exist_ok=True)
        self.job_timeout_sec = job_timeout_sec
        self.job_ttl_sec = job_ttl_sec
        self.max_offset_ms = max_offset_ms
        self.record_ttl_days = record_ttl_days

        self._jobs: dict[str, MergeJob] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._shutdown = threading.Event()

        self.records = MergeRecordStore(
            db_path if db_path is not None else self.work_root.parent / "merge.db"
        )

        self._purge_orphan_dirs()

        self._threads = [
            threading.Thread(target=self._worker_loop, name=f"merge-worker-{index}", daemon=True)
            for index in range(max(1, workers))
        ]
        for thread in self._threads:
            thread.start()

        self._restore_from_records()

    # ----------------------------------------------------------------- restore

    def _restore_from_records(self) -> None:
        """Rebuild state after a restart.

        Finished jobs come back as-is so status polls keep working. Jobs that
        were mid-flight cannot be resumed -- their scratch files are gone -- but
        the stored request is enough to run them again from the top, and the
        presigned URLs are usually still inside their 6-hour window.
        """
        try:
            removed = self.records.purge_older_than(self.record_ttl_days)
            if removed:
                print(f"INFO merge_records_purged count={removed}", flush=True)
            finished = self.records.load_recent_finished()
            unfinished = self.records.load_unfinished()
        except Exception as exc:  # noqa: BLE001 - a broken DB must not block startup
            print(f"WARN merge_record_restore_failed error={exc}", flush=True)
            return

        for record in finished:
            job = MergeJob.from_record(record)
            with self._lock:
                self._jobs[job.job_id] = job

        requeued: list[str] = []
        for record in unfinished:
            job = MergeJob.from_record(record)

            # An upload-path job can only re-run while its source bytes survive.
            if job.source == SOURCE_UPLOAD and not self._upload_sources_present(job):
                job.status = STATUS_ERROR
                job.stage = None
                job.finished_at = _now()
                job.error = {
                    "code": ERROR_SOURCES_GONE,
                    "message": "server restarted and the uploaded source files are no longer on disk",
                }
                with self._lock:
                    self._jobs[job.job_id] = job
                self._persist(job.to_record())
                continue

            job.status = STATUS_WAITING
            job.stage = None
            job.progress = 0
            job.started_at = None
            job.finished_at = None
            job.error = None
            job.requeue_count += 1
            with self._lock:
                self._jobs[job.job_id] = job
            self._persist(job.to_record())
            self._queue.put(job.job_id)
            requeued.append(job.job_id)

        if requeued:
            print(
                f"INFO merge_requeued_after_restart count={len(requeued)} "
                f"jobs={','.join(requeued[:10])}",
                flush=True,
            )

    @staticmethod
    def _upload_sources_present(job: MergeJob) -> bool:
        paths = [entry.get("sourcePath") for entry in job.request["files"]]
        return all(path and Path(path).is_file() for path in paths)

    # ------------------------------------------------------------------ intake

    def submit(self, payload: dict) -> dict:
        request = validate_merge_payload(payload)
        self._expire_finished()

        with self._lock:
            for job in self._jobs.values():
                if job.is_active and job.room_no == request["roomNo"]:
                    raise MergeValidationError(
                        "E4090", f"a merge job for roomNo={request['roomNo']} is already in progress"
                    )
            job_id = f"mrg_{uuid.uuid4().hex[:20]}"
            job = MergeJob(job_id, request)
            self._jobs[job_id] = job
            payload_out = job.accepted_payload()

        self._persist(job.to_record())
        self._queue.put(job_id)
        return payload_out

    def submit_upload(self, uploads: list[tuple[str, bytes]], **options) -> dict:
        """Accept files posted directly and queue them like any other job."""
        request = validate_upload_request(uploads, **options)
        self._expire_finished()

        job_id = f"mrg_{uuid.uuid4().hex[:20]}"
        # Land the bytes before queueing so the worker only ever sees paths.
        work_dir = self.work_root / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        for index, (_filename, payload) in enumerate(uploads):
            target = work_dir / f"src_{index}"
            target.write_bytes(payload)
            request["files"][index]["sourcePath"] = str(target)

        with self._lock:
            job = MergeJob(job_id, request)
            self._jobs[job_id] = job
            payload_out = job.accepted_payload()

        self._persist(job.to_record())
        self._queue.put(job_id)
        return payload_out

    def retry(self, job_id: str, overrides: dict | None = None) -> dict:
        """Re-run a finished job from its stored request.

        A new jobId is issued and linked back via `retriedFrom`, so the history
        keeps both attempts instead of overwriting the first.

        `overrides` may carry fresh presigned URLs -- the common case, since a
        job usually fails because the old ones expired.
        """
        source = self._lookup(job_id)
        if source is None:
            raise MergeValidationError("E4040", f"jobId not found: {job_id}")
        if source.is_active:
            raise MergeValidationError(
                "E4091", f"jobId {job_id} is still {source.status}; wait for it to finish"
            )
        if source.source == SOURCE_UPLOAD:
            raise MergeValidationError(
                "E4092",
                "retry is only available for the presigned path; re-post the files "
                "to /v1/merge/upload instead",
            )

        request = _apply_retry_overrides(source.request, overrides or {})

        self._expire_finished()
        with self._lock:
            for job in self._jobs.values():
                if job.is_active and job.room_no == request["roomNo"]:
                    raise MergeValidationError(
                        "E4090", f"a merge job for roomNo={request['roomNo']} is already in progress"
                    )
            new_id = f"mrg_{uuid.uuid4().hex[:20]}"
            job = MergeJob(new_id, request, retried_from=job_id)
            self._jobs[new_id] = job
            payload_out = job.accepted_payload()
        payload_out["retriedFrom"] = job_id

        self._persist(job.to_record())
        self._queue.put(new_id)
        return payload_out

    def _lookup(self, job_id: str) -> MergeJob | None:
        """Memory first, then SQLite -- the cache is bounded, the history is not."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            return job
        record = self.records.get(job_id)
        return MergeJob.from_record(record) if record else None

    def get(self, job_id: str) -> dict | None:
        self._expire_finished()
        job = self._lookup(job_id)
        return job.status_payload() if job else None

    def history(self, *, room_no: str | None = None, limit: int = 50) -> list[dict]:
        """Recent records, newest first. Backs the history endpoint."""
        return self.records.recent(room_no=room_no, limit=limit)

    def result_path(self, job_id: str) -> Path | None:
        """Local result file for an upload-path job, once it has finished."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != STATUS_DONE or job.result_path is None:
                return None
            path = job.result_path
        return path if path.is_file() else None

    def shutdown(self, timeout: float = 5.0) -> None:
        self._shutdown.set()
        for _ in self._threads:
            self._queue.put("")
        for thread in self._threads:
            thread.join(timeout=timeout)

    # ------------------------------------------------------------- bookkeeping

    def _expire_finished(self) -> None:
        cutoff = time.time() - self.job_ttl_sec
        with self._lock:
            stale = [
                job_id
                for job_id, job in self._jobs.items()
                if not job.is_active and job.finished_at and job.finished_at.timestamp() < cutoff
            ]
            expired = [self._jobs.pop(job_id) for job_id in stale]
        for job in expired:
            if job.result_path is not None:
                job.result_path.unlink(missing_ok=True)

    def _purge_orphan_dirs(self) -> None:
        """Drop scratch dirs and results a crashed process left behind."""
        cutoff = time.time() - self.job_ttl_sec
        for root in (self.work_root, self.results_root):
            if not root.exists():
                continue
            for entry in root.iterdir():
                try:
                    if entry.stat().st_mtime >= cutoff:
                        continue
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        entry.unlink(missing_ok=True)
                except OSError:
                    continue

    def _persist(self, record: dict) -> None:
        """Best-effort write. The in-memory job is authoritative while it runs;
        the database exists for recovery and history, so a disk hiccup must not
        take down a worker or fail a merge that is otherwise fine."""
        try:
            self.records.save(record)
        except Exception as exc:  # noqa: BLE001
            print(
                f"WARN merge_record_save_failed job={record.get('job_id')} error={exc}",
                flush=True,
            )

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            record = job.to_record()
        # Written outside the lock: SQLite has its own serialization and a slow
        # disk should not stall the other workers' state updates.
        self._persist(record)

    def _set_stage(self, job_id: str, stage: str, *, done: int = 0, total: int = 1) -> None:
        low, high = _STAGE_SPAN[stage]
        ratio = 0.0 if total <= 0 else min(1.0, max(0.0, done / total))
        self._update(job_id, stage=stage, progress=int(low + (high - low) * ratio))

    # ----------------------------------------------------------------- workers

    def _worker_loop(self) -> None:
        while not self._shutdown.is_set():
            job_id = self._queue.get()
            try:
                if not job_id or self._shutdown.is_set():
                    continue
                self._run_job(job_id)
            finally:
                self._queue.task_done()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            request = job.request
        started = _now()
        deadline = time.monotonic() + self.job_timeout_sec
        self._update(job_id, status=STATUS_RUNNING, started_at=started, stage=STAGE_DOWNLOADING, progress=0)

        work_dir = self.work_root / job_id
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            result = self._process(job_id, request, work_dir, deadline)
            self._update(
                job_id,
                status=STATUS_DONE,
                stage=None,
                progress=100,
                finished_at=_now(),
                output=result["output"],
                alignment=result["alignment"],
                timing=result["timing"],
                result_path=result.get("resultPath"),
            )
        except MergeJobError as exc:
            error = {"code": exc.code, "message": exc.message}
            if exc.participant_id:
                error["participantId"] = exc.participant_id
            self._update(job_id, status=STATUS_ERROR, stage=None, finished_at=_now(), error=error)
        except Exception as exc:  # noqa: BLE001 - never leave a job RUNNING forever
            self._update(
                job_id,
                status=STATUS_ERROR,
                stage=None,
                finished_at=_now(),
                error={"code": "E5000", "message": str(exc)},
            )
        finally:
            # Always clear the work dir: success, failure, or timeout.
            shutil.rmtree(work_dir, ignore_errors=True)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MergeJobError("E4106", f"job exceeded the {self.job_timeout_sec}s timeout")
        return remaining

    def _process(self, job_id: str, request: dict, work_dir: Path, deadline: float) -> dict:
        files = request["files"]
        align = request["options"]["align"]
        source_mode = request.get("source", SOURCE_PRESIGNED)

        # ---- DOWNLOADING -------------------------------------------------
        download_started = time.monotonic()
        if source_mode == SOURCE_UPLOAD:
            # Bytes already landed at submit time.
            sources = [Path(entry["sourcePath"]) for entry in files]
        else:
            self._set_stage(job_id, STAGE_DOWNLOADING, done=0, total=len(files))
            sources = self._download_all(job_id, files, work_dir, deadline)
        download_ms = int((time.monotonic() - download_started) * 1000)

        process_started = time.monotonic()

        # ---- NORMALIZING -------------------------------------------------
        self._set_stage(job_id, STAGE_NORMALIZING, done=0, total=len(files))
        normalized: list[Path] = []
        for index, source in enumerate(sources):
            target = work_dir / f"norm_{index}.wav"
            try:
                audio.export_stt_track(
                    source, target, WORKING_SAMPLE_RATE, timeout=self._remaining(deadline)
                )
            except audio.AudioError as exc:
                raise MergeJobError(
                    "E4103", f"decode failed for participantId={files[index]['participantId']}: {exc}",
                    files[index]["participantId"],
                ) from exc
            except Exception as exc:  # subprocess timeout and friends
                raise MergeJobError("E4106", f"normalize timed out: {exc}") from exc
            normalized.append(target)
            self._set_stage(job_id, STAGE_NORMALIZING, done=index + 1, total=len(files))

        # ---- MIXING ------------------------------------------------------
        self._set_stage(job_id, STAGE_MIXING)
        if align == ALIGN_TIMESTAMP:
            reference, tracks = compute_offsets_ms(files, max_offset_ms=self.max_offset_ms)
            alignment = {"mode": ALIGN_TIMESTAMP, "reference": reference, "tracks": tracks}
            delays = [track["offsetMs"] for track in tracks]
        else:
            alignment = {"mode": ALIGN_NONE}
            delays = None

        output_format = request["output"]["format"]
        mixed = work_dir / f"merged.{output_format}"
        try:
            audio.mix_tracks(
                [str(path) for path in normalized],
                mixed,
                delays_ms=delays,
                timeout=self._remaining(deadline),
            )
        except audio.AudioError as exc:
            raise MergeJobError("E4104", f"mix failed: {exc}") from exc
        except Exception as exc:
            raise MergeJobError("E4106", f"mix timed out: {exc}") from exc

        metadata = audio.audio_metadata(mixed)
        process_ms = int((time.monotonic() - process_started) * 1000)

        # ---- UPLOADING ---------------------------------------------------
        self._set_stage(job_id, STAGE_UPLOADING)
        upload_started = time.monotonic()
        result_path: Path | None = None
        if source_mode == SOURCE_UPLOAD:
            # Nothing to push: keep the file for GET /v1/merge/{jobId}/download.
            result_path = self.results_root / f"{job_id}.{output_format}"
            shutil.move(str(mixed), result_path)
            size_bytes = result_path.stat().st_size
            originalname = f"{request['roomNo']}_merged.{output_format}"
        else:
            try:
                size_bytes = upload(
                    request["output"]["putUrl"],
                    mixed,
                    originalname=request["output"]["originalname"],
                    content_type=f"audio/{output_format}",
                    timeout=self._remaining(deadline),
                )
            except TransferError as exc:
                raise MergeJobError(exc.code, exc.message) from exc
            originalname = request["output"]["originalname"]
        upload_ms = int((time.monotonic() - upload_started) * 1000)

        return {
            "output": {
                "format": output_format,
                "sampleRate": metadata["sample_rate"],
                "channels": metadata["channels"],
                "durationMs": int(round(metadata["duration_seconds"] * 1000)),
                "sizeBytes": size_bytes,
                "originalname": originalname,
            },
            "alignment": alignment,
            "timing": {
                "downloadMs": download_ms,
                "processMs": process_ms,
                "uploadMs": upload_ms,
                "totalMs": download_ms + process_ms + upload_ms,
            },
            "resultPath": result_path,
        }

    def _download_all(self, job_id: str, files: list[dict], work_dir: Path, deadline: float) -> list[Path]:
        """Fetch every source in parallel. One failure fails the whole job:
        merging a partial set would silently drop a participant's speech.
        """
        targets = [work_dir / f"src_{index}" for index in range(len(files))]
        failures: list[MergeJobError] = []
        completed = {"count": 0}
        guard = threading.Lock()

        def fetch(index: int) -> None:
            entry = files[index]
            try:
                size = download(entry["getUrl"], targets[index], timeout=self._remaining(deadline))
                if size > MAX_FILE_BYTES:
                    raise MergeJobError(
                        "E4101",
                        f"file exceeds {MAX_FILE_BYTES} bytes for participantId={entry['participantId']}",
                        entry["participantId"],
                    )
            except TransferError as exc:
                with guard:
                    failures.append(
                        MergeJobError(
                            exc.code,
                            f"{exc.message} (participantId={entry['participantId']})",
                            entry["participantId"],
                        )
                    )
            except MergeJobError as exc:
                with guard:
                    failures.append(exc)
            else:
                with guard:
                    completed["count"] += 1
                    done = completed["count"]
                self._set_stage(job_id, STAGE_DOWNLOADING, done=done, total=len(files))

        threads = [threading.Thread(target=fetch, args=(index,)) for index in range(len(files))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        if failures:
            raise failures[0]
        return targets
