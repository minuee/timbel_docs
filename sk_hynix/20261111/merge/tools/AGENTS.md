<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Tools

## Purpose

Standalone Python CLI tools for verification, benchmarking, and evidence generation. Thin runners that call into `testkit/` and `src/` packages. Each tool is independently executable for testing, PoC validation, and release gates.

## Key Files

| File | Purpose |
|------|---------|
| `generate_synthetic_corpus.py` | Generate synthetic test session corpus (tones, noise, silence, mixed) with configurable parameters |
| `run_load_probe.py` | Repeatable load stress test: process N sessions, measure latency, generate listening rubric |
| `evaluate_synthetic_alignment.py` | Evaluate alignment quality on synthetic corpus (accuracy, drift bounds) |
| `benchmark_anchor_detector.py` | Benchmark anchor detection performance (precision, recall on silence boundaries) |
| `check_recorder_baseline.py` | Validation check: confirm audio canonicalization baseline (format, sample rate, channels) |
| `check_mobile_contracts.py` | Validate Flutter mobile recorder API contracts (upload format, metadata schema) |
| `check_mobile_scaffold.py` | Check Flutter scaffold build status and device availability |
| `check_mobile_mock_flow.py` | Test mock mobile flow (simulated uploads without actual device) |
| `export_controlled_device_bundle.py` | Export controlled-device test bundle (known offsets, fixtures) for validation |
| `init_evidence_bundle.py` | Initialize evidence bundle structure for new test run |
| `render_artifact_contract.py` | Render artifact contract spec (manifest schema, file requirements) |
| `render_benchmark_report.py` | Render benchmark results to markdown report |
| `render_evidence_template.py` | Render evidence template for test results |
| `render_failure_taxonomy.py` | Render failure case taxonomy (categories, recovery strategies) |
| `render_listening_rubric.py` | Render listening test rubric (qualitative audio checklist) |
| `render_regression_plan.py` | Render regression test plan (past failures, coverage matrix) |
| `render_status_flow.py` | Render session state machine diagram |
| `render_stt_handoff.py` | Render STT handoff manifest specification |
| `run_controlled_session_scaffold.py` | Run controlled-device session scaffold (known offsets for validation) |
| `summarize_recorder_poc.py` | Summarize Flutter recorder PoC results (decision gates, pass/fail) |

## For AI Agents

### Working In This Directory

Each tool is independently runnable from the repository root with `PYTHONPATH=src python3 tools/<script>.py [args]`.

**Common usage patterns:**

```bash
# Generate synthetic corpus
PYTHONPATH=src python3 tools/generate_synthetic_corpus.py --tracks 3 --duration 30

# Run load probe
PYTHONPATH=src python3 tools/run_load_probe.py /tmp/probe_run --tracks 5 --duration 60

# Check baseline
PYTHONPATH=src python3 tools/check_recorder_baseline.py

# Render reports
PYTHONPATH=src python3 tools/render_benchmark_report.py /tmp/benchmark_results.json

# Summarize PoC
PYTHONPATH=src python3 tools/summarize_recorder_poc.py /path/to/poc/results/
```

### Testing Requirements

- Each tool is tested via `tests/tools/test_*.py`:
  - Verify tool exits 0 on valid input
  - Verify tool produces expected output files (JSON, markdown, tar.gz)
  - Verify error handling (invalid args, missing input, permission errors)
- Integration: `scripts/` calls these tools in sequences for PoC validation and evidence collection

### Common Patterns

- **Argument parsing**: Use `argparse` for CLI interface; all tools support `--help`
- **Output**: JSON or markdown (no binary; if tar.gz, must be gzipped tar not raw)
- **Exit codes**: 0 success, 1 validation error, 2 processing error, 3 missing dependency
- **Logging**: Print to stdout (tools output) and stderr (diagnostics); no file logging

## Dependencies

### Internal

- `testkit/` — Fixture generators, report renderers, validators
- `src/audio_sync/`, `src/recog/` — Core library functions

### External

- **stdlib argparse, json, pathlib, subprocess** — Core utilities
- **PYTHONPATH=src** — Required to import audio_sync and recog

<!-- MANUAL: -->

