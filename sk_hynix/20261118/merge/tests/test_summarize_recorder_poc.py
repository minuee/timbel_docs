from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOL = PROJECT_ROOT / "tools" / "summarize_recorder_poc.py"


class SummarizeRecorderPocTests(unittest.TestCase):
    def test_all_valid_reports_keep_flutter_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(2):
                (root / f"{index}.json").write_text(
                    json.dumps(
                        {
                            "baseline_valid": True,
                            "container": "wav",
                            "codec": "pcm_s16le",
                            "sample_rate_hz": 48000,
                            "channels": 1,
                            "violations": [],
                        }
                    )
                )
            completed = subprocess.run(
                [sys.executable, str(TOOL), str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["decision"], "keep_flutter_recorder_strategy")
            self.assertEqual(payload["valid_count"], 2)

    def test_partial_success_prefers_native_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.json").write_text(json.dumps({"baseline_valid": True, "violations": []}))
            (root / "bad.json").write_text(
                json.dumps({"baseline_valid": False, "violations": ["sample_rate=44100 expected=48000"]})
            )
            completed = subprocess.run(
                [sys.executable, str(TOOL), str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["decision"], "keep_flutter_plus_native_bridge")
            self.assertEqual(payload["valid_count"], 1)
