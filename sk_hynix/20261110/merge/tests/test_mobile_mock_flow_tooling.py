from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class MobileMockFlowToolingTests(unittest.TestCase):
    def test_check_mobile_mock_flow_reports_success(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / 'tools' / 'check_mobile_mock_flow.py')],
            check=True,
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['required_file_count'], len(payload['items']))
        self.assertTrue(all(not item['missing_markers'] for item in payload['items']))


if __name__ == '__main__':
    unittest.main()
