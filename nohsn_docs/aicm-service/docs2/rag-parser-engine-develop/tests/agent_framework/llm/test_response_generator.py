from unittest.mock import AsyncMock
import pytest

from src.agent_framework.llm.response_generator import ResponseGenerator


@pytest.mark.asyncio
async def test_renders_template_and_streams():
    llm = AsyncMock()

    async def stream_gen(system, user):
        for t in ["안", "녕", "하세요"]:
            yield t

    llm.stream = stream_gen

    gen = ResponseGenerator(llm_client=llm)
    chunks = []
    async for t in gen.stream(
        template_name="greet_derm.md",
        context={
            "tenant": {"name": "아름다운피부과"},
            "history": "",
            "user_message": "안녕",
        },
    ):
        chunks.append(t)
    assert "".join(chunks) == "안녕하세요"
