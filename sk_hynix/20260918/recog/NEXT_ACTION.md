# Next Action

## Goal
Run the Flutter recorder PoC and decide whether the Flutter recorder strategy is viable.

## Exact steps
1. Build or open the Flutter recorder PoC app.
2. Record one sample on iOS.
3. Record one sample on Android.
4. Run the baseline checker:

```bash
scripts/run_recorder_poc_check.sh <ios-file.wav> <android-file.wav>
```

5. Record the results in:
- `docs/mobile/flutter-recorder-poc-template.md`
- `docs/mobile/flutter-recorder-plugin-comparison.md`

## Decision rule
- Both pass baseline -> keep Flutter recorder strategy
- One partially passes -> keep Flutter + native bridge for recorder/route
- Both fail -> revisit recorder/plugin strategy

## Main reference
- `docs/mobile/flutter-recorder-poc-runbook.md`
