<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Templates and Forms

## Purpose

Reusable document templates and evidence capture forms for standardizing the collection and documentation of experimental results, listening evaluations, and validation artifacts across the Audio Sync Capture Platform development lifecycle.

## Key Files

| File | Purpose |
|------|---------|
| `audio-sync-merge-evidence-summary.md` | Reusable template for documenting experimental evidence: session metadata (sessionId, participants, duration), audio evidence (sample file paths, format, codec, sample rate), manifest evidence (path, schemaVersion, alignment offsets), listening notes, QA findings, operator sign-off |

## For AI Agents

### Working In This Directory

1. **Evidence capture**: Use this template whenever running experiments, PoC validation, or baseline testing.
2. **Standardized documentation**: Templates ensure consistent evidence capture across operators and test phases.
3. **Evidence aggregation**: Completed templates are collected into evidence bundles (see `../verification/evidence-bundle-spec.md`) for gate decisions.

### Documentation Review

- Verify that template sections map to the evidence requirements in `../verification/evidence-bundle-spec.md`.
- Check that all template fields have clear instructions or examples (no ambiguity in what to fill in).
- Ensure template is scannable (headers, bullet points, empty fields with prompts) and not a wall of text.
- Validate that template can be completed without external references (but can link to related docs).
- Cross-reference template with relevant protocols (e.g., if template is for PoC, reference `../mobile/flutter-recorder-poc-runbook.md`).

### Common Patterns

- **Evidence types**: Audio files (original + processed), manifests (JSON), listening notes (subjective assessment), QA metrics (objective measurements).
- **Metadata capture**: Session ID, participant count, duration, device types, recording conditions (location, time, network state if relevant).
- **Operator sign-off**: Template signed by person who conducted the test, with date and contact info for follow-up questions.
- **Reproducibility**: Template includes enough detail that another operator could reproduce the test with the same results.

## Dependencies

### Internal

- `../verification/evidence-bundle-spec.md` — Specification for evidence bundle format and contents; templates feed this specification.
- `../mobile/flutter-recorder-poc-template.md` — PoC-specific template that extends this general template.
- `../mobile/native-smoke-evidence-template.md` — Native platform smoke test template.
- `../protocols/controlled-device-protocol.md` — Controlled-device protocol that uses evidence from these templates.
- `../protocols/field-validation-protocol.md` — Field-validation protocol that uses evidence from these templates.

### External

None.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Single general evidence template present; PoC and native-platform templates extend this. -->
