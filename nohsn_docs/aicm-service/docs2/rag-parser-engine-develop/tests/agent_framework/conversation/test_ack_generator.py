"""ack_generator — E2B 7020 wrapper + static fallback (httpx mock)."""

from __future__ import annotations

import pytest
import httpx

from src.agent_framework.conversation.ack_generator import (
    DEFAULT_STATIC_ACKS,
    AckGenerator,
)


class TestAckGeneratorStaticOnly:
    @pytest.mark.asyncio
    async def test_no_base_url_returns_static(self, monkeypatch):
        monkeypatch.delenv("KMS_ACK_MODEL_URL", raising=False)
        gen = AckGenerator(base_url=None)
        out = await gen.generate("주식 결제일 알려 줘")
        assert out.source == "static"
        assert out.text in DEFAULT_STATIC_ACKS

    @pytest.mark.asyncio
    async def test_empty_message_skipped(self):
        gen = AckGenerator(base_url=None)
        out = await gen.generate("")
        assert out.source == "skipped"
        assert out.text == ""

    @pytest.mark.asyncio
    async def test_round_robin_static(self):
        gen = AckGenerator(
            base_url=None, static_acks=("a", "b", "c")
        )
        a = (await gen.generate("hi")).text
        b = (await gen.generate("hi")).text
        c = (await gen.generate("hi")).text
        d = (await gen.generate("hi")).text
        assert (a, b, c) == ("a", "b", "c")
        assert d == "a"  # wrap


class TestAckGeneratorModelPath:
    @pytest.mark.asyncio
    async def test_model_returns_text(self, monkeypatch):
        # mock httpx.AsyncClient.post → 200 with content
        async def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "네, 잠시만요!"}}
                    ]
                },
                request=request,
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        gen = AckGenerator(base_url="http://localhost:7020/v1", timeout_ms=500)
        out = await gen.generate("주식 결제일?")
        assert out.source == "model"
        assert "잠시만요" in out.text

    @pytest.mark.asyncio
    async def test_model_truncates_long_text(self, monkeypatch):
        long_resp = "한국어로 매우 매우 매우 매우 매우 매우 매우 긴 응답입니다 " * 5

        async def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": long_resp}}]},
                request=request,
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        gen = AckGenerator(base_url="http://x/v1")
        out = await gen.generate("hi")
        assert out.source == "model"
        assert len(out.text) <= 30

    @pytest.mark.asyncio
    async def test_model_500_falls_back(self, monkeypatch):
        async def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
            request = httpx.Request("POST", url)
            return httpx.Response(500, json={"error": "x"}, request=request)

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        gen = AckGenerator(base_url="http://x/v1")
        out = await gen.generate("hi")
        assert out.source == "static"

    @pytest.mark.asyncio
    async def test_model_timeout_falls_back(self, monkeypatch):
        async def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
            raise httpx.TimeoutException("timed out")

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        gen = AckGenerator(base_url="http://x/v1", timeout_ms=100)
        out = await gen.generate("hi")
        assert out.source == "static"

    @pytest.mark.asyncio
    async def test_model_network_error_falls_back(self, monkeypatch):
        async def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
            raise httpx.ConnectError("dns fail")

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        gen = AckGenerator(base_url="http://x/v1")
        out = await gen.generate("hi")
        assert out.source == "static"
