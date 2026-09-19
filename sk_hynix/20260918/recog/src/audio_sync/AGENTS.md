<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Audio Sync

## Purpose

Audio DSP primitives + export pipeline library. Handles canonicalization (48kHz mono PCM), anchor detection, cross-correlation alignment, drift correction, and artifact export (aligned tracks, mixdown, manifest).

## Key Files

| File | Purpose |
|------|---------|
| `dsp/alignment.py` | Cross-correlation based track alignment; returns per-track offset |
| `dsp/anchor.py` | Anchor detection (silence boundaries, tone detection) |
| `dsp/canonicalize.py` | Normalize input audio to 48kHz mono PCM via ffmpeg subprocess |
| `dsp/drift.py` | Simple drift correction (clock-skew estimation) |
| `dsp/ffmpeg_filters.py` | ffmpeg filter graph builder (resample, remix, normalize) |
| `dsp/models.py` | Pydantic models for DSP state (Track, AlignmentResult, DriftResult) |
| `dsp/EVIDENCE.json` | Evidence checklist for DSP module (alignment accuracy, drift handling) |
| `dsp/README.md` | DSP pipeline overview and algorithm notes |
| `export/service.py` | Main export orchestrator; calls DSP then produces artifacts |
| `export/package.py` | Artifact packaging (tar.gz structure) |
| `export/manifest.py` | Manifest generation (track metadata, offset, drift, hash) |
| `export/mixdown.py` | Listening mixdown audio production (gain-balanced stereo or mono) |
| `export/validation.py` | Post-export integrity checks (file presence, hash validation) |
| `export/recog_adapter.py` | Bridge from recog session state to export pipeline |
| `export/compat.py` | Compatibility helpers (format conversions, legacy path handling) |
| `export/models.py` | Pydantic models for export (Manifest, ArtifactBundle, ValidationResult) |
| `export/EVIDENCE.json` | Evidence checklist for export module (completeness, manifest schema) |
| `export/README.md` | Export pipeline overview and manifest spec |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `dsp/` | Audio DSP primitives (alignment, anchor, canonicalize, drift, ffmpeg filters) |
| `export/` | Export pipeline (service, packaging, manifest, mixdown, validation) |

## For AI Agents

### Working In This Directory

This is a pure library—no CLI, no server. Always imported by `recog/` service or called directly by `tools/`.

**Common usage patterns:**

```python
from audio_sync.dsp import canonicalize, alignment, drift
from audio_sync.export import service

# Canonicalize tracks
canonical_path = canonicalize.to_pcm(input_wav, output_wav, sample_rate=48000, channels=1)

# Align tracks
offset_result = alignment.estimate_offset(reference_track, participant_track)

# Export aligned bundle
bundle = service.export_aligned_session(session_id, tracks, reference_id)
```

### Testing Requirements

- Unit tests in `tests/audio_sync/dsp/test_*.py` and `tests/audio_sync/export/test_*.py`
- DSP tests verify alignment accuracy, drift estimation, and canonicalization
- Export tests verify manifest schema, package structure, and hash integrity
- Synthetic corpus tests in `testkit/synthetic_corpus.py`

### Common Patterns

- **DSP models**: Inherit from Pydantic BaseModel for validation and serialization
- **ffmpeg calls**: Via subprocess in `dsp/canonicalize.py` and `dsp/ffmpeg_filters.py` (no library import)
- **Export artifacts**: Tar.gz bundles with manifest.json + audio files + listening.wav
- **Evidence**: Each module includes EVIDENCE.json checklist for verification

## Dependencies

### Internal

- Models in `dsp/models.py`, `export/models.py`
- DSP algorithms in `dsp/` called by `export/service.py`

### External

- **ffmpeg** — External subprocess tool for audio canonicalization
- **Pydantic** — (Optional, MVP uses stdlib only; upgrade path for validation)

<!-- MANUAL: -->

