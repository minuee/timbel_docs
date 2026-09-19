# Audio Sync Merge Service Operator Runbook

This runbook is for operators validating an MVP batch-processing session for the audio sync merge service.

## 1. Purpose
- Confirm a session can ingest smartphone recordings, process them through normalization/alignment/export, and emit evidence for STT-first delivery.
- Prevent accidental scope creep into non-goals during MVP validation.

## 2. Preconditions
- Session metadata service is reachable.
- Object storage for source and derived artifacts is writable.
- Background worker can execute the pipeline stages `queued -> normalizing -> aligning -> mixing -> qa -> done`.
- Fixture set is available for one of the following cases:
  - synthetic benchmark corpus
  - device sample corpus
  - manual listening review bundle

## 3. Session intake checklist
1. Create a session.
2. Register participant recordings (2, 3, or 5 tracks depending on scenario).
3. Capture source-file metadata before processing:
   - filename
   - participant identifier
   - content type / codec
   - sample rate / duration
   - upload timestamp
4. Reject unsupported or corrupt files before queueing DSP work.
5. Record any early rejection under file-scoped error notes.

## 4. Processing checkpoints
| Stage | Required observation | Failure evidence |
|---|---|---|
| `queued` | Job accepted and session state persisted | missing session/job identifiers |
| `normalizing` | Canonical audio format selected and logged | ffmpeg/decoder failure, unsupported format |
| `aligning` | Reference track, offsets, drift summary, confidence captured | low-confidence or catastrophic alignment note |
| `mixing` | Listening mix artifact emitted with checksum/duration | missing mix artifact or clipping/howling notes |
| `qa` | Loudness stats, artifact checks, rubric placeholder produced | absent QA summary or invalid values |
| `done` | Tracks bundle, mixdown, manifest, QA summary all present | incomplete artifact set |

## 5. Required output artifacts
- aligned individual track bundle
- listening mixdown
- manifest JSON for STT handoff
- QA summary / evidence bundle

Store raw outputs under a timestamped directory in `verification/evidence/` or the deployed artifact bucket equivalent.

## 6. Validation flow
1. Run automated verification collection (`scripts/collect_verification_evidence.sh`).
2. Verify artifact set and checksums.
3. Review manifest fields using `docs/audio-sync-merge-manifest-interpretation.md`.
4. Complete the listening rubric template (`docs/audio-sync-merge-listening-rubric-template.md`).
5. Update the verification matrix with PASS/FAIL/BLOCKED status.
6. Confirm non-goals remain absent using `docs/audio-sync-merge-scope-audit.md`.

## 7. Failure handling
- If a file fails validation before DSP: keep the session, mark only the file failed, and capture the rejection reason.
- If alignment confidence is low: keep raw intermediate artifacts and benchmark logs for diagnosis.
- If mixdown QA fails: do not recommend mixdown as STT input; preserve aligned tracks evidence.
- If retention/access rules cannot be enforced: stop distribution of derived artifacts until policy controls are applied.

## 8. Completion criteria
A session is ready for release review only when:
- all required artifacts exist,
- the verification matrix has no unresolved `FAIL` or `BLOCKED` rows for the targeted scenario,
- the listening rubric is completed for manual QA scenarios,
- scope audit confirms MVP non-goals remain excluded.
