from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ControlledSessionScaffoldTests(unittest.TestCase):
    def test_run_controlled_session_scaffold_creates_evidence_bundle(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "controlled-run"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(project_root / "tools" / "run_controlled_session_scaffold.py"),
                    str(out),
                    "--tracks",
                    "2",
                    "--duration-seconds",
                    "6",
                ],
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(project_root / "src")},
            )
            payload = json.loads(completed.stdout)
            self.assertIn("session_id", payload)
            self.assertTrue((out / "summary.json").exists())
            self.assertTrue((out / "session-metadata.json").exists())
            self.assertTrue((out / "room-state.json").exists())
            self.assertTrue((out / "protocol-events.ndjson").exists())
            self.assertTrue((out / "artifacts" / "manifest.json").exists())
            self.assertTrue((out / "controlled-device" / "beep.wav").exists())
            summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["participants"]["expected"], 2)
            self.assertEqual(summary["participants"]["received_files"], 2)


if __name__ == "__main__":
    unittest.main()
