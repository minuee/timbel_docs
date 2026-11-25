<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Tests: Metadata Fixtures (Recording Envelopes)

## Purpose

Recording metadata envelope fixture files for testing upload contracts and metadata validation. These JSON files represent the metadata that accompanies each participant's recording when uploaded to the API.

Fixtures cover:
- **Valid envelope**: All required fields present, sensible values, passes schema validation
- **Missing timing**: Timing-related fields absent or null (degraded/edge-case scenario)
- **Bluetooth**: Real-world metadata from Bluetooth recording device

Tests load these fixtures to validate that:
1. Metadata parsing conforms to schema
2. Upload API correctly rejects invalid metadata
3. Export pipeline correctly handles degraded metadata gracefully

## Key Files

| File | Purpose |
|------|---------|
| `recording-envelope.valid.json` | Complete, valid recording metadata (template for correct structure) |
| `recording-envelope.missing-timing.json` | Metadata with missing timing fields (tests degradation handling) |
| `recording-envelope.bluetooth.json` | Metadata from Bluetooth source (real-world hardware variant) |

## For AI Agents

### Working In This Directory

Metadata fixtures are **read-only** to tests. Do not modify existing fixtures without understanding their role in tests.

**When to add a new fixture:**

1. A new edge case or scenario needs testing (e.g., new device type, new metadata schema field)
2. New fixture should be named: `recording-envelope.<scenario>.json`
3. Document the scenario in this AGENTS.md

**When to update a fixture:**

1. Schema changed (coordinated with API/export contract updates)
2. Real-world hardware data collected that needs to be added
3. Always document reason in commit message (links issue/ADR)

### Using Metadata Fixtures in Tests

Tests that load these fixtures:
- `tests/test_upload_metadata.py` — Validates metadata envelope against schema
- `tests/test_upload_contract.py` — Validates upload API metadata handling
- `tests/export/test_manifest.py` — Validates manifest generation with various metadata inputs

### Fixture Structure (Example)

```json
{
  "device": "iPhone 14 Pro",
  "device_type": "mobile",
  "recording_started_at": "2026-04-20T10:30:00Z",
  "duration_ms": 3600000,
  "sample_rate_hz": 48000,
  "channels": 1,
  "bit_depth": 16,
  "codec": "pcm"
}
```

## Dependencies

### Internal

- Tests: `tests/test_upload_metadata.py`, `tests/test_upload_contract.py`, `tests/export/test_manifest.py`
- Schema: `docs/schema/audio-sync-merge-manifest.schema.json` (validates recording envelope structure)

### External

None (fixtures are static JSON files).

