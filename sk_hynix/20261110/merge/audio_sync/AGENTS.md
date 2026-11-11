<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Audio Sync (Shim)

## Purpose

Root-level shim package that re-exports from `src/audio_sync/`. Allows importing `audio_sync` directly when `src/` is on PYTHONPATH. Contains only `__init__.py`; all implementation lives in `src/audio_sync/`.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Module path redirector to `src/audio_sync/` |

## For AI Agents

### Working In This Directory

Do not write code here. This is a discovery mechanism only.

When `PYTHONPATH=src` is set:
- `from audio_sync import ...` → discovers `src/audio_sync/...`
- The `__init__.py` rewrites `__path__` to point to `src/audio_sync/`

Real implementation lives at `src/audio_sync/`. Always work there.

## Dependencies

### Internal

- Redirects to `src/audio_sync/`

### External

None.

<!-- MANUAL: -->

