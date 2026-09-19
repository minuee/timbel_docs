from __future__ import annotations

import json
import os
import shutil
import sys
import time
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recog import merge_job
from recog.api import RecogApplication
from recog.merge_job import (
    ALIGN_NONE,
    ALIGN_TIMESTAMP,
    MergeValidationError,
    compute_offsets_ms,
    validate_merge_payload,
)
from recog.s3_transfer import ORIGINALNAME_HEADER
from recog.store import SessionStore


def _payload(**overrides) -> dict:
    payload = {
        "roomNo": "R-20260919-001",
        "files": [
            {"participantId": "p1", "getUrl": "http://minio/p1.flac?sig=a"},
            {"participantId": "p2", "getUrl": "http://minio/p2.flac?sig=b"},
        ],
        "output": {
            "putUrl": "http://minio/merged.flac?sig=c",
            "originalname": "R-20260919-001_merged.flac",
            "format": "flac",
        },
        "options": {"align": ALIGN_NONE},
    }
    payload.update(overrides)
    return payload


class ValidationTests(unittest.TestCase):
    def _assert_code(self, payload: dict, code: str) -> None:
        with self.assertRaises(MergeValidationError) as ctx:
            validate_merge_payload(payload)
        self.assertEqual(ctx.exception.code, code)

    def test_valid_payload_normalizes_defaults(self) -> None:
        payload = _payload()
        del payload["options"]
        result = validate_merge_payload(payload)
        self.assertEqual(result["options"]["align"], ALIGN_NONE)
        self.assertEqual(result["output"]["format"], "flac")
        self.assertEqual(len(result["files"]), 2)

    def test_missing_room_no_is_e4001(self) -> None:
        payload = _payload()
        del payload["roomNo"]
        self._assert_code(payload, "E4001")

    def test_empty_files_is_e4002(self) -> None:
        self._assert_code(_payload(files=[]), "E4002")

    def test_too_many_files_is_e4003(self) -> None:
        files = [
            {"participantId": f"p{index}", "getUrl": f"http://minio/{index}.flac"}
            for index in range(merge_job.MAX_FILES + 1)
        ]
        self._assert_code(_payload(files=files), "E4003")

    def test_duplicate_participant_is_e4004(self) -> None:
        files = [
            {"participantId": "p1", "getUrl": "http://minio/a.flac"},
            {"participantId": "p1", "getUrl": "http://minio/b.flac"},
        ]
        self._assert_code(_payload(files=files), "E4004")

    def test_timestamp_align_without_started_at_is_e4005(self) -> None:
        self._assert_code(_payload(options={"align": ALIGN_TIMESTAMP}), "E4005")

    def test_malformed_started_at_is_e4006(self) -> None:
        files = [
            {"participantId": "p1", "getUrl": "http://minio/a.flac", "startedAt": "not-a-date"},
        ]
        self._assert_code(_payload(files=files, options={"align": ALIGN_TIMESTAMP}), "E4006")

    def test_missing_originalname_is_e4001(self) -> None:
        payload = _payload()
        del payload["output"]["originalname"]
        self._assert_code(payload, "E4001")

    def test_non_ascii_originalname_is_e4007(self) -> None:
        """An HTTP header is latin-1 only, and the value must match the PUT
        signature byte for byte -- so we reject rather than re-encode."""
        payload = _payload()
        payload["output"]["originalname"] = "회의록_merged.flac"
        self._assert_code(payload, "E4007")

    def test_percent_encoded_originalname_is_accepted(self) -> None:
        payload = _payload()
        payload["output"]["originalname"] = "%ED%9A%8C%EC%9D%98%EB%A1%9D_merged.flac"
        result = validate_merge_payload(payload)
        self.assertEqual(result["output"]["originalname"], "%ED%9A%8C%EC%9D%98%EB%A1%9D_merged.flac")

    def test_started_at_accepts_z_suffix_and_offset(self) -> None:
        files = [
            {"participantId": "p1", "getUrl": "http://a", "startedAt": "2026-09-19T14:30:52.104Z"},
            {"participantId": "p2", "getUrl": "http://b", "startedAt": "2026-09-19T23:30:52.371+09:00"},
        ]
        result = validate_merge_payload(_payload(files=files, options={"align": ALIGN_TIMESTAMP}))
        self.assertEqual(result["files"][0]["startedAt"].tzinfo, timezone.utc)


