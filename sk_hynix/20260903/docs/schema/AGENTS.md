<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Data Schemas

## Purpose

Formal JSON Schema definitions for the primary data contracts of the Audio Sync Capture Platform: the STT-handoff manifest, metadata structures, and evidence bundle formats. These schemas are the authoritative contract for data producers (Python MVP export lane) and consumers (STT systems, downstream processing, verification automation).

## Key Files

| File | Purpose |
|------|---------|
| `audio-sync-merge-manifest.schema.json` | JSON Schema for the STT-handoff manifest: schemaVersion, sessionId, generatedAt, canonicalFormat (sampleRateHz, channels, sampleFormat), tracks (per-track alignment and export metadata), qaSummary, listeningMix, artifactsBundle, alignmentConfidence |

## For AI Agents

### Working In This Directory

1. **Schema as contract**: Use this schema to validate manifest generation in unit/integration tests.
2. **Schema documentation**: Cross-reference schema definitions with the interpretation guide (`../audio-sync-merge-manifest-interpretation.md`) when implementing manifest producers or consumers.
3. **Schema evolution**: If the manifest contract must change, update schema and interpretation guide in lockstep; semantic versioning in schemaVersion field.

### Documentation Review

- Validate that the JSON Schema syntax is correct (valid $schema version, no typos in keywords like `type`, `properties`, `required`).
- Check that all required fields (schemaVersion, sessionId, generatedAt, tracks, canonicalFormat, recommendedSttInput) are marked as required.
- Verify that field types and constraints match the interpretation guide (e.g., confidence is a number 0.0–1.0, offsetMs is an integer milliseconds).
- Ensure per-track properties (trackId, participantId, alignedArtifact, offsetMs, driftPpm, gainDb, weight) are fully described.
- Validate numeric field constraints (min/max values) are appropriate for expected ranges (e.g., driftPpm ±10000, gainDb ±20).
- Cross-reference the example manifest (`../examples/audio-sync-merge-manifest-example.json`) against the schema to ensure compatibility.

### Common Patterns

- **Semantic versioning**: schemaVersion follows major.minor format (e.g., 1.0, 1.1, 2.0); bumped when new required fields added (major) or optional fields added (minor).
- **Required vs. optional**: P0 fields (sessionId, tracks, canonicalFormat) are required; P1 fields (listeningMix, artifactsBundle) are optional but expected in mature implementation.
- **Numeric precision**: Confidence rounded to 4 decimal places (0.0000–1.0000); offsets/drift as integers (milliseconds/ppm); gain as floats (dB).
- **Array constraints**: tracks array must have at least 1 element; qaSummary can be empty dict initially but should populate before release.

## Dependencies

### Internal

- `src/recog/export/manifest.py` — Python MVP implementation that generates manifests matching this schema.
- `../audio-sync-merge-manifest-interpretation.md` — Interpretation guide that explains schema fields in operational terms.
- `../examples/audio-sync-merge-manifest-example.json` — Example manifest that must validate against this schema.
- `../verification/metadata-schema.md` — Related metadata schema for recording session metadata (different from manifest schema).

### External

None.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Single manifest schema present; defines authoritative contract for STT-handoff manifest. -->
