# Audio Sync Merge MVP Scope Audit

This checklist enforces the PRD non-goals during MVP delivery.

## Explicit non-goals
- Real-time processing
- Speaker diarization
- Speaker identification
- Manual editing UI
- Video synchronization

## Scope audit checklist
Before release, confirm all answers remain `NO`.

| Question | Expected answer |
|---|---|
| Does the service depend on live/streaming ingestion or partial real-time alignment? | NO |
| Does the service attempt diarization or speaker identity inference? | NO |
| Does the service expose a manual trim/edit waveform UI? | NO |
| Does the service align or export video timelines? | NO |
| Does the release note promise anything outside aligned tracks, mixdown, manifest, and QA evidence? | NO |

## Suggested audit commands
Run these searches once implementation exists and archive the output under `verification/evidence/<timestamp>/scope-audit/`.
Scope the audit to the audio-sync delivery surface (`src/audio_sync`, `tests`, `testkit`, `tools`, `scripts`, and related docs) so unrelated legacy features elsewhere in the repository do not produce false positives for this MVP lane.

```bash
rg -n "realtime|real-time|streaming|websocket" src/audio_sync docs tests testkit tools scripts
rg -n "diarization|speaker id|speaker identification" src/audio_sync docs tests testkit tools scripts
rg -n "video sync|video alignment|ffmpeg.*video" src/audio_sync docs tests testkit tools scripts
rg -n "waveform|manual edit|trim UI|editor" src/audio_sync docs tests testkit tools scripts
```

## Current status
- Initial documentation audit: PASS (current workspace contains planning state only; no implementation paths for non-goals exist yet).
- Release audit: BLOCKED until source, tests, and docs are implemented.
