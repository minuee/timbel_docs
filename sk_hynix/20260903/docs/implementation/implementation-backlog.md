# Implementation Backlog

This backlog translates the planning artifacts into execution-ready workstreams.

## Workstream 0 — Recorder Feasibility Gate
### Goal
Prove whether Flutter can generate the research-baseline recording format.

### Tasks
- Run Flutter recorder PoC on iOS
- Run Flutter recorder PoC on Android
- Validate outputs with `tools/check_recorder_baseline.py`
- Record results in `docs/mobile/flutter-recorder-poc-template.md`
- Decide one of:
  - keep Flutter recorder strategy
  - keep Flutter + add native bridge
  - replace plugin
  - revisit recorder strategy

### Exit criteria
- Baseline validity decision is documented

## Workstream 1 — Contract Freeze
### Goal
Lock the capture-platform contracts before implementation fans out.

### Core docs
- `docs/product/audio-sync-capture-platform-prd.md`
- `docs/verification/metadata-schema.md`
- `docs/api/room-session-api.md`
- `docs/policy/recording-policy.md`
- `docs/policy/anchor-policy.md`

### Exit criteria
- App, server, backend, and test owners approve the five P0 docs

## Workstream 2 — Mobile App MVP
### Goal
Create a capture client that can join a room, record under policy, and upload file + metadata.

### Tasks
- Flutter shell
- room create/join screens
- lobby + ready flow
- host start handling
- recorder integration
- metadata JSON builder
- upload + retry
- route / policy checks

### Exit criteria
- One device can create/join a room and upload a valid baseline file with metadata

## Workstream 3 — Session / Control Server
### Goal
Implement the control plane for room lifecycle and metadata-aware uploads.

### Tasks
- `POST /rooms`
- `GET /rooms/{room_id}`
- `POST /rooms/{room_id}/join`
- `POST /rooms/{room_id}/ready`
- `POST /rooms/{room_id}/start`
- `POST /rooms/{room_id}/stop`
- `POST /sessions/{session_id}/files`
- metadata persistence
- host / all-ready validation
- file-level policy validation

### Exit criteria
- Room lifecycle and upload contract are functional end-to-end

## Workstream 4 — Backend Metadata + Alignment Upgrade
### Goal
Teach the processing engine to use app-produced metadata and anchor strategy.

### Tasks
- Extend models for capture metadata
- Ingest upload metadata in backend
- Add metadata prior hook
- Add anchor metadata hook
- Add degraded classification
- Keep current artifact generation path intact

### Exit criteria
- Backend accepts app metadata and preserves current artifacts

## Workstream 5 — Evidence Pipeline
### Goal
Make every experiment produce a reusable evidence bundle.

### Tasks
- Evidence directory creation
- Artifact collection
- Benchmark summary generation
- Listening review packet generation
- Release checklist scaffolding

### Exit criteria
- Each run can emit a timestamped evidence bundle under `verification/evidence/`

## Workstream 6 — Controlled-device Baseline
### Goal
Prove the app/server/backend path works with real phones under controlled rules.

### Tasks
- 2-device smoke
- 3-device / 10-minute run
- Start/end anchor verification
- Metadata completeness verification
- Artifact verification
- Operator notes and listening review packet generation

### Exit criteria
- Controlled-device baseline evidence exists and is reviewable

## Workstream 7 — Long-duration Validation
### Goal
Prove 5-device / 1-hour controlled-device feasibility.

### Tasks
- 5-device / 10-minute run
- 5-device / 1-hour run
- Drift summary
- Runtime / memory summary
- Failure-path review

### Exit criteria
- AC1 evidence bundle exists

## Workstream 8 — Field Validation
### Goal
Determine whether the system is usable and valuable in a real meeting.

### Tasks
- Real meeting pilot
- STT comparison vs central mic / simple mix / processed output
- Listening rubric completion
- Operator feedback collection

### Exit criteria
- AC7 evidence exists and a release decision can be made

## Suggested execution order
1. Workstream 0
2. Workstream 1
3. Workstream 2 + 3 in parallel
4. Workstream 4
5. Workstream 5
6. Workstream 6
7. Workstream 7
8. Workstream 8

## Important rule
Do not optimize DSP or expand product scope until Workstream 0 and Workstream 1 are closed.
