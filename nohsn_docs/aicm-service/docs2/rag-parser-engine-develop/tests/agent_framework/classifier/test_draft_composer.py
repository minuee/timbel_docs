"""DraftComposer — Task 34 Phase A unit tests.

LLM 을 AsyncMock 으로 stub 해 JSON 유효/무효, retry 동작, 최종 실패 경로를 검증.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from src.agent_framework.classifier.draft_composer import (
    DraftComposer,
    DraftError,
)


def _valid_yaml(id_: str = "user_defined_portfolio_check") -> str:
    return (
        "skill:\n"
        f"  id: {id_}\n"
        '  version: "1.1"\n'
        "  domain: finance\n"
        '  description: "포트폴리오 점검 기능"\n'
        "triggers:\n"
        "  - intent: check_portfolio\n"
        "slots: []\n"
        "initial_state: greet\n"
        "states:\n"
        "  - id: greet\n"
        "    transitions:\n"
        "      - to: done\n"
        "  - id: done\n"
    )


def _valid_response(id_: str = "user_defined_portfolio_check") -> str:
    return json.dumps(
        {
            "title": "포트폴리오 점검",
            "yaml": _valid_yaml(id_),
            "rationale": "사용자가 주식 포트폴리오를 주기적으로 확인하고 싶다고 하여 정의했습니다.",
        }
    )


FIXED_ACCOUNT_ID = UUID("11111111-1111-1111-1111-111111111111")
FIXED_TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")


@pytest.mark.asyncio
async def test_compose_returns_skill_draft_on_valid_llm_output():
    """LLM 이 유효 YAML 을 바로 주면 한 번의 호출로 SkillDraft 반환."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value=_valid_response())
    comp = DraftComposer(llm_client=llm)

    draft = await comp.compose(
        history=[{"role": "user", "content": "어제 주식 얼마나 올랐지?"}],
        user_message="포트폴리오 자동으로 점검해 주는 기능 만들어 줘",
        account_id=FIXED_ACCOUNT_ID,
        tenant_id=FIXED_TENANT_ID,
    )
    assert draft.title == "포트폴리오 점검"
    assert "user_defined_portfolio_check" in draft.yaml_text
    assert "포트폴리오" in (draft.rationale or "")
    # 단일 호출 (retry 없음)
    assert llm.chat_completion_json.await_count == 1


@pytest.mark.asyncio
async def test_compose_retries_once_when_yaml_invalid_then_succeeds():
    """첫 응답 YAML 무효 → 두 번째 시도 성공."""
    llm = AsyncMock()
    invalid = json.dumps(
        {
            "title": "x",
            "yaml": "not: a: valid: yaml: because: too: many: colons:\n",
            "rationale": "r",
        }
    )
    llm.chat_completion_json = AsyncMock(
        side_effect=[invalid, _valid_response()]
    )
    comp = DraftComposer(llm_client=llm)

    draft = await comp.compose(
        history=[],
        user_message="어떤 기능",
        account_id=FIXED_ACCOUNT_ID,
        tenant_id=FIXED_TENANT_ID,
    )
    assert draft.title == "포트폴리오 점검"
    assert llm.chat_completion_json.await_count == 2


@pytest.mark.asyncio
async def test_compose_raises_draft_error_after_two_failures():
    """연속 두 번 실패 → DraftError."""
    llm = AsyncMock()
    bad = json.dumps({"title": "", "yaml": "", "rationale": ""})
    llm.chat_completion_json = AsyncMock(return_value=bad)
    comp = DraftComposer(llm_client=llm)

    with pytest.raises(DraftError):
        await comp.compose(
            history=[],
            user_message="...",
            account_id=FIXED_ACCOUNT_ID,
            tenant_id=FIXED_TENANT_ID,
        )
    assert llm.chat_completion_json.await_count == 2


@pytest.mark.asyncio
async def test_compose_slugifies_bad_id_before_validation():
    """LLM 이 대문자/공백 섞인 id 를 줘도 slugify 로 정상화."""
    llm = AsyncMock()
    bad_id_yaml = (
        "skill:\n"
        '  id: "User Defined FOO"\n'  # 대문자/공백 — 원본은 pydantic 에서 거절됨
        '  version: "1.1"\n'
        "  domain: personal\n"
        '  description: "테스트"\n'
        "triggers:\n"
        "  - intent: do_foo\n"
        "slots: []\n"
        "initial_state: s0\n"
        "states:\n"
        "  - id: s0\n"
    )
    llm.chat_completion_json = AsyncMock(
        return_value=json.dumps(
            {"title": "FOO", "yaml": bad_id_yaml, "rationale": "r"}
        )
    )
    comp = DraftComposer(llm_client=llm)
    draft = await comp.compose(
        history=[],
        user_message="foo 만들어",
        account_id=FIXED_ACCOUNT_ID,
        tenant_id=FIXED_TENANT_ID,
    )
    # slugify 결과가 yaml 에 다시 덤프돼야 함
    assert "user_defined_foo" in draft.yaml_text.lower()
    assert llm.chat_completion_json.await_count == 1
