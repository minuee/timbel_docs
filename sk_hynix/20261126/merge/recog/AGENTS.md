<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Recog (Shim)

## Purpose

Root-level shim package that re-exports from `src/recog/`. Allows importing `recog` directly when `src/` is on PYTHONPATH. Contains only `__init__.py`; all implementation lives in `src/recog/`.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Module path redirector to `src/recog/` |

## For AI Agents

### Working In This Directory

Do not write code here. This is a discovery mechanism only.

When `PYTHONPATH=src` is set:
- `from recog import ...` → discovers `src/recog/...`
- `python3 -m recog` → executes `src/recog/__main__.py`
- The `__init__.py` rewrites `__path__` to point to `src/recog/`

Real implementation lives at `src/recog/`. Always work there.

## Dependencies

### Internal

- Redirects to `src/recog/`

### External

None.

<!-- MANUAL: -->

