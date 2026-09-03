<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# System Architecture

## Purpose

Architectural documentation describing the Audio Sync Capture Platform topology, synchronization algorithm, service boundaries, and mobile-to-backend interaction patterns. These documents inform both the Python MVP design and Flutter mobile client implementation.

## Key Files

| File | Purpose |
|------|---------|
| `system-overview.md` | High-level service topology: mobile recorder, control plane, upload plane, processing lanes (alignment, export), manifest generation; participant flows and data movement |
| `synchronization-strategy.md` | Offset and drift alignment algorithm: metadata-prior approach, anchor detection, audio fine-alignment, drift correction, fallback strategies, research baseline constraints |

## For AI Agents

### Working In This Directory

1. **Implementation reference**: Use `system-overview.md` to understand service boundaries before implementing new features or modifying inter-service contracts.
2. **Alignment algorithm**: Reference `synchronization-strategy.md` when implementing or debugging the synchronization lane in the Python MVP.
3. **Mobile-backend interaction**: Consult `system-overview.md` for the expected data flow from Flutter recorder to processing pipeline.

### Documentation Review

- Verify that service boundaries in `system-overview.md` (control plane, upload plane, processing lanes) match the actual code organization in `src/recog/`.
- Check that synchronization strategy algorithm description matches the implementation in synchronization lane.
- Validate that all participant flows (join → ready → start → stop → export) are correctly sequenced.
- Ensure HTML/Mermaid diagrams (if present) render without errors and accurately reflect the architecture.
- Cross-reference policy constraints from `../policy/` that affect architectural decisions (e.g., anchor requirements, recording format baseline).

### Common Patterns

- **Metadata-prior alignment**: Synchronization relies on metadata (server start time, device timestamps) as the first signal, with audio analysis as final truth.
- **Anchor detection**: Start/end beeps or acoustic events provide ground-truth alignment points; fallback to metadata-only alignment if anchor detection fails.
- **Canonical format**: All audio processing uses 48kHz mono PCM internally (float32 sample format); transformations logged in manifest.
- **Lane architecture**: Processing pipeline consists of distinct lanes (ingest, alignment, export, manifest) with deterministic checkpoints.

## Dependencies

### Internal

- `src/recog/` — Python MVP implementing the architecture and synchronization strategy.
- `apps/recorder-mobile/` — Flutter recorder generating input data (audio files + metadata) for the system.
- `../api/` — API contracts that implement the control plane and upload plane interfaces.
- `../policy/` — Recording policy and anchor policy that constrain architectural decisions.

### External

- ffmpeg — Audio processing tool used in the export lane for sample-rate conversion, mixing, and artifact generation.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Two architecture documents present, system topology and algorithm strategy documented, baseline constraints noted. -->
