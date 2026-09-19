# Audio Sync Merge Service Verification Matrix

This matrix translates `.omx/plans/test-spec-audio-sync-merge-service.md` into concrete evidence that operators and implementers can gather before claiming release readiness.

## Evidence policy
- Every acceptance criterion must have at least one machine-generated artifact and, where required, one operator-confirmed note.
- Store raw command output under `verification/evidence/<timestamp>/`.
- When a criterion cannot yet be verified because upstream implementation is incomplete, record it explicitly as `BLOCKED` with the missing dependency.
- Do not mark the service release-ready while any AC is `BLOCKED` or `FAIL`.

## Acceptance criteria to evidence map
| AC | Goal | Primary evidence | Supporting evidence | Suggested command / source |
|---|---|---|---|---|
| AC1 | Up to 5 participants / 1 hour | End-to-end processing record for a 5-track / 60-minute fixture session | Runtime and memory notes | `verification/evidence/*/pipeline-smoke.log`, load-test output |
| AC2 | Canonicalization independent of input format | Mixed-format fixture run showing canonical output metadata | Rejection logs for unsupported/corrupt inputs | Canonicalization test output, `ffprobe` summaries, unit test logs |
| AC3 | Aligned tracks bundle exists | Artifact manifest showing per-track aligned outputs | Download / bundle checksum list | Export step logs, artifact directory listing |
| AC4 | Listening mixdown exists | Mixdown artifact checksum and duration | Manual listening rubric sheet | Export step logs, listening review note |
| AC5 | Manifest includes offset / drift / QA | Manifest JSON inspection against documented field meanings | Schema or serialization tests | Manifest file, manifest-focused tests |
| AC6 | Sync error p95 ≤ 10ms is verifiable | Benchmark report on synthetic corpus | Raw per-track residual error samples | Benchmark output, regression report |
| AC7 | No overlap/howling + loudness consistency | Completed listening rubric and loudness spread report | Operator sign-off note | Manual review sheet, benchmark output |
| AC8 | Non-goals remain excluded | Scope audit confirming no real-time / diarization / editing UI / video sync code paths | Release checklist sign-off | Code search output, release note checklist |
| AC9 | Corrupt/unsupported input rejected early | Failure-path log showing file-scoped rejection before DSP | Error taxonomy notes | Integration tests, upload / validation logs |

## Release gate summary template
Use this table in the final release note or task completion message.

| AC | Status (`PASS` / `FAIL` / `BLOCKED`) | Evidence path | Notes |
|---|---|---|---|
| AC1 | BLOCKED | _fill after load/e2e run_ | Requires synthetic/device corpus |
| AC2 | BLOCKED | _fill after ingestion tests_ | |
| AC3 | BLOCKED | _fill after export implementation_ | |
| AC4 | BLOCKED | _fill after mixdown implementation_ | |
| AC5 | BLOCKED | _fill after manifest implementation_ | |
| AC6 | BLOCKED | _fill after benchmark implementation_ | |
| AC7 | BLOCKED | _fill after listening review_ | |
| AC8 | PASS | docs/audio-sync-merge-scope-audit.md | Initial scope guard documented |
| AC9 | BLOCKED | _fill after validation tests_ | |
