from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from statistics import mean

from audio_sync.export import (
    build_file_record_session_export,
    validate_export_manifest,
    validate_recog_manifest,
)
from .audio import (
    AudioError,
    active_speech_dbfs,
    align_track,
    apply_drift_correction,
    audio_metadata,
    canonicalize,
    clipped_samples,
    detect_anchor_peak_seconds,
    estimate_alignment_and_drift,
    export_stt_track,
    mix_tracks,
    normalize_track,
)
from .evidence import export_session_to_evidence_bundle
from .models import FileRecord
from .store import SessionStore


class AudioSyncPipeline:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    @staticmethod
    def _parse_iso_timestamp(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    @classmethod
    def _coarse_prior_offset_seconds(cls, reference: FileRecord, target: FileRecord) -> tuple[float | None, str | None]:
        for source, ref_value, target_value in (
            ("recording_started_at", reference.recording_started_at, target.recording_started_at),
            ("start_command_received_at", reference.start_command_received_at, target.start_command_received_at),
            ("server_start_issued_at", reference.server_start_issued_at, target.server_start_issued_at),
        ):
            ref_ts = cls._parse_iso_timestamp(ref_value)
            target_ts = cls._parse_iso_timestamp(target_value)
            if ref_ts is not None and target_ts is not None:
                return target_ts - ref_ts, source
        return None, None

    @classmethod
    def _anchor_relative_seconds(cls, file_record: FileRecord) -> float | None:
        anchor_expected = cls._parse_iso_timestamp(file_record.anchor_expected_at)
        recording_started = cls._parse_iso_timestamp(file_record.recording_started_at)
        if anchor_expected is None or recording_started is None:
            return None
        relative = anchor_expected - recording_started
        if relative < 0:
            return None
        return relative

    @classmethod
    def _anchor_detected_at(cls, file_record: FileRecord, detected_seconds: float | None) -> str | None:
        base = cls._parse_iso_timestamp(file_record.recording_started_at)
        if base is None or detected_seconds is None:
            return None
        return datetime.fromtimestamp(base + detected_seconds, timezone.utc).isoformat().replace("+00:00", "Z")

    def process_session(
        self,
        session_id: str,
        *,
        evidence_export_root: str | None = None,
        evidence_run_type: str | None = None,
        evidence_reviewer: str = "backend_auto_export",
    ) -> dict:
        self.store.append_session_event(
            session_id,
            event_type="processing_requested",
            payload={"requested_at": self.store.get_session(session_id).updated_at},
        )
        session = self.store.set_session_state(session_id, status="processing", stage="queued")
        try:
            normalized_files = self._normalize(session_id)
            aligned_files = self._align(session_id, normalized_files)
            qa_summary = self._mix_and_export(session_id, aligned_files)
            self.store.set_session_state(
                session_id, status="done", stage="done", qa_summary=qa_summary
            )
            self._maybe_export_evidence_bundle(
                session_id,
                evidence_export_root=evidence_export_root,
                evidence_run_type=evidence_run_type,
                evidence_reviewer=evidence_reviewer,
            )
            self.store.append_session_event(
                session_id,
                event_type="processing_completed",
                payload={"qa_summary": qa_summary},
            )
            return self.store.get_session(session_id).to_dict()
        except Exception as exc:  # noqa: BLE001
            self.store.append_error(
                session_id,
                {"stage": self.store.get_session(session_id).stage, "message": str(exc)},
            )
            failed = self.store.set_session_state(session_id, status="failed", stage="failed")
            self.store.append_session_event(
                session_id,
                event_type="processing_failed",
                payload={"error": str(exc), "stage": failed.stage},
            )
            raise RuntimeError(f"session processing failed: {exc}") from exc

    def _maybe_export_evidence_bundle(
        self,
        session_id: str,
        *,
        evidence_export_root: str | None = None,
        evidence_run_type: str | None = None,
        evidence_reviewer: str = "backend_auto_export",
    ) -> None:
        root = evidence_export_root or os.environ.get("RECOG_EVIDENCE_EXPORT_ROOT")
        if not root:
            return
        evidence_root = Path(root) / session_id
        export_session_to_evidence_bundle(
            self.store.root,
            session_id,
            evidence_root,
            run_type=evidence_run_type,
            reviewer=evidence_reviewer,
        )
        session = self.store.get_session(session_id)
        self.store.mark_evidence_exported(
            session_id,
            evidence_bundle_path=str(evidence_root),
            evidence_run_type=evidence_run_type or session.recommended_run_type or "controlled_device",
            artifacts_index_path=str(evidence_root / "artifacts-index.json"),
        )

    def _normalize(self, session_id: str) -> list[FileRecord]:
        session = self.store.set_session_state(session_id, stage="normalizing")
        if not 1 <= len(session.files) <= session.limits["max_participants"]:
            raise ValueError("session must contain between 1 and 5 files")
        canonical_dir = self.store.session_dir(session_id) / "canonical"
        normalized: list[FileRecord] = []
        for file_record in session.files:
            try:
                metadata = audio_metadata(file_record.uploaded_path)
                if metadata["duration_seconds"] > session.limits["max_duration_seconds"]:
                    raise AudioError("file exceeds 1 hour limit")
                canonical_path = canonical_dir / f"{file_record.file_id}.wav"
                stt_path = canonical_dir / f"{file_record.file_id}.stt.wav"
                canonical_metadata = canonicalize(file_record.uploaded_path, canonical_path)
                export_stt_track(canonical_path, stt_path)
                updated = self.store.update_file(
                    session_id,
                    file_record.file_id,
                    status="canonicalized",
                    metadata=canonical_metadata | {"source": metadata},
                    canonical_path=str(canonical_path),
                    stt_path=str(stt_path),
                )
                normalized.append(updated)
            except Exception as exc:  # noqa: BLE001
                self.store.update_file(
                    session_id,
                    file_record.file_id,
                    status="rejected",
                    rejection_reason=str(exc),
                )
                raise
        return normalized

    def _select_reference(self, files: list[FileRecord]) -> FileRecord:
        loudest = max(files, key=lambda entry: active_speech_dbfs(entry.canonical_path or entry.uploaded_path))
        return loudest

    def _align(self, session_id: str, files: list[FileRecord]) -> list[FileRecord]:
        self.store.set_session_state(session_id, stage="aligning")
        aligned_dir = self.store.session_dir(session_id) / "aligned"
        work_dir = self.store.session_dir(session_id) / "work"
        reference = self._select_reference(files)
        reference_duration = audio_metadata(reference.canonical_path)["duration_seconds"]  # type: ignore[arg-type]
        reference_anchor_seconds = self._anchor_relative_seconds(reference)
        reference_anchor_detected_seconds = None
        reference_anchor_confidence = 0.0
        if reference_anchor_seconds is not None:
            reference_anchor_detected_seconds, reference_anchor_confidence = detect_anchor_peak_seconds(
                reference.canonical_path,
                expected_anchor_seconds=reference_anchor_seconds,
            )  # type: ignore[arg-type]
            reference = self.store.update_file(
                session_id,
                reference.file_id,
                anchor_detected_at=self._anchor_detected_at(reference, reference_anchor_detected_seconds),
                metadata=reference.metadata
                | {
                    "anchor_expected_seconds": reference_anchor_seconds,
                    "anchor_detected_seconds": reference_anchor_detected_seconds,
                    "anchor_detection_confidence": round(reference_anchor_confidence, 6),
                },
            )
        alignment_summaries: dict[str, dict] = {
            reference.file_id: {
                "offset_seconds": 0.0,
                "confidence": 1.0,
                "drift_ppm": 0.0,
                "correction_factor": 1.0,
                "anchor_detected_seconds": reference_anchor_detected_seconds,
                "anchor_detection_confidence": reference_anchor_confidence,
            }
        }
        max_duration = reference_duration
        for file_record in files:
            if file_record.file_id == reference.file_id:
                continue
            prior_offset_seconds, prior_source = self._coarse_prior_offset_seconds(reference, file_record)
            target_anchor_seconds = self._anchor_relative_seconds(file_record)
            target_anchor_detected_seconds = None
            target_anchor_confidence = 0.0
            anchor_detected_offset_seconds = None
            if target_anchor_seconds is not None:
                target_anchor_detected_seconds, target_anchor_confidence = detect_anchor_peak_seconds(
                    file_record.canonical_path,
                    expected_anchor_seconds=target_anchor_seconds,
                )  # type: ignore[arg-type]
            if reference_anchor_detected_seconds is not None and target_anchor_detected_seconds is not None:
                anchor_detected_offset_seconds = target_anchor_detected_seconds - reference_anchor_detected_seconds
            effective_prior = anchor_detected_offset_seconds if anchor_detected_offset_seconds is not None else prior_offset_seconds
            summary = estimate_alignment_and_drift(
                reference.canonical_path,
                file_record.canonical_path,
                coarse_offset_seconds=effective_prior,
                anchor_seconds=reference_anchor_seconds,
            )  # type: ignore[arg-type]
            corrected_path = work_dir / f"{file_record.file_id}.corrected.wav"
            apply_drift_correction(file_record.canonical_path, corrected_path, summary["correction_factor"])  # type: ignore[arg-type]
            corrected_duration = audio_metadata(corrected_path)["duration_seconds"]
            max_duration = max(max_duration, corrected_duration + max(0.0, summary["offset_seconds"]))
            alignment_summaries[file_record.file_id] = summary | {
                "corrected_path": str(corrected_path),
                "metadata_prior_offset_seconds": prior_offset_seconds,
                "metadata_prior_source": prior_source,
                "anchor_seconds": reference_anchor_seconds,
                "anchor_detected_seconds": target_anchor_detected_seconds,
                "anchor_detection_confidence": target_anchor_confidence,
                "anchor_detected_offset_seconds": anchor_detected_offset_seconds,
            }
        offset_baseline = min(float(summary["offset_seconds"]) for summary in alignment_summaries.values())
        normalized_offsets = {
            file_id: float(summary["offset_seconds"]) - offset_baseline
            for file_id, summary in alignment_summaries.items()
        }
        max_duration = 0.0
        for file_record in files:
            summary = alignment_summaries[file_record.file_id]
            source = summary.get("corrected_path", file_record.canonical_path)
            duration = audio_metadata(source)["duration_seconds"]
            max_duration = max(max_duration, duration + normalized_offsets[file_record.file_id])
        aligned_records: list[FileRecord] = []
        for file_record in files:
            summary = alignment_summaries[file_record.file_id]
            source = summary.get("corrected_path", file_record.canonical_path)
            aligned_path = aligned_dir / f"{file_record.file_id}.aligned.wav"
            align_track(
                source,
                aligned_path,
                offset_seconds=normalized_offsets[file_record.file_id],
                duration_seconds=max_duration,
            )
            updated = self.store.update_file(
                session_id,
                file_record.file_id,
                status="aligned",
                aligned_path=str(aligned_path),
                offset_seconds=normalized_offsets[file_record.file_id],
                drift_ppm=float(summary["drift_ppm"]),
                correction_factor=float(summary["correction_factor"]),
                alignment_confidence=float(summary["confidence"]),
                anchor_detected_at=self._anchor_detected_at(file_record, summary.get("anchor_detected_seconds")),
                metadata=file_record.metadata
                | {
                    "activity_offset_seconds": summary.get("activity_offset_seconds"),
                    "metadata_prior_offset_seconds": summary.get("metadata_prior_offset_seconds"),
                    "metadata_prior_source": summary.get("metadata_prior_source"),
                    "anchor_refined": summary.get("anchor_refined", False),
                    "anchor_seconds": summary.get("anchor_seconds"),
                    "anchor_detected_seconds": summary.get("anchor_detected_seconds"),
                    "anchor_detection_confidence": round(float(summary.get("anchor_detection_confidence", 0.0)), 6),
                    "anchor_detected_offset_seconds": summary.get("anchor_detected_offset_seconds"),
                },
            )
            aligned_records.append(updated)
        return aligned_records

    def _mix_and_export(self, session_id: str, files: list[FileRecord]) -> dict:
        self.store.set_session_state(session_id, stage="mixing")
        work_dir = self.store.session_dir(session_id) / "work"
        artifacts_dir = self.store.session_dir(session_id) / "artifacts"
        normalized_paths: list[str] = []
        loudness_values: list[float] = []
        track_entries: list[dict] = []
        capture_policy_warnings: list[dict[str, str]] = []
        for file_record in files:
            normalized_path = work_dir / f"{file_record.file_id}.normalized.wav"
            loudness = normalize_track(file_record.aligned_path, normalized_path)  # type: ignore[arg-type]
            loudness_values.append(loudness)
            normalized_paths.append(str(normalized_path))
            updated = self.store.update_file(
                session_id,
                file_record.file_id,
                status="ready",
                aligned_path=str(normalized_path),
                loudness_dbfs=loudness,
            )
            if updated.mic_route not in {"", "unknown", "built_in_mic"}:
                capture_policy_warnings.append({
                    "file_id": updated.file_id,
                    "warning": "non_built_in_mic_route",
                })
            if any(bool(value) for value in updated.audio_processing_flags.values()):
                capture_policy_warnings.append({
                    "file_id": updated.file_id,
                    "warning": "audio_processing_flags_enabled",
                })
            if updated.pause_resume_events:
                capture_policy_warnings.append({
                    "file_id": updated.file_id,
                    "warning": "pause_resume_events_present",
                })
            if updated.start_command_id is None and updated.room_id is not None:
                capture_policy_warnings.append({
                    "file_id": updated.file_id,
                    "warning": "missing_start_telemetry",
                })
            track_entries.append(
                {
                    "file_id": updated.file_id,
                    "participant_id": updated.participant_id,
                    "filename": updated.filename,
                    "aligned_path": updated.aligned_path,
                    "stt_path": updated.stt_path,
                    "offset_seconds": round(updated.offset_seconds, 6),
                    "drift_ppm": round(updated.drift_ppm, 3),
                    "correction_factor": round(updated.correction_factor, 8),
                    "alignment_confidence": round(updated.alignment_confidence, 6),
                    "loudness_dbfs": round(updated.loudness_dbfs or -120.0, 3),
                }
            )
        mix_path = work_dir / "listening_mix.wav"
        mix_tracks(normalized_paths, mix_path)
        self.store.add_artifact(
            session_id,
            kind="mixdown",
            name="listening_mix.wav",
            source_path=mix_path,
            mime_type="audio/wav",
        )
        qa_summary = {
            "alignment_confidence_mean": round(mean(entry["alignment_confidence"] for entry in track_entries), 6),
            "loudness_spread_db": round(max(loudness_values) - min(loudness_values), 3),
            "clipped_samples_mix": clipped_samples(mix_path),
            "recommended_stt_input": "tracks" if len(track_entries) > 1 else "mixdown",
            "metadata_prior_tracks_used": sum(
                1 for file_record in files if (file_record.metadata or {}).get("metadata_prior_offset_seconds") is not None
            ),
            "capture_policy_warnings": capture_policy_warnings,
        }
        session = self.store.get_session(session_id)
        export_result = build_file_record_session_export(
            session_id=session_id,
            files=session.files,
            mix_output_path=str(mix_path),
            manifest_path=artifacts_dir / "manifest.export.json",
            compat_manifest_path=artifacts_dir / "manifest.json",
            bundle_path=artifacts_dir / "aligned_tracks.zip",
            qa_summary=qa_summary,
            recommended_stt_input=qa_summary["recommended_stt_input"],
        )
        export_manifest = json.loads(export_result.manifest_path.read_text())
        validate_export_manifest(export_manifest)
        compat_manifest = json.loads(export_result.compat_manifest_path.read_text())
        validate_recog_manifest(compat_manifest)
        self.store.add_artifact(
            session_id,
            kind="manifest_export",
            name="manifest.export.json",
            source_path=export_result.manifest_path,
            mime_type="application/json",
            metadata={"recommended_stt_input": qa_summary["recommended_stt_input"]},
        )
        self.store.add_artifact(
            session_id,
            kind="manifest",
            name="manifest.json",
            source_path=export_result.compat_manifest_path,
            mime_type="application/json",
            metadata={"recommended_stt_input": qa_summary["recommended_stt_input"]},
        )
        self.store.add_artifact(
            session_id,
            kind="bundle",
            name="aligned_tracks.zip",
            source_path=export_result.bundle_path,
            mime_type="application/zip",
            metadata={"track_count": len(track_entries)},
        )
        self.store.set_session_state(session_id, stage="qa", qa_summary=qa_summary)
        return qa_summary
