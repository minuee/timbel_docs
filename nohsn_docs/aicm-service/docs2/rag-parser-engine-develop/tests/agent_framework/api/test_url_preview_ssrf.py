"""SSRF guard tests for ``src.agent_framework.api.url_preview`` (PR P6).

- private IP / loopback / link-local / metadata service / raw IP literal /
  DNS-rebinding (hostname → private IP) 거부.
- public URL 은 mock httpx 로 200 + og 태그 → ``status="ok"``.
- oversized body / disallowed content-type / redirect-flood / timeout 거부.

httpx 호출은 ``MockTransport`` 로 가로채서 외부로 나가지 않도록 한다. DNS 해석은
``getaddrinfo`` 를 monkeypatch 해 반환 IP 를 통제한다.
"""
from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest

from src.agent_framework.api import url_preview as up


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _public_resolver(addr: str = "93.184.216.34"):
    """getaddrinfo 가 항상 공인 IP 를 반환하도록 patch (예: example.com)."""

    async def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (addr, 0))]

    return _fake_getaddrinfo


def _private_resolver(addr: str = "10.1.2.3"):
    """getaddrinfo 가 사설 IP 를 반환 — DNS rebinding 시뮬레이션."""

    async def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (addr, 0))]

    return _fake_getaddrinfo


def _patch_dns(monkeypatch, fake_getaddrinfo):
    class _Loop:
        def __init__(self, fn):
            self._fn = fn

        async def getaddrinfo(self, host, port, *args, **kwargs):
            return await self._fn(host, port, *args, **kwargs)

    def _get_event_loop():
        return _Loop(fake_getaddrinfo)

    monkeypatch.setattr(up.asyncio, "get_event_loop", _get_event_loop)


