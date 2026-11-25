<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Recog

## Purpose

WSGI API service + session store + CLI. Exposes session management endpoints (create, upload, process, retrieve) and integrates with audio_sync export pipeline for artifact generation.

## Key Files

| File | Purpose |
|------|---------|
| `__main__.py` | CLI entry point: `python3 -m recog serve` or `generate-fixture`/`process-fixture` commands |
| `api.py` | WSGI application: routes `POST /sessions`, `POST /files`, `POST /process`, `GET /sessions/{id}`, `GET /artifacts` |
| `models.py` | Pydantic models: Session, Track, UploadMetadata, ProcessingRequest, SessionState |
| `store.py` | Session persistence: file-based store at `--data-root` directory |
| `rooms.py` | Room/session lifecycle management (create, list, get, update state) |
| `events.py` | Event logging (session created, file uploaded, processing started/completed) |
| `audio.py` | Audio file handling: upload validation, temporary storage, format detection |
| `pipeline.py` | Processing orchestrator: calls `audio_sync.export` to align tracks and generate artifacts |
| `synthetic.py` | Synthetic fixture generation: creates test sessions with tones, noise, silence |
| `contracts.py` | API contract definitions (request/response schemas, error codes) |
| `protocol_models.py` | Protocol-level models (wire format, serialization) |
| `evidence.py` | Evidence tracking: logs processing steps, DSP results, validation decisions |

## For AI Agents

### Working In This Directory

This is the service layer. Handles HTTP, session state, orchestration to DSP.

**Run the service:**

```bash
PYTHONPATH=src python3 -m recog --data-root .runtime serve
```

**Generate synthetic fixture (for testing):**

```bash
PYTHONPATH=src python3 -m recog --data-root .runtime generate-fixture --output /tmp/fixture --tracks 3
```

**API endpoints:**

- `POST /sessions` → Create new session, returns `session_id`
- `POST /sessions/{id}/files?participant_id=p1&filename=a.wav` → Upload audio file
- `POST /sessions/{id}/process` → Run alignment + export pipeline
- `GET /sessions/{id}` → Get session state and metadata
- `GET /sessions/{id}/artifacts` → List artifact bundles for session

### Testing Requirements

- Unit tests in `tests/recog/test_*.py`:
  - `test_api.py` — Route behavior, request validation, response formats
  - `test_store.py` — Session persistence, CRUD operations
  - `test_pipeline.py` — Integration with audio_sync export
  - `test_synthetic.py` — Fixture generation
- Integration tests via `tools/run_load_probe.py` (repeatable sessions, load stress)
- Contract validation in `tools/check_recorder_baseline.py`

### Common Patterns

- **Session state machine**: CREATED → FILES_UPLOADED → PROCESSING → COMPLETED or FAILED
- **Error handling**: Return HTTP 400 on validation, 404 on missing session, 500 on processing error
- **File uploads**: Store in `{data-root}/{session-id}/raw/` temporarily; move to `final/` after processing
- **Evidence tracking**: Log all DSP decisions, offsets, validation results to `evidence.json` in session dir

## Dependencies

### Internal

- `audio_sync` — Export pipeline
- `models.py`, `contracts.py`, `protocol_models.py` — Data structures
- `store.py`, `rooms.py`, `events.py` — State management
- `synthetic.py` — Fixture generation for testing

### External

- **stdlib WSGI** — No external web framework (use http.server or compatible runner)
- **stdlib json** — Serialization
- **pathlib** — File I/O

<!-- MANUAL: -->

