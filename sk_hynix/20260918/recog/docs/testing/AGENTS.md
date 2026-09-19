<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Testing and Validation Fixtures

## Purpose

Specification and design of the synthetic test corpus used for deterministic integration testing and baseline validation of the Audio Sync Capture Platform before real-world experiments. These documents define the fixture matrix, ground-truth generation procedures, and benchmark evaluation methodology.

## Key Files

| File | Purpose |
|------|---------|
| `synthetic-corpus.md` | Design specification for the synthetic test corpus: 2/3/5-participant session matrices for load-style coverage, sample-rate mismatch scenarios for canonicalization testing, per-track offset/drift ground-truth data for alignment validation, corrupt/unsupported input fixtures for error-path testing; includes fixture generation procedures (`testkit.synthetic_corpus.generate_integration_matrix`) and evaluation workflows |

## For AI Agents

### Working In This Directory

1. **Test fixture generation**: Reference this document when implementing or extending the synthetic corpus generator.
2. **Integration testing**: Use synthetic fixtures to validate alignment lane logic, manifest generation, and error handling before field testing.
3. **Benchmark baseline**: Use synthetic ground-truth data to evaluate alignment algorithm performance (offset accuracy, drift estimation).
4. **Regression detection**: Synthetic corpus provides a stable baseline for detecting algorithm regressions during development.

### Documentation Review

- Verify that synthetic corpus matrices (2/3/5 participant sessions) cover expected load patterns and edge cases (sample-rate mismatch, offset ranges, drift scenarios).
- Check that ground-truth offset/drift values are realistic and traceable (documented in the fixture or computed deterministically).
- Ensure corrupt/unsupported input fixtures exercise error paths (missing files, wrong codec, insufficient channels).
- Validate that fixture generation is deterministic (same seed produces same fixtures) for reproducibility.
- Cross-reference synthetic corpus design with acceptance criteria in `../audio-sync-merge-verification-matrix.md` (e.g., AC2: sample-rate mismatch handling).

### Common Patterns

- **Fixture matrix**: Varies participant count (2/3/5) to cover single/multi-track scenarios; varies sample-rate mismatch (44.1kHz, 48kHz mix) for canonicalization testing.
- **Ground truth**: Per-session fixture includes documented offset/drift values; used to evaluate alignment algorithm accuracy (e.g., within ±10ms for 2-participant, ±20ms for 5-participant).
- **Error paths**: Separate error fixtures (corrupt audio, unsupported codec, channel mismatch) for testing failure handling and error message quality.
- **Evaluation workflow**: `tools/evaluate_synthetic_alignment.py` compares predicted offsets against ground-truth; `tools/render_regression_plan.py` generates performance report.

## Dependencies

### Internal

- `testkit/synthetic_corpus.py` — Python implementation of synthetic corpus generator; implements design from this document.
- `tests/test_synthetic_corpus.py` — Unit tests validating synthetic corpus generation and evaluation.
- `src/recog/` — Python MVP that processes synthetic fixtures and produces alignment results for evaluation.
- `tools/evaluate_synthetic_alignment.py` — Evaluation tool that validates alignment accuracy against ground-truth.
- `tools/render_regression_plan.py` — Regression report generator.
- `../audio-sync-merge-verification-matrix.md` — Acceptance criteria that synthetic tests help validate (AC1: multi-participant coverage, AC2: sample-rate mismatch, AC5/AC6: offset/drift accuracy).

### External

None.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Single synthetic corpus specification present; covers matrix design, fixture generation, and evaluation workflow. -->