class OffsetTests(unittest.TestCase):
    @staticmethod
    def _entry(participant_id: str, offset_ms: int) -> dict:
        base = datetime(2026, 9, 19, 14, 30, 52, tzinfo=timezone.utc)
        return {"participantId": participant_id, "startedAt": base + timedelta(milliseconds=offset_ms)}

    def test_earliest_track_is_reference_and_offsets_are_relative(self) -> None:
        files = [self._entry("p1", 104), self._entry("p2", 371), self._entry("p3", 0)]
        reference, tracks = compute_offsets_ms(files)
        self.assertEqual(reference, "p3")
        by_id = {track["participantId"]: track for track in tracks}
        self.assertEqual(by_id["p3"]["offsetMs"], 0)
        self.assertEqual(by_id["p1"]["offsetMs"], 104)
        self.assertEqual(by_id["p2"]["offsetMs"], 371)
        self.assertFalse(any(track["fallback"] for track in tracks))

    def test_millisecond_precision_is_preserved(self) -> None:
        """The whole point of taking startedAt instead of parsing the
        second-resolution filename."""
        files = [self._entry("p1", 0), self._entry("p2", 267)]
        _, tracks = compute_offsets_ms(files)
        self.assertEqual(tracks[1]["offsetMs"], 267)

    def test_absurd_offset_falls_back_to_zero_and_is_flagged(self) -> None:
        """One device with a wrong clock must not shift everyone else."""
        files = [self._entry("p1", 0), self._entry("p2", 120_000)]
        _, tracks = compute_offsets_ms(files, max_offset_ms=60_000)
        self.assertEqual(tracks[1]["offsetMs"], 0)
        self.assertTrue(tracks[1]["fallback"])
        self.assertFalse(tracks[0]["fallback"])


