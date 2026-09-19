from __future__ import annotations

import unittest

from audio_sync.dsp import (
    DEFAULT_STT_SAMPLE_RATE,
    DEFAULT_WORKING_SAMPLE_RATE,
    build_canonicalize_command,
    build_stt_export_command,
    summarize_canonical_metadata,
)


class CanonicalizeHelperTests(unittest.TestCase):
    def test_build_canonicalize_command_targets_working_format(self) -> None:
        command = build_canonicalize_command('input.m4a', 'output.wav')
        self.assertEqual(
            command,
            (
                'ffmpeg', '-y', '-i', 'input.m4a', '-ac', '1', '-ar', str(DEFAULT_WORKING_SAMPLE_RATE), '-sample_fmt', 's16', 'output.wav'
            ),
        )

    def test_build_stt_export_command_targets_stt_sample_rate(self) -> None:
        command = build_stt_export_command('input.wav', 'output.stt.wav')
        self.assertIn(str(DEFAULT_STT_SAMPLE_RATE), command)
        self.assertEqual(command[-1], 'output.stt.wav')

    def test_summarize_canonical_metadata_normalizes_value_types(self) -> None:
        summary = summarize_canonical_metadata(
            {
                'sample_rate': '48000',
                'channels': 1,
                'codec_name': 'pcm_s16le',
                'duration_seconds': '12.5',
                'bit_rate': '1536000',
            }
        )
        self.assertEqual(summary['sample_rate'], 48000)
        self.assertEqual(summary['channels'], 1)
        self.assertEqual(summary['codec_name'], 'pcm_s16le')
        self.assertAlmostEqual(summary['duration_seconds'], 12.5)
        self.assertEqual(summary['bit_rate'], 1536000)


if __name__ == '__main__':
    unittest.main()
