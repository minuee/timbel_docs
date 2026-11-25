from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from zipfile import ZipFile

from audio_sync.export import create_artifact_bundle


class ArtifactBundleTests(unittest.TestCase):
    def test_creates_bundle_with_checksums_and_artifacts(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest = root / "manifest.json"
            manifest.write_text('{"ok": true}\n', encoding="utf-8")
            compat_manifest = root / "manifest.recog.json"
            compat_manifest.write_text('{"ok": "compat"}\n', encoding="utf-8")
            track_a = root / "alice.wav"
            track_a.write_bytes(b"alice")
            track_b = root / "bob.wav"
            track_b.write_bytes(b"bob")
            mix = root / "mix.wav"
            mix.write_bytes(b"mix")
            bundle = root / "session.zip"

            create_artifact_bundle(
                bundle,
                manifest_path=manifest,
                compat_manifest_path=compat_manifest,
                track_paths=(track_a, track_b),
                mixdown_path=mix,
            )

            with ZipFile(bundle) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    [
                        "checksums.json",
                        "manifest.json",
                        "manifest.recog.json",
                        "mix/mix.wav",
                        "tracks/alice.wav",
                        "tracks/bob.wav",
                    ],
                )
                checksums = json.loads(archive.read("checksums.json"))
                self.assertEqual(checksums["manifest"]["path"], "manifest.json")
                self.assertEqual(checksums["manifest"]["sizeBytes"], len(b'{"ok": true}\n'))
                self.assertEqual(checksums["compatManifest"]["path"], "manifest.recog.json")
                self.assertEqual(
                    checksums["compatManifest"]["sizeBytes"],
                    len(b'{"ok": "compat"}\n'),
                )
                self.assertEqual(checksums["mixdown"]["path"], "mix.wav")
                self.assertEqual(checksums["mixdown"]["sizeBytes"], len(b"mix"))
                self.assertEqual(
                    [entry["path"] for entry in checksums["tracks"]],
                    ["alice.wav", "bob.wav"],
                )
                self.assertEqual(
                    [entry["sizeBytes"] for entry in checksums["tracks"]],
                    [len(b"alice"), len(b"bob")],
                )


if __name__ == "__main__":
    unittest.main()
