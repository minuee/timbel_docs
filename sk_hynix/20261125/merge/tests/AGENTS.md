<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Tests: Audio Sync Capture Platform

## Purpose

Unit and integration tests for the Audio Sync Capture Platform. Tests verify DSP pipeline correctness, API endpoint contracts, export pipeline validation, and session lifecycle management using stdlib `unittest`.

The test suite covers:
- DSP alignment, anchor detection, drift estimation, and filtering primitives
- Export pipeline: mixdown, validation, package generation, manifest contracts
- API endpoints: session/room control plane, file upload contracts, evidence protocols
- Evidence bundle tooling and controlled-session scaffolding

## Key Files

| File | Purpose |
|------|---------|
| `test_api.py` | WSGI API endpoint contracts (session/room lifecycle, file upload, artifact retrieval) |
| `test_pipeline.py` | End-to-end audio processing pipeline: upload → canonical → alignment → export |
| `test_rooms.py` | Room and session management contracts and state transitions |
| `test_evidence.py` | Evidence bundle format and metadata validation |
| `test_upload_contract.py` | File upload protocol and metadata schema validation |
| `test_upload_metadata.py` | Recording metadata envelope schema and fixture validation |
| `test_metadata_schema.py` | Metadata envelope JSON schema validation |
| `test_protocol_models.py` | Request/response protocol model contracts |
| `__init__.py` | Test package marker |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `dsp/` | DSP module tests: alignment, anchor, canonicalize, drift, filters |
| `export/` | Export pipeline tests: service, mixdown, validation, manifest contracts, compatibility |
| `fixtures/` | Regression snapshots and metadata fixture files (read-only) |
| `recog/` | Placeholder for future recog-scoped test organization |
| `audio_sync/` | Placeholder for future audio_sync-scoped test organization |

## For AI Agents

### Working In This Directory

Run tests from the repository root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Run a specific test file:

```bash
PYTHONPATH=src python3 -m unittest tests.test_api
```

Run a specific test class:

```bash
PYTHONPATH=src python3 -m unittest tests.test_api.SessionLifecycleTest
```

### Adding New Tests

1. **Top-level tests** (tests at `tests/test_*.py`): Add here if the test covers multiple subsystems or top-level integration concerns (API, rooms, pipeline, evidence).
2. **DSP tests** (module-specific): Add to `tests/dsp/test_*.py` if testing a DSP module from `src/audio_sync/dsp/`.
3. **Export tests** (module-specific): Add to `tests/export/test_*.py` if testing an export module from `src/audio_sync/export/`.

Follow naming: `test_<module>.py` mirrors the source module name.

### Test Organization

- **Fixtures**: Static test data live in `tests/fixtures/`. Snapshots are regression baselines; do not modify existing fixture files without understanding impact on related tests.
- **Evidence bundle tests**: Verify manifest format, metadata schema, and bundle structure using fixtures from `fixtures/metadata/`.
- **Integration tests**: Tests like `test_pipeline.py` use synthetic fixtures generated on-the-fly; no static data dependency.

### Common Test Patterns

- **Session lifecycle**: `POST /sessions` → `POST /files` (up to 5) → `POST /process` → `GET /artifacts`
- **Upload contract**: File metadata envelope (recording envelope) must conform to schema; validation via `test_upload_metadata.py`
- **Export validation**: Manifest and audio output must match integrity checksums and schema definitions
- **DSP correctness**: Alignment tests use synthetic test corpus with known ground truth (SNR, phase offset)

## Dependencies

### Internal

- `src/audio_sync/` — DSP and export modules tested by `dsp/` and `export/` subtests
- `src/recog/` — API and session store tested by top-level test files
- `testkit/` — Synthetic corpus and evidence bundle generators used by tests

### External

- **Python 3.9+** — Stdlib `unittest` only (no external test runner)
- **ffmpeg** — Used by export pipeline tests via subprocess (required in PATH)

### Test Data

- `tests/fixtures/metadata/` — Recording envelope JSON files for upload contract tests
- `tests/fixtures/lane4/` — Benchmark and integration matrix snapshots for regression detection

