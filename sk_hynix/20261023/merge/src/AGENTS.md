<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Source Root

## Purpose

Python source packages root. Set `PYTHONPATH=src` to import `audio_sync` and `recog` directly. No executable code at this level; pure package containers.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `audio_sync/` | Audio DSP primitives + export pipeline library |
| `recog/` | WSGI API + session store + CLI |

## For AI Agents

### Working In This Directory

Never execute code at this level. Always work within `audio_sync/` or `recog/` subdirectories. When running tests or the service, set `PYTHONPATH=src` from the repository root.

### Common Patterns

- Imports from here: `from audio_sync import ...` or `from recog import ...`
- External callers set `PYTHONPATH=src` in their command
- No __main__.py, no CLI here (all in `recog/__main__.py`)

## Dependencies

### Internal

- `audio_sync/` — Pure DSP/export package
- `recog/` — Service and API package

### External

None at this level.

<!-- MANUAL: -->

