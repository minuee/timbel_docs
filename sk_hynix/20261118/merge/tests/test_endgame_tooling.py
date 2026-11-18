from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from recog.synthetic import generate_fixture_session
from testkit.listening_review import build_prefilled_listening_review


class EndgameToolingTests(unittest.TestCase):
    def test_generate_fixture_session_accepts_duration_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            truth = generate_fixture_session(temp_dir, track_count=5, duration_seconds=12.5)
            self.assertEqual(len(truth["tracks"]), 5)
            self.assertAlmostEqual(truth["duration_seconds"], 12.5)

    def test_listening_review_prefills_manifest_context(self) -> None:
        markdown = build_prefilled_listening_review(
            session_id="session-123",
            recommended_stt_input="tracks",
            fixture_type="synthetic",
            review_date="2026-04-07",
        )
        self.assertIn("Session ID: session-123", markdown)
        self.assertIn("Recommended STT input from manifest: tracks", markdown)
        self.assertIn("Result: `BLOCKED`", markdown)

    def test_run_load_probe_cli_outputs_summary_and_review(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(project_root / "tools" / "run_load_probe.py"),
                    temp_dir,
                    "--tracks",
                    "3",
                    "--duration-seconds",
                    "4",
                ],
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(project_root / "src")},
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["tracks"], 3)
            self.assertAlmostEqual(payload["duration_seconds"], 4.0)
            self.assertTrue(Path(payload["manifest_path"]).exists())
            review = Path(payload["listening_review_path"]).read_text()
            self.assertIn("Reviewer decision", review)
            self.assertTrue((Path(temp_dir) / "probe-summary.json").exists())


if __name__ == "__main__":
    unittest.main()
