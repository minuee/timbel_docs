# Flutter Recorder Plugin Comparison

Use this table to compare candidate recorder plugins against the research baseline.

| Plugin | Version | iOS WAV | Android WAV | PCM control | 48kHz control | Mono control | Route detection | Timestamp capture | Maintenance status | Verdict | Notes |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| Candidate A |  |  |  |  |  |  |  |  |  |  |  |
| Candidate B |  |  |  |  |  |  |  |  |  |  |  |
| Candidate C |  |  |  |  |  |  |  |  |  |  |  |

## Scoring legend
- `PASS`
- `PARTIAL`
- `FAIL`

## Minimum acceptance for the first PoC
A candidate is acceptable for the first implementation path only if:
- iOS WAV = PASS
- Android WAV = PASS
- PCM control = PASS
- 48kHz control = PASS
- Mono control = PASS
- Timestamp capture = PASS

Route detection may be `PARTIAL` temporarily only if the team explicitly agrees to add a native bridge before controlled-device validation.

## Decision rules
### Accept
- Baseline file generation works on both iOS and Android
- Timestamp capture is reliable
- Route detection is acceptable or bridgeable

### Accept with native bridge
- Baseline generation works but route detection or timing precision is incomplete

### Reject
- Either platform cannot consistently produce the baseline format
- Sample rate / channel count / codec cannot be controlled

## Candidate notes template
### <Plugin name>
- Package:
- Version:
- Last update seen:
- iOS result:
- Android result:
- Known limitations:
- Suggested next action:
