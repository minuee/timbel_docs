<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Export

## Purpose

Export pipeline orchestrator: chains DSP operations, produces aligned tracks + listening mixdown + STT-handoff manifest. Bridges recog session state to DSP and generates release artifacts.

## Key Files

| File | Purpose |
|------|---------|
| `service.py` | Main orchestrator: takes session state, calls DSP, writes artifact bundle |
| `package.py` | Tar.gz bundling: creates release artifact with aligned tracks, manifest, mixdown |
| `manifest.py` | Manifest generation (JSON): track metadata, offsets, drift model, hash validation |
| `mixdown.py` | Listening mixdown: gain-balanced mix of aligned tracks (mono or stereo stereo or mono) |
| `validation.py` | Post-export checks: file presence, hash validation, manifest schema validation |
| `recog_adapter.py` | Bridge from `recog` session state to export pipeline input |
| `compat.py` | Compatibility helpers: legacy path resolution, format conversions |
| `models.py` | Pydantic models: Manifest, ArtifactBundle, ValidationResult, ExportConfig |
| `EVIDENCE.json` | Evidence checklist: completeness checks, manifest schema, release gate criteria |
| `README.md` | Export pipeline overview, manifest schema, release artifact structure |

## For AI Agents

### Working In This Directory

Orchestrator for DSP + packaging. Called by `recog/api.py` on `POST /sessions/{id}/process`.

**Typical call sequence:**

```python
from audio_sync.export import service, recog_adapter

# Get recog session state
session = recog_store.get(session_id)

# Convert to export pipeline input
export_input = recog_adapter.session_to_export_input(session)

# Run export pipeline
bundle = service.export_aligned_session(export_input)

# Write artifact bundle
artifact_path = package.write_bundle(bundle, output_dir)
```

### Testing Requirements

- Unit tests verify:
  - Manifest schema completeness (all tracks present, valid offsets)
  - Hash consistency (input files → manifest hashes)
  - Mixdown audio properties (48kHz, mono or stereo, no clipping)
  - Validation catches missing files, corrupted manifest
- Integration tests:
  - End-to-end with `testkit/controlled_bundle.py`
  - Synthetic corpus flow in `tools/evaluate_synthetic_alignment.py`

### Common Patterns

- **Artifact structure**: `artifact-id/manifest.json`, `artifact-id/tracks/p1.wav`, `artifact-id/listening.wav`, `artifact-id/metadata.json`
- **Manifest schema**: JSON with track array (id, filename, offset_ms, drift_model), timestamp, hash
- **Validation checklist**: All tracks present, all hashes match, manifest valid JSON, manifest references existing files
- **Release gate**: Validation must pass before artifact made available

## Dependencies

### Internal

- `audio_sync.dsp` — Alignment, drift, canonicalization functions
- `recog` — Session models and store (imported by `recog_adapter.py`)
- `models.py` — Pydantic models for export

### External

- **tarfile** (stdlib) — Artifact bundling
- **json** (stdlib) — Manifest serialization
- **hashlib** (stdlib) — File hash computation

<!-- MANUAL: -->

