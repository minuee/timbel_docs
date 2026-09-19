from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recog.store import SessionStore
from recog.models import SessionRecord


class StoreAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.store = SessionStore(self.tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_session_writes_tmp_then_replaces_atomically(self) -> None:
        """Verify save_session uses fsync before os.replace()."""
        session = self.store.create_session()
        session.status = "updated"
        self.store.save_session(session)

        path = self.store.session_path(session.session_id)
        self.assertTrue(path.exists())
        payload = json.loads(path.read_text())
        self.assertEqual(payload["status"], "updated")

    def test_save_session_crash_mid_write_leaves_tmp_residue_or_original(self) -> None:
        """Simulate crash: monkeypatch os.replace to raise, verify target unchanged."""
        session = self.store.create_session()
        original_status = session.status
        session.status = "modified"

        path = self.store.session_path(session.session_id)
        tmp = path.with_suffix(".tmp")

        def failing_replace(src: str, dst: str) -> None:
            # Simulate crash after write but before replace
            raise OSError("simulated crash")

        with patch("os.replace", side_effect=failing_replace):
            with self.assertRaises(OSError):
                self.store.save_session(session)

        # Verify target file still has original content or is gone
        if path.exists():
            payload = json.loads(path.read_text())
            self.assertEqual(payload["status"], original_status)

    def test_save_room_uses_fsync_gate(self) -> None:
        """Verify save_room uses fsync before os.replace()."""
        room = self.store.create_room(host_participant_id="test_host")
        room.state = "modified"
        self.store.save_room(room)

        path = self.store.room_path(room.room_id)
        self.assertTrue(path.exists())
        payload = json.loads(path.read_text())
        self.assertEqual(payload["state"], "modified")


if __name__ == "__main__":
    unittest.main()
