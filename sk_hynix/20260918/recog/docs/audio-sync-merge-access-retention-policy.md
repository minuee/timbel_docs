# Audio Sync Merge Access and Retention Notes

These notes document the minimum operator expectations for handling uploaded recordings and derived artifacts during MVP validation.

## Data classification
- Source smartphone recordings: sensitive meeting audio
- Derived aligned tracks: sensitive meeting audio
- Listening mixdown: sensitive meeting audio
- Manifest / QA summary: operational metadata that may still reveal participant identifiers and should be treated as sensitive-by-association

## Access policy
- Limit raw and derived audio access to the session operator, designated reviewer, and service accounts required for processing.
- Use time-limited artifact links or equivalent scoped access.
- Do not share listening mixes or aligned tracks in public channels.
- Capture every manual download or review action in the session audit trail when the platform supports it.

## Retention policy
- Keep source audio only as long as needed for processing, QA, and approved replay/debug workflows.
- Keep derived artifacts only until downstream STT handoff and review obligations are complete.
- Delete raw and derived artifacts together when the session retention window expires unless an explicit investigation hold exists.
- Preserve only non-sensitive benchmark summaries and redacted QA metrics for long-term trend analysis.

## Operator checks
Before declaring a session complete, confirm:
1. artifact access is limited to intended reviewers,
2. retention/deletion owner is identified,
3. manifest or QA exports do not expose more participant data than necessary,
4. any copied evidence bundles are stored in approved locations.
