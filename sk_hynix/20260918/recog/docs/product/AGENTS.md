<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Product Requirements and Vision

## Purpose

The canonical product requirements document (PRD) defining the vision, user stories, acceptance criteria, and scope boundaries for the Audio Sync Capture Platform MVP and pilot phases.

## Key Files

| File | Purpose |
|------|---------|
| `audio-sync-capture-platform-prd.md` | Complete PRD: platform vision, user personas, user stories, functional requirements (meeting recording, alignment, manifest export), non-functional requirements (performance, reliability), MVP scope, pilot roadmap |

## For AI Agents

### Working In This Directory

1. **Requirements source**: Reference the PRD when planning features, defining acceptance criteria, and prioritizing backlog items.
2. **Scope boundaries**: Use the PRD to determine what is in/out of scope for MVP and pilot phases.
3. **User story validation**: Check that implementation tasks and test cases map back to the PRD user stories.

### Documentation Review

- Verify that user stories have clear acceptance criteria (what does "success" mean?).
- Check that functional requirements are specific and testable (e.g., "align 5 participants' audio within ±50ms offset" vs. vague "align audio").
- Ensure non-functional requirements (latency, reliability) are quantified or have measurable gates (e.g., "P99 processing latency < 60s for 1-hour 5-participant session").
- Validate that MVP scope is focused and achievable (can be completed in 1–2 sprints).
- Cross-reference scope boundaries with `../audio-sync-merge-scope-audit.md` to ensure consistency.
- Ensure the PRD does not contradict policies defined in `../policy/` or architectural decisions in `../architecture/`.

### Common Patterns

- **MVP scope**: Focus on core alignment and manifest export; exclude advanced features like real-time feedback, complex UI, or multi-language support.
- **Pilot scope**: Real-world testing with controlled participants; evidence capture and listening evaluation before production.
- **User personas**: Researchers (require reproducibility, evidence), operators (require clear runbooks and error handling), STT consumers (require manifest contract).
- **Non-functional gates**: Performance, reliability, and data-privacy requirements should map to release gates (see `../verification/release-gate.md`).

## Dependencies

### Internal

- `../implementation/implementation-backlog.md` — Backlog priorities derived from PRD user stories.
- `../architecture/system-overview.md` — Architecture that fulfills PRD requirements.
- `../api/` — API contracts that implement PRD functional requirements.
- `../verification/release-gate.md` — Release gates that verify PRD acceptance criteria.
- `../audio-sync-merge-scope-audit.md` — Scope audit cross-checked against PRD definitions.

### External

None.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Single PRD file present; serves as north star for implementation planning and acceptance criteria. -->
