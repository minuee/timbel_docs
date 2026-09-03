<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Examples and Reference Data

## Purpose

Sample data structures and reference examples for the Audio Sync Capture Platform. These files serve as concrete instantiations of abstract contracts and schemas, enabling engineers to understand expected data formats during development and integration testing.

## Key Files

| File | Purpose |
|------|---------|
| `audio-sync-merge-manifest-example.json` | Complete example STT-handoff manifest produced by the export lane: schemaVersion, sessionId, tracks, alignment confidence, listening mix metadata, QA summary |

## For AI Agents

### Working In This Directory

1. **Contract instantiation**: Use the manifest example to understand the concrete shape of data flowing from the Python MVP export lane to downstream STT consumers.
2. **Integration testing**: Reference this example when building test fixtures or validating manifest generation in integration tests.
3. **Documentation**: Update this example if the manifest schema (`../schema/audio-sync-merge-manifest.schema.json`) or interpretation guide (`../audio-sync-merge-manifest-interpretation.md`) changes.

### Documentation Review

- Validate that the example manifest conforms to the JSON Schema defined in `../schema/audio-sync-merge-manifest.schema.json`.
- Check that all required fields (schemaVersion, sessionId, generatedAt, tracks, canonicalFormat, recommendedSttInput) are present.
- Verify that per-track fields (trackId, participantId, alignedArtifact, offsetMs, driftPpm, gainDb, weight) match the interpretation guide.
- Ensure numeric values (offsets, confidence, gain, LUFS) are within expected ranges (e.g., confidence 0.0–1.0, offset ±several seconds, gain ±20dB).
- Cross-reference participant IDs and file paths with realistic metadata from `../verification/metadata-schema.md`.

### Common Patterns

- **Manifest structure**: Top-level metadata (schemaVersion, sessionId, generatedAt, canonicalFormat) followed by per-track arrays and optional artifacts (listeningMix, artifactsBundle).
- **Per-track offset/drift**: Each track includes alignment metadata (offsetMs, driftPpm) and export parameters (gainDb, weight) computed during the alignment lane.
- **QA summary**: Arbitrary key-value metadata capturing validation metrics (loudnessSpreadDb, clippedSamples, artifactGuardWarnings) for operator review.
- **Listening mix**: When present, includes format/codec, targetLufs, and optional notes for downstream handlers.

## Dependencies

### Internal

- `src/recog/export/manifest.py` — Python MVP implementation that generates manifests matching this example.
- `../schema/audio-sync-merge-manifest.schema.json` — Formal JSON Schema that this example must validate against.
- `../audio-sync-merge-manifest-interpretation.md` — Interpretation guide explaining field meanings.

### External

None.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Single manifest example present; represents complete session with multiple participants. -->
