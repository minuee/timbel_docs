# Audio Sync Merge Manifest Interpretation Guide

This document explains how operators and downstream consumers should read the MVP manifest produced by the export lane implementation under `src/audio_sync/export/manifest.py`. It is a documentation contract for review and handoff.

## Top-level fields
| Field | Meaning | Required for MVP | Notes |
|---|---|---|---|
| `schemaVersion` | Manifest contract version | Yes | Current implementation emits `1.0` |
| `sessionId` | Unique session identifier | Yes | Must match session API metadata |
| `generatedAt` | UTC timestamp when the manifest was written | Yes | ISO-8601 string |
| `canonicalFormat.sampleRateHz` | Internal processing sample rate | Yes | Current default: `48000` |
| `canonicalFormat.channels` | Internal processing channel count | Yes | Current default: `1` |
| `canonicalFormat.sampleFormat` | Internal processing sample format | Yes | Current default: `float32` |
| `recommendedSttInput` | Preferred downstream STT source (`tracks` or `mixdown`) | Yes | Defaults to `tracks` for STT-first workflows |
| `tracks` | Per-track aligned artifact entries | Yes | Must contain at least one aligned track |
| `qaSummary` | QA metrics and warnings | Yes | Can be empty during early scaffolding, but should be populated before release |
| `listeningMix` | Mixdown artifact metadata | Optional but expected for MVP | Present when mix/export stage produced a listening mix |
| `artifactsBundle` | Bundle archive path/URI | Optional but expected for packaged delivery | Present when packaging stage runs |
| `alignmentConfidence` | Session-level confidence summary | Optional | Rounded to 4 decimal places by the current implementation |

## Per-track fields
Each element in `tracks[]` should expose enough metadata for debugging, replay, and downstream STT handling.

| Field | Meaning | Required |
|---|---|---|
| `trackId` | Stable aligned-track identifier | Yes |
| `participantId` | Participant identity or stable alias | Yes |
| `alignedArtifact` | Path/URI for the aligned canonical track | Yes |
| `offsetMs` | Estimated alignment offset relative to the reference track | Yes |
| `driftPpm` | Estimated drift correction summary | Yes |
| `gainDb` | Gain applied during export planning | Yes |
| `weight` | Mix weighting for the track | Yes |
| `originalArtifact` | Original upload path/URI | Optional |
| `durationMs` | Duration of the aligned export | Optional |
| `loudness.*` | Loudness details such as `integratedLufs` and `truePeakDbfs` | Optional |
| `metadata` | Additional deterministic per-track metadata | Optional |

## Listening mix fields
When `listeningMix` is present, operators should expect:
- `path`
- `format`
- `codec`
- `targetLufs`
- optional `notes[]`

## QA summary recommendations
The current code accepts arbitrary QA keys, but the MVP review flow should prefer metrics such as:
- `loudnessSpreadDb`
- `clippedSamples`
- `artifactGuardWarnings`
- `syncErrorP50Ms`
- `syncErrorP95Ms`

## Example shape
```json
{
  "schemaVersion": "1.0",
  "sessionId": "session-123",
  "generatedAt": "2026-04-07T07:45:00Z",
  "canonicalFormat": {
    "sampleRateHz": 48000,
    "channels": 1,
    "sampleFormat": "float32"
  },
  "recommendedSttInput": "tracks",
  "alignmentConfidence": 0.9823,
  "tracks": [
    {
      "trackId": "track-a",
      "participantId": "alice",
      "alignedArtifact": "aligned/alice.wav",
      "originalArtifact": "raw/alice.m4a",
      "offsetMs": 42.125,
      "driftPpm": -3.5,
      "gainDb": 1.5,
      "weight": 1.0,
      "durationMs": 1000,
      "loudness": {
        "integratedLufs": -18.2,
        "truePeakDbfs": -0.7
      }
    }
  ],
  "listeningMix": {
    "path": "mix/listening_mix.wav",
    "format": "wav",
    "codec": "pcm_f32le",
    "targetLufs": -16.0
  },
  "qaSummary": {
    "loudnessSpreadDb": 2.1,
    "clippedSamples": 0,
    "syncErrorP95Ms": 8.7
  },
  "artifactsBundle": "bundle/session-123.zip"
}
```

## Interpretation rules
- Prefer `recommendedSttInput` over assumptions about always using the mixdown.
- Treat low per-track confidence as a debugging signal even when the session-level confidence looks acceptable.
- A manifest without `qaSummary` is incomplete for MVP release verification.
- The presence of `listeningMix` and `artifactsBundle` should match exported artifacts on disk or in object storage.
- Artifact URIs should only be shared according to the access/retention notes in `docs/audio-sync-merge-access-retention-policy.md`.
