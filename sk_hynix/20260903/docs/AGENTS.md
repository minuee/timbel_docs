<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Documentation: Audio Sync Capture Platform

## Purpose

Canonical design, policy, protocol, and verification documentation for the Audio Sync Capture Platform — a Python MVP that aligns and merges up to 5 participant meeting recordings (48kHz mono PCM via ffmpeg) with STT-handoff manifest export, plus Flutter mobile recorder PoC.

The `docs/` tree is the single source of truth for:
- Product requirements and architectural decisions
- Data and process policies
- API contracts and schemas
- Implementation procedures and checklists
- Verification criteria and evidence protocols

## Key Files

| File | Purpose |
|------|---------|
| `audio-sync-capture-platform-overview.html` | Interactive visual overview of platform architecture and data flow |
| `audio-sync-real-workflow.html` | Detailed HTML walkthrough of a complete end-to-end meeting capture and merge workflow |
| `audio-sync-merge-manifest-interpretation.md` | Operational guide for reading the STT-handoff manifest contract produced by export lane |
| `audio-sync-merge-access-retention-policy.md` | Data retention, access control, and lifecycle management policy |
| `audio-sync-merge-listening-rubric-template.md` | Template and criteria for human subjective listening evaluation |
| `audio-sync-merge-operator-runbook.md` | Step-by-step operational procedures for running merge, alignment, and export workflows |
| `audio-sync-merge-release-checklist.md` | Final validation checklist before production release |
| `audio-sync-merge-scope-audit.md` | Scope boundary definitions and exclusion list for MVP and pilot phases |
| `audio-sync-merge-verification-matrix.md` | Acceptance criteria matrix mapping to test/evidence requirements |
| `next-implementation-priorities-ko.md` | Korean priority roadmap for immediate implementation phases |
| `next-steps-one-page-ko.md` | Korean one-page action plan for next sprint |
| `overall-progress-summary-ko.md` | Korean comprehensive project status and progress summary |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `api/` | REST API contracts: rooms/sessions control plane, file upload plane |
| `architecture/` | System topology, synchronization strategy, service/mobile interaction |
| `examples/` | Sample manifests and reference data structures |
| `implementation/` | Execution plans, backlog, PoC runbooks, first-week procedures |
| `mobile/` | Flutter recorder design, state machine, plugin comparison, PoC templates |
| `policy/` | Recording constraints, anchor detection policy, data access/retention rules |
| `product/` | Product requirements document (PRD) and vision |
| `protocols/` | Operational test protocols for controlled-device baseline and field validation |
| `schema/` | JSON Schema definitions for manifest, metadata, and evidence bundles |
| `templates/` | Reusable document templates for evidence capture and summary |
| `testing/` | Synthetic test corpus specification and integration matrix |
| `verification/` | Release gates, evidence bundle format, metadata schema, acceptance criteria |

## For AI Agents

### Working In This Directory

1. **Documentation review**: Read implementation-relevant sections from `product/`, `api/`, `architecture/`, and `verification/` before engineering work.
2. **Policy enforcement**: Cross-reference `policy/` documents during design reviews and testing (recording policy, anchor policy, access/retention).
3. **Manifest contracts**: Use `audio-sync-merge-manifest-interpretation.md` and `schema/audio-sync-merge-manifest.schema.json` as the operational contract for the export lane.
4. **Execution procedures**: Reference `implementation/` and `mobile/` docs for step-by-step procedures, checklists, and PoC templates.

### Documentation Review

- Verify markdown syntax: headers, links, code blocks, and cross-references.
- Check for broken internal references (e.g., `../api/room-session-api.md`).
- Validate that HTML files (`audio-sync-capture-platform-overview.html`, `audio-sync-real-workflow.html`) load without console errors.
- Cross-check policy and manifest examples against actual schema definitions.
- For Korean files: verify terminology consistency and formal tone (존댓말).

### Common Patterns

- **Manifest interpretation**: The manifest is the primary integration contract between the Python MVP and downstream STT systems. Update `audio-sync-merge-manifest-interpretation.md` and schema when contract changes.
- **Execution procedure**: PoC and operational runbooks should reference or include reusable templates from `templates/` (e.g., `audio-sync-merge-evidence-summary.md`).
- **Evidence protocol**: All validation artifacts must conform to `verification/evidence-bundle-spec.md` format.
- **Release criteria**: Gate decisions reference `verification/release-gate.md` and acceptance criteria in `audio-sync-merge-verification-matrix.md`.

## Dependencies

### Internal

- `src/recog/` — Python MVP implementation; consumes/generates artifacts described in schema and manifest docs.
- `apps/recorder-mobile/` — Flutter recorder app; implements policies from `policy/` and UI requirements from `mobile/`.
- `testkit/synthetic_corpus.py` — Synthetic test corpus generator; implements design from `testing/synthetic-corpus.md`.

### External

- ffmpeg (audio processing, sample-rate conversion, mixing) — requirements in `audio-sync-merge-operator-runbook.md`.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: All top-level files present, subdirectories mapped, inter-doc cross-references verified. -->
