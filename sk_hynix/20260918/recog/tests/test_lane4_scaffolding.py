from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from testkit.artifact_contract import build_artifact_contract
from testkit.benchmark import TrackPrediction, evaluate_alignment
from testkit.benchmark_report import build_benchmark_report_examples
from testkit.evidence_report import build_evidence_template
from testkit.failure_taxonomy import build_failure_taxonomy
from testkit.ingestion_matrix import build_ingestion_matrix
from testkit.listening_rubric import build_listening_rubric
from testkit.load_profile import build_default_load_profile
from testkit.regression_plan import build_regression_plan
from testkit.status_flow import build_status_flow
from testkit.stt_handoff import build_stt_handoff_cases
from testkit.synthetic_corpus import build_integration_matrix, build_default_session_plan, generate_session_fixture


class Lane4ScaffoldingTests(unittest.TestCase):
    def _fixture_path(self, name: str) -> Path:
        return Path(__file__).resolve().parent / "fixtures" / "lane4" / name

    def test_ingestion_matrix_covers_mixed_formats_and_failures(self) -> None:
        cases = {case.case_id: case for case in build_ingestion_matrix()}

        self.assertEqual(cases["wav-happy-path"].expected_outcome, "canonicalize")
        self.assertEqual(cases["m4a-happy-path"].media_type, "audio/mp4")
        self.assertEqual(cases["flac-happy-path"].media_type, "audio/flac")
        self.assertEqual(cases["corrupt-wav"].expected_outcome, "reject_corrupt")
        self.assertEqual(cases["unsupported-text"].acceptance_criteria, ("AC9",))

    def test_load_profile_matches_mvp_limits_and_retry_paths(self) -> None:
        profile = build_default_load_profile()

        self.assertEqual(profile.profile_id, "mvp-5p-60m")
        self.assertEqual(profile.participant_count, 5)
        self.assertEqual(profile.duration_minutes, 60)
        self.assertEqual(profile.acceptance_criteria, ("AC1", "AC6", "AC7"))
        self.assertIn("worker_crash_during_align", profile.retry_cases)
        self.assertEqual(sum(stage.budget_minutes for stage in profile.stages), 50)

    def test_regression_plan_aggregates_lane4_scaffolding(self) -> None:
        plan = build_regression_plan()

        self.assertEqual(plan["summary"]["ingestion_case_count"], 5)
        self.assertEqual(plan["summary"]["verification_scenario_count"], 5)
        self.assertEqual(plan["summary"]["retry_case_count"], 3)

    def test_render_regression_plan_cli_outputs_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "tools" / "render_regression_plan.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertIn("ingestion_matrix", payload)
        self.assertIn("verification_matrix", payload)
        self.assertEqual(payload["load_profile"]["profile_id"], "mvp-5p-60m")

    def test_evidence_template_exposes_scaffolded_acceptance_checks(self) -> None:
        template = build_evidence_template()

        self.assertEqual(template["task"], "task-5 synthetic corpus + regression test lane")
        self.assertEqual(template["status"], "in_progress")
        self.assertEqual(template["summary"]["verification_scenario_count"], 5)
        acceptance_criteria = {item["acceptance_criterion"] for item in template["acceptance_checks"]}
        self.assertEqual(acceptance_criteria, {"AC1", "AC2", "AC6", "AC9"})

    def test_render_evidence_template_cli_outputs_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "tools" / "render_evidence_template.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "in_progress")
        self.assertEqual(payload["summary"]["ingestion_case_count"], 5)

    def test_integration_matrix_matches_golden_snapshot(self) -> None:
        snapshot = json.loads(self._fixture_path("integration-matrix.snapshot.json").read_text())
        actual = {
            "sessions": [
                {
                    "session_id": plan.session_id,
                    "participant_count": len(plan.tracks),
                    "duration_s": plan.duration_s,
                    "offsets_ms": [track.start_offset_ms for track in plan.tracks],
                    "sample_rates_hz": [track.sample_rate_hz for track in plan.tracks],
                }
                for plan in build_integration_matrix()
            ]
        }
        self.assertEqual(actual, snapshot)

    def test_benchmark_thresholds_match_golden_snapshot(self) -> None:
        snapshot = json.loads(self._fixture_path("benchmark-thresholds.snapshot.json").read_text())
        plan = build_default_session_plan(participants=3, duration_s=6.0, max_offset_ms=1_000)

        actual_cases = []
        for item in snapshot["cases"]:
            with tempfile.TemporaryDirectory() as temp_dir:
                session_dir = generate_session_fixture(temp_dir, plan)
                ground_truth = json.loads((Path(session_dir) / "ground_truth.json").read_text())
                predictions = [
                    TrackPrediction(
                        participant_id=track["participant_id"],
                        predicted_offset_ms=track["start_offset_ms"] + item["offset_error_ms"],
                        predicted_drift_ppm=track["drift_ppm"] + 1.0,
                    )
                    for track in ground_truth["tracks"]
                ]
                result = evaluate_alignment(ground_truth, predictions)
            actual_cases.append(
                {
                    "case_id": item["case_id"],
                    "offset_error_ms": item["offset_error_ms"],
                    "expected_verdict": result.verdict,
                }
            )

        self.assertEqual(actual_cases, snapshot["cases"])

    def test_artifact_contract_covers_tracks_mixdown_and_manifest(self) -> None:
        contract = {item.artifact_type: item for item in build_artifact_contract()}

        self.assertEqual(
            contract["aligned_tracks_bundle"].required_fields,
            ("sessionId", "trackCount", "canonicalFormat", "tracks"),
        )
        self.assertEqual(contract["mixdown"].acceptance_criteria, ("AC4", "AC7"))
        self.assertIn("recommendedSttInput", contract["manifest"].required_fields)

    def test_render_artifact_contract_cli_outputs_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "tools" / "render_artifact_contract.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        artifact_types = [item["artifact_type"] for item in payload]
        self.assertEqual(artifact_types, ["aligned_tracks_bundle", "mixdown", "manifest"])

    def test_listening_rubric_matches_ac7_thresholds(self) -> None:
        rubric = {item.name: item for item in build_listening_rubric()}

        self.assertEqual(len(rubric), 5)
        self.assertEqual(rubric["howling_free"].min_score, 4.5)
        self.assertEqual(rubric["overlap_smear_free"].min_score, 4.5)
        self.assertEqual(rubric["stt_clarity"].min_score, 4.0)

    def test_render_listening_rubric_cli_outputs_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "tools" / "render_listening_rubric.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        names = [item["name"] for item in payload]
        self.assertEqual(
            names,
            [
                "howling_free",
                "overlap_smear_free",
                "loudness_consistency",
                "naturalness",
                "stt_clarity",
            ],
        )

    def test_failure_taxonomy_covers_file_and_session_failures(self) -> None:
        taxonomy = {item.code: item for item in build_failure_taxonomy()}

        self.assertEqual(taxonomy["unsupported_format"].scope, "file")
        self.assertFalse(taxonomy["corrupt_audio_payload"].retryable)
        self.assertTrue(taxonomy["worker_crash_during_align"].retryable)
        self.assertEqual(taxonomy["artifact_publish_mismatch"].acceptance_criteria, ("AC3", "AC4", "AC5"))

    def test_render_failure_taxonomy_cli_outputs_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "tools" / "render_failure_taxonomy.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        codes = [item["code"] for item in payload]
        self.assertIn("unsupported_format", codes)
        self.assertIn("worker_crash_during_align", codes)

    def test_status_flow_matches_prd_state_sequence(self) -> None:
        flows = build_status_flow()

        self.assertEqual(flows["happy_path"], ("queued", "normalizing", "aligning", "mixing", "qa", "done"))
        self.assertIn("aligning_retry", flows["retry_path"])
        self.assertEqual(flows["failure_path"][-1], "failed")

    def test_render_status_flow_cli_outputs_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "tools" / "render_status_flow.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["happy_path"][0], "queued")
        self.assertEqual(payload["happy_path"][-1], "done")

    def test_stt_handoff_cases_cover_tracks_and_mixdown_paths(self) -> None:
        cases = {item.case_id: item for item in build_stt_handoff_cases()}

        self.assertEqual(cases["tracks_preferred"].recommended_input, "tracks")
        self.assertEqual(cases["mixdown_fallback"].recommended_input, "mixdown")
        self.assertIn("manual_review_required", cases["degraded_alignment_review"].conditions)

    def test_render_stt_handoff_cli_outputs_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "tools" / "render_stt_handoff.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        recommended_inputs = [item["recommended_input"] for item in payload]
        self.assertEqual(recommended_inputs, ["tracks", "mixdown", "tracks"])

    def test_benchmark_report_examples_cover_pass_degraded_fail(self) -> None:
        report = build_benchmark_report_examples()

        self.assertEqual(report["target_p95_ms"], 10.0)
        self.assertEqual(report["degraded_p95_ms"], 20.0)
        self.assertEqual([item["verdict"] for item in report["examples"]], ["pass", "degraded", "fail"])

    def test_render_benchmark_report_cli_outputs_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "tools" / "render_benchmark_report.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["examples"][0]["verdict"], "pass")
        self.assertEqual(payload["examples"][-1]["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()
