"""mail.compose — LLM-driven draft generation tests.

LLM 호출은 monkeypatch 로 fake response 주입. 실제 vLLM 미접속.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio


# Override autouse Redis fixture from conftest — 이 tool 은 Redis 없음.
@pytest_asyncio.fixture(autouse=True)
async def _no_redis(monkeypatch):  # noqa: PT004
    yield


@pytest.fixture
def fake_llm(monkeypatch):
    """VLLMAdapter.complete 를 AsyncMock 으로 교체."""
    from src.agent_framework.tools import mail_compose

    fake = AsyncMock()
    instance = mail_compose.VLLMAdapter.__new__(mail_compose.VLLMAdapter)
    instance.complete = fake  # type: ignore[method-assign]
    monkeypatch.setattr(mail_compose, "_LLM", instance)
    return fake


@pytest.mark.asyncio
async def test_compose_returns_draft_from_json(fake_llm):
    from src.agent_framework.tools import mail_compose

    fake_llm.return_value = (
        '{"subject": "수요일 미팅 가능 여부 확인", '
        '"body_text": "안녕하세요. 수요일 오후 미팅 가능하신지 여쭙고자 메일드립니다."}'
    )
    out = await mail_compose.compose(
        {
            "recipient": "cdma3988@naver.com",
            "body_hint": "수요일 오후 만남 가능 여부 확인",
        }
    )
    assert out["success"] is True
    draft = out["draft"]
    assert draft["to"] == "cdma3988@naver.com"
    assert "수요일" in draft["subject"]
    assert "미팅" in draft["body_text"] or "수요일" in draft["body_text"]
    assert "summary" in out and "수요일" in out["summary"]


@pytest.mark.asyncio
async def test_compose_strips_code_fence(fake_llm):
    from src.agent_framework.tools import mail_compose

    fake_llm.return_value = (
        "```json\n"
        '{"subject": "안내", "body_text": "본문입니다."}\n'
        "```"
    )
    out = await mail_compose.compose(
        {"recipient": ["a@b.com"], "body_hint": "테스트"}
    )
    assert out["success"] is True
    assert out["draft"]["subject"] == "안내"
    assert out["draft"]["body_text"] == "본문입니다."


@pytest.mark.asyncio
async def test_compose_empty_args_returns_error(fake_llm):
    from src.agent_framework.tools import mail_compose

    out = await mail_compose.compose({})
    assert out["success"] is False
    assert "error" in out
    # LLM 호출도 안 됨.
    fake_llm.assert_not_called()


@pytest.mark.asyncio
async def test_compose_falls_back_when_json_invalid(fake_llm):
    from src.agent_framework.tools import mail_compose

    # 비-JSON 응답 — body_text 에 raw 가 들어가야 함.
    fake_llm.return_value = "이것은 그냥 일반 문장 응답입니다 — 본문으로 활용."
    out = await mail_compose.compose(
        {
            "recipient": "x@y.com",
            "subject_hint": "회의 일정",
            "body_hint": "어쨌든",
        }
    )
    assert out["success"] is True
    # subject_hint 가 fallback 제목으로 사용.
    assert out["draft"]["subject"] == "회의 일정"
    assert "일반 문장" in out["draft"]["body_text"]


@pytest.mark.asyncio
async def test_compose_recipient_list_normalized(fake_llm):
    from src.agent_framework.tools import mail_compose

    fake_llm.return_value = '{"subject": "공유", "body_text": "내용"}'
    out = await mail_compose.compose(
        {
            "recipient": "a@b.com, c@d.com",
            "body_hint": "공지",
        }
    )
    assert out["success"] is True
    assert out["draft"]["to"] == ["a@b.com", "c@d.com"]


@pytest.mark.asyncio
async def test_compose_llm_failure_returns_error(monkeypatch):
    from src.agent_framework.tools import mail_compose

    async def _boom(*args, **kwargs):
        raise RuntimeError("vLLM down")

    instance = mail_compose.VLLMAdapter.__new__(mail_compose.VLLMAdapter)
    instance.complete = _boom  # type: ignore[method-assign]
    monkeypatch.setattr(mail_compose, "_LLM", instance)

    out = await mail_compose.compose(
        {"recipient": "a@b.com", "body_hint": "테스트"}
    )
    assert out["success"] is False
    assert "vLLM down" in out["error"]
