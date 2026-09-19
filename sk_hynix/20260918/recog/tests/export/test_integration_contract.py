from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from zipfile import ZipFile

from audio_sync.export import (
    build_exports_from_file_records,
    build_recog_manifest,
    build_session_export,
    validate_recog_manifest,
)
from recog.models import FileRecord


class ExportIntegrationContractTests(unittest.TestCase):
    def test_file_records_to_manifest_and_bundle_contract(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            aligned = root / "aligned.wav"
            aligned.write_bytes(b"aligned-track")
            stt = root / "aligned.stt.wav"
            stt.write_bytes(b"stt-track")
            upload = root / "upload.m4a"
            upload.write_bytes(b"source-track")
            mix = root / "listening_mix.wav"
            mix.write_bytes(b"mix-track")

            exports = build_exports_from_file_records(
                session_id="session-contract",
                files=[
                    FileRecord(
                        file_id="file-1",
                        participant_id="alice",
                        filename="alice.m4a",
                        uploaded_path=str(upload),
                        aligned_path=str(aligned),
                        stt_path=str(stt),
                        offset_seconds=0.25,
                        drift_ppm=2.0,
                        correction_factor=1.000002,
                        alignment_confidence=0.93,
                        loudness_dbfs=-18.1,
                    )
                ],
                mix_output_path=mix,
                qa_summary={"clipped_samples_mix": 0, "loudness_spread_db": 0.0},
                bundle_path=root / "aligned_tracks.zip",
            )

            compat_manifest = build_recog_manifest(exports)
            validate_recog_manifest(compat_manifest)

            result = build_session_export(
                exports,
                manifest_path=root / "manifest.json",
                bundle_path=root / "aligned_tracks.zip",
            )

            manifest_json = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest_json["recommendedSttInput"], "mixdown")
            with ZipFile(result.bundle_path) as archive:  # type: ignore[arg-type]
                self.assertIn("manifest.json", archive.namelist())
                self.assertIn("tracks/aligned.wav", archive.namelist())
                self.assertIn("mix/listening_mix.wav", archive.namelist())

            self.assertEqual(compat_manifest["tracks"][0]["stt_path"], str(stt))
            self.assertEqual(compat_manifest["qa_summary"]["clipped_samples_mix"], 0)


if __name__ == "__main__":
    unittest.main()
