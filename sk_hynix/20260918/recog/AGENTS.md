<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Audio Sync Capture Platform

## Purpose

Audio Sync Capture Platform MVP. A Python WSGI service that ingests up to 5 participant recordings per session, canonicalizes to 48kHz mono PCM via ffmpeg, estimates per-track offset + drift against a reference track, and exports aligned tracks + listening mixdown + STT-handoff manifest. Currently **blocked on Flutter recorder PoC** per STATUS.json / BLOCKED_ON_POC.md — iOS+Android recording validation is the gating decision.

## Key Files

| File | Purpose |
|------|---------|
| `README.md` | Service overview, API routes, run/verify commands |
| `STATUS.json` | Project state, completed artifacts by priority, PoC decision gates |
| `BLOCKED_ON_POC.md` | Why Flutter recorder PoC is required before MVP release |
| `FLUTTER_POC_SETUP.md` | Steps to run Flutter PoC in capable environment |
| `HANDOFF_STATUS.md` | Handoff readiness checklist (docs, contracts, PoCs) |
| `NEXT_ACTION.md` | Next required action: run PoC, decision tree |
| `Makefile` | Build targets for testing, linting, documentation |
| `run_flutter_poc_first_step.sh` | Entry script for Flutter PoC validation |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/` | Python source root (PYTHONPATH=src); contains `audio_sync/` and `recog/` packages |
| `audio_sync/` | Root-level shim re-exporting from `src/audio_sync` |
| `recog/` | Root-level shim re-exporting from `src/recog` |
| `apps/` | (TBD) Application layer or integration examples |
| `docs/` | Product, API, architecture, implementation, and verification documentation |
| `mobile_app/` | Flutter mobile recorder scaffold (iOS + Android) |
| `mobile/` | (Empty; skip) |
| `testkit/` | Python test helpers: fixture generators, evidence bundles, rubrics, verification matrices |
| `tests/` | Python unit tests (discover-friendly layout) |
| `tools/` | Standalone Python CLI tools that call into testkit and src packages |
| `scripts/` | Operational shell + Python scripts (field validation, device bootstrap, PoC checks) |
| `verification/` | Evidence artifacts and controlled-device run outputs |

## For AI Agents

### Working In This Directory

The root is an orchestration layer. Real implementation lives in `src/audio_sync/` and `src/recog/`.

**Typical workflows:**

1. **Run the service**: `PYTHONPATH=src python3 -m recog --data-root .runtime serve`
2. **Generate synthetic corpus**: `PYTHONPATH=src python3 -m recog --data-root .runtime generate-fixture --output /tmp/fixture --tracks 3`
3. **Run unit tests**: `PYTHONPATH=src python3 -m unittest discover -s tests -v`
4. **Check syntax**: `PYTHONPATH=src python3 -m compileall src tests`

**Shim packages**: `recog/` and `audio_sync/` directories at root are minimal redirects. Users import `recog` or `audio_sync` directly when `src/` is on PYTHONPATH—the shims handle discovery.

### Testing Requirements

- **Unit tests**: `tests/` directory, runnable via `unittest discover`
- **Synthetic fixtures**: `tools/generate_synthetic_corpus.py` and `PYTHONPATH=src python3 -m recog generate-fixture`
- **Integration**: `tools/run_load_probe.py` for repeatable load and listening-review generation
- **PoC validation**: `scripts/run_recorder_poc_check.sh` for Flutter recorder decision gates

### Common Patterns

- **DSP pipeline**: audiocanonical → anchor detection → alignment (cross-correlation) → drift → export
- **Session lifecycle**: `POST /sessions` → `POST /files` (up to 5 tracks) → `POST /process` → `GET /artifacts`
- **Evidence flow**: Synthetic corpus → load probe → listening rubric → failure taxonomy
- **Verification**: Controlled device protocol + field validation protocol via scripts/

## Dependencies

### Internal

- `src/audio_sync/` — Audio DSP + export library (no external audio deps except ffmpeg as subprocess)
- `src/recog/` — WSGI API + session store
- `testkit/` — Test fixtures and evidence generators (no external test runners; uses stdlib only)
- `tools/`, `scripts/` — Runners calling into above

### External

- **ffmpeg** — External tool for canonicalization (subprocess call, not library import)
- **Python 3.9+** — Stdlib only for core service (no pip dependencies)
- **Flutter + Dart** — For mobile_app/ PoC only (not part of core service)

<!-- MANUAL: -->

