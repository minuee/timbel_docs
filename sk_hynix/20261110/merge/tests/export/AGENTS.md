<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Tests: Export Pipeline

## Purpose

Unit and integration tests for the export pipeline in `src/audio_sync/export/`. Tests verify output packaging, manifest generation, validation contracts, mixdown audio quality, and compatibility with downstream systems.

The export pipeline is the final stage of processing: it takes aligned tracks and produces consumable artifacts (stereo mixdown WAV, STT-handoff manifest JSON, integrity metadata).

## Key Files

| File | Purpose |
|------|---------|
| `test_service.py` | Export service orchestration and artifact generation |
| `test_mixdown.py` | Stereo mixdown generation, gain normalization, audio quality |
| `test_manifest.py` | STT-handoff manifest contract and structure validation |
| `test_package.py` | Artifact bundling, directory structure, file naming conventions |
| `test_validation.py` | Output validation: checksums, schema conformance, integrity checks |
| `test_integration_contract.py` | End-to-end export contract between processing pipeline and consumer systems |
| `test_recog_adapter.py` | Adapter/bridge code between recog API and export pipeline |
| `test_compat.py` | Backward compatibility checks for manifest versions and output formats |
| `__init__.py` | Test package marker |

## Corresponding Source Modules

These tests mirror the structure of `src/audio_sync/export/`:

| Test File | Source Module |
|-----------|---------------|
| `test_service.py` | `src/audio_sync/export/service.py` |
| `test_mixdown.py` | `src/audio_sync/export/mixdown.py` |
| `test_manifest.py` | `src/audio_sync/export/manifest.py` |
| `test_package.py` | `src/audio_sync/export/package.py` |
| `test_validation.py` | `src/audio_sync/export/validation.py` |

## For AI Agents

### Working In This Directory

Run export tests from the repository root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/export -v
```

Run a specific export test file:

```bash
PYTHONPATH=src python3 -m unittest tests.export.test_manifest
```

### Adding New Export Tests

1. Create test file: `tests/export/test_<module_name>.py`
2. Import from `src/audio_sync/export.<module_name>`
3. Use fixtures from `tests/fixtures/metadata/` or generate test data on-the-fly
4. Follow naming convention: test classes as `Test<FunctionName>` or `Test<ModuleName>`

### Test Data Strategy

- **Metadata fixtures**: Use recordings from `tests/fixtures/metadata/` (valid, missing-timing, bluetooth variants)
- **Manifest examples**: Reference examples in `docs/examples/` for expected output structure
- **Integration data**: Generate aligned track bundles via in-memory DSP pipeline for end-to-end tests

### Common Export Test Patterns

- **Manifest validation**: Load fixture metadata, generate manifest, validate against schema
- **Mixdown quality**: Generate synthetic aligned tracks, produce mixdown, verify audio properties (RMS, peak, gain)
- **Package structure**: Export full bundle, verify directory layout and file naming match spec
- **Backward compatibility**: Load historical manifest versions, verify parsing and rendering still work
- **Integration contract**: Verify manifest fields match what downstream STT systems expect

## Dependencies

### Internal

- `src/audio_sync/export/` — Modules under test
- `src/audio_sync/dsp/` — DSP alignment pipeline used for test data generation
- `tests/fixtures/metadata/` — Recording envelope fixtures for validation tests

### External

- **Python 3.9+** — Stdlib `unittest` only
- **ffmpeg** — Required for mixdown generation (audio mixing via subprocess)
- **json.schema** (if used) — For manifest JSON schema validation

