from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from recog.evidence import build_evidence_summary, classify_session_payload, export_session_to_evidence_bundle
from recog.pipeline import AudioSyncPipeline
from recog.store import SessionStore
from recog.synthetic import generate_fixture_session


class EvidenceTests(unittest.TestCase):
    def test_build_evidence_summary_marks_done_session_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_dir = Path(tmpdir) / 'fixture'
            truth = generate_fixture_session(fixture_dir, track_count=2)
            store = SessionStore(Path(tmpdir) / 'data')
            session = store.create_session()
            for track in truth['tracks']:
                store.add_file(
                    session.session_id,
                    participant_id=track['participant_id'],
                    filename=track['filename'],
                    payload=Path(track['path']).read_bytes(),
                )
            result = AudioSyncPipeline(store).process_session(session.session_id)
            summary = build_evidence_summary(result)
            self.assertTrue(summary['evidence_ready'])
            self.assertEqual(summary['recommended_run_type'], 'synthetic')
            self.assertIn('export_session_to_evidence_bundle.py', summary['evidence_export_hint'])

    def test_classify_session_payload_rejected_when_file_missing_identity(self) -> None:
        payload = {
            'status': 'done',
            'mode': 'research',
            'room_id': 'room_1',
            'start_strategy': 'server_authoritative_beep',
            'files': [
                {
                    'participant_id': '',
                    'session_id': 'session_1',
                    'rejection_reason': None,
                    'baseline_valid': True,
                    'container': 'wav',
                    'channels': 1,
                    'sample_rate_hz': 48000,
                    'pause_resume_events': [],
                    'mic_route': 'built_in_mic',
                }
            ],
        }
        classification, reason, failed_rules, degraded_rules = classify_session_payload(payload)
        self.assertEqual(classification, 'rejected')
        self.assertIn('missing_participant_id', failed_rules)
        self.assertEqual(degraded_rules, [])
        self.assertIn('missing_participant_id', reason)

    def test_export_session_to_evidence_bundle_writes_bundle_and_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_dir = Path(tmpdir) / 'fixture'
            truth = generate_fixture_session(fixture_dir, track_count=2)
            data_root = Path(tmpdir) / 'data'
            store = SessionStore(data_root)
            session = store.create_session()
            for track in truth['tracks']:
                store.add_file(
                    session.session_id,
                    participant_id=track['participant_id'],
                    filename=track['filename'],
                    payload=Path(track['path']).read_bytes(),
                )
            AudioSyncPipeline(store).process_session(session.session_id)
            evidence_root = Path(tmpdir) / 'evidence'
            export_session_to_evidence_bundle(data_root, session.session_id, evidence_root, run_type='synthetic', reviewer='tester')
            bundle = json.loads((evidence_root / 'bundle.json').read_text())
            classification = json.loads((evidence_root / 'classification.json').read_text())
            self.assertEqual(bundle['run_type'], 'synthetic')
            self.assertEqual(classification['reviewer'], 'tester')
            self.assertIn('manifest', bundle['artifacts'])
            self.assertTrue((evidence_root / 'artifacts' / 'manifest.json').exists())

    def test_process_session_auto_exports_when_env_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_dir = Path(tmpdir) / 'fixture'
            truth = generate_fixture_session(fixture_dir, track_count=2)
            data_root = Path(tmpdir) / 'data'
            evidence_root = Path(tmpdir) / 'auto-evidence'
            store = SessionStore(data_root)
            session = store.create_session()
            for track in truth['tracks']:
                store.add_file(
                    session.session_id,
                    participant_id=track['participant_id'],
                    filename=track['filename'],
                    payload=Path(track['path']).read_bytes(),
                )
            import os
            old = os.environ.get('RECOG_EVIDENCE_EXPORT_ROOT')
            os.environ['RECOG_EVIDENCE_EXPORT_ROOT'] = str(evidence_root)
            try:
                result = AudioSyncPipeline(store).process_session(session.session_id)
            finally:
                if old is None:
                    os.environ.pop('RECOG_EVIDENCE_EXPORT_ROOT', None)
                else:
                    os.environ['RECOG_EVIDENCE_EXPORT_ROOT'] = old
            self.assertEqual(result['evidence_bundle_path'], str(evidence_root / session.session_id))
            self.assertEqual(result['evidence_run_type'], 'synthetic')
            self.assertTrue((evidence_root / session.session_id / 'bundle.json').exists())
            self.assertTrue((evidence_root / session.session_id / 'artifacts-index.json').exists())

            exported_session = store.get_session(session.session_id)
            artifact_names = {artifact.name for artifact in exported_session.artifacts}
            self.assertIn('bundle.json', artifact_names)
            self.assertIn('classification.json', artifact_names)
            self.assertIn('artifacts-index.json', artifact_names)


if __name__ == '__main__':
    unittest.main()
