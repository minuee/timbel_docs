# Immediate Next Steps

This document converts the planning artifacts into a short execution checklist.

## 1. Freeze the contracts
Review and approve these five documents first:
- `docs/product/audio-sync-capture-platform-prd.md`
- `docs/verification/metadata-schema.md`
- `docs/api/room-session-api.md`
- `docs/policy/recording-policy.md`
- `docs/policy/anchor-policy.md`

Approval checklist:
- project is defined as capture platform, not backend-only
- required metadata fields are sufficient
- room -> upload -> process flow is complete
- research baseline is strict enough
- start/end anchor roles are clear

## 2. Run the recorder PoC
Goal: verify Flutter can produce the research-baseline file format.

### PoC checks
- iOS can record WAV
- Android can record WAV
- codec is PCM (`pcm_s16le`)
- sample rate is 48kHz
- channel count is mono
- route can be detected
- recording start time can be captured

### Validation tool
Run:

```bash
python3 tools/check_recorder_baseline.py <path/to/file.wav>
```

Record the result in:
- `docs/mobile/flutter-recorder-poc-template.md`

Decision rule:
- if both iOS and Android pass -> keep Flutter recorder strategy
- if one side partially fails -> keep Flutter, add native bridge only for recorder/route
- if both fail -> reconsider recorder strategy

## 3. Start implementation in this order
### Track A — Mobile
1. Flutter shell
2. room create/join screens
3. lobby + ready state
4. host start flow
5. recorder baseline PoC integration
6. metadata JSON builder
7. upload + retry

### Track B — Server
1. `POST /rooms`
2. `POST /rooms/{id}/join`
3. `POST /rooms/{id}/ready`
4. `POST /rooms/{id}/start`
5. `POST /sessions/{id}/files`
6. metadata persistence

### Track C — Backend
1. extend `FileRecord` / session models with metadata
2. ingest upload metadata
3. add metadata prior hook
4. add anchor metadata hook
5. keep current artifact generation path working

## 4. First implementation milestone
A first milestone is complete when:
- two devices can join the same room
- host can start
- each device records a baseline file
- file + metadata upload succeeds
- backend processes the session
- artifacts are produced:
  - aligned tracks bundle
  - listening mix
  - manifest

## 5. First validation milestone
After the first milestone, run:
- 2-device smoke
- 3-device / 10-minute controlled-device baseline

Evidence should be stored under:
- `verification/evidence/<timestamp>/`

## 6. Important rule
Do not start optimizing DSP before the capture contract and recorder baseline are proven.