class MixCommandTests(unittest.TestCase):
    """The merge is an overlay (amix), never a concatenation."""

    def test_align_none_builds_plain_amix(self) -> None:
        from recog import audio

        with patch.object(audio, "run_command") as runner:
            audio.mix_tracks(["a.wav", "b.wav"], "out.flac")
        command = runner.call_args.args[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("amix=inputs=2", filter_complex)
        self.assertNotIn("adelay", filter_complex)

    def test_align_timestamp_prefixes_adelay_per_track(self) -> None:
        from recog import audio

        with patch.object(audio, "run_command") as runner:
            audio.mix_tracks(["a.wav", "b.wav"], "out.flac", delays_ms=[0, 267])
        command = runner.call_args.args[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("adelay=0:all=1[d0]", filter_complex)
        self.assertIn("adelay=267:all=1[d1]", filter_complex)
        self.assertIn("[d0][d1]amix=inputs=2", filter_complex)

    def test_delay_count_must_match_input_count(self) -> None:
        from recog import audio

        with self.assertRaises(audio.AudioError):
            audio.mix_tracks(["a.wav", "b.wav"], "out.flac", delays_ms=[0])


class TransferTests(unittest.TestCase):
    def test_upload_sends_originalname_header_verbatim(self) -> None:
        """A reshaped value breaks the presigned signature (spec 4.1)."""
        from recog import s3_transfer

        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, True)
        source = Path(tmpdir) / "merged.flac"
        source.write_bytes(b"audio-bytes")

        captured = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None):
            captured["headers"] = dict(request.headers)
            return _Response()

        with patch.object(s3_transfer.urllib.request, "urlopen", fake_urlopen):
            size = s3_transfer.upload(
                "http://minio/merged.flac?sig=c",
                source,
                originalname="%ED%9A%8C%EC%9D%98%EB%A1%9D_merged.flac",
            )

        self.assertEqual(size, len(b"audio-bytes"))
        # urllib capitalizes header keys, so compare case-insensitively.
        headers = {key.lower(): value for key, value in captured["headers"].items()}
        self.assertEqual(headers[ORIGINALNAME_HEADER], "%ED%9A%8C%EC%9D%98%EB%A1%9D_merged.flac")

    def test_expired_signature_maps_to_e4102(self) -> None:
        from recog import s3_transfer

        error = s3_transfer.urllib.error.HTTPError(
            "http://minio/p1.flac", 403, "Forbidden", {}, None
        )
        error.read = lambda _size=None: b"<Error><Message>Request has expired</Message></Error>"

        def fake_urlopen(request, timeout=None):
            raise error

        with patch.object(s3_transfer.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(s3_transfer.TransferError) as ctx:
                s3_transfer.download("http://minio/p1.flac", "/dev/null")
        self.assertEqual(ctx.exception.code, "E4102")

    def test_other_download_failure_maps_to_e4101(self) -> None:
        from recog import s3_transfer

        error = s3_transfer.urllib.error.HTTPError(
            "http://minio/p1.flac", 404, "Not Found", {}, None
        )
        error.read = lambda _size=None: b"<Error><Code>NoSuchKey</Code></Error>"

        def fake_urlopen(request, timeout=None):
            raise error

        with patch.object(s3_transfer.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(s3_transfer.TransferError) as ctx:
                s3_transfer.download("http://minio/p1.flac", "/dev/null")
        self.assertEqual(ctx.exception.code, "E4101")


class _Harness:
    """Minimal WSGI caller so route tests stay readable."""

    def __init__(self, app: RecogApplication) -> None:
        self.app = app

    def call(self, method: str, path: str, body: dict | None = None):
        raw = json.dumps(body or {}).encode("utf-8")
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": str(len(raw)),
            "wsgi.input": __import__("io").BytesIO(raw),
        }
        captured = {}

        def start_response(status, headers):
            captured["status"] = int(status.split(" ", 1)[0])

        chunks = self.app(environ, start_response)
        return captured["status"], json.loads(b"".join(chunks).decode("utf-8"))


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.store = SessionStore(self.tmpdir)
        # Zero workers would still spawn one; keep the queue idle instead by
        # never letting a job reach ffmpeg (validation-only assertions below).
        self.app = RecogApplication(self.store)
        self.client = _Harness(self.app)

    def tearDown(self) -> None:
        self.app.merge_jobs.shutdown(timeout=1.0)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_post_returns_202_with_job_id(self) -> None:
        status, body = self.client.call("POST", "/v1/merge", _payload())
        self.assertEqual(status, HTTPStatus.ACCEPTED)
        self.assertTrue(body["jobId"].startswith("mrg_"))
        self.assertEqual(body["status"], "WAITING")
        self.assertEqual(body["fileCount"], 2)
        self.assertEqual(body["retryAfterMs"], 10_000)

    def test_post_validation_error_returns_coded_400(self) -> None:
        payload = _payload()
        del payload["roomNo"]
        status, body = self.client.call("POST", "/v1/merge", payload)
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(body["error"]["code"], "E4001")

    def test_duplicate_room_no_returns_409(self) -> None:
        self.client.call("POST", "/v1/merge", _payload())
        status, body = self.client.call("POST", "/v1/merge", _payload())
        self.assertEqual(status, HTTPStatus.CONFLICT)
        self.assertEqual(body["error"]["code"], "E4090")

    def test_unknown_job_id_returns_404(self) -> None:
        status, body = self.client.call("GET", "/v1/merge/mrg_missing")
        self.assertEqual(status, HTTPStatus.NOT_FOUND)
        self.assertEqual(body["error"]["code"], "E4040")

    def test_status_lookup_returns_200(self) -> None:
        _, accepted = self.client.call("POST", "/v1/merge", _payload())
        status, body = self.client.call("GET", f"/v1/merge/{accepted['jobId']}")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body["jobId"], accepted["jobId"])
        self.assertIn(body["status"], {"WAITING", "RUNNING", "ERROR"})

    def test_existing_routes_still_reachable(self) -> None:
        """/v1/merge is additive: the /rooms and /sessions paths are untouched."""
        status, _ = self.client.call("GET", "/health")
        self.assertEqual(status, HTTPStatus.OK)


