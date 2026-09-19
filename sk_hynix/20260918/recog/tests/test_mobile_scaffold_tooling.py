from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class MobileScaffoldToolingTests(unittest.TestCase):
    def test_check_mobile_scaffold_reports_success(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "tools" / "check_mobile_scaffold.py")],
            check=True,
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["existing_count"], payload["required_count"])


if __name__ == "__main__":
    unittest.main()
