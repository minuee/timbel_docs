<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Scripts

## Purpose

Operational shell and Python scripts for field validation, device bootstrap, PoC checks, and evidence collection. Orchestrate tools and coordinate multi-step test runs. Not for regular development—primarily used during release gates and PoC validation.

## Key Files (Shell)

| File | Purpose |
|------|---------|
| `bootstrap_controlled_device_run.sh` | Initialize controlled-device test environment (directories, fixtures, evidence bundle) |
| `finalize_controlled_device_run.sh` | Finalize controlled-device run (compress artifacts, compute hashes, validate completeness) |
| `bootstrap_field_validation_run.sh` | Initialize field validation run (device setup, baseline checks, permission validation) |
| `finalize_field_validation_run.sh` | Finalize field validation run (collect evidence, generate report, cleanup temporary files) |
| `bootstrap_mobile_validation_evidence.sh` | Prepare mobile validation evidence structure (directories for iOS/Android results) |
| `prepare_mobile_validation_run.sh` | Pre-flight checks for mobile validation (Flutter version, device availability) |
| `update_mobile_validation_status.sh` | Update mobile validation status file during test execution |
| `sync_mobile_validation_metadata.sh` | Sync mobile validation metadata across test phases |
| `print_mobile_validation_summary.sh` | Print human-readable summary of mobile validation results |
| `check_flutter_poc_prereqs.sh` | Check Flutter PoC prerequisites (Flutter SDK, Dart, device connectivity) |
| `run_flutter_run_ready_checks.sh` | Pre-flight checks before running `flutter run` (device online, build state) |
| `run_recorder_poc_check.sh` | Run recorder PoC validation (iOS + Android recording tests) |
| `run_scope_audit.sh` | Audit project scope against plan (file counts, LOC, module counts) |
| `launch_virtual_test_devices.sh` | Launch virtual test devices (Android emulator + iOS simulator) |
| `collect_verification_evidence.sh` | Collect all verification evidence into single bundle |
| `record_run_command.sh` | Record the command used to start a test run (for reproducibility) |

## Key Files (Python)

| File | Purpose |
|------|---------|
| `append_experiment_ledger.py` | Log test run metadata to experiment ledger (params, results, timestamp) |
| `export_session_to_evidence_bundle.py` | Export completed session to evidence bundle (artifacts, metadata, logs) |
| `prepare_runtime_device_evidence_dir.py` | Prepare runtime directory structure for device evidence collection |
| `validate_manifest_contract.py` | Validate manifest against contract spec (schema, file presence, hashes) |

## For AI Agents

### Working In This Directory

These are orchestration scripts, rarely modified. Invoked manually during PoC validation or integrated into CI/CD pipelines.

**Typical execution sequence:**

```bash
# Controlled-device test run
./scripts/bootstrap_controlled_device_run.sh
PYTHONPATH=src python3 tools/run_controlled_session_scaffold.py /tmp/controlled_run
./scripts/finalize_controlled_device_run.sh

# Field validation
./scripts/bootstrap_field_validation_run.sh
./scripts/run_recorder_poc_check.sh
./scripts/finalize_field_validation_run.sh
./scripts/print_mobile_validation_summary.sh
```

### Testing Requirements

- Shell scripts validated by `tests/scripts/test_*.sh` (bash unit tests)
- Python scripts tested by `tests/scripts/test_*.py`:
  - Verify script produces expected output files
  - Verify error handling (missing input, invalid JSON)
- Integration: `Makefile` targets may chain scripts for release gates

### Common Patterns

- **Directory structure**: Scripts create predictable trees (`{run-id}/evidence/`, `{run-id}/artifacts/`, `{run-id}/logs/`)
- **Status files**: JSON status at `{run-id}/status.json` (machine-readable) and markdown summary at `{run-id}/SUMMARY.md` (human-readable)
- **Error handling**: `set -e` in shell scripts (exit on first error); Python scripts use `sys.exit(1)` on validation failure
- **Logging**: All steps logged to `{run-id}/logs/{step}.log`; stdout also echoed for user visibility

## Dependencies

### Internal (Python)

- `testkit/` — For fixture generation and report rendering
- `src/recog/`, `src/audio_sync/` — Core library functions

### Internal (Shell)

- Calls `python3` with `PYTHONPATH=src` for Python tools
- Calls `tools/*.py` and `testkit/` modules indirectly

### External

- **bash 4.0+** — For shell scripts
- **python3** — For Python runners
- **flutter** (conditional) — For mobile PoC checks only
- **adb** (conditional) — For Android device checks
- **xcrun** (conditional) — For iOS simulator checks

<!-- MANUAL: -->

