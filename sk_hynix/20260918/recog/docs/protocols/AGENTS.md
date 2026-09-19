<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Operational Test Protocols

## Purpose

Step-by-step operational protocols for executing controlled experiments and field validation that verify the Audio Sync Capture Platform meets acceptance criteria. These documents define the test procedures, baseline configurations, evidence capture, and pass/fail criteria required before advancing to the next release gate.

## Key Files

| File | Purpose |
|------|---------|
| `controlled-device-protocol.md` | Lab-controlled baseline test protocol: participant setup, device configuration (built-in mics only, 48kHz mono), recording procedure (start beep → speech → end beep), alignment verification, evidence capture (audio files, manifest, listening notes) |
| `field-validation-protocol.md` | Field validation protocol for pilot testing: real-world participant recruitment, device configuration (pilot-mode relaxations allowed), multi-location/multi-timezone recording, alignment quality assessment, listening evaluation rubric, evidence bundle generation |

## For AI Agents

### Working In This Directory

1. **Test execution**: Follow these protocols precisely when running baseline experiments or pilot validation; deviation must be documented.
2. **Evidence capture**: Use evidence templates (see `../templates/`) to capture all required data during protocol execution.
3. **Gate determination**: Completion of these protocols and review of evidence determines release gate advancement (see `../verification/release-gate.md`).
4. **Operator training**: These protocols are the basis for operator training and runbook procedures (see `../audio-sync-merge-operator-runbook.md`).

### Documentation Review

- Verify that controlled-device protocol is strictly defined (no ambiguity in participant setup, device config, or recording procedure).
- Check that field-validation protocol handles real-world edge cases (network delays, time-zone differences, device heterogeneity) explicitly.
- Ensure evidence capture requirements are met by templates (see `../templates/audio-sync-merge-evidence-summary.md`).
- Validate that pass/fail criteria are objective and measurable (e.g., "offset within ±50ms" vs. "sounds correct").
- Cross-reference policy constraints (e.g., anchor detection requirement, microphone type) that these protocols must enforce.
- Verify that listening evaluation procedures align with the rubric (see `../audio-sync-merge-listening-rubric-template.md`).

### Common Patterns

- **Controlled baseline**: Strictly constrained (built-in mics, 48kHz mono, beep anchors) to maximize reproducibility and isolate issues.
- **Field validation**: Relaxed constraints (pilot-mode devices allowed) to test real-world conditions and participant acceptance.
- **Evidence-first**: All protocol results documented with supporting evidence (audio files, manifest, operator notes, listening assessment).
- **Iterative refinement**: Failures in controlled-device baseline trigger engineering fixes; field-validation failures trigger acceptance or post-pilot roadmap items.
- **Operator qualification**: Persons executing protocols should have read and understood the corresponding runbooks (e.g., `../audio-sync-merge-operator-runbook.md`).

## Dependencies

### Internal

- `../audio-sync-merge-operator-runbook.md` — Operational runbook that operators follow when executing these protocols.
- `../audio-sync-merge-listening-rubric-template.md` — Listening evaluation rubric referenced in field-validation protocol.
- `../templates/audio-sync-merge-evidence-summary.md` — Evidence capture template for documenting protocol results.
- `../policy/recording-policy.md` — Recording policy constraints that these protocols enforce.
- `../verification/release-gate.md` — Release gates that these protocol results support.

### External

None.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Two protocol documents present, covering controlled lab baseline and field validation. -->