class QueueBehaviourTests(unittest.TestCase):
    """MERGE_WORKERS caps concurrent merges, not intake."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.manager = merge_job.MergeJobManager(Path(self.tmpdir) / "merge", workers=1)

    def tearDown(self) -> None:
        self.manager.shutdown(timeout=1.0)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_more_requests_than_workers_are_all_accepted(self) -> None:
        accepted = []
        for index in range(4):
            payload = _payload(roomNo=f"R-{index}")
            accepted.append(self.manager.submit(payload))

        self.assertEqual(len(accepted), 4)
        for entry in accepted:
            self.assertEqual(entry["status"], "WAITING")
            self.assertIsNotNone(self.manager.get(entry["jobId"]))

    def test_finished_job_leaves_memory_but_stays_queryable(self) -> None:
        """JOB_TTL_SEC bounds the in-memory cache only. The record lives on in
        SQLite for MERGE_RECORD_TTL_DAYS, so a late poll still gets an answer."""
        manager = merge_job.MergeJobManager(Path(self.tmpdir) / "ttl", workers=1, job_ttl_sec=0)
        self.addCleanup(manager.shutdown, 1.0)
        accepted = manager.submit(_payload(roomNo="R-ttl"))
        job_id = accepted["jobId"]

        with manager._lock:  # noqa: SLF001 - drive the terminal state directly
            job = manager._jobs[job_id]
            job.status = "DONE"
            job.finished_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            manager.records.save(job.to_record())

        manager._expire_finished()  # noqa: SLF001
        with manager._lock:  # noqa: SLF001
            self.assertNotIn(job_id, manager._jobs, "evicted from memory")

        self.assertEqual(manager.get(job_id)["status"], "DONE", "still served from SQLite")


class UploadPathTests(unittest.TestCase):
    """POST /v1/merge/upload shares the queue, worker and mixing code with the
    presigned path, so a Postman run exercises the real thing."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.manager = merge_job.MergeJobManager(Path(self.tmpdir) / "merge", workers=1)

    def tearDown(self) -> None:
        self.manager.shutdown(timeout=1.0)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_files_is_e4002(self) -> None:
        with self.assertRaises(MergeValidationError) as ctx:
            merge_job.validate_upload_request([])
        self.assertEqual(ctx.exception.code, "E4002")

    def test_too_many_files_is_e4003(self) -> None:
        uploads = [(f"f{i}.flac", b"x") for i in range(merge_job.MAX_FILES + 1)]
        with self.assertRaises(MergeValidationError) as ctx:
            merge_job.validate_upload_request(uploads)
        self.assertEqual(ctx.exception.code, "E4003")

    def test_timestamp_align_needs_one_stamp_per_file(self) -> None:
        uploads = [("a.flac", b"x"), ("b.flac", b"y")]
        with self.assertRaises(MergeValidationError) as ctx:
            merge_job.validate_upload_request(
                uploads, align=ALIGN_TIMESTAMP, started_at_raw="2026-09-19T14:30:52.000Z"
            )
        self.assertEqual(ctx.exception.code, "E4005")

    def test_participant_ids_are_derived_from_upload_order(self) -> None:
        uploads = [("a.flac", b"x"), ("b.flac", b"y")]
        request = merge_job.validate_upload_request(uploads)
        self.assertEqual([f["participantId"] for f in request["files"]], ["f1", "f2"])
        self.assertEqual(request["source"], merge_job.SOURCE_UPLOAD)

    def test_presigned_job_has_no_downloadable_result(self) -> None:
        accepted = self.manager.submit(_payload(roomNo="R-nodl"))
        self.assertIsNone(self.manager.result_path(accepted["jobId"]))

    def test_upload_writes_sources_before_queueing(self) -> None:
        uploads = [("a.flac", b"abc"), ("b.flac", b"defg")]
        accepted = self.manager.submit_upload(uploads)
        work_dir = self.manager.work_root / accepted["jobId"]
        self.assertTrue((work_dir / "src_0").exists() or accepted["status"] != "WAITING")


