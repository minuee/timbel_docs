# First Week Execution Plan

This document turns the implementation backlog into a practical week-one schedule.

## Weekly Goal
Prove that Flutter can generate the research-baseline recording format and complete one minimum end-to-end path:
- room/session contract approved
- recorder PoC executed
- room/session/upload skeleton implemented
- 2-device smoke attempted

## Day 1 — Contract Review + Recorder Setup
### Goals
- Approve P0 contracts
- Prepare recorder PoC workspace

### Tasks
- Review:
  - `docs/product/audio-sync-capture-platform-prd.md`
  - `docs/verification/metadata-schema.md`
  - `docs/api/room-session-api.md`
  - `docs/policy/recording-policy.md`
  - `docs/policy/anchor-policy.md`
- Pick initial Flutter recorder plugin candidate
- Prepare PoC app shell or spike branch
- Confirm iOS/Android test devices are available

### Done criteria
- Contract reviewers agree there are no blocking ambiguities
- Recorder plugin candidate is chosen
- PoC app workspace exists

## Day 2 — Recorder PoC
### Goals
- Record one file on iOS and one file on Android
- Validate baseline format

### Tasks
- Implement start/stop only
- Generate iOS sample file
- Generate Android sample file
- Run:

```bash
python3 tools/check_recorder_baseline.py <path/to/file.wav>
```

- Record outcomes in:
  - `docs/mobile/flutter-recorder-poc-template.md`

### Done criteria
- Both platform results are documented
- A strategy decision is made:
  - keep Flutter recorder strategy
  - keep Flutter + native bridge
  - switch plugin / revisit strategy

## Day 3 — Room / Session API Skeleton
### Goals
- Expose the minimal control-plane endpoints

### Tasks
- Implement:
  - `POST /rooms`
  - `GET /rooms/{room_id}`
  - `POST /rooms/{room_id}/join`
  - `POST /rooms/{room_id}/ready`
  - `POST /rooms/{room_id}/start`
- Add minimal room/session persistence
- Add host / all-ready validation

### Done criteria
- API routes respond correctly
- Room state changes are persisted

## Day 4 — Flutter Room Flow + Metadata Builder
### Goals
- Wire the app to the control plane
- Build upload-ready metadata

### Tasks
- Create room/join screens
- Create lobby + ready flow
- Trigger host start from UI
- Build metadata JSON builder with required fields
- Capture `recording_started_at` and related timing data

### Done criteria
- App can create/join room and reach ready/start flow
- Metadata JSON can be printed or stored locally

## Day 5 — Upload + Backend Metadata Ingest + Smoke
### Goals
- Connect file upload to backend
- Attempt first end-to-end smoke

### Tasks
- Implement `POST /sessions/{session_id}/files`
- Send file + metadata multipart upload
- Extend backend models for capture metadata
- Ingest upload metadata into backend session/file records
- Attempt 2-device smoke

### Done criteria
- One session can upload file + metadata
- Backend accepts metadata without breaking artifacts
- 2-device smoke has at least one complete run result

## Week-end Review Questions
- Did the recorder PoC pass the baseline check?
- Can two devices join the same room and start a session?
- Can the backend ingest metadata and still produce artifacts?
- What is the next blocker: recorder, control plane, or processing engine?

## Immediate References
- `docs/implementation/next-steps.md`
- `docs/implementation/implementation-backlog.md`
- `docs/implementation/flutter-recorder-poc-task.md`
- `docs/mobile/flutter-recorder-poc-template.md`
