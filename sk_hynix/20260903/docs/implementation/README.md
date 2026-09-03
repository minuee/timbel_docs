# Audio Sync Capture Platform Documentation Index

This index links the planning, policy, implementation, and validation artifacts created for the project.

## 1. Core Contracts (P0)
- Product PRD: `../product/audio-sync-capture-platform-prd.md`
- Metadata Schema: `../verification/metadata-schema.md`
- Room / Session API: `../api/room-session-api.md`
- Recording Policy: `../policy/recording-policy.md`
- Anchor Policy: `../policy/anchor-policy.md`

## 2. App / Architecture (P1)
- Flutter App Requirements: `../mobile/flutter-app-requirements.md`
- Flutter State Machine: `../mobile/flutter-state-machine.md`
- Upload Contract: `../api/upload-contract.md`
- System Overview: `../architecture/system-overview.md`
- Synchronization Strategy: `../architecture/synchronization-strategy.md`

## 3. Validation / Operations (P2)
- Controlled-device Protocol: `../protocols/controlled-device-protocol.md`
- Evidence Bundle Spec: `../verification/evidence-bundle-spec.md`
- Field Validation Protocol: `../protocols/field-validation-protocol.md`
- Release Gate: `../verification/release-gate.md`
- Access / Retention Policy: `../policy/access-retention-policy.md`

## 4. Execution Documents
- Immediate Next Steps: `next-steps.md`
- Flutter Recorder PoC Task: `flutter-recorder-poc-task.md`
- First Week Execution Plan: `first-week-plan.md`
- Implementation Backlog: `implementation-backlog.md`
- Flutter Recorder PoC Template: `../mobile/flutter-recorder-poc-template.md`

## 5. Recommended Reading Order
1. Product PRD
2. Metadata Schema
3. Room / Session API
4. Recording Policy
5. Anchor Policy
6. Flutter App Requirements
7. Flutter State Machine
8. Upload Contract
9. Controlled-device Protocol
10. Immediate Next Steps / First Week Plan

## 6. Immediate Action
Use the following sequence to start execution:
1. Approve the five P0 documents
2. Run the Flutter recorder PoC
3. Record the result in the PoC template
4. Start the room/session API skeleton
5. Start backend metadata ingest

## 7. Key Rule
Do not optimize DSP before the capture contract and recorder baseline are proven.
