<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Tests: Recog (Placeholder)

## Purpose

Reserved container directory for future recog-scoped unit tests. Currently, tests for `src/recog/` modules are organized at the top level (`tests/test_api.py`, `tests/test_rooms.py`, `tests/test_pipeline.py`, `tests/test_evidence.py`) rather than nested under `tests/recog/`.

This directory exists to support future reorganization if the test suite expands significantly.

## For AI Agents

### Working In This Directory

Do not add test files here at present. Continue adding recog-related tests to the top level:
- `tests/test_api.py` — WSGI API endpoint contracts
- `tests/test_rooms.py` — Room and session management
- `tests/test_pipeline.py` — End-to-end processing pipeline
- `tests/test_evidence.py` — Evidence bundle format

When the recog test suite grows and reorganization is warranted, this directory can be used as the parent for module-scoped subdirectories:
- `tests/recog/api/` — API tests
- `tests/recog/session/` — Session store tests
- etc.

### Future Migration

If reorganizing, plan to:
1. Move top-level recog tests to `tests/recog/test_*.py`
2. Create AGENTS.md in `tests/recog/` documenting the module-scoped test organization
3. Update parent references accordingly

## Dependencies

### Internal

None at present (placeholder).

### External

None.

