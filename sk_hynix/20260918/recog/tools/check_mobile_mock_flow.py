#!/usr/bin/env python3
"""Validate that the mobile mock flow covers the expected baseline session stages."""

from __future__ import annotations

import json
from pathlib import Path

REQUIREMENTS = {
    'mobile_app/lib/app/mock_host_member_flow.dart': [
        'class MockHostMemberFlow',
        'PreflightFlowService',
        'RecordingFlowService',
        'UploadFlowService',
        'ResultFlowService',
        'run() async',
    ],
    'mobile_app/lib/features/home/home_controller.dart': [
        '_sessionController.onRoomCreatedDto',
        '_sessionController.onRoomJoined',
    ],
    'mobile_app/lib/features/room/domain/room_flow_service.dart': [
        'AppBootstrap.sessionController.onRoomPolled',
        'AppBootstrap.sessionController.onStartReceived',
    ],
    'mobile_app/lib/app/mock_flow_snapshot_formatter.dart': [
        "'preflight'",
        "'recording'",
        "'upload'",
        "'result'",
        "'classification'",
    ],
    'mobile_app/lib/features/preflight/domain/preflight_flow_service.dart': [
        'controller.setResult',
        'routeBridge.inspectCurrentRoute',
        'timeSyncBridge.measureTimeSync',
        'submitPreflight',
        'AppBootstrap.sessionController.onPreflightRequired',
        'AppBootstrap.sessionController.onPreflightCompleted',
    ],
    'mobile_app/lib/features/recording/domain/recording_flow_service.dart': [
        'prepareRecorder',
        'startRecording',
        'scheduleSyncBeep',
        "status: 'recording'",
        'AppBootstrap.sessionController.onRecorderStarted',
        'AppBootstrap.sessionController.onBeepScheduled',
        'AppBootstrap.sessionController.onBeepPlayed',
    ],
    'mobile_app/lib/features/upload/domain/upload_flow_service.dart': [
        'UploadBundleBuilder',
        'buildEnvelope(',
        'uploadRecording',
        'onUploadCompleted',
        'AppBootstrap.sessionController.onUploadStarted',
        'AppBootstrap.sessionController.onUploadCompleted',
    ],
    'mobile_app/lib/features/result/domain/result_flow_service.dart': [
        'fetchSession',
        'processingStatus',
        'artifacts:',
        'AppBootstrap.sessionController.onProcessingCompleted',
    ],
    'mobile_app/lib/features/preflight/presentation/preflight_screen.dart': [
        'Continue to recording',
        'FutureBuilder',
        'AppBootstrap.sessionController.state',
    ],
    'mobile_app/lib/features/recording/presentation/recording_screen.dart': [
        'Continue to upload',
        'beepPlayedAt',
        'FutureBuilder',
        '_resolveStartResponse',
        'arguments: _controller.state',
        'AppBootstrap.sessionController.state',
    ],
    'mobile_app/lib/features/upload/presentation/upload_screen.dart': [
        'Open result',
        'UploadStatusBanner',
        'FutureBuilder',
        '_resolveRecordingState',
        'arguments: MockSessionContext.sessionId',
        'AppBootstrap.sessionController.state',
    ],
    'mobile_app/lib/features/result/presentation/result_screen.dart': [
        'ResultSummaryCard',
        'ArtifactList',
        'QA summary',
        '_resolveSessionId',
        'AppBootstrap.sessionController.state',
    ],
    'mobile_app/lib/features/room/presentation/room_lobby_screen.dart': [
        "arguments: startResponse",
        'Run preflight as participant',
    ],
}


def main() -> int:
    root = Path.cwd()
    items = []
    ok = True
    for rel, markers in REQUIREMENTS.items():
        path = root / rel
        exists = path.exists()
        text = path.read_text(encoding='utf-8') if exists else ''
        missing = [marker for marker in markers if marker not in text]
        if not exists or missing:
            ok = False
        items.append({
            'path': rel,
            'exists': exists,
            'required_markers': markers,
            'missing_markers': missing,
        })
    payload = {
        'schema_version': 'mobile-mock-flow-check/v1',
        'ok': ok,
        'required_file_count': len(REQUIREMENTS),
        'items': items,
    }
    print(json.dumps(payload, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