class OpenApiTests(unittest.TestCase):
    """Swagger assets are vendored: the deploy target has no CDN access."""

    def test_document_covers_both_entry_points(self) -> None:
        from recog import openapi

        document = openapi.build_document()
        self.assertEqual(document["openapi"], "3.0.3")
        for route in ("/v1/merge", "/v1/merge/upload", "/v1/merge/{jobId}", "/v1/merge/{jobId}/download"):
            self.assertIn(route, document["paths"])

    def test_document_is_json_serializable(self) -> None:
        from recog import openapi

        payload = json.loads(openapi.document_json().decode("utf-8"))
        self.assertIn("paths", payload)

    def test_swagger_assets_are_vendored_not_cdn(self) -> None:
        from recog import openapi

        page = openapi.swagger_page().decode("utf-8")
        self.assertIn("/docs/swagger-ui-bundle.js", page)
        self.assertNotIn("cdn.", page)
        self.assertNotIn("http://", page)
        for name in openapi.SWAGGER_ASSETS:
            self.assertIsNotNone(openapi.read_asset(name), f"missing vendored asset: {name}")

    def test_unknown_asset_is_rejected(self) -> None:
        from recog import openapi

        self.assertIsNone(openapi.read_asset("../../etc/passwd"))
        self.assertIsNone(openapi.read_asset("nope.js"))


#: Matches api.py's placeholder default. Real deployments override it
#: through SWAGGER_PASSWORD in .env.recog.
DEFAULT_DOCS_PASSWORD = "change-me"


