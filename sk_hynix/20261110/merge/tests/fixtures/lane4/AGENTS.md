<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Tests: Lane4 Benchmark Snapshots

## Purpose

Regression snapshot files for lane4 alignment testing. Lane4 is the integration test matrix that validates multi-participant alignment across controlled scenarios with known ground truth.

Snapshots capture:
- Benchmark thresholds: acceptable error bounds for alignment metrics (SNR, phase error, drift estimation error)
- Integration matrix: 5-track test scenarios with expected output signatures

Snapshots are regression baselines; tests compare current output against these snapshots to detect inadvertent performance degradation.

## Key Files

| File | Purpose |
|------|---------|
| `benchmark-thresholds.snapshot.json` | Regression bounds for alignment accuracy metrics |
| `integration-matrix.snapshot.json` | Expected signatures for 5-track integration test scenarios |

## For AI Agents

### Working In This Directory

Snapshots are **read-only inputs** to tests. Do not modify them directly.

**When updating snapshots:**

1. Run lane4 integration tests and capture new output
2. Compare against snapshot (diff should be minimal and justified)
3. If output legitimately improved or performance bounds changed, update snapshot with git commit referencing the reason (ADR, bug fix, optimization)
4. Always document why snapshot changed in commit message

### Using Snapshots in Tests

Tests in `tests/test_lane4_scaffolding.py` load these snapshots at runtime to:
1. Validate that current alignment output matches expected metrics
2. Detect regressions (if actual output falls outside bounds)
3. Regression testing: ensure fixes don't break previously-passing scenarios

## File Format

Both files are JSON structures with metric definitions and expected ranges. Examples:

```json
{
  "alignment_accuracy": {
    "phase_error_ms": {"min": 0, "max": 15},
    "snr_db": {"min": 25, "target": 35}
  }
}
```

## Dependencies

### Internal

- Test: `tests/test_lane4_scaffolding.py` loads and validates against these snapshots
- Fixtures: Lane4 test scenarios may reference audio or metadata from `tests/fixtures/metadata/`

### External

None (snapshots are static JSON).

