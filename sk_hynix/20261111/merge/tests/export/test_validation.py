from pathlib import Path
import unittest

from audio_sync.export import (
    AlignedTrackArtifact,
    ExportArtifacts,
    MixArtifact,
    build_export_manifest,
    build_exports_from_file_records,
    build_recog_manifest,
    validate_export_manifest,
    validate_recog_manifest,
)
from recog.models import FileRecord


class ManifestValidationTests(unittest.TestCase):
    def test_validate_export_manifest_accepts_valid_payload(self) -> None:
        manifest = build_export_manifest(
            ExportArtifacts(
                session_id="session-1",
                tracks=(
                    AlignedTrackArtifact(
                        track_id="track-1",
                        participant_id="alice",
                        aligned_path=Path("aligned/alice.wav"),
                    ),
                ),
                mix_artifact=MixArtifact(output_path=Path("mix/listening_mix.wav")),
                qa_summary={"alignment": "pass"},
            )
        )

        validate_export_manifest(manifest)

    def test_validate_recog_manifest_accepts_valid_payload(self) -> None:
        exports = build_exports_from_file_records(
            session_id="session-2",
            files=[
                FileRecord(
                    file_id="file-1",
                    participant_id="alice",
                    filename="alice.wav",
                    uploaded_path="uploads/alice.wav",
                    aligned_path="aligned/alice.wav",
                )
            ],
            mix_output_path=Path("mix/listening_mix.wav"),
        )

        manifest = build_recog_manifest(exports)

        validate_recog_manifest(manifest)

    def test_validate_export_manifest_rejects_missing_track_list(self) -> None:
        with self.assertRaisesRegex(ValueError, "tracks"):
            validate_export_manifest(
                {
                    "sessionId": "session",
                    "schemaVersion": "1.0",
                    "canonicalFormat": {},
                    "recommendedSttInput": "tracks",
                    "qaSummary": {},
                }
            )


if __name__ == "__main__":
    unittest.main()