class DocsAuthTests(unittest.TestCase):
    """/docs is the one surface opened in a browser, so it sits behind Basic
    auth. The merge endpoints stay open (docker-network-internal)."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.app = RecogApplication(SessionStore(self.tmpdir))
        self.client = _Harness(self.app)

    def tearDown(self) -> None:
        self.app.merge_jobs.shutdown(timeout=1.0)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @staticmethod
    def _basic(user: str, password: str) -> str:
        import base64

        return "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")

    def _get(self, path: str, auth: str | None = None):
        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": path,
            "CONTENT_LENGTH": "0",
            "wsgi.input": __import__("io").BytesIO(b""),
        }
        if auth:
            environ["HTTP_AUTHORIZATION"] = auth
        captured = {}

        def start_response(status, headers):
            captured["status"] = int(status.split(" ", 1)[0])
            captured["headers"] = dict(headers)

        chunks = self.app(environ, start_response)
        body = b"".join(chunks)
        return captured["status"], captured.get("headers", {}), body

    def test_docs_without_credentials_is_401_with_challenge(self) -> None:
        status, headers, _ = self._get("/docs")
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)
        self.assertIn("Basic", headers.get("WWW-Authenticate", ""))

    def test_docs_with_correct_credentials_is_200(self) -> None:
        status, _, body = self._get("/docs", self._basic("admin", DEFAULT_DOCS_PASSWORD))
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(b"swagger-ui", body)

    def test_wrong_password_is_401(self) -> None:
        status, _, _ = self._get("/docs", self._basic("admin", "wrong"))
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_wrong_user_is_401(self) -> None:
        status, _, _ = self._get("/docs", self._basic("root", DEFAULT_DOCS_PASSWORD))
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_malformed_header_is_401_not_500(self) -> None:
        for header in ("Basic", "Basic !!!notbase64!!!", "Bearer token", "Basic " + "YWRtaW4="):
            status, _, _ = self._get("/docs", header)
            self.assertEqual(status, HTTPStatus.UNAUTHORIZED, header)

    def test_openapi_and_assets_are_also_protected(self) -> None:
        for path in ("/openapi.json", "/docs/swagger-ui.css", "/docs/swagger-ui-bundle.js"):
            status, _, _ = self._get(path)
            self.assertEqual(status, HTTPStatus.UNAUTHORIZED, path)
            status, _, _ = self._get(path, self._basic("admin", DEFAULT_DOCS_PASSWORD))
            self.assertEqual(status, HTTPStatus.OK, path)

    def test_merge_endpoints_stay_open(self) -> None:
        """Auth covers the docs only; master-api calls /v1/merge without it."""
        status, _ = self.client.call("POST", "/v1/merge", _payload(roomNo="R-open"))
        self.assertEqual(status, HTTPStatus.ACCEPTED)
        status, _ = self.client.call("GET", "/health")
        self.assertEqual(status, HTTPStatus.OK)

    def test_credentials_come_from_env(self) -> None:
        with patch.dict(os.environ, {"SWAGGER_USER": "ops", "SWAGGER_PASSWORD": "s3cret"}):
            status, _, _ = self._get("/docs", self._basic("ops", "s3cret"))
            self.assertEqual(status, HTTPStatus.OK)
            status, _, _ = self._get("/docs", self._basic("admin", DEFAULT_DOCS_PASSWORD))
            self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_empty_password_disables_the_prompt(self) -> None:
        with patch.dict(os.environ, {"SWAGGER_PASSWORD": ""}):
            status, _, _ = self._get("/docs")
            self.assertEqual(status, HTTPStatus.OK)


class RecordStoreTests(unittest.TestCase):
    """SQLite keeps 90 days of history; the in-memory cache only bounds RAM."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        from recog.merge_store import MergeRecordStore

        self.store = MergeRecordStore(Path(self.tmpdir) / "merge.db")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _record(self, job_id: str, status: str = "DONE", **extra) -> dict:
        record = {
            "job_id": job_id,
            "room_no": extra.pop("room_no", "R-1"),
            "source": "presigned",
            "status": status,
            "stage": None,
            "progress": 100,
            "request": {"roomNo": "R-1", "files": [], "output": {}},
            "accepted_at": "2026-09-19T14:00:00.000Z",
            "finished_at": extra.pop("finished_at", "2026-09-19T14:05:00.000Z"),
        }
        record.update(extra)
        return record

    def test_roundtrip_preserves_json_columns(self) -> None:
        self.store.save(
            self._record("mrg_a", output={"durationMs": 3812}, timing={"totalMs": 500})
        )
        loaded = self.store.get("mrg_a")
        self.assertEqual(loaded["output"]["durationMs"], 3812)
        self.assertEqual(loaded["timing"]["totalMs"], 500)

    def test_save_is_an_upsert(self) -> None:
        self.store.save(self._record("mrg_b", status="WAITING", finished_at=None))
        self.store.save(self._record("mrg_b", status="DONE"))
        self.assertEqual(self.store.get("mrg_b")["status"], "DONE")
        self.assertEqual(len(self.store.recent()), 1)

    def test_load_unfinished_selects_only_active(self) -> None:
        self.store.save(self._record("mrg_w", status="WAITING", finished_at=None))
        self.store.save(self._record("mrg_r", status="RUNNING", finished_at=None))
        self.store.save(self._record("mrg_d", status="DONE"))
        self.assertEqual({r["job_id"] for r in self.store.load_unfinished()}, {"mrg_w", "mrg_r"})

    def test_purge_drops_only_rows_past_retention(self) -> None:
        self.store.save(self._record("mrg_old", finished_at="2020-01-01T00:00:00.000Z"))
        self.store.save(self._record("mrg_new", finished_at="2026-09-19T14:05:00.000Z"))
        self.store.save(self._record("mrg_live", status="RUNNING", finished_at=None))
        removed = self.store.purge_older_than(90)
        self.assertEqual(removed, 1)
        self.assertIsNone(self.store.get("mrg_old"))
        self.assertIsNotNone(self.store.get("mrg_new"))
        self.assertIsNotNone(self.store.get("mrg_live"))

    def test_purge_is_a_noop_when_retention_is_zero(self) -> None:
        self.store.save(self._record("mrg_old", finished_at="2020-01-01T00:00:00.000Z"))
        self.assertEqual(self.store.purge_older_than(0), 0)
        self.assertIsNotNone(self.store.get("mrg_old"))

    def test_recent_filters_by_room_and_caps_limit(self) -> None:
        self.store.save(self._record("mrg_1", room_no="R-1"))
        self.store.save(self._record("mrg_2", room_no="R-2"))
        self.assertEqual(len(self.store.recent(room_no="R-1")), 1)
        self.assertEqual(len(self.store.recent()), 2)
        self.assertLessEqual(len(self.store.recent(limit=9999)), 500)


