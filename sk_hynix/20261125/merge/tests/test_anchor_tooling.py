from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


class AnchorToolingTests(unittest.TestCase):
    def test_generate_sync_beep_cli_writes_wave_file(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "sync-beep.wav"
            completed = subprocess.run(
                [sys.executable, str(project_root / "tools" / "generate_sync_beep.py"), str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(Path(completed.stdout.strip()), output)
            with wave.open(str(output), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertGreater(handle.getnframes(), 0)

    def test_benchmark_anchor_detector_cli_outputs_expected_cases(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "tools" / "benchmark_anchor_detector.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        by_name = {case["name"]: case for case in payload["cases"]}
        self.assertTrue(by_name["expected_window"]["detected"])
        self.assertEqual(by_name["expected_window"]["search_mode"], "expected")
        self.assertTrue(by_name["fallback_window"]["detected"])
        self.assertEqual(by_name["fallback_window"]["search_mode"], "fallback")
        self.assertFalse(by_name["silence"]["detected"])


if __name__ == "__main__":
    unittest.main()
