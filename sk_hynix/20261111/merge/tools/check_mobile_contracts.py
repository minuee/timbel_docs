#!/usr/bin/env python3
"""Validate that key mobile_app scaffold files contain required contract markers."""

from __future__ import annotations

import json
from pathlib import Path

REQUIREMENTS = {
    'mobile_app/lib/app/bootstrap.dart': [
        'class AppBootstrap',
        "import '../native/recorder/recorder_bridge.dart';",
        "import '../native/time_sync/time_sync_bridge.dart';",
        "import '../native/route/route_bridge.dart';",
        "import '../native/beep/beep_bridge.dart';",
        'static const runtimeMode',
        'static final sessionController',
        'static final bridgeRegistry',
        'static RecorderBridge get recorderBridge',
    ],
    'mobile_app/lib/app/bridge_registry.dart': [
        'class BridgeRegistry',
        'factory BridgeRegistry.forMode',
        'MethodChannelRecorderBridge',
        'FakeRecorderBridge',
    ],
    'mobile_app/lib/app/mock_host_member_flow.dart': [
        'class MockHostMemberFlow',
        'MockHostMemberFlowSnapshot',
        'run()',
    ],
    'mobile_app/lib/features/room/data/room_dto.dart': [
        'class CreateRoomRequestDto',
        'CreateRoomResponseDto.fromJson',
        'class GetRoomResponseDto',
        'RoomEventDto.fromJson',
    ],
    'mobile_app/lib/features/preflight/data/preflight_dto.dart': [
        'class PreflightRequestDto',
        'class PreflightResponseDto',
        'PreflightResponseDto.fromJson',
    ],
    'mobile_app/lib/features/recording/data/recording_dto.dart': [
        'class StartRoomRequestDto',
        'class StartRoomResponseDto',
        'StartRoomResponseDto.fromJson',
    ],
    'mobile_app/lib/features/upload/data/upload_dto.dart': [
        'class RecordingEnvelopeDto',
        'class RecordingUploadResponseDto',
        'factory RecordingUploadResponseDto.fromJson',
        'toJson() =>',
    ],
    'mobile_app/lib/features/result/domain/result_controller.dart': [
        'class ResultController',
        'ResultState state =',
    ],
    'mobile_app/lib/features/result/data/result_dto.dart': [
        'class SessionResponseDto',
        'class QaSummaryDto',
        'ArtifactDto.fromJson',
    ],
    'mobile_app/lib/features/room/data/room_api_fake.dart': [
        "'minimum_ready_participants':",
    ],
    'mobile_app/lib/features/preflight/domain/preflight_flow_service.dart': [
        'class PreflightFlowService',
        'AppBootstrap.routeBridge',
        'AppBootstrap.timeSyncBridge',
        'AppBootstrap.preflightApi',
    ],
    'mobile_app/lib/features/recording/domain/recording_flow_service.dart': [
        'class RecordingFlowService',
        'AppBootstrap.recorderBridge',
        'AppBootstrap.beepBridge',
    ],
    'mobile_app/lib/features/upload/domain/upload_flow_service.dart': [
        'class UploadFlowService',
        'UploadBundleBuilder',
        'AppBootstrap.uploadApi',
    ],
    'mobile_app/lib/features/result/domain/result_flow_service.dart': [
        'class ResultFlowService',
        'AppBootstrap.resultApi',
    ],
    'mobile_app/lib/native/recorder/recorder_method_channel.dart': [
        'class MethodChannelRecorderBridge',
        'MethodChannel(\'audio_sync/recorder\')',
        'startRecording',
    ],
    'mobile_app/lib/native/time_sync/time_sync_method_channel.dart': [
        'class MethodChannelTimeSyncBridge',
        'MethodChannel(\'audio_sync/time_sync\')',
    ],
    'mobile_app/lib/native/route/route_method_channel.dart': [
        'class MethodChannelRouteBridge',
        'MethodChannel(\'audio_sync/route\')',
    ],
    'mobile_app/lib/native/beep/beep_method_channel.dart': [
        'class MethodChannelBeepBridge',
        'MethodChannel(\'audio_sync/beep\')',
    ],
    'mobile_app/ios/Runner/AudioSyncBridges/RecorderBridge.swift': [
        'final class RecorderBridge',
        'func getRecorderState',
        'func prepareRecorder',
        'func startRecording',
    ],
    'mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/RecorderBridge.kt': [
        'class RecorderBridge',
        'fun getRecorderState',
        'fun prepareRecorder',
        'fun startRecording',
    ],
}

VOCABULARY_REQUIREMENTS = {
    'mobile_app/lib/features/preflight/data/preflight_dto.dart': [
        "'noise_suppression'",
        "'echo_cancellation'",
    ],
    'mobile_app/lib/native/route/route_fake.dart': [
        "micRoute: 'built_in_mic'",
        "'noise_suppression'",
        "'echo_cancellation'",
    ],
    'mobile_app/lib/features/upload/domain/upload_flow_service.dart': [
        "micRoute: 'built_in_mic'",
        "'noise_suppression'",
        "'echo_cancellation'",
    ],
    'src/recog/protocol_models.py': [
        '"built_in_mic"',
    ],
}


def main() -> int:
    project_root = Path.cwd()
    report_items = []
    ok = True
    for relative, markers in REQUIREMENTS.items():
        path = project_root / relative
        exists = path.exists()
        content = path.read_text(encoding='utf-8') if exists else ''
        missing_markers = [marker for marker in markers if marker not in content]
        if not exists or missing_markers:
            ok = False
        report_items.append(
            {
                'path': relative,
                'exists': exists,
                'required_markers': markers,
                'missing_markers': missing_markers,
            }
        )

    for relative, markers in VOCABULARY_REQUIREMENTS.items():
        path = project_root / relative
        exists = path.exists()
        content = path.read_text(encoding='utf-8') if exists else ''
        missing_markers = [marker for marker in markers if marker not in content]
        if not exists or missing_markers:
            ok = False
        report_items.append(
            {
                'path': relative,
                'exists': exists,
                'required_markers': markers,
                'missing_markers': missing_markers,
            }
        )

    duplicate_checks = []
    time_sync_defs = []
    for path in project_root.joinpath('mobile_app/lib').rglob('*.dart'):
        content = path.read_text(encoding='utf-8')
        if 'class TimeSyncResultDto' in content:
            time_sync_defs.append(str(path.relative_to(project_root)))
    duplicate_missing = len(time_sync_defs) != 1
    if duplicate_missing:
        ok = False
    duplicate_checks.append(
        {
            'path': 'mobile_app/lib/**',
            'exists': True,
            'required_markers': ['single class TimeSyncResultDto definition'],
            'missing_markers': [] if not duplicate_missing else [f'found {len(time_sync_defs)} definitions: {time_sync_defs}'],
        }
    )

    payload = {
        'schema_version': 'mobile-contract-check/v1',
        'ok': ok,
        'required_file_count': len(REQUIREMENTS) + len(VOCABULARY_REQUIREMENTS) + len(duplicate_checks),
        'items': report_items + duplicate_checks,
    }
    print(json.dumps(payload, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