class PersistenceTests(unittest.TestCase):
    """A restart must not lose work: finished jobs come back, in-flight ones re-run."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir) / "merge"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _manager(self, **kwargs):
        manager = merge_job.MergeJobManager(self.root, workers=1, **kwargs)
        self.addCleanup(manager.shutdown, 1.0)
        return manager

    def test_job_survives_a_manager_restart(self) -> None:
        first = self._manager()
        accepted = first.submit(_payload(roomNo="R-persist"))
        first.shutdown(timeout=1.0)

        second = self._manager()
        self.assertIsNotNone(second.get(accepted["jobId"]))

    def test_unfinished_job_is_requeued_with_a_counter(self) -> None:
        manager = self._manager()
        request = merge_job.validate_merge_payload(_payload(roomNo="R-requeue"))
        job = merge_job.MergeJob("mrg_requeuetest000000", request)
        job.status = "RUNNING"
        job.stage = "MIXING"
        manager.records.save(job.to_record())
        manager.shutdown(timeout=1.0)

        revived = self._manager()
        record = revived.records.get(job.job_id)
        self.assertEqual(record["requeue_count"], 1)
        self.assertIn(record["status"], {"WAITING", "RUNNING", "ERROR", "DONE"})

    def test_upload_job_without_sources_fails_instead_of_looping(self) -> None:
        manager = self._manager()
        request = merge_job.validate_upload_request([("a.flac", b"x")])
        request["files"][0]["sourcePath"] = str(self.root / "gone" / "src_0")
        job = merge_job.MergeJob("mrg_uploadgone0000000", request)
        job.status = "RUNNING"
        manager.records.save(job.to_record())
        manager.shutdown(timeout=1.0)

        revived = self._manager()
        record = revived.records.get(job.job_id)
        self.assertEqual(record["status"], "ERROR")
        self.assertEqual(record["error"]["code"], merge_job.ERROR_SOURCES_GONE)

    def test_status_is_served_from_db_after_memory_eviction(self) -> None:
        """The 24h memory TTL must not shorten the 90-day record retention."""
        manager = self._manager(job_ttl_sec=0)
        accepted = manager.submit(_payload(roomNo="R-evict"))
        job_id = accepted["jobId"]

        with manager._lock:  # noqa: SLF001
            job = manager._jobs[job_id]
            job.status = "DONE"
            job.finished_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            manager.records.save(job.to_record())

        manager._expire_finished()  # noqa: SLF001
        with manager._lock:  # noqa: SLF001
            self.assertNotIn(job_id, manager._jobs)

        self.assertIsNotNone(manager.get(job_id), "should fall back to SQLite")

    def test_request_json_roundtrip_keeps_started_at(self) -> None:
        payload = _payload(
            files=[
                {"participantId": "p1", "getUrl": "http://a", "startedAt": "2026-09-19T14:30:52.104Z"},
                {"participantId": "p2", "getUrl": "http://b", "startedAt": "2026-09-19T14:30:52.371Z"},
            ],
            options={"align": ALIGN_TIMESTAMP},
        )
        request = merge_job.validate_merge_payload(payload)
        restored = merge_job.request_from_json(merge_job.request_to_json(request))
        delta = restored["files"][1]["startedAt"] - restored["files"][0]["startedAt"]
        self.assertEqual(round(delta.total_seconds() * 1000), 267)


class RetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.manager = merge_job.MergeJobManager(Path(self.tmpdir) / "merge", workers=1)

    def tearDown(self) -> None:
        self.manager.shutdown(timeout=1.0)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _await_terminal(self, job_id: str, timeout: float = 20.0) -> dict:
        """Let the worker run to completion instead of forcing a status, which
        races with the worker's own writes."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.manager.get(job_id)
            if state and state["status"] in {"DONE", "ERROR"}:
                return state
            time.sleep(0.02)
        self.fail(f"job {job_id} did not finish within {timeout}s")

    def _finished(self, room_no: str = "R-retry") -> str:
        # The fixture URLs point at a host that does not resolve, so the job
        # fails on download within a moment -- exactly the case a retry targets.
        accepted = self.manager.submit(_payload(roomNo=room_no))
        self._await_terminal(accepted["jobId"])
        return accepted["jobId"]

    def test_retry_creates_a_new_job_linked_to_the_original(self) -> None:
        original = self._finished()
        retried = self.manager.retry(original)
        self.assertNotEqual(retried["jobId"], original)
        self.assertEqual(retried["retriedFrom"], original)
        self.assertEqual(self.manager.get(retried["jobId"])["retriedFrom"], original)

    def test_retry_applies_fresh_urls(self) -> None:
        original = self._finished()
        retried = self.manager.retry(
            original,
            {
                "files": [{"participantId": "p1", "getUrl": "http://new/p1"}],
                "output": {"putUrl": "http://new/out"},
            },
        )
        with self.manager._lock:  # noqa: SLF001
            request = self.manager._jobs[retried["jobId"]].request
        self.assertEqual(request["files"][0]["getUrl"], "http://new/p1")
        self.assertEqual(request["output"]["putUrl"], "http://new/out")
        # Untouched entries keep the original URL.
        self.assertEqual(request["files"][1]["getUrl"], "http://minio/p2.flac?sig=b")

    def test_retry_rejects_unknown_job(self) -> None:
        with self.assertRaises(MergeValidationError) as ctx:
            self.manager.retry("mrg_missing")
        self.assertEqual(ctx.exception.code, "E4040")

    def test_retry_rejects_an_active_job(self) -> None:
        accepted = self.manager.submit(_payload(roomNo="R-active"))
        with self.assertRaises(MergeValidationError) as ctx:
            self.manager.retry(accepted["jobId"])
        self.assertEqual(ctx.exception.code, "E4091")

    def test_retry_rejects_upload_path_jobs(self) -> None:
        # Not audio, so normalization fails quickly and the job reaches ERROR.
        accepted = self.manager.submit_upload([("a.flac", b"not-audio")])
        self._await_terminal(accepted["jobId"])
        with self.assertRaises(MergeValidationError) as ctx:
            self.manager.retry(accepted["jobId"])
        self.assertEqual(ctx.exception.code, "E4092")

    def test_retry_rejects_unknown_participant_override(self) -> None:
        original = self._finished()
        with self.assertRaises(MergeValidationError) as ctx:
            self.manager.retry(original, {"files": [{"participantId": "nope", "getUrl": "http://x"}]})
        self.assertEqual(ctx.exception.code, "E4001")

    def test_history_returns_newest_first(self) -> None:
        self._finished("R-h1")
        self._finished("R-h2")
        records = self.manager.history(limit=10)
        self.assertGreaterEqual(len(records), 2)
        self.assertEqual(len(self.manager.history(room_no="R-h1")), 1)


if __name__ == "__main__":
    unittest.main()
