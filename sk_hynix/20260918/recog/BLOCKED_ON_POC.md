# Blocked on Flutter Recorder PoC

## Current status
All repo-side planning, documentation, validation helpers, and handoff artifacts are complete.

## Why work is blocked
Further progress depends on an external Flutter-capable environment. This repo cannot continue meaningfully until the recorder PoC is executed and actual output files are produced.

## Unblock condition
Bring back the Flutter recorder PoC results:
- iOS result: PASS / PARTIAL / FAIL
- Android result: PASS / PARTIAL / FAIL
- `scripts/run_recorder_poc_check.sh` output JSON
- route detection result
- timestamp capture result

## Once unblocked
The next decision will be one of:
- keep Flutter recorder strategy
- keep Flutter + native bridge
- change plugin
- revisit recorder strategy
