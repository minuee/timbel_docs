from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recog.api import RecogApplication
from recog.store import SessionStore


def _wsgi_request(app, method: str, path: str, body: bytes = b"", content_type: str = ""):
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    environ["CONTENT_LENGTH"] = str(len(body))
    environ["wsgi.input"] = io.BytesIO(body)
    if content_type:
        environ["CONTENT_TYPE"] = content_type
    captured = {}

    def start_response(status, headers):  # noqa: ANN001
        captured["status"] = status
        captured["headers"] = headers

    body_bytes = b"".join(app(environ, start_response))
    captured["body"] = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    return captured


class CloseEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.store = SessionStore(self.tmpdir)
        self.app = RecogApplication(self.store)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_close_session_happy_path(self) -> None:
        """Happy path: close open session, verify state transitions."""
        session = self.store.create_session()
        session_id = session.session_id
        join_code = "TEST_CLOSE_001"
        session.join_code = join_code
        self.store.save_session(session)

        # Create some dummy artifacts
        artifacts_dir = self.store.session_dir(session_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "test.wav").write_text("dummy audio")

        # Close the session
        response = _wsgi_request(
            self.app,
            "POST",
            f"/sessions/{session_id}/close",
            json.dumps({"join_code": join_code}).encode("utf-8"),
            content_type="application/json",
        )

        self.assertIn("200", response["status"])
        body = response["body"]
        self.assertEqual(body["state"], "closed")
        self.assertIsNotNone(body["closed_at"])

    def test_close_session_idempotent_second_call(self) -> None:
        """Idempotent: second close call returns 200 with same payload."""
        session = self.store.create_session()
        session_id = session.session_id
        join_code = "TEST_CLOSE_002"
        session.join_code = join_code
        self.store.save_session(session)

        # First close
        response1 = _wsgi_request(
            self.app,
            "POST",
            f"/sessions/{session_id}/close",
            json.dumps({"join_code": join_code}).encode("utf-8"),
            content_type="application/json",
        )
        self.assertIn("200", response1["status"])
        closed_at_1 = response1["body"]["closed_at"]

        # Second close
        response2 = _wsgi_request(
            self.app,
            "POST",
            f"/sessions/{session_id}/close",
            json.dumps({"join_code": join_code}).encode("utf-8"),
            content_type="application/json",
        )
        self.assertIn("200", response2["status"])
        closed_at_2 = response2["body"]["closed_at"]
        self.assertEqual(closed_at_1, closed_at_2)

    def test_close_session_invalid_join_code_returns_403(self) -> None:
        """Invalid join_code: return 403 Forbidden."""
        session = self.store.create_session()
        session_id = session.session_id

        response = _wsgi_request(
            self.app,
            "POST",
            f"/sessions/{session_id}/close",
            json.dumps({"join_code": "wrong_code"}).encode("utf-8"),
            content_type="application/json",
        )

        self.assertIn("403", response["status"])

    def test_close_session_missing_join_code_returns_400(self) -> None:
        """Missing join_code: return 400 Bad Request."""
        session = self.store.create_session()
        session_id = session.session_id

        response = _wsgi_request(
            self.app,
            "POST",
            f"/sessions/{session_id}/close",
            json.dumps({}).encode("utf-8"),
            content_type="application/json",
        )

        self.assertIn("400", response["status"])

    def test_close_session_io_failure_leaves_state_closing(self) -> None:
        """Simulated I/O failure: state stays 'closing', includes error in session."""
        session = self.store.create_session()
        session_id = session.session_id
        join_code = "TEST_CLOSE_003"
        session.join_code = join_code
        self.store.save_session(session)

        def failing_shutil_move(src, dst):  # noqa: ANN001, ANN202
            raise OSError("simulated move failure")

        with patch("shutil.move", side_effect=failing_shutil_move):
            response = _wsgi_request(
                self.app,
                "POST",
                f"/sessions/{session_id}/close",
                json.dumps({"join_code": join_code}).encode("utf-8"),
                content_type="application/json",
            )

            self.assertIn("500", response["status"])

        # Verify state is still 'closing' and error is recorded
        reloaded = self.store.get_session(session_id)
        self.assertEqual(reloaded.state, "closing")
        self.assertTrue(len(reloaded.errors) > 0)


if __name__ == "__main__":
    unittest.main()
