<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Tests: Audio Sync (Placeholder)

## Purpose

Reserved container directory for future audio_sync-scoped unit tests. Currently, tests for `src/audio_sync/dsp/` and `src/audio_sync/export/` modules are organized in top-level subdirectories (`tests/dsp/` and `tests/export/`) rather than nested under `tests/audio_sync/`.

This directory exists to support future reorganization if the test tree expands.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `export/` | Currently holds only cached bytecode (`__pycache__`); tests are in `tests/export/` at top level |

## For AI Agents

### Working In This Directory

Do not add test files here at present. Continue adding audio_sync-related tests to:
- `tests/dsp/` for DSP module tests
- `tests/export/` for export pipeline tests

When the test suite grows and reorganization is warranted, this directory can be used as the parent for nested `dsp/` and `export/` subdirectories.

### Future Migration

If reorganizing, plan to:
1. Move `tests/dsp/` → `tests/audio_sync/dsp/`
2. Move `tests/export/` → `tests/audio_sync/export/`
3. Update parent references in each AGENTS.md from `../AGENTS.md` to `../../AGENTS.md`
4. Update imports in test files accordingly

## Dependencies

### Internal

None at present (placeholder).

### External

None.

