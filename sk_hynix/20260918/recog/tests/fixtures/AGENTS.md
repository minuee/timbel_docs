<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Tests: Fixtures (Regression Snapshots and Metadata)

## Purpose

Static test data and regression snapshots for unit and integration tests. Fixtures are read-only inputs used to verify that code behavior remains consistent across versions and that output matches expected contracts.

The fixture tree contains:
- **Metadata envelopes** (JSON): Recording envelope test cases for upload contract validation
- **Benchmark snapshots** (JSON): Lane4 regression baselines for alignment and DSP correctness

Do not modify existing fixture files without understanding the impact on dependent tests.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `lane4/` | Lane4 benchmark regression snapshots (integration matrix, threshold bounds) |
| `metadata/` | Recording envelope metadata fixtures (valid, degraded, edge cases) |

## For AI Agents

### Working In This Directory

Fixtures are **read-only** to tests. Tests import and parse fixture files but do not modify them.

Use fixtures as ground truth:
1. **Metadata validation**: Load fixture from `metadata/`, verify parsing against schema
2. **Regression detection**: Compare current output against snapshot from `lane4/`, flag differences
3. **Contract testing**: Verify that API responses match fixture structure expectations

### Modifying Fixtures

**Only update fixture files if:**

1. **Schema or contract changed** — documented in ADR or decision record
2. **Intentional regression** — approved by team, breaking change is justified
3. **Bug fix** — fixture contained incorrect data that tests incorrectly validated against

**Process for updating:**

1. Document reason in commit message (links ADR or issue)
2. Update fixture file(s)
3. Run affected tests to confirm they pass with new fixture
4. Verify no other tests regress

### Fixture Naming Conventions

- **Metadata**: `recording-envelope.<variant>.json` (e.g., `recording-envelope.valid.json`, `recording-envelope.missing-timing.json`)
- **Snapshots**: `<stage>-<scenario>.snapshot.json` (e.g., `integration-matrix.snapshot.json`)

## File Inventory

### `lane4/` (Benchmark snapshots)

| File | Purpose |
|------|---------|
| `benchmark-thresholds.snapshot.json` | Regression bounds for lane4 alignment metrics (SNR, phase error, drift) |
| `integration-matrix.snapshot.json` | End-to-end test matrix results (5-track scenarios, ground truth alignment) |

### `metadata/` (Recording envelope fixtures)

| File | Purpose |
|------|---------|
| `recording-envelope.valid.json` | Valid recording metadata (all fields present, sensible values) |
| `recording-envelope.missing-timing.json` | Recording metadata with missing/null timing fields (degraded case) |
| `recording-envelope.bluetooth.json` | Recording from Bluetooth device (real-world hardware case) |

## Dependencies

### Internal

- Tests in `tests/test_upload_metadata.py`, `tests/export/test_manifest.py` load fixtures
- Tests in `tests/dsp/` and `tests/export/` validate against snapshots

### External

None (fixtures are static JSON files).

