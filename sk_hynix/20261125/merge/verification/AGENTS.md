<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Verification: Evidence Artifacts and Controlled-Device Runs

## Purpose

Historical archive of verification evidence bundles and controlled-device test run outputs. Verification artifacts document proof of correctness: audio analysis results, metrics, manifest validation evidence, and controlled-environment baseline captures.

Evidence is **append-only historical data**. New evidence bundles are created via tooling (`tools/init_evidence_bundle.py`, `scripts/collect_verification_evidence.sh`), not by hand. Existing evidence directories must not be modified.

The verification tree serves as:
- **Proof of correctness**: Auditable record of successful test runs with metrics
- **Regression baseline**: Reference for comparing future runs against established performance
- **Decision support**: Evidence for release gates and PoC validation decisions

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `evidence/` | Evidence bundles and run artifacts (append-only) |

## For AI Agents

### Working In This Directory

**Do not modify or delete existing evidence directories.** They are immutable historical records.

**To create new evidence:**

1. Use tooling: `tools/init_evidence_bundle.py` to initialize a new bundle
2. Or use operational script: `scripts/collect_verification_evidence.sh` to capture run outputs
3. New bundles are automatically timestamped and stored in `verification/evidence/`

**To review evidence:**

1. Read the evidence bundle manifest (e.g., `verification/evidence/20260407T074959Z/manifest.json`)
2. Check subdirectories for specific artifacts (fixture, runtime, metrics, etc.)
3. Cross-reference with docs: `docs/verification/evidence-bundle-spec.md`

### Evidence Bundle Structure

Each timestamped bundle contains:
- `fixture/` — Input test data (recordings, metadata, configuration)
- `runtime/` — Runtime artifacts (aligned tracks, sessions, processing logs)
- `metrics/` — Computed metrics (alignment accuracy, SNR, processing time)
- `manifest.json` — Bundle metadata (timestamp, scenario, tool versions, outcomes)

Example path: `verification/evidence/20260407T074959Z/p5-smoke/runtime/sessions/session_aef824c5dcd0/`

### Named Evidence Runs

Some evidence directories use descriptive names for specific test campaigns:

| Directory | Purpose |
|-----------|---------|
| `TEST-CONTROLLED-RUN` | Controlled environment baseline (lab conditions) |
| `TEST-FIELD-RUN` | Field validation (real-world deployment) |
| `mobile/TEST-MOBILE-*` | Mobile recorder testing variants |
| `worker5-docs-pass*` | Worker-specific verification passes |

These are also append-only; do not modify existing runs.

## Common Verification Workflows

1. **Run controlled baseline**: `scripts/collect_verification_evidence.sh --scenario controlled-baseline`
2. **Analyze evidence**: `tools/analyze_evidence_bundle.py verification/evidence/20260407T074959Z`
3. **Compare against prior**: `tools/diff_evidence.py verification/evidence/20260407T074959Z verification/evidence/TEST-CONTROLLED-RUN`

## Dependencies

### Internal

- `tools/init_evidence_bundle.py` — Creates new evidence bundles
- `scripts/collect_verification_evidence.sh` — Collects run artifacts
- `docs/verification/evidence-bundle-spec.md` — Specifies bundle format

### External

None (evidence is static output data).

