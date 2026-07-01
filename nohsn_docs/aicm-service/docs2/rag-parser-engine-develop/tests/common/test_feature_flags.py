import os
import pytest
from src.common.feature_flags import FeatureFlag, is_enabled


def test_all_flags_default_false(monkeypatch):
    """새 flag 추가 시 자동으로 검증됨 — 하드코딩된 env 리스트 X."""
    for f in FeatureFlag:
        monkeypatch.delenv(f"FEATURE_{f.value.upper()}", raising=False)
    for f in FeatureFlag:
        assert is_enabled(f) is False, f"{f.value} 가 기본 false 아님"


def test_env_activation(monkeypatch):
    monkeypatch.setenv("FEATURE_LATENCY_PROBE_SSE", "true")
    assert is_enabled(FeatureFlag.LATENCY_PROBE_SSE) is True


def test_env_false_values(monkeypatch):
    for v in ["", "0", "false", "False", "no", "NO"]:
        monkeypatch.setenv("FEATURE_LATENCY_PROBE_SSE", v)
        assert is_enabled(FeatureFlag.LATENCY_PROBE_SSE) is False, f"{v!r} 이 false 로 안 읽힘"


def test_tenant_override(monkeypatch):
    """tenant 단위 활성 — Redis key 가 우선 (post-demo A/B)."""
    monkeypatch.delenv("FEATURE_LATENCY_PROBE_SSE", raising=False)
    # tenant 가 None 이거나 redis 없으면 env 폴백 → false
    assert is_enabled(FeatureFlag.LATENCY_PROBE_SSE, tenant_id=None) is False


def test_enum_values_are_lowercase_snake():
    """enum value 는 lowercase snake_case (env var 변환 시 대소문자 일관성)."""
    for f in FeatureFlag:
        assert f.value == f.value.lower(), f"{f.name} value '{f.value}' 가 lowercase 아님"
        assert " " not in f.value, f"{f.name} value 에 공백 포함"
