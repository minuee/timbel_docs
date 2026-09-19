<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Mobile Recorder (Flutter)

## Purpose

Complete design, architecture, PoC runbooks, and plugin comparison library for the Flutter mobile recorder application. These documents guide Flutter development from spike evaluation through first-app commit, including state machine design, method-channel integration, device testing procedures, and evidence capture templates.

## Key Files

| File | Purpose |
|------|---------|
| `flutter-app-requirements.md` | Functional requirements for the Flutter recorder app: record audio at 48kHz mono PCM, manage metadata (participant ID, device ID, recording timestamps), integrate with room/session API, display anchor UX cues |
| `flutter-state-machine.md` | State machine definition for recorder lifecycle: idle → recording → paused → stopped → uploaded, with policy-blocking transitions and error recovery paths |
| `flutter-recorder-plugin-comparison.md` | Evaluation matrix comparing candidate audio recorder plugins (e.g., record, audio_recorder, flutter_sound): feature support, platform coverage, sample-rate control, format support, metadata capture |
| `flutter-recorder-poc-runbook.md` | Step-by-step operational procedures for executing the Flutter recorder PoC: plugin selection, baseline implementation, iOS/Android sample generation, policy validation |
| `flutter-recorder-poc-template.md` | Evidence capture template for PoC execution: test environment details, sample files generated, policy violations encountered, plugin baseline results, listening evidence |
| `flutter-recorder-spike-structure.md` | Directory and file organization for the Flutter recorder spike project: module structure, dependency management, build configuration |
| `flutter-first-week-execution-plan.md` | Detailed day-by-day plan for first-week Flutter development: environment setup, plugin evaluation, baseline implementation, running-check execution |
| `flutter-run-ready-checklist.md` | Pre-execution checklist ensuring Flutter environment is ready: Xcode/Android Studio versions, Flutter SDK, simulator/device availability, repository clone and workspace setup |
| `flutter-implementation-handoff-packet.md` | Complete handoff package for transitioning Flutter development from spike/PoC to first-real-app: architecture decisions, plugin selection rationale, state machine implementation, integration approach |
| `first-real-app-commit-guide.md` | Procedures for the first commit into the main Flutter app repository: branch naming, commit message format, integration test requirements, CI/CD gate validation |
| `method-channel-registration-checklist.md` | Pre-integration checklist for native (Swift/Kotlin) method-channel setup: native code paths, native binding declarations, error handler registration |
| `method-channel-registration-guide.md` | Step-by-step guide for registering Flutter method channels to native recording libraries: platform-channel naming conventions, argument serialization, error mapping |
| `virtual-device-smoke-runbook.md` | Smoke test procedures for iOS simulator and Android emulator: device configuration, app installation, baseline recording generation, artifact verification |
| `native-smoke-evidence-template.md` | Evidence capture template for native platform smoke tests: device model, OS version, sample file paths, format/codec verification, policy compliance check |

## For AI Agents

### Working In This Directory

1. **App development**: Reference `flutter-app-requirements.md` and `flutter-state-machine.md` when implementing recorder UI and state management.
2. **Plugin selection**: Use `flutter-recorder-plugin-comparison.md` to evaluate candidate libraries and justify selection.
3. **PoC execution**: Follow `flutter-recorder-poc-runbook.md` step-by-step; capture results in `flutter-recorder-poc-template.md`.
4. **Native integration**: Reference method-channel guides and checklists before implementing platform-specific recording logic.
5. **Device testing**: Execute virtual-device and native smoke tests using provided runbooks; document evidence in templates.
6. **Handoff**: Use `flutter-implementation-handoff-packet.md` to transition spike work to the main app repository.

### Documentation Review

- Verify that app requirements in `flutter-app-requirements.md` match API contract expectations from `../api/room-session-api.md`.
- Check that state machine transitions in `flutter-state-machine.md` align with policy constraints from `../policy/recording-policy.md` (e.g., no pause/resume in research mode).
- Validate that plugin comparison criteria (sample-rate control, metadata capture, format support) are exhaustive and objective.
- Ensure PoC runbook and spike structure guide are mutually consistent (same directory organization, file naming).
- Cross-reference method-channel integration guides with actual native binding declarations in the app.
- Verify that smoke-test runbooks are executable without external dependencies (simulator/emulator configuration self-contained or clearly documented).

### Common Patterns

- **Plugin baseline**: PoC evaluates plugins against research-mode constraints: 48kHz mono PCM, no pause/resume, metadata header capture.
- **State machine blocking**: Transitions like record→pause blocked in research mode; warn/allow in pilot mode (see `../policy/recording-policy.md`).
- **Metadata in headers**: Recording metadata (participant ID, device ID, start timestamp) passed as HTTP headers in upload, not in form data (see `../api/upload-contract.md`).
- **Evidence capture**: All PoC and smoke-test results documented in templates for operator review and release gating.
- **Method channels**: Platform-specific recording implementations use Flutter method channels for audio format/codec control not exposed by high-level Dart plugins.

## Dependencies

### Internal

- `apps/recorder-mobile/` — Flutter recorder application; documents guide development and integration work.
- `../api/` — REST API contracts (room-session, upload) that the recorder client consumes.
- `../policy/recording-policy.md` — Recording constraints enforced by app state machine.
- `../architecture/system-overview.md` — System topology describing mobile-to-backend interaction.

### External

- Flutter SDK (stable or dev channel, version TBD)
- Xcode (iOS development and simulator)
- Android Studio (Android development and emulator)
- Candidate recorder plugins (e.g., record, audio_recorder, flutter_sound)

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Fourteen mobile documents present, covering app requirements, state machine, plugin comparison, PoC runbooks, native integration, and device testing. -->
