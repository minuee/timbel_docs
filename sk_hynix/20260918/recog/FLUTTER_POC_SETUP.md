# Flutter PoC Environment Setup

## Goal
Prepare a machine so the Flutter recorder PoC can run successfully.

## Required tools
- Flutter SDK
- Dart SDK (normally bundled with Flutter)
- Python 3
- ffmpeg
- ffprobe

## Verify after installation
Run:

```bash
./run_flutter_poc_first_step.sh
```

The preflight must show:
- `[OK] flutter`
- `[OK] dart`
- `[OK] python3`
- `[OK] ffmpeg`
- `[OK] ffprobe`

## If Flutter is missing
Install Flutter and ensure `flutter` is on `PATH`.
Then run:

```bash
flutter --version
flutter doctor
```

## If Dart is missing
Dart should be available once Flutter is installed correctly.
Confirm:

```bash
dart --version
```

## If ffmpeg / ffprobe are missing
Install them and confirm:

```bash
ffmpeg -version
ffprobe -version
```

## Repo-side checks
These files must exist before running the PoC:
- `NEXT_ACTION.md`
- `docs/mobile/flutter-recorder-poc-runbook.md`
- `docs/mobile/flutter-recorder-poc-template.md`
- `docs/mobile/flutter-recorder-plugin-comparison.md`
- `tools/check_recorder_baseline.py`
- `scripts/run_recorder_poc_check.sh`
- `scripts/check_flutter_poc_prereqs.sh`
- `run_flutter_poc_first_step.sh`

## After setup
Follow this order:
1. `./run_flutter_poc_first_step.sh`
2. Build/open the Flutter recorder PoC app
3. Record one iOS sample and one Android sample
4. Run baseline validation
5. Record the result in the PoC template and plugin comparison sheet
