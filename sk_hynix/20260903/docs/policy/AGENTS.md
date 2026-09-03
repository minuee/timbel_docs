<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# Policy and Constraints

## Purpose

Data and process policies governing recording behavior, anchor detection, and access/retention lifecycle for the Audio Sync Capture Platform. These documents define the constraints that the mobile app enforces at runtime and that the backend re-validates, ensuring research integrity and data governance.

## Key Files

| File | Purpose |
|------|---------|
| `recording-policy.md` | Recording baseline and blocking/warning conditions for research and pilot modes: format (WAV/PCM), sample rate (48kHz), channels (mono), microphone route (built-in only), pause/resume allowed, anchor required; server-side re-validation of format, codec, sample rate, channels |
| `anchor-policy.md` | Anchor detection strategy and fallback behavior: start/end beep requirements in research mode, acoustic ground-truth signal, fallback to metadata-only alignment if anchor detection fails, degraded classification |
| `access-retention-policy.md` | Data access control and retention lifecycle: participant data access, retention periods, deletion procedures, audit logging, destruction verification |

## For AI Agents

### Working In This Directory

1. **Policy enforcement**: Reference these policies during app development (Flutter state machine), API endpoint implementation (request validation), and processing pipeline design.
2. **Constraint validation**: Check that your implementation enforces all blocking conditions (e.g., reject Bluetooth mics, enforce 48kHz sampling) and logs warnings.
3. **Server re-validation**: Ensure backend validates that uploaded audio matches policy even if client-side enforcement failed.
4. **Gate criteria**: Use policy documents when defining release gate acceptance criteria (e.g., "must confirm anchor detection working in research baseline").

### Documentation Review

- Verify that blocking conditions in `recording-policy.md` are exhaustive and unambiguous (e.g., what is "Bluetooth mic"? Include HID/UAC vs. audio-endpoint distinction if relevant).
- Check that warning conditions and pilot-mode relaxations are clearly marked as optional (can be suppressed or logged without blocking).
- Ensure anchor policy fallback is realistic: metadata-only alignment is acceptable, but degraded classification must be documented in the manifest.
- Validate that access/retention policy aligns with actual data storage and deletion implementation (e.g., if retention is 30 days, confirm backend has scheduled deletion).
- Cross-reference policy constraints with their enforcement locations (e.g., Flutter app, backend API endpoint, processing lane validation).

### Common Patterns

- **Research baseline**: Strict constraints (WAV/PCM, 48kHz mono, built-in mic, anchor required) applied during controlled experiments to maximize reproducibility.
- **Pilot mode**: Relaxed constraints (additional formats allowed, Bluetooth warning instead of block, anchor optional) for real-world flexibility.
- **Server-side re-validation**: Even if Flutter client enforces policy, backend re-checks format, codec, sample rate, and channels because client cannot be fully trusted.
- **Anchor fallback**: If start/end beep not detected, proceed with metadata-prior alignment and mark confidence as degraded; do not block.
- **Warning vs. blocking**: Blocking conditions prevent upload/processing entirely; warnings log an issue but allow continuation.

## Dependencies

### Internal

- `src/recog/` — Python MVP backend; enforces recording policy at file ingest and processing stages.
- `apps/recorder-mobile/` — Flutter recorder; implements policy constraints in state machine and request validation.
- `../mobile/flutter-state-machine.md` — State machine that enforces recording policy transitions (e.g., block pause in research mode).
- `../api/room-session-api.md` — API endpoints that validate policy constraints in request handlers.
- `../architecture/synchronization-strategy.md` — Synchronization algorithm that depends on anchor policy (fallback to metadata-only if anchor missing).
- `../audio-sync-merge-manifest-interpretation.md` — Manifest specification that includes degraded classification when anchor fallback occurs.

### External

None.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Three policy documents present, covering recording baseline, anchor detection, and data lifecycle. -->
