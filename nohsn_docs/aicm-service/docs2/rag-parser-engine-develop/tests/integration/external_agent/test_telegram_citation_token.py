"""D41 Phase 4 — Telegram adapter HMAC token 첨부 integration test.

검증:
- citation_url_map 가 `?t=<token>&exp=<ts>` 첨부.
- URL 화이트리스트 (외부 URL / 임의 path 는 token 미첨부).
- tenant_id 없으면 link 생성 X (fail-safe, plain [N]).
- synthetic ID (doc_id#idx) → block_id UUID invalid → skip.
- URL whitelist on inline keyboard (javascript:/data: 차단).
"""
from __future__ import annotations

import importlib
import uuid

import pytest


_DEV_SECRET = "MIPKScw-vYjiSqtHLJubX7x-RBvGJZTaK3vGd3UzYU4N-wzFEgwDuIXazUd4A1Ap"


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    from src.common import config as _cfg
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_SECRET", _DEV_SECRET, raising=False)
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_TTL_SECS", 43200, raising=False)
    yield


def _fresh_adapter_module():
    import src.common.security.citation_token as ct
    importlib.reload(ct)
    import src.integration.external_agent.telegram_adapter as ta
    importlib.reload(ta)
    return ta


def test_build_citation_url_map_attaches_token():
    ta = _fresh_adapter_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    citations = [
        {"number": 1, "id": block_id, "url": f"/api/v1/citations/{block_id}"},
    ]
    result = ta._build_citation_url_map(
        citations, "https://example.com", tenant_id=tenant_id
    )
    assert 1 in result
    url = result[1]
    assert url.startswith(f"https://example.com/api/v1/citations/{block_id}")
    assert "?t=v1." in url
    assert "&exp=" in url


def test_build_citation_url_map_no_tenant_returns_empty():
    """tenant_id 미주입 → link 생성 X (fail-safe)."""
    ta = _fresh_adapter_module()
    block_id = str(uuid.uuid4())
    citations = [
        {"number": 1, "id": block_id, "url": f"/api/v1/citations/{block_id}"},
    ]
    result = ta._build_citation_url_map(citations, "https://example.com")
    assert result == {}
    # 명시적 None 도 동일.
    result2 = ta._build_citation_url_map(
        citations, "https://example.com", tenant_id=None
    )
    assert result2 == {}


def test_build_citation_url_map_external_url_skipped():
    """`/api/v1/citations/` 시작 안 하는 URL → token 첨부 X (whitelist)."""
    ta = _fresh_adapter_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    citations = [
        # 외부 도메인
        {"number": 1, "id": block_id, "url": "https://evil.com/leak"},
        # 내부 다른 path
        {"number": 2, "id": block_id, "url": "/repos/some/docs/abc"},
        # 화이트리스트 통과
        {"number": 3, "id": block_id, "url": f"/api/v1/citations/{block_id}"},
    ]
    result = ta._build_citation_url_map(
        citations, "https://example.com", tenant_id=tenant_id
    )
    assert 1 not in result
    assert 2 not in result
    assert 3 in result


def test_build_citation_url_map_synthetic_id_skipped():
    """block_id 가 UUID 아니면 (synthetic doc#idx) sign 시점 raise → skip."""
    ta = _fresh_adapter_module()
    tenant_id = str(uuid.uuid4())
    # synthetic id — `/api/v1/citations/` 시작도 안 하므로 어쨌든 skip.
    citations = [
        {"number": 1, "id": "doc-abc#0", "url": "/api/v1/citations/doc-abc#0"},
    ]
    result = ta._build_citation_url_map(
        citations, "https://example.com", tenant_id=tenant_id
    )
    # synthetic UUID 이라 sign 시점 ValueError → skip.
    assert result == {}


def test_build_citation_url_map_no_base_returns_empty():
    """public_base 없으면 절대 URL 못 만들어 skip."""
    ta = _fresh_adapter_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    citations = [
        {"number": 1, "id": block_id, "url": f"/api/v1/citations/{block_id}"},
    ]
    result = ta._build_citation_url_map(citations, None, tenant_id=tenant_id)
    assert result == {}


def test_build_citation_url_map_empty_input():
    ta = _fresh_adapter_module()
    assert ta._build_citation_url_map(None, "https://x", tenant_id=str(uuid.uuid4())) == {}
    assert ta._build_citation_url_map([], "https://x", tenant_id=str(uuid.uuid4())) == {}


def test_build_inline_keyboard_blocks_javascript_url():
    """defense-in-depth — javascript:/data: URL 버튼 차단."""
    ta = _fresh_adapter_module()
    from src.integration.external_agent.response_blocks import ButtonBlock
    btns = [
        ButtonBlock(label="Safe", action="url", payload="https://example.com"),
        ButtonBlock(label="XSS", action="url", payload="javascript:alert(1)"),
        ButtonBlock(label="Data", action="url", payload="data:text/html,<script>"),
        ButtonBlock(label="Cb", action="postback", payload="cb-data"),
    ]
    kb = ta.TelegramAdapter._build_inline_keyboard(btns)
    assert kb is not None
    rows = kb["inline_keyboard"]
    # safe + postback 2개만 살아남음.
    assert len(rows) == 2
    urls = [r[0].get("url") for r in rows if "url" in r[0]]
    assert urls == ["https://example.com"]


def test_token_contains_block_id_binding():
    """sign 한 token 이 block_id 변경 시 verify mismatch — payload binding 검증."""
    ta = _fresh_adapter_module()
    block_a = str(uuid.uuid4())
    block_b = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    citations_a = [
        {"number": 1, "id": block_a, "url": f"/api/v1/citations/{block_a}"},
    ]
    result = ta._build_citation_url_map(
        citations_a, "https://example.com", tenant_id=tenant_id
    )
    # 생성된 token 을 block_b path 로 verify 하면 invalid 여야 함.
    url = result[1]
    # parse token from URL
    token_part = url.split("?t=", 1)[1].split("&", 1)[0]
    exp_part = int(url.split("&exp=", 1)[1])

    from src.common.security.citation_token import verify_citation_token
    # block_a 로 verify → OK
    r_a = verify_citation_token(block_id=block_a, token=token_part, exp=exp_part)
    assert r_a.tenant_id == uuid.UUID(tenant_id)
    # block_b 로 verify → invalid (path tampering 차단)
    r_b = verify_citation_token(block_id=block_b, token=token_part, exp=exp_part)
    assert r_b.signature_invalid
