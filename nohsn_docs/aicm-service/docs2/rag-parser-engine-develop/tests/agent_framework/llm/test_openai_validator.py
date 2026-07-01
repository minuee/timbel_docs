"""OpenAI cross-validator 단위 테스트.

실 OpenAI 호출은 하지 않는다 (비용 0). MagicMock 으로 chat.completions.create
응답을 주입해 JSON 파싱 / 반환 구조만 검증한다.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.agent_framework.llm import openai_validator as ov


def _mock_client_with_response(payload: dict) -> MagicMock:
    text = json.dumps(payload, ensure_ascii=False)
    msg = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=msg)
    response = SimpleNamespace(choices=[choice])

    client = MagicMock()
    client.chat.completions.create = MagicMock(return_value=response)
    return client


@pytest.fixture(autouse=True)
def _reset_client_and_env(monkeypatch):
    """각 테스트마다 client 와 env 초기화."""
    monkeypatch.delenv("KMS_OPENAI_VALIDATOR", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ov.reset_client_for_tests()
    yield
    ov.reset_client_for_tests()


# ---------- is_enabled ----------

def test_is_enabled_default_false():
    assert ov.is_enabled() is False


def test_is_enabled_only_env_flag_no_key(monkeypatch):
    monkeypatch.setenv("KMS_OPENAI_VALIDATOR", "true")
    assert ov.is_enabled() is False  # key 없음


def test_is_enabled_both_set(monkeypatch):
    monkeypatch.setenv("KMS_OPENAI_VALIDATOR", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-xxxx")
    assert ov.is_enabled() is True


# ---------- validate_intent ----------

def test_validate_intent_returns_parsed_json(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = _mock_client_with_response(
        {"agree": True, "openai_label": "book", "confidence": 0.95, "reason": "예약 요청 명확"}
    )
    ov.set_client_for_tests(client)

    out = ov.validate_intent(user_text="내일 3시 예약해줘", our_label="book", our_confidence=0.9)

    assert out["agree"] is True
    assert out["openai_label"] == "book"
    assert out["confidence"] == 0.95
    # 호출 인자 확인 — response_format json_object 는 항상.
    # 2026-04-25: gpt-5.x 계열은 ``temperature`` 미지원 (default=1) +
    # ``max_completion_tokens`` 사용. gpt-4o-mini 계열은 ``temperature=0`` + ``max_tokens``.
    args = client.chat.completions.create.call_args
    assert args.kwargs["response_format"] == {"type": "json_object"}
    if ov._DEFAULT_MODEL.startswith(("gpt-5", "o1", "o3")):
        assert "temperature" not in args.kwargs
        assert "max_completion_tokens" in args.kwargs
    else:
        assert args.kwargs["temperature"] == 0
        assert "max_tokens" in args.kwargs


# ---------- validate_overlap_relation ----------

def test_validate_overlap_relation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = _mock_client_with_response(
        {"agree": False, "openai_relation": "supersedes_existing", "confidence": 0.8, "reason": "신규가 최신"}
    )
    ov.set_client_for_tests(client)

    out = ov.validate_overlap_relation(
        new_summary="2026-04-25 신규 약관",
        peer_title="2025-12 약관",
        peer_snippet="…",
        our_relation="duplicate",
        our_confidence=0.6,
    )
    assert out["agree"] is False
    assert out["openai_relation"] == "supersedes_existing"


# ---------- validate_synonym ----------

def test_validate_synonym(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = _mock_client_with_response(
        {"agree": True, "openai_decision": True, "confidence": 0.97, "reason": "동의어"}
    )
    ov.set_client_for_tests(client)

    out = ov.validate_synonym(term_a="장병내일준비적금", term_b="장병적금", our_decision=True)
    assert out["agree"] is True
    assert out["openai_decision"] is True


# ---------- validate_qa_pair ----------

def test_validate_qa_pair(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = _mock_client_with_response(
        {
            "semantic_score": 0.85,
            "agree_facts": ["월 40만원 상한"],
            "missing_facts": [],
            "extra_facts": [],
            "reason": "핵심 사실 일치",
        }
    )
    ov.set_client_for_tests(client)

    out = ov.validate_qa_pair(
        question="월 최대 얼마까지?",
        our_answer="월 40만원까지 가입 가능합니다.",
        reference_answer="월 40만원 한도.",
    )
    assert out["semantic_score"] == 0.85
    assert "월 40만원 상한" in out["agree_facts"]


# ---------- 키 없을 때 _make_client 가 raise ----------

def test_make_client_raises_without_key(monkeypatch):
    """키 없이 _call_json 호출 시 RuntimeError."""
    ov.reset_client_for_tests()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        ov._make_client()


# ---------- json 파싱 실패 graceful ----------

def test_json_parse_failure_graceful(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    bad_msg = SimpleNamespace(content="not json at all")
    bad_choice = SimpleNamespace(message=bad_msg)
    bad_resp = SimpleNamespace(choices=[bad_choice])
    client = MagicMock()
    client.chat.completions.create = MagicMock(return_value=bad_resp)
    ov.set_client_for_tests(client)

    out = ov.validate_intent(user_text="hi", our_label="chat", our_confidence=0.5)
    assert out.get("error") == "json_parse_failed"
    assert out["agree"] is False
