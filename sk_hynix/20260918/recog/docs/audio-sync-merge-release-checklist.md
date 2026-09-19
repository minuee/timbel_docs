# Audio Sync Merge Release Checklist

Use this checklist before handing the MVP to downstream STT consumers or operational reviewers.

## 1. Artifact readiness
- [ ] Aligned tracks bundle exists and matches manifest entries.
- [ ] Listening mixdown exists and matches manifest metadata.
- [ ] Manifest JSON validates with `scripts/validate_manifest_contract.py`.
- [ ] QA summary and evidence bundle are stored under `verification/evidence/<timestamp>/`.

## 2. Acceptance criteria coverage
- [ ] AC1 evidence recorded for a 5-participant / 1-hour style session or equivalent fixture.
- [ ] AC2 mixed-format canonicalization evidence recorded.
- [ ] AC3 aligned track bundle evidence recorded.
- [ ] AC4 listening mix evidence recorded.
- [ ] AC5 manifest field evidence recorded.
- [ ] AC6 benchmark report recorded.
- [ ] AC7 listening rubric completed.
- [ ] AC8 scope audit completed.
- [ ] AC9 corrupt / unsupported input rejection evidence recorded.

## 3. Operational controls
- [ ] Access to source and derived artifacts is limited to intended reviewers.
- [ ] Retention / deletion owner is identified for the session.
- [ ] Evidence bundle location is approved for sensitive audio metadata.
- [ ] Any investigation hold is documented if artifacts are retained beyond normal expiry.

## 4. Non-goal guardrails
- [ ] No real-time or streaming requirement is implied by the release note.
- [ ] No diarization / speaker identification behavior is implied.
- [ ] No manual editing UI or waveform editor is implied.
- [ ] No video synchronization behavior is implied.

## 5. Verification command pack
Run and archive the output of:

```bash
scripts/collect_verification_evidence.sh <timestamp>
scripts/run_scope_audit.sh <timestamp>
python3 scripts/validate_manifest_contract.py docs/examples/audio-sync-merge-manifest-example.json
```

## 6. Release decision
- Decision: `PASS` / `HOLD` / `FAIL`
- Reviewer:
- Date:
- Notes:
