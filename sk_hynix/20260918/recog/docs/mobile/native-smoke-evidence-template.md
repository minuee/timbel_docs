# Native Smoke Evidence Template — Audio Sync Platform

## Purpose
이 문서는 iOS / Android에서 method-channel registration 후 수행하는 **native smoke test** 결과를 일관된 형식으로 기록하기 위한 템플릿이다.

목표는:
1. fake mode -> native bridge mode 전환 초기에 최소 smoke 결과를 남기고
2. 각 채널의 성공/실패를 비교 가능하게 기록하며
3. 다음 단계(recorder 실제 capture smoke)로 넘어갈지 판단하는 근거를 남기는 것이다.

---

## 1. Session Metadata
- Timestamp:
- Operator:
- Branch / commit:
- App runtime mode: `fake | nativeBridge`
- Flutter version:
- Dart version:
- iOS device / simulator:
- Android device / emulator:

---

## 2. Channel Registration Status
### iOS
- [ ] `audio_sync/recorder` registered
- [ ] `audio_sync/time_sync` registered
- [ ] `audio_sync/route` registered
- [ ] `audio_sync/beep` registered

### Android
- [ ] `audio_sync/recorder` registered
- [ ] `audio_sync/time_sync` registered
- [ ] `audio_sync/route` registered
- [ ] `audio_sync/beep` registered

---

## 3. Smoke Calls Run
Record whether each call succeeds on each platform.

| Call | iOS | Android | Notes |
|---|---|---|---|
| `getRecorderState` |  |  |  |
| `measureTimeSync` |  |  |  |
| `inspectCurrentRoute` |  |  |  |
| `inspectProcessingFlags` |  |  |  |
| `scheduleSyncBeep` |  |  |  |

Status values:
- `PASS`
- `PARTIAL`
- `FAIL`

---

## 4. Expected Payload Checks
### `getRecorderState`
Expected fields:
- `ok`
- `recorderState`

Observed payload:
```json
{}
```

### `measureTimeSync`
Expected fields:
- `ok`
- `serverTimeOffsetMs`
- `roundTripMs`
- `syncQualityBucket`
- `measuredAt`

Observed payload:
```json
{}
```

### `inspectCurrentRoute`
Expected fields:
- `ok`
- `micRoute`

Observed payload:
```json
{}
```

### `inspectProcessingFlags`
Expected fields:
- `ok`
- `audioProcessingFlags.agc`
- `audioProcessingFlags.noiseSuppression`
- `audioProcessingFlags.aec`

Observed payload:
```json
{}
```

### `scheduleSyncBeep`
Expected fields:
- `ok`
- `anchorType`
- `anchorSpecVersion`
- `beepScheduledAt`
- `beepPlayedAt`
- `playbackStatus`

Observed payload:
```json
{}
```

---

## 5. Error Payload Checks
If any call failed, paste one representative error payload per platform.

### iOS error payload
```json
{}
```

### Android error payload
```json
{}
```

Questions:
- Was the error converted into the expected Flutter/native shape?
- Was severity understandable (`blocker`, `warning`, `info`)?

---

## 6. Environment Notes
- Audio route during test:
- Bluetooth connected? `yes/no`
- Microphone permission granted? `yes/no`
- Any simulator/emulator limitations?
- Any platform-specific registration quirks?

---

## 7. Decision Summary
### iOS verdict
- `PASS | PARTIAL | FAIL`
- Why:

### Android verdict
- `PASS | PARTIAL | FAIL`
- Why:

### Combined verdict
- `PASS | PARTIAL | FAIL`

### Recommended next step
- [ ] stay in fake mode and fix registration issues
- [ ] keep shell, proceed to native smoke for recorder start
- [ ] keep shell, but recorder must move deeper into native implementation
- [ ] revisit app/bootstrap strategy

---

## 8. Attachments Checklist
- [ ] iOS console log
- [ ] Android logcat snippet
- [ ] one successful payload sample
- [ ] one failed payload sample (if any)
- [ ] screenshots if helpful
- [ ] updated `docs/mobile/method-channel-registration-checklist.md`

---

## 9. Suggested Evidence Location
Store under:
```text
verification/evidence/<timestamp>/mobile-native-smoke/
```

Suggested files:
```text
verification/evidence/<timestamp>/mobile-native-smoke/
  summary.md
  ios-smoke.log
  android-smoke.log
  payload-success.json
  payload-failure.json
```