def _patch_http(monkeypatch, handler):
    """httpx.AsyncClient 가 MockTransport 로 응답하도록."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(up.httpx, "AsyncClient", _factory)


# ---------------------------------------------------------------------------
# 1. 사설 / loopback / link-local / metadata IP 차단
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/secret",
        "http://localhost/admin",  # localhost — DNS resolver 가 127.* 반환
    ],
)
@pytest.mark.asyncio
async def test_blocks_localhost(monkeypatch, url):
    _patch_dns(monkeypatch, _private_resolver("127.0.0.1"))
    out = await up.fetch_url_preview(url)
    assert out["status"] == "rejected"


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1/",
        "http://192.168.1.1/admin",
        "http://172.16.0.1/internal",
    ],
)
@pytest.mark.asyncio
async def test_blocks_private_ip(url):
    out = await up.fetch_url_preview(url)
    assert out["status"] == "rejected"


@pytest.mark.asyncio
async def test_blocks_link_local():
    out = await up.fetch_url_preview("http://169.254.1.1/")
    assert out["status"] == "rejected"


@pytest.mark.asyncio
async def test_blocks_metadata_aws():
    """AWS/GCP metadata service IP — link-local 이라 차단되어야 함."""
    out = await up.fetch_url_preview("http://169.254.169.254/latest/meta-data/")
    assert out["status"] == "rejected"


@pytest.mark.asyncio
async def test_blocks_raw_ip_in_url():
    out = await up.fetch_url_preview("http://1.2.3.4/")
    assert out["status"] == "rejected"
    assert "raw IP" in out["reason"]


@pytest.mark.asyncio
async def test_blocks_ipv6_loopback():
    out = await up.fetch_url_preview("http://[::1]/")
    assert out["status"] == "rejected"


# ---------------------------------------------------------------------------
# 2. scheme / hostname 검증
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "gopher://example.com/",
    ],
)
@pytest.mark.asyncio
async def test_blocks_disallowed_scheme(url):
    out = await up.fetch_url_preview(url)
    assert out["status"] == "rejected"


@pytest.mark.asyncio
async def test_blocks_empty_url():
    out = await up.fetch_url_preview("")
    assert out["status"] == "rejected"


# ---------------------------------------------------------------------------
# 3. DNS rebinding — hostname 은 정상이지만 사설 IP 로 해석
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocks_dns_rebinding(monkeypatch):
    """hostname 은 도메인 형태지만 DNS resolve 결과가 10.x → 차단."""
    _patch_dns(monkeypatch, _private_resolver("10.0.0.5"))
    out = await up.fetch_url_preview("http://evil-rebind.example.com/")
    assert out["status"] == "rejected"
    assert "private" in out["reason"].lower() or "unresolvable" in out["reason"].lower()


# ---------------------------------------------------------------------------
# 4. 정상 URL — mock httpx 로 og 태그 응답
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allows_public_url_with_og_tags(monkeypatch):
    _patch_dns(monkeypatch, _public_resolver())

    body_html = (
        b"<html><head>"
        b"<title>Example Domain</title>"
        b'<meta property="og:title" content="OG Example Title" />'
        b'<meta property="og:description" content="A short description" />'
        b'<meta property="og:image" content="https://example.com/image.png" />'
        b"</head><body></body></html>"
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body_html,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    _patch_http(monkeypatch, _handler)
    out = await up.fetch_url_preview("https://example.com/")
    assert out["status"] == "ok"
    assert out["title"] == "OG Example Title"
    assert out["description"] == "A short description"
    assert out["image"] == "https://example.com/image.png"


@pytest.mark.asyncio
async def test_allows_public_url_title_only(monkeypatch):
    _patch_dns(monkeypatch, _public_resolver())
    body_html = b"<html><head><title>Just A Title</title></head></html>"

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body_html, headers={"content-type": "text/html"})

    _patch_http(monkeypatch, _handler)
    out = await up.fetch_url_preview("https://example.com/")
    assert out["status"] == "ok"
    assert out["title"] == "Just A Title"


# ---------------------------------------------------------------------------
# 5. Oversized body 차단
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocks_oversized_content_length(monkeypatch):
    _patch_dns(monkeypatch, _public_resolver())

    def _handler(request: httpx.Request) -> httpx.Response:
        # content-length 헤더만으로 차단되도록 설정 — 실제 본문은 짧게.
        return httpx.Response(
            200,
            content=b"<html></html>",
            headers={
                "content-type": "text/html",
                "content-length": str(up.MAX_BYTES + 1),
            },
        )

    _patch_http(monkeypatch, _handler)
    out = await up.fetch_url_preview("https://example.com/")
    assert out["status"] == "rejected"
    assert "size" in out["reason"]


@pytest.mark.asyncio
async def test_blocks_oversized_actual_body(monkeypatch):
    _patch_dns(monkeypatch, _public_resolver())
    big = b"x" * (up.MAX_BYTES + 100)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big, headers={"content-type": "text/html"})

    _patch_http(monkeypatch, _handler)
    out = await up.fetch_url_preview("https://example.com/")
    assert out["status"] == "rejected"
    assert "size" in out["reason"]


# ---------------------------------------------------------------------------
# 6. content-type whitelist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ctype",
    [
        "application/octet-stream",
        "image/png",
        "application/zip",
        "application/pdf",
    ],
)
@pytest.mark.asyncio
async def test_blocks_disallowed_content_type(monkeypatch, ctype):
    _patch_dns(monkeypatch, _public_resolver())

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data", headers={"content-type": ctype})

    _patch_http(monkeypatch, _handler)
    out = await up.fetch_url_preview("https://example.com/")
    assert out["status"] == "rejected"
    assert "content-type" in out["reason"]


# ---------------------------------------------------------------------------
# 7. timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handles_timeout(monkeypatch):
    _patch_dns(monkeypatch, _public_resolver())

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated")

    _patch_http(monkeypatch, _handler)
    out = await up.fetch_url_preview("https://example.com/")
    assert out["status"] == "rejected"
    assert "timeout" in out["reason"].lower()
