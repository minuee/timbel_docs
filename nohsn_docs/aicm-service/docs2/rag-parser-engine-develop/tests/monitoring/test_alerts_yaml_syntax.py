"""D31d Phase 3 §4 (#212) — Prometheus alerts.yml syntax + 정의 검증.

검증:
- yaml.safe_load 통과.
- 8 alert 정의 (기존 5 + 신규 3) 존재.
- 신규 3 alert (KmsPayloadSalvageRateHigh / KmsRlsViolationDetected /
  KmsEsIndexFailureRateHigh) 의 alert / expr / for / labels / annotations 키.
- severity 가 warning|critical 중 하나.
- annotations.summary / description 존재.

GPT-5 §4 pre verdict: severity 값 유효성 + summary/description 검증 권고 반영.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ALERTS_YML = Path(__file__).resolve().parents[2] / "monitoring/prometheus/alerts.yml"

EXISTING_ALERTS = {
    "PipelineHighFailureRate",
    "KafkaConsumerLagHigh",
    "VllmHealthCheckFailed",
    "VllmKvCacheNearFull",
    "DlqBacklogHigh",
}

NEW_ALERTS = {
    "KmsPayloadSalvageRateHigh",
    "KmsRlsViolationDetected",
    "KmsEsIndexFailureRateHigh",
}

ALL_ALERTS = EXISTING_ALERTS | NEW_ALERTS


@pytest.fixture(scope="module")
def loaded() -> dict:
    """alerts.yml 을 yaml.safe_load 로 파싱."""
    text = ALERTS_YML.read_text(encoding="utf-8")
    return yaml.safe_load(text)


def test_alerts_yml_yaml_syntax(loaded: dict) -> None:
    """yaml syntax 무결."""
    assert isinstance(loaded, dict)
    assert "groups" in loaded
    assert isinstance(loaded["groups"], list)
    assert len(loaded["groups"]) >= 1


def test_alerts_yml_group_name(loaded: dict) -> None:
    """첫 group 이 aicm_pipeline_alerts."""
    assert loaded["groups"][0]["name"] == "aicm_pipeline_alerts"


def test_alerts_yml_total_count(loaded: dict) -> None:
    """8 alert (기존 5 + 신규 3)."""
    rules = loaded["groups"][0]["rules"]
    alert_names = {r["alert"] for r in rules if "alert" in r}
    assert alert_names == ALL_ALERTS, f"alerts mismatch: {alert_names}"


def test_alerts_yml_existing_alerts_preserved(loaded: dict) -> None:
    """기존 5 alert 보존."""
    rules = loaded["groups"][0]["rules"]
    alert_names = {r["alert"] for r in rules if "alert" in r}
    for name in EXISTING_ALERTS:
        assert name in alert_names, f"기존 alert {name} 누락"


def test_alerts_yml_new_alerts_added(loaded: dict) -> None:
    """신규 3 alert 추가."""
    rules = loaded["groups"][0]["rules"]
    alert_names = {r["alert"] for r in rules if "alert" in r}
    for name in NEW_ALERTS:
        assert name in alert_names, f"신규 alert {name} 누락"


@pytest.mark.parametrize("alert_name", sorted(NEW_ALERTS))
def test_new_alert_required_keys(loaded: dict, alert_name: str) -> None:
    """신규 alert 의 필수 키 존재."""
    rules = loaded["groups"][0]["rules"]
    rule = next((r for r in rules if r.get("alert") == alert_name), None)
    assert rule is not None, f"{alert_name} 정의 없음"
    for key in ("alert", "expr", "for", "labels", "annotations"):
        assert key in rule, f"{alert_name}: {key} 키 누락"


@pytest.mark.parametrize("alert_name", sorted(NEW_ALERTS))
def test_new_alert_severity_valid(loaded: dict, alert_name: str) -> None:
    """severity 가 warning|critical 중 하나."""
    rules = loaded["groups"][0]["rules"]
    rule = next((r for r in rules if r.get("alert") == alert_name), None)
    assert rule is not None
    severity = rule["labels"].get("severity")
    assert severity in ("warning", "critical"), (
        f"{alert_name}: severity={severity} (warning|critical 아님)"
    )


@pytest.mark.parametrize("alert_name", sorted(NEW_ALERTS))
def test_new_alert_annotations_complete(loaded: dict, alert_name: str) -> None:
    """annotations.summary 와 description 모두 존재 + 비어있지 않음."""
    rules = loaded["groups"][0]["rules"]
    rule = next((r for r in rules if r.get("alert") == alert_name), None)
    assert rule is not None
    annotations = rule["annotations"]
    assert "summary" in annotations and annotations["summary"].strip()
    assert "description" in annotations and annotations["description"].strip()


def test_rls_alert_label_preservation(loaded: dict) -> None:
    """KmsRlsViolationDetected 가 sum by (source, table, operation) 사용 — 라벨 보존."""
    rules = loaded["groups"][0]["rules"]
    rule = next(
        (r for r in rules if r.get("alert") == "KmsRlsViolationDetected"), None
    )
    assert rule is not None
    expr = rule["expr"]
    assert "sum by (source, table, operation)" in expr or "sum by(source, table, operation)" in expr, (
        f"RLS alert 의 sum by 라벨 보존 미반영: {expr}"
    )


def test_es_failure_alert_uses_success_denominator(loaded: dict) -> None:
    """KmsEsIndexFailureRateHigh 의 분모가 (failure + success) 합 — retry 포함 X."""
    rules = loaded["groups"][0]["rules"]
    rule = next(
        (r for r in rules if r.get("alert") == "KmsEsIndexFailureRateHigh"), None
    )
    assert rule is not None
    expr = rule["expr"]
    # success counter 가 분모에 포함되어 있어야 함.
    assert "kms_es_index_success_total" in expr, (
        f"ES failure alert 의 분모에 success counter 미포함 (GPT-5 §4 권고): {expr}"
    )
    # retry 는 분모에서 제외 (시도 횟수가 아님).
    failure_lines = [
        line for line in expr.split("\n") if "kms_es_index_failure_total" in line
    ]
    assert failure_lines, f"failure counter 미사용: {expr}"


def test_salvage_alert_idle_guard(loaded: dict) -> None:
    """KmsPayloadSalvageRateHigh 가 idle 가드 (분모>0) 포함 — false positive 방지."""
    rules = loaded["groups"][0]["rules"]
    rule = next(
        (r for r in rules if r.get("alert") == "KmsPayloadSalvageRateHigh"), None
    )
    assert rule is not None
    expr = rule["expr"]
    # AND clause 또는 unless 로 idle 가드 (newline 또는 space 둘 다).
    has_and = "\nand\n" in expr or " and " in expr
    has_unless = "\nunless\n" in expr or " unless " in expr
    assert has_and or has_unless, (
        f"salvage alert 의 idle 가드 미포함 (GPT-5 §4 권고): {expr}"
    )
