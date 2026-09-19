<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Verification and Release Criteria

## Purpose

Verification criteria, evidence bundle specifications, metadata schema, and release gate definitions for the Audio Sync Capture Platform. These documents define what "done" means, how to collect evidence, and when the system is ready to advance from engineering to research to pilot phases.

## Key Files

| File | Purpose |
|------|---------|
| `evidence-bundle-spec.md` | Formal specification for evidence bundle format and contents: required artifacts (audio samples, manifests, logs), metadata headers, directory structure, compression format; used during controlled-device and field-validation protocols |
| `metadata-schema.md` | Formal specification for recording session metadata: participant identity, device identity, recording timestamps (requested start, actual start, stop), microphone route, audio device properties, metadata collected by mobile app and validated by backend |
| `release-gate.md` | Release gate criteria for advancing from engineering ready → research ready → pilot ready: Gate A (room/session flow working, synthetic baseline passing, artifacts generating), Gate B (controlled-device baseline complete, evidence bundles generating, operator confidence in alignment), Gate C (5-participant 1-hour evidence, human listening sign-off, release checklist complete) |

## For AI Agents

### Working In This Directory

1. **Acceptance criteria**: Use release-gate criteria and metadata-schema definitions when implementing features and designing acceptance tests.
2. **Evidence collection**: Reference evidence-bundle-spec when designing observation and logging in the Python MVP.
3. **Gate decisions**: Use these criteria when evaluating whether to advance to the next phase (check gate checklist, review collected evidence).
4. **Integration with platform**: Ensure backend (Python MVP) generates evidence bundles matching the spec; ensure metadata collection matches the schema.

### Documentation Review

- Verify that evidence-bundle-spec defines directory structure, file naming, and compression format clearly (no ambiguity in "how to package a bundle").
- Check that metadata-schema covers all fields collected by the Flutter mobile app and validated by the backend (device ID, participant ID, timestamps, microphone route, etc.).
- Validate that release gates have objective, measurable criteria (not subjective "looks good"; gate checks list specific artifacts and test results required).
- Ensure gate criteria map back to product requirements and acceptance criteria from `../product/` and `../audio-sync-merge-verification-matrix.md`.
- Cross-reference gate blockers (AC1: 5-participant evidence, AC7: human listening sign-off) with actual test procedures in `../protocols/`.

### Common Patterns

- **Gate progression**: Engineering ready (code works) → Research ready (controlled baseline works) → Pilot ready (real-world evidence + human evaluation complete).
- **Evidence artifacts**: Audio files (original + processed), manifests (JSON), logs (processing pipeline steps), listening notes (human evaluation).
- **Metadata completeness**: Every uploaded audio file paired with metadata headers (participant ID, device ID, start timestamp, microphone route, etc.).
- **Sign-off**: Gate decisions require sign-off from appropriate roles (engineer for Gate A, researcher for Gate B, product/leadership for Gate C).
- **Blockers vs. nice-to-haves**: Gate requirements list blocking issues (must pass) vs. optional issues (should address but can defer).

## Dependencies

### Internal

- `../audio-sync-merge-verification-matrix.md` — Acceptance criteria matrix (AC1–AC9) that these gates operationalize.
- `../protocols/controlled-device-protocol.md` — Gate B verification procedure; produces evidence bundles.
- `../protocols/field-validation-protocol.md` — Gate C verification procedure; produces evidence bundles.
- `../templates/audio-sync-merge-evidence-summary.md` — Template used to document evidence during protocol execution.
- `../product/audio-sync-capture-platform-prd.md` — Product requirements that gates verify.
- `src/recog/` — Python MVP backend that generates metadata and evidence bundles matching these specs.

### External

None.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Three verification documents present, covering evidence bundles, metadata schema, and release gates. -->
