# Synthetic corpus scaffolding

This lane-4 scaffold gives the team a deterministic fixture source before the
service runtime is finalized.

## What it covers

- 2 / 3 / 5 participant session matrix for AC1 load-style coverage
- Sample-rate mismatch coverage for AC2 canonicalization checks
- Per-track offset and drift ground truth for AC5 / AC6 validation
- Corrupt and unsupported input placeholders for AC9 failure-path checks

## Current workflow

Run:

```bash
python3 -m unittest discover -s tests -v
```

Optional fixture generation:

```python
from testkit.synthetic_corpus import generate_integration_matrix
generate_integration_matrix("artifacts/synthetic")
```

Benchmark evaluation:

```bash
python3 tools/evaluate_synthetic_alignment.py \
  artifacts/synthetic/synthetic-session-p3/ground_truth.json \
  predictions.json
```

Regression-plan export:

```bash
python3 tools/render_regression_plan.py
```

Evidence-template export:

```bash
python3 tools/render_evidence_template.py
```

Artifact-contract export:

```bash
python3 tools/render_artifact_contract.py
```

Listening-rubric export:

```bash
python3 tools/render_listening_rubric.py
```

Failure-taxonomy export:

```bash
python3 tools/render_failure_taxonomy.py
```

Status-flow export:

```bash
python3 tools/render_status_flow.py
```

STT-handoff export:

```bash
python3 tools/render_stt_handoff.py
```

Benchmark-report export:

```bash
python3 tools/render_benchmark_report.py
```

## Notes for integration

- The fixtures are standard-library only, so they can run before the main DSP
  stack (ffmpeg/librosa/soxr/etc.) is locked.
- `ground_truth.json` is the contract artifact other lanes can consume for
  alignment, drift, manifest, and failure-path assertions.
- `testkit/verification_matrix.py` maps each synthetic fixture to the intended
  AC / verification-type coverage so later integration and evidence work can
  reuse one machine-readable matrix.
- `testkit/benchmark.py` turns predicted offsets/drift values into p50/p95/max
  sync metrics with `pass/degraded/fail` gating aligned to the test spec.
- `testkit/ingestion_matrix.py` captures the mixed-format ingestion contract
  (`wav` / `m4a` / `flac` + corrupt/unsupported rejection paths).
- `testkit/load_profile.py` captures the 5 participant / 60 minute load and
  retry scaffolding for later queue and benchmark implementation.
