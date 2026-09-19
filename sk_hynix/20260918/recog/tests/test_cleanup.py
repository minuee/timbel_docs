from __future__ import annotations

import errno
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import cleanup  # noqa: E402


def _utcnow_minus(seconds: int) -> str:
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return ts.isoformat().replace("+00:00", "Z")


def _write_session(root: Path, session_id: str, *, state: str, closed_at: str | None,
                   with_artifacts: bool = True) -> Path:
    session_dir = root / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": session_id,
        "state": state,
        "closed_at": closed_at,
        "room_id": "room1",
        "join_code": "ABC123",
    }
    (session_dir / "session.json").write_text(json.dumps(payload))
    if with_artifacts:
        (session_dir / "artifacts").mkdir(exist_ok=True)
        (session_dir / "artifacts" / "listening_mix.wav").write_bytes(b"RIFF" + b"x" * 100)
        (session_dir / "work").mkdir(exist_ok=True)
        (session_dir / "work" / "scratch.bin").write_bytes(b"y" * 50)
    return session_dir


class CleanupRunOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.runtime = Path(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reconcile_stale_closing_session(self):
        _write_session(
            self.runtime,
            "sess-a",
            state="closing",
            closed_at=_utcnow_minus(10 * 60),
        )
        metric = cleanup.run_once(self.runtime, self.runtime / "cleanup.log", dry_run=False)
        self.assertEqual(metric["reconciled"], 1)
        self.assertEqual(metric["stuck_count"], 0)
        archive = self.runtime / "archive" / "sessions" / "sess-a" / "artifacts"
        self.assertTrue((archive / "listening_mix.wav").exists())
        reread = json.loads((self.runtime / "sessions" / "sess-a" / "session.json").read_text())
        self.assertEqual(reread["state"], "closed")
        # work dir purged
        self.assertFalse((self.runtime / "sessions" / "sess-a" / "work").exists())

    def test_recent_closing_not_reconciled(self):
        _write_session(
            self.runtime,
            "sess-b",
            state="closing",
            closed_at=_utcnow_minus(30),  # too recent
        )
        metric = cleanup.run_once(self.runtime, self.runtime / "cleanup.log", dry_run=False)
        self.assertEqual(metric["reconciled"], 0)
        self.assertEqual(metric["stuck_count"], 0)

    def test_purge_old_archive_entry(self):
        archive = self.runtime / "archive" / "sessions" / "sess-old"
        archive.mkdir(parents=True)
        (archive / "artifacts").mkdir()
        (archive / "artifacts" / "listening_mix.wav").write_bytes(b"a" * 200)
        old_time = time.time() - (8 * 24 * 3600)
        os.utime(archive, (old_time, old_time))
        metric = cleanup.run_once(self.runtime, self.runtime / "cleanup.log", dry_run=False)
        self.assertEqual(metric["purged"], 1)
        self.assertGreater(metric["bytes_freed"], 0)
        self.assertFalse(archive.exists())

    def test_dry_run_does_not_mutate_state(self):
        _write_session(
            self.runtime,
            "sess-c",
            state="closing",
            closed_at=_utcnow_minus(10 * 60),
        )
        cleanup.run_once(self.runtime, self.runtime / "cleanup.log", dry_run=True)
        reread = json.loads((self.runtime / "sessions" / "sess-c" / "session.json").read_text())
        self.assertEqual(reread["state"], "closing")
        self.assertFalse((self.runtime / "cleanup.log").exists())

    def test_metric_log_appends_one_json_line(self):
        _write_session(self.runtime, "sess-d", state="closing",
                       closed_at=_utcnow_minus(10 * 60), with_artifacts=False)
        log_path = self.runtime / "cleanup.log"
        cleanup.run_once(self.runtime, log_path, dry_run=False)
        cleanup.run_once(self.runtime, log_path, dry_run=False)
        lines = log_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            entry = json.loads(line)
            for key in ("ts", "stuck_count", "stuck_ids", "reconciled", "purged", "bytes_freed"):
                self.assertIn(key, entry)


class RetryPolicyTests(unittest.TestCase):
    def test_retry_on_eacces_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise OSError(errno.EACCES, "locked")

        with patch.object(cleanup, "RETRY_BACKOFF_SECONDS", 0):
            cleanup._retry_on_transient(flaky, "flaky-op", dry_run=False)
        self.assertEqual(calls["n"], 2)

    def test_retry_raises_after_max(self):
        def boom():
            raise OSError(errno.EAGAIN, "stuck")

        with patch.object(cleanup, "RETRY_BACKOFF_SECONDS", 0):
            with self.assertRaises(OSError):
                cleanup._retry_on_transient(boom, "boom-op", dry_run=False)

    def test_non_transient_error_does_not_retry(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise OSError(errno.EPERM, "nope")

        with self.assertRaises(OSError):
            cleanup._retry_on_transient(boom, "perm-op", dry_run=False)
        self.assertEqual(calls["n"], 1)


class DirSizeTests(unittest.TestCase):
    def test_bytes_freed_safe_with_dangling_symlink(self):
        """Dangling symlinks must NOT raise and must NOT inflate the count via
        a followed read of the target (which doesn't exist)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.bin").write_bytes(b"a" * 50)
            (root / "dangling.lnk").symlink_to(root / "does-not-exist")
            size = cleanup._dir_size_bytes(root)
            # Must at least account for the real file, and must not raise.
            self.assertGreaterEqual(size, 50)
            # Bounded — no recursion into a non-existent target.
            self.assertLess(size, 50 + 4096)


if __name__ == "__main__":
    unittest.main()
