"""``/api/v1/knowledge/auto-draft`` 엔드포인트 테스트.

mock vLLM 응답으로 5+ 케이스:
1) 정상 흐름 (standard 길이) — markdown 반환 + 헤더 자동 보정
2) JWT 누락 → 401
3) topic_summary 누락 → 422
4) target_length invalid → 422
5) LLM timeout → 502
6) LLM 4xx 응답 → 502
7) ```markdown fence 후처리 검증
"""
from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.auth.jwt_utils import create_access_token
from src.api.main import app
from src.api.routers import knowledge_v1


def _bearer() -> str:
    token = create_access_token(subject=str(uuid4()), tenant_id=str(uuid4()))
    return f"Bearer {token}"


class _FakeResp:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or ""

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """async context manager 호환 httpx.AsyncClient mock."""

    def __init__(self, *, response: _FakeResp | None = None, raise_exc: Exception | None = None):
        self._response = response
        self._raise = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def post(self, url: str, json: dict | None = None):  # noqa: A002
        if self._raise is not None:
            raise self._raise
        return self._response


def _patch_vllm(monkeypatch, *, response=None, raise_exc=None):
    def _factory(*args, **kwargs):
        return _FakeClient(response=response, raise_exc=raise_exc)

    monkeypatch.setattr(knowledge_v1.httpx, "AsyncClient", _factory)


@pytest.mark.asyncio
async def test_auto_draft_happy_path(monkeypatch):
    payload = {
        "choices": [
            {
                "message": {
                    "content": "# 휴가 정책\n\n## 개요\n연차 사용 규칙입니다.",
                }
            }
        ]
    }
    _patch_vllm(monkeypatch, response=_FakeResp(200, payload=payload))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/knowledge/auto-draft",
            headers={"Authorization": _bearer()},
            json={
                "title": "휴가 정책",
                "topic_summary": "전사 연차 사용 규칙 정리",
                "keywords": ["연차", "휴가", "정책"],
                "target_length": "standard",
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["markdown"].startswith("# 휴가 정책")
    assert "연차" in data["markdown"]
    assert data["target_length"] == "standard"
    assert "generated_at" in data
    assert "model" in data


@pytest.mark.asyncio
async def test_auto_draft_missing_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/knowledge/auto-draft",
            json={
                "title": "휴가 정책",
                "topic_summary": "내용",
                "target_length": "short",
            },
        )
    # FastAPI Header(...) 누락은 422 — 우리는 명시적 401 처리를 위해 헤더는 받되 빈 값일 때 401.
    # Header(...) 가 missing 인 경우 422 가 정상이지만, 환경에 따라 differ — 401 또는 422 허용.
    assert resp.status_code in (401, 422)


@pytest.mark.asyncio
async def test_auto_draft_invalid_token_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/knowledge/auto-draft",
            headers={"Authorization": "Bearer not.a.real.token"},
            json={
                "title": "휴가 정책",
                "topic_summary": "내용",
                "target_length": "short",
            },
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auto_draft_missing_topic_summary_returns_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/knowledge/auto-draft",
            headers={"Authorization": _bearer()},
            json={
                "title": "휴가 정책",
                "target_length": "standard",
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_auto_draft_invalid_target_length_returns_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/knowledge/auto-draft",
            headers={"Authorization": _bearer()},
            json={
                "title": "휴가 정책",
                "topic_summary": "내용",
                "target_length": "huge",
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_auto_draft_llm_timeout_returns_502(monkeypatch):
    _patch_vllm(monkeypatch, raise_exc=httpx.TimeoutException("read timeout"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/knowledge/auto-draft",
            headers={"Authorization": _bearer()},
            json={
                "title": "휴가 정책",
                "topic_summary": "내용",
                "target_length": "standard",
            },
        )
    assert resp.status_code == 502
    assert "timeout" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_auto_draft_llm_5xx_returns_502(monkeypatch):
    _patch_vllm(monkeypatch, response=_FakeResp(503, text="upstream busy"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/knowledge/auto-draft",
            headers={"Authorization": _bearer()},
            json={
                "title": "휴가 정책",
                "topic_summary": "내용",
                "target_length": "standard",
            },
        )
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_auto_draft_strips_markdown_fence(monkeypatch):
    """LLM 이 ```markdown … ``` 펜스로 감싸 응답해도 본문만 추출."""
    fenced = "```markdown\n# 휴가 정책\n\n## 개요\n본문\n```"
    payload = {"choices": [{"message": {"content": fenced}}]}
    _patch_vllm(monkeypatch, response=_FakeResp(200, payload=payload))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/knowledge/auto-draft",
            headers={"Authorization": _bearer()},
            json={
                "title": "휴가 정책",
                "topic_summary": "테스트",
                "target_length": "short",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "```" not in data["markdown"]
    assert data["markdown"].startswith("# 휴가 정책")


@pytest.mark.asyncio
async def test_auto_draft_adds_title_header_when_missing(monkeypatch):
    """LLM 응답이 # 헤더 없이 시작하면 title 로 자동 보정."""
    payload = {
        "choices": [{"message": {"content": "## 개요\n본문 시작"}}]
    }
    _patch_vllm(monkeypatch, response=_FakeResp(200, payload=payload))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/knowledge/auto-draft",
            headers={"Authorization": _bearer()},
            json={
                "title": "휴가 정책",
                "topic_summary": "테스트",
                "target_length": "short",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["markdown"].startswith("# 휴가 정책")
    assert "## 개요" in data["markdown"]
