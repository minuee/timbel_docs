# audio_sync.export

Isolated export-lane package for the audio sync merge MVP.

## Responsibilities
- build listening-mix ffmpeg plans without owning DSP alignment internals
- serialize canonical export manifests for STT handoff
- serialize compatibility manifests matching the current `recog.pipeline` shape
- package artifacts into a checksum-bearing zip bundle
- provide adapters from `recog.models.FileRecord` to export-lane dataclasses

## Intended integration surface
- `build_exports_from_file_records(...)`
  - maps existing `recog` file records into `ExportArtifacts`
- `build_export_manifest(...)`
  - canonical export/STT handoff payload
- `build_recog_manifest(...)`
  - compatibility payload matching the current pipeline contract
- `build_session_export(...)`
  - writes manifest + bundle and returns a listening-mix command plan

## Notes
- This package is stdlib-only so it can be developed before shared app scaffolding is finalized.
- It intentionally avoids touching alignment/drift implementation details beyond public record fields.
