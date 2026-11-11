<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Tests: DSP Module

## Purpose

Unit tests for audio DSP primitives in `src/audio_sync/dsp/`. Tests verify correctness of signal processing stages: canonicalization, anchor detection, cross-correlation-based alignment, drift estimation, and filtering.

Test coverage ensures that the DSP pipeline reliably aligns multiple participant tracks with sub-frame accuracy and detects real-world phenomena (clock drift, jitter).

## Key Files

| File | Purpose |
|------|---------|
| `test_alignment.py` | Cross-correlation alignment, phase detection, confidence metrics |
| `test_anchor.py` | Anchor detection (silence gaps, voice activity markers), robustness to noise |
| `test_canonicalize.py` | Audio canonicalization (sample rate conversion, bit depth, channel normalization) |
| `test_drift.py` | Clock drift estimation and compensation |
| `test_filters.py` | DSP filtering operations (bandpass, notch, pre-emphasis) |

## Corresponding Source Modules

These tests mirror the structure of `src/audio_sync/dsp/`:

| Test File | Source Module |
|-----------|---------------|
| `test_alignment.py` | `src/audio_sync/dsp/alignment.py` |
| `test_anchor.py` | `src/audio_sync/dsp/anchor.py` |
| `test_canonicalize.py` | `src/audio_sync/dsp/canonicalize.py` |
| `test_drift.py` | `src/audio_sync/dsp/drift.py` |
| `test_filters.py` | `src/audio_sync/dsp/filters.py` |

## For AI Agents

### Working In This Directory

Run DSP tests from the repository root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/dsp -v
```

Run a specific DSP test file:

```bash
PYTHONPATH=src python3 -m unittest tests.dsp.test_alignment
```

### Adding New DSP Tests

1. Create test file: `tests/dsp/test_<module_name>.py`
2. Import from `src/audio_sync/dsp.<module_name>`
3. Use synthetic test data or fixtures from `tests/fixtures/` as needed
4. Follow naming convention: test classes as `Test<FunctionName>` or `Test<ModuleName>`

### Test Data Strategy

- **Synthetic signals**: Generate programmatically in test setup (e.g., sine waves, noise, silence)
- **Ground truth**: Tests assert alignment against known offsets and phase relationships
- **Real-world fixtures**: Lane4 benchmark snapshots in `tests/fixtures/lane4/` provide regression baselines

### Common DSP Test Patterns

- **Alignment**: Create stereo pair with known offset, run alignment, verify recovered offset matches
- **Anchor**: Generate synthetic silence gaps and voice bursts, detect anchors, verify boundaries
- **Canonicalization**: Input various sample rates/bit depths, verify output is 48kHz mono PCM
- **Drift**: Simulate clock drift (clock skew over time), estimate via DSP, verify error < threshold
- **Filters**: Verify frequency response against specifications (passband, stopband, ripple)

## Dependencies

### Internal

- `src/audio_sync/dsp/` — Modules under test

### External

- **Python 3.9+** — Stdlib `unittest` only
- **ffmpeg** — Required for canonicalize tests (audio format conversion via subprocess)
- **numpy** (if used) — For signal generation and DSP operations

