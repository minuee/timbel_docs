#!/usr/bin/env python3
"""Validate audio-sync manifest shape without external dependencies."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


REQUIRED_TOP_LEVEL = {
    "schemaVersion": str,
    "sessionId": str,
    "generatedAt": str,
    "canonicalFormat": dict,
    "recommendedSttInput": str,
    "tracks": list,
    "qaSummary": dict,
}
REQUIRED_CANONICAL = {
    "sampleRateHz": int,
    "channels": int,
    "sampleFormat": str,
}
REQUIRED_TRACK = {
    "trackId": str,
    "participantId": str,
    "alignedArtifact": str,
    "offsetMs": (int, float),
    "driftPpm": (int, float),
    "gainDb": (int, float),
    "weight": (int, float),
}


def _expect_type(payload: dict[str, Any], key: str, expected: Any, errors: list[str]) -> None:
    if key not in payload:
        errors.append(f"missing key: {key}")
        return
    if not isinstance(payload[key], expected):
        errors.append(
            f"invalid type for {key}: expected {expected}, got {type(payload[key]).__name__}"
        )


def validate_manifest(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key, expected in REQUIRED_TOP_LEVEL.items():
        _expect_type(payload, key, expected, errors)

    if payload.get("recommendedSttInput") not in {"tracks", "mixdown"}:
        errors.append("recommendedSttInput must be 'tracks' or 'mixdown'")

    canonical = payload.get("canonicalFormat")
    if isinstance(canonical, dict):
        for key, expected in REQUIRED_CANONICAL.items():
            _expect_type(canonical, key, expected, errors)

    tracks = payload.get("tracks")
    if isinstance(tracks, list):
        if not tracks:
            errors.append("tracks must contain at least one entry")
        for index, track in enumerate(tracks):
            if not isinstance(track, dict):
                errors.append(f"tracks[{index}] must be an object")
                continue
            for key, expected in REQUIRED_TRACK.items():
                if key not in track:
                    errors.append(f"tracks[{index}] missing key: {key}")
                elif not isinstance(track[key], expected):
                    errors.append(
                        f"tracks[{index}].{key} has invalid type: {type(track[key]).__name__}"
                    )

    listening_mix = payload.get("listeningMix")
    if listening_mix is not None:
        if not isinstance(listening_mix, dict):
            errors.append("listeningMix must be an object when present")
        else:
            for key in ("path", "format", "codec", "targetLufs"):
                if key not in listening_mix:
                    errors.append(f"listeningMix missing key: {key}")

    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_manifest_contract.py <manifest.json>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_manifest(payload)
    if errors:
        print(f"manifest validation FAILED: {path}")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"manifest validation OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
