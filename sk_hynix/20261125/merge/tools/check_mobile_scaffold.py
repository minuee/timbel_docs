#!/usr/bin/env python3
"""Validate that the expected mobile_app scaffold exists and report coverage."""

from __future__ import annotations

import json
from pathlib import Path


REQUIRED_FILES = [
    "mobile_app/pubspec.yaml",
    "mobile_app/lib/main.dart",
    "mobile_app/lib/app/app.dart",
    "mobile_app/lib/app/bootstrap.dart",
    "mobile_app/lib/app/bridge_registry.dart",
    "mobile_app/lib/app/route_names.dart",
    "mobile_app/lib/app/mock_host_member_flow.dart",
    "mobile_app/lib/features/home/home_screen.dart",
    "mobile_app/lib/features/room/data/room_dto.dart",
    "mobile_app/lib/features/room/domain/session_controller.dart",
    "mobile_app/lib/features/preflight/data/preflight_dto.dart",
    "mobile_app/lib/features/preflight/domain/preflight_flow_service.dart",
    "mobile_app/lib/features/recording/data/recording_dto.dart",
    "mobile_app/lib/features/recording/domain/recording_flow_service.dart",
    "mobile_app/lib/features/upload/data/upload_dto.dart",
    "mobile_app/lib/features/upload/domain/upload_flow_service.dart",
    "mobile_app/lib/features/result/data/result_dto.dart",
    "mobile_app/lib/features/result/domain/result_flow_service.dart",
    "mobile_app/lib/native/recorder/recorder_fake.dart",
    "mobile_app/lib/native/recorder/recorder_method_channel.dart",
    "mobile_app/lib/native/time_sync/time_sync_fake.dart",
    "mobile_app/lib/native/time_sync/time_sync_method_channel.dart",
    "mobile_app/lib/native/route/route_fake.dart",
    "mobile_app/lib/native/route/route_method_channel.dart",
    "mobile_app/lib/native/beep/beep_fake.dart",
    "mobile_app/lib/native/beep/beep_method_channel.dart",
    "mobile_app/ios/Runner/AudioSyncBridges/RecorderBridge.swift",
    "mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/RecorderBridge.kt",
]


def main() -> int:
    project_root = Path.cwd()
    results = []
    for relative in REQUIRED_FILES:
        path = project_root / relative
        results.append(
            {
                "path": relative,
                "exists": path.exists(),
                "kind": "file",
            }
        )
    existing = sum(1 for item in results if item["exists"])
    payload = {
        "schema_version": "mobile-scaffold-check/v1",
        "required_count": len(results),
        "existing_count": existing,
        "missing_count": len(results) - existing,
        "ok": existing == len(results),
        "items": results,
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
