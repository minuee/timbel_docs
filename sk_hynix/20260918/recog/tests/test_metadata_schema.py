from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "recog"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "metadata"

PACKAGE_NAME = "src_recog"
if PACKAGE_NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        SRC_ROOT / "__init__.py",
        submodule_search_locations=[str(SRC_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to build import spec for src_recog")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)

protocol_models = importlib.import_module(f"{PACKAGE_NAME}.protocol_models")
RecordingEnvelope = protocol_models.RecordingEnvelope
classify_baseline = protocol_models.classify_baseline
degraded_envelope_from_legacy = protocol_models.degraded_envelope_from_legacy
validate_required_fields = protocol_models.validate_required_fields


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class MetadataSchemaTests(unittest.TestCase):
    def test_full_valid_envelope_roundtrips(self) -> None:
        payload = fixture("recording-envelope.valid.json")
        envelope = RecordingEnvelope.from_dict(payload)
        self.assertEqual(envelope.to_dict(), payload)

    def test_missing_timing_field_produces_validation_violation(self) -> None:
        payload = fixture("recording-envelope.missing-timing.json")
        envelope = RecordingEnvelope.from_dict(payload)
        violations = validate_required_fields(envelope)
        self.assertIn("timing.recording_started_at_missing", violations)

    def test_baseline_valid_classification(self) -> None:
        envelope = RecordingEnvelope.from_dict(fixture("recording-envelope.valid.json"))
        valid, violations, classification = classify_baseline(envelope)
        self.assertTrue(valid)
        self.assertEqual(violations, [])
        self.assertEqual(classification, "baseline_valid")

    def test_bluetooth_route_classifies_as_degraded(self) -> None:
        envelope = RecordingEnvelope.from_dict(fixture("recording-envelope.bluetooth.json"))
        valid, violations, classification = classify_baseline(envelope)
        self.assertFalse(valid)
        self.assertIn("mic_route_bluetooth_not_allowed", violations)
        self.assertEqual(classification, "degraded")

    def test_legacy_envelope_falls_back_to_degraded_defaults(self) -> None:
        envelope = degraded_envelope_from_legacy(
            session_id="session_legacy_001",
            participant_id="participant_legacy_001",
            filename="legacy_input.wav",
        )
        valid, violations, classification = classify_baseline(envelope)
        self.assertFalse(valid)
        self.assertEqual(classification, "degraded")
        self.assertIn("start_strategy_not_server_authoritative_beep", violations)
        self.assertIn("timing.recording_started_at_missing", violations)


if __name__ == "__main__":
    unittest.main()
