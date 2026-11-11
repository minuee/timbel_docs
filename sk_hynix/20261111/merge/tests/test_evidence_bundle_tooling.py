from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class EvidenceBundleToolingTests(unittest.TestCase):
    def test_init_evidence_bundle_creates_expected_scaffold(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "20260409T103000Z"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(project_root / "tools" / "init_evidence_bundle.py"),
                    str(out),
                    "--run-type",
                    "controlled_device",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(Path(completed.stdout.strip()), out)
            self.assertTrue((out / "summary.md").exists())
            self.assertTrue((out / "summary.json").exists())
            self.assertTrue((out / "protocol-events.ndjson").exists())
            self.assertTrue((out / "controlled-device" / "load-probe").is_dir())
            self.assertTrue((out / "diagnostics" / "scope-audit").is_dir())
            payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["bundle_id"], out.name)
            self.assertEqual(payload["run_type"], "controlled_device")


if __name__ == "__main__":
    unittest.main()
