# audio_sync.dsp

Isolated DSP helper surface for the audio-sync merge MVP.

## Scope
- canonicalization command builders for working/STT export audio
- coarse envelope/correlation-based offset helpers
- fine offset refinement on in-memory sample arrays
- ffmpeg filter-chain builders for drift correction and alignment staging
- activity-window based alignment estimation
- bounded drift/correction-factor helpers
- piecewise drift segment fitting from landmarks

## Intent
This package is intentionally side-effect free and does not own ffmpeg execution,
file I/O, session storage, or API orchestration. It exists so higher-level lanes
can compose DSP primitives without importing the full `recog` pipeline module.

## Current integration note
- The live pipeline in `src/recog/audio.py` still owns runtime execution.
- This package captures the minimal reusable primitives extracted for task 3.
- Worker-1 can decide whether to migrate `recog.audio` to these helpers during
  final consolidation without changing the verified DSP contract in this lane.

## Verification
- `env PYTHONPATH="$PWD/src:$PWD" python3 -m unittest discover -s tests/dsp -v`
- `python3 -m py_compile src/audio_sync/dsp/*.py tests/dsp/*.py`
