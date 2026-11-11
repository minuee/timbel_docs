<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Testkit

## Purpose

Python test helpers and evidence artifact generators. Provides fixtures, scaffolding, rubrics, and validation matrices for controlled testing and PoC decision gates. Not executed directly; imported by `tools/` and test suite.

## Key Files

| File | Purpose |
|------|---------|
| `synthetic_corpus.py` | Generator for synthetic test sessions (silence, tones, white noise, mixed) with configurable duration/track count |
| `controlled_bundle.py` | Builder for controlled-device test bundles with known offsets and drift profiles |
| `artifact_contract.py` | Artifact specification: validates bundle structure, manifest schema, file presence |
| `benchmark.py` | Benchmark runner: measures alignment accuracy, drift estimation, export time |
| `benchmark_report.py` | Report formatter: renders benchmark results to markdown/JSON |
| `evidence_report.py` | Evidence template generator: formats test results as structured markdown |
| `verification_matrix.py` | Matrix builder: cross-validation of alignment quality (accuracy, precision, recall) |
| `failure_taxonomy.py` | Failure case categorizer: misalignment causes (silence, noise, clipping, format mismatch) |
| `ingestion_matrix.py` | Ingestion test matrix: validates file format handling (WAV, MP3, AAC, M4A, OGG) |
| `listening_rubric.py` | Listening test rubric: qualitative audio quality checklist (clipping, noise, panning, sync) |
| `listening_review.py` | Listening review generator: prefilled markdown for human verification |
| `load_profile.py` | Load profile builder: parametrizes track count, duration, format variety for stress tests |
| `regression_plan.py` | Regression test plan: tracks past failures to prevent regressions |
| `status_flow.py` | Status state machine: renders session state transitions for documentation |
| `stt_handoff.py` | STT handoff spec: validates manifest for speech recognition downstream contracts |

## For AI Agents

### Working In This Directory

Pure helper library—no CLI, no execution. Imported by `tools/` and test suite.

**Typical usage:**

```python
from testkit import synthetic_corpus, benchmark, listening_rubric

# Generate synthetic test session
corpus = synthetic_corpus.generate_session(
    track_count=3,
    duration_seconds=30,
    sample_rate=48000
)

# Run benchmark
results = benchmark.run_alignment_benchmark(corpus)

# Generate listening rubric
rubric = listening_rubric.create_rubric(results)
```

### Testing Requirements

- Testkit itself is tested by `tests/testkit/test_*.py`:
  - `test_synthetic_corpus.py` — Corpus generation produces valid audio
  - `test_controlled_bundle.py` — Bundle builder creates expected structure
  - `test_artifact_contract.py` — Validation catches schema violations
  - `test_benchmark.py` — Benchmark reporting is accurate
- Integration: `tools/run_load_probe.py` uses testkit to generate, process, and report

### Common Patterns

- **Builders**: Fluent/builder pattern for complex fixtures (`.with_duration().with_tracks().generate()`)
- **Templates**: Markdown/JSON templates with placeholders (filled by report generators)
- **Matrices**: Cross-product of parameters (format × duration × track_count)
- **Evidence**: All generators produce `EVIDENCE.json` sidecars with metadata (generation args, checksum, timestamp)

## Dependencies

### Internal

- No cross-testkit imports; each module is standalone

### External

- **stdlib json, pathlib, typing** — Core utilities
- **audio_sync** — To validate artifact bundles (imported by `artifact_contract.py`)

<!-- MANUAL: -->

