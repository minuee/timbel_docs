from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOL = PROJECT_ROOT / "tools" / "check_recorder_baseline.py"


def write_wav(path: Path, *, sample_rate: int, channels: int) -> None:
    frames = array("h", [0] * sample_rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames.tobytes())


class RecorderBaselineToolTests(unittest.TestCase):
    def test_valid_baseline_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.wav"
            write_wav(path, sample_rate=48_000, channels=1)
            completed = subprocess.run(
                [sys.executable, str(TOOL), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 0)
            self.assertTrue(payload["baseline_valid"])
            self.assertEqual(payload["sample_rate_hz"], 48_000)
            self.assertEqual(payload["channels"], 1)
            self.assertEqual(payload["codec"], "pcm_s16le")

    def test_invalid_sample_rate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.wav"
            write_wav(path, sample_rate=44_100, channels=1)
            completed = subprocess.run(
                [sys.executable, str(TOOL), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(payload["baseline_valid"])
            self.assertTrue(any("sample_rate" in item for item in payload["violations"]))
