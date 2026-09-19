from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recog.api import RecogApplication
from recog.store import SessionStore


def _wsgi_request(app, method: str, path: str, headers: dict | None = None):
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    # Split path and query string
    if "?" in path:
        path_part, query_part = path.split("?", 1)
        environ["PATH_INFO"] = path_part
        environ["QUERY_STRING"] = query_part
    else:
        environ["PATH_INFO"] = path
        environ["QUERY_STRING"] = ""
    if headers:
        for key, value in headers.items():
            env_key = f"HTTP_{key.upper().replace('-', '_')}"
            environ[env_key] = value
    captured = {}

    def start_response(status, response_headers):  # noqa: ANN001
        captured["status"] = status
        captured["headers"] = {k: v for k, v in response_headers}

    body_bytes = b"".join(app(environ, start_response))
    captured["body"] = body_bytes
    return captured


class StreamingEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.store = SessionStore(self.tmpdir)
        self.app = RecogApplication(self.store)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_streaming_full_get_returns_200_with_full_body(self) -> None:
        """Full GET returns 200 with entire file."""
        session = self.store.create_session()
        session_id = session.session_id
        join_code = "TEST123"
        session.join_code = join_code
        self.store.save_session(session)

        # Create a test artifact
        artifacts_dir = self.store.session_dir(session_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        test_file = artifacts_dir / "listening_mix.wav"
        test_content = b"RIFF" + b"x" * 1000  # Fake WAV header
        test_file.write_bytes(test_content)

        # Register artifact
        self.store.add_artifact(
            session_id,
            kind="mixdown",
            name="listening_mix.wav",
            source_path=test_file,
            mime_type="audio/wav",
            metadata={"duration_ms": 5000},
        )

        response = _wsgi_request(
            self.app,
            "GET",
            f"/sessions/{session_id}/artifacts/listening_mix?token={join_code}",
        )

        self.assertIn("200", response["status"])
        self.assertEqual(response["body"], test_content)

    def test_streaming_head_returns_same_headers_empty_body(self) -> None:
        """HEAD returns headers but empty body."""
        session = self.store.create_session()
        session_id = session.session_id
        join_code = "TEST456"
        session.join_code = join_code
        self.store.save_session(session)

        # Create a test artifact
        artifacts_dir = self.store.session_dir(session_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        test_file = artifacts_dir / "listening_mix.wav"
        test_content = b"RIFF" + b"x" * 1000
        test_file.write_bytes(test_content)

        self.store.add_artifact(
            session_id,
            kind="mixdown",
            name="listening_mix.wav",
            source_path=test_file,
            mime_type="audio/wav",
        )

        response = _wsgi_request(
            self.app,
            "HEAD",
            f"/sessions/{session_id}/artifacts/listening_mix?token={join_code}",
        )

        self.assertIn("200", response["status"])
        self.assertEqual(response["body"], b"")
        self.assertIn("Content-Length", response["headers"])

    def test_streaming_partial_range_returns_206(self) -> None:
        """Partial GET with Range header returns 206."""
        session = self.store.create_session()
        session_id = session.session_id
        join_code = "TEST789"
        session.join_code = join_code
        self.store.save_session(session)

        artifacts_dir = self.store.session_dir(session_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        test_file = artifacts_dir / "listening_mix.wav"
        test_content = b"0123456789" * 100  # 1000 bytes
        test_file.write_bytes(test_content)

        self.store.add_artifact(
            session_id,
            kind="mixdown",
            name="listening_mix.wav",
            source_path=test_file,
            mime_type="audio/wav",
        )

        response = _wsgi_request(
            self.app,
            "GET",
            f"/sessions/{session_id}/artifacts/listening_mix?token={join_code}",
            headers={"Range": "bytes=0-99"},
        )

        self.assertIn("206", response["status"])
        self.assertEqual(len(response["body"]), 100)
        self.assertIn("Content-Range", response["headers"])

    def test_streaming_invalid_range_returns_416(self) -> None:
        """Invalid Range returns 416 Range Not Satisfiable."""
        session = self.store.create_session()
        session_id = session.session_id
        join_code = "RANGE416"
        session.join_code = join_code
        self.store.save_session(session)

        artifacts_dir = self.store.session_dir(session_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        test_file = artifacts_dir / "listening_mix.wav"
        test_file.write_bytes(b"x" * 1000)

        self.store.add_artifact(
            session_id,
            kind="mixdown",
            name="listening_mix.wav",
            source_path=test_file,
            mime_type="audio/wav",
        )

        response = _wsgi_request(
            self.app,
            "GET",
            f"/sessions/{session_id}/artifacts/listening_mix?token={join_code}",
            headers={"Range": "bytes=999999999-"},
        )

        self.assertIn("416", response["status"])
        self.assertIn("Content-Range", response["headers"])

    def test_streaming_missing_token_returns_403(self) -> None:
        """Missing token returns 403 Forbidden."""
        session = self.store.create_session()
        session_id = session.session_id

        artifacts_dir = self.store.session_dir(session_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        test_file = artifacts_dir / "listening_mix.wav"
        test_file.write_bytes(b"x" * 100)

        self.store.add_artifact(
            session_id,
            kind="mixdown",
            name="listening_mix.wav",
            source_path=test_file,
            mime_type="audio/wav",
        )

        response = _wsgi_request(
            self.app,
            "GET",
            f"/sessions/{session_id}/artifacts/listening_mix",
        )

        self.assertIn("403", response["status"])

    def test_streaming_artifact_not_found_returns_404(self) -> None:
        """Missing artifact returns 404."""
        session = self.store.create_session()
        session_id = session.session_id
        join_code = "NOTFOUND"
        session.join_code = join_code
        self.store.save_session(session)

        response = _wsgi_request(
            self.app,
            "GET",
            f"/sessions/{session_id}/artifacts/listening_mix?token={join_code}",
        )

        self.assertIn("404", response["status"])


if __name__ == "__main__":
    unittest.main()
