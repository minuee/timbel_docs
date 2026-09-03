<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-20 | Updated: 2026-04-20 -->

# API Contracts

## Purpose

REST API contract definitions for the Audio Sync Capture Platform control plane (rooms and sessions) and upload plane (file ingestion). These documents are the canonical interface specification between mobile clients (Flutter recorder) and the backend Python MVP.

## Key Files

| File | Purpose |
|------|---------|
| `room-session-api.md` | REST contract for rooms (participant coordination) and sessions (processing/results) endpoints, including join, ready, start, stop, and status flows |
| `upload-contract.md` | File upload contract for `POST /sessions/{id}/files` endpoint: multipart form encoding, metadata headers, processing triggers, and success/error responses |

## For AI Agents

### Working In This Directory

1. **Contract reference**: Use these files as the single source of truth for mobile client implementation and backend route definitions.
2. **Error handling**: Reference the common response format (success/failure JSON) and error codes when designing error paths.
3. **Integration testing**: Use request/response examples as a basis for integration test cases.
4. **API versioning**: If modifying endpoints, ensure backward compatibility or document breaking changes in the corresponding backend/mobile AGENTS.md.

### Documentation Review

- Verify all endpoint methods, paths, and request/response formats are syntactically correct.
- Check that HTTP status codes (200, 400, 403, 409, etc.) align with actual backend implementation.
- Validate that error codes (e.g., `policy_blocked`, `format_unsupported`) are implemented and tested.
- Ensure request examples (curl, JSON) are runnable against the API (when backend is deployed).
- Cross-reference endpoint fields against `../verification/metadata-schema.md` for consistency.

### Common Patterns

- **Common response format**: All responses follow `{ ok: boolean, data: {...}, error: null | {code, message} }` structure.
- **Metadata headers**: File uploads include headers like `X-Participant-ID`, `X-Device-ID`, `X-Recording-Started-At` to pass recording metadata without reparsing audio.
- **Policy validation**: Both control plane (ready/start) and upload plane reject requests that violate policies from `../policy/recording-policy.md`.
- **Session state machine**: Rooms progress through participant registration → ready → start → stop → export phases.

## Dependencies

### Internal

- `src/recog/` — Python MVP backend implementing all defined endpoints.
- `apps/recorder-mobile/` — Flutter recorder client consuming these API contracts.
- `../policy/recording-policy.md` — Policy constraints enforced by these endpoints (e.g., Bluetooth mic rejection).
- `../verification/metadata-schema.md` — Metadata field definitions and validation rules.

### External

None.

<!-- MANUAL: -->
<!-- Reviewed 2026-04-20: Two contract files present, endpoint structure verified, common response format documented. -->
