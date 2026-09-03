<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Implementation Planning and Execution

## Purpose

Execution-level plans, sprint roadmaps, PoC task briefs, and immediate-action checklists for the Audio Sync Capture Platform. These documents guide day-to-day development and PoC validation work across backend (Python MVP) and mobile (Flutter recorder) tracks.

## Key Files

| File | Purpose |
|------|---------|
| `README.md` | Index and reading order for implementation documents; links core P0 contracts, recommended sequence for approval and execution |
| `first-week-plan.md` | Detailed day-by-day activities for sprint 0: API skeleton, synthetic corpus validation, Flutter recorder PoC kickoff |
| `flutter-recorder-poc-task.md` | Task brief for Flutter recorder PoC: scope (recorder baseline, file storage), exclusions (room/session flow, upload), success criteria |
| `implementation-backlog.md` | Prioritized backlog for post-PoC phases: room/session API completion, alignment lane hardening, manifest export, evidence protocols |
| `next-steps.md` | Immediate action items and blockers for next execution phase |

## For AI Agents

### Working In This Directory

1. **Sprint planning**: Reference `first-week-plan.md` to understand the planned execution sequence and workstream split (backend vs. mobile).
2. **PoC execution**: Use `flutter-recorder-poc-task.md` as the authoritative brief for Flutter recorder PoC scope and success criteria.
3. **Backlog prioritization**: Consult `implementation-backlog.md` when planning follow-on work after PoC completion.
4. **Immediate actions**: Check `next-steps.md` for the current blocking issues and next immediate action items.

### Documentation Review

- Verify that task scope boundaries (inclusions/exclusions) in `flutter-recorder-poc-task.md` are clearly drawn and achievable.
- Check that first-week plan aligns with PoC task brief (no task expects features outside PoC scope).
- Ensure all acceptance criteria reference verifiable evidence (test passes, artifact generated, runbook completed).
- Cross-reference implementation backlog with `../product/audio-sync-capture-platform-prd.md` to ensure alignment with product vision.
- Validate that all referenced documents (e.g., `../mobile/flutter-recorder-poc-template.md`) exist and are current.

### Common Patterns

- **Task scope boundaries**: PoC typically includes minimum recording/file-storage functionality; excludes room/session flow, upload, and BLE.
- **Success evidence**: PoC completion requires evidence templates filled (`../mobile/flutter-recorder-poc-template.md`) and baseline checks passing (`../policy/recording-policy.md`).
- **Backlog ordering**: P0 items (API skeleton, synthetic corpus) come before P1 items (alignment hardening, manifest export) before P2 items (evidence protocols, field validation).
- **Sprint rhythm**: Execution follows weekly gates (Gate A: engineering ready, Gate B: research ready, Gate C: pilot ready; see `../verification/release-gate.md`).

## Dependencies

### Internal

- `src/recog/` — Python MVP backend; tasks reference implementation checkpoints (e.g., room/session API skeleton completion).
- `apps/recorder-mobile/` — Flutter recorder mobile app; PoC task brief targets the recorder spike or PoC app branch.
- `../mobile/` — Mobile-side design and PoC runbooks that guide Flutter implementation work.
- `../product/audio-sync-capture-platform-prd.md` — Product vision that implementation planning executes against.
- `../verification/release-gate.md` — Release gate criteria that determine readiness for next phase.

### External

None.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Five implementation documents present; first-week plan and PoC task brief reviewed for scope clarity. -->
