from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checksum_entry(path: Path) -> dict[str, str | int]:
    return {
        "path": path.name,
        "sha256": sha256_file(path),
        "sizeBytes": path.stat().st_size,
    }


def create_artifact_bundle(
    bundle_path: Path,
    *,
    manifest_path: Path,
    compat_manifest_path: Path | None = None,
    track_paths: tuple[Path, ...],
    mixdown_path: Path | None = None,
) -> Path:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    checksum_manifest = {
        "manifest": _checksum_entry(manifest_path),
        "tracks": [_checksum_entry(track) for track in track_paths],
    }
    if compat_manifest_path is not None:
        checksum_manifest["compatManifest"] = _checksum_entry(compat_manifest_path)
    if mixdown_path is not None:
        checksum_manifest["mixdown"] = _checksum_entry(mixdown_path)

    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.write(manifest_path, arcname=manifest_path.name)
        if compat_manifest_path is not None:
            archive.write(compat_manifest_path, arcname=compat_manifest_path.name)
        for track in track_paths:
            archive.write(track, arcname=f"tracks/{track.name}")
        if mixdown_path is not None:
            archive.write(mixdown_path, arcname=f"mix/{mixdown_path.name}")
        archive.writestr(
            "checksums.json",
            json.dumps(checksum_manifest, indent=2, sort_keys=True) + "\n",
        )

    return bundle_path
