<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# DSP (Digital Signal Processing)

## Purpose

Audio DSP primitives: canonicalization, anchor detection, cross-correlation alignment, and drift correction. No end-to-end orchestration here—`export/service.py` chains these together.

## Key Files

| File | Purpose |
|------|---------|
| `alignment.py` | Cross-correlation estimator: given reference track and participant track, returns offset in samples |
| `anchor.py` | Anchor detection: identifies silence boundaries and tone signatures for alignment validation |
| `canonicalize.py` | Normalize input audio: subprocess call to ffmpeg, output 48kHz mono PCM WAV |
| `drift.py` | Drift correction: simple linear clock-skew estimation (slope + intercept in sample space) |
| `ffmpeg_filters.py` | Filter graph builder: constructs ffmpeg `-filter_complex` strings (resample, remix, normalize) |
| `models.py` | Pydantic BaseModel definitions: Track, TrackMetadata, AlignmentResult, DriftResult, CanonicalResult |
| `EVIDENCE.json` | Evidence checklist: alignment accuracy targets, drift bounds, canonicalization validation steps |
| `README.md` | Algorithm overview, accuracy notes, edge cases (short tracks, noise robustness) |

## For AI Agents

### Working In This Directory

Pure DSP library. Functions are stateless; take audio arrays or file paths, return results or write files.

**Typical call sequence:**

1. `canonicalize.to_pcm(input_file, output_file)` → canonical 48kHz mono WAV
2. `alignment.estimate_offset(ref_array, participant_array)` → offset in samples (can be negative)
3. `drift.estimate_drift(ref_array, participant_array, offset)` → linear model (slope, intercept)
4. Export calls these to build aligned bundle

### Testing Requirements

- Synthetic test cases in `testkit/synthetic_corpus.py` (silence, tones, white noise)
- Unit tests verify:
  - Alignment ±50ms accuracy on synthetic offsets
  - Drift handling on speed-varied audio
  - Canonicalization byte-for-byte consistency
  - Anchor detection on short (<2s) tracks
- Load tests in `tools/run_load_probe.py` (5 tracks, 1–60s duration)

### Common Patterns

- **Array handling**: NumPy or raw byte arrays (depends on implementation; check imports)
- **File I/O**: Direct WAV read/write, no compression
- **ffmpeg calls**: Via `subprocess.run()` with filter_complex, never via library import
- **Error handling**: Raise ValueError or AudioProcessingError on invalid input (silence, clipping, format mismatch)

## Dependencies

### Internal

- `models.py` — Pydantic models

### External

- **ffmpeg** (subprocess) — Audio format conversion, resampling, mixing
- **NumPy** (optional) — If implementation uses arrays; MVP may use struct/wave module only
- **scipy.signal** (optional) — For cross-correlation; MVP may use naive algorithm

<!-- MANUAL: -->

