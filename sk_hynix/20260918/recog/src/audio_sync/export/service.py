from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .compat import build_recog_manifest
from .manifest import build_export_manifest, write_manifest
from .mixdown import ListeningMixPlan, build_listening_mix_plan
from .models import ExportArtifacts
from .package import create_artifact_bundle
from .recog_adapter import build_exports_from_file_records


@dataclass(frozen=True)
class ExportBuildResult:
    manifest_path: Path
    compat_manifest_path: Path | None
    bundle_path: Path | None
    mix_plan: ListeningMixPlan | None


def build_session_export(
    exports: ExportArtifacts,
    *,
    manifest_path: Path,
    compat_manifest_path: Path | None = None,
    bundle_path: Path | None = None,
) -> ExportBuildResult:
    mix_plan = None
    if exports.mix_artifact is not None:
        mix_plan = build_listening_mix_plan(exports.tracks, exports.mix_artifact)

    manifest_payload = build_export_manifest(exports)
    manifest_destination = write_manifest(manifest_payload, manifest_path)

    compat_destination = None
    if compat_manifest_path is not None:
        compat_payload = build_recog_manifest(exports)
        compat_destination = write_manifest(compat_payload, compat_manifest_path)

    bundle_destination = None
    if bundle_path is not None:
        bundle_destination = create_artifact_bundle(
            bundle_path,
            manifest_path=manifest_destination,
            compat_manifest_path=compat_destination,
            track_paths=tuple(track.aligned_path for track in exports.tracks),
            mixdown_path=exports.mix_artifact.output_path if exports.mix_artifact else None,
        )

    return ExportBuildResult(
        manifest_path=manifest_destination,
        compat_manifest_path=compat_destination,
        bundle_path=bundle_destination,
        mix_plan=mix_plan,
    )


def build_file_record_session_export(
    *,
    session_id: str,
    files,
    manifest_path: Path,
    mix_output_path: str | Path | None,
    compat_manifest_path: Path | None = None,
    bundle_path: Path | None = None,
    qa_summary: dict | None = None,
    recommended_stt_input: str | None = None,
) -> ExportBuildResult:
    exports = build_exports_from_file_records(
        session_id=session_id,
        files=list(files),
        mix_output_path=mix_output_path,
        qa_summary=qa_summary,
        recommended_stt_input=recommended_stt_input,
        bundle_path=bundle_path,
    )
    return build_session_export(
        exports,
        manifest_path=manifest_path,
        compat_manifest_path=compat_manifest_path,
        bundle_path=bundle_path,
    )
