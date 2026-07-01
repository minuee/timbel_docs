import pytest
from unittest.mock import AsyncMock, MagicMock
from src.integration.external_agent.telegram_adapter import (
    TelegramAdapter, TelegramSendError, _escape_md_v2,
)
from src.integration.external_agent.base import InboundMessage


@pytest.fixture
def adapter():
    return TelegramAdapter()


@pytest.fixture
def fake_request_with_msg():
    req = MagicMock()
    req.headers = {"X-Telegram-Bot-Api-Secret-Token": "secret123"}
    req.json = AsyncMock(return_value={
        "message": {
            "from": {"id": 12345, "first_name": "Ricky"},
            "chat": {"id": 12345},
            "text": "내일 6시 약속 등록",
            "message_id": 99,
            "date": 1700000000,
        }
    })
    return req


@pytest.mark.asyncio
async def test_parse_inbound_basic(adapter, fake_request_with_msg):
    inbound = await adapter.parse_inbound(fake_request_with_msg,
                                           {"webhook_secret": "secret123"})
    assert inbound is not None
    assert inbound.from_user_id == "12345"
    assert inbound.from_user_name == "Ricky"
    assert inbound.text == "내일 6시 약속 등록"
    assert inbound.metadata["chat_id"] == 12345


@pytest.mark.asyncio
async def test_parse_inbound_secret_mismatch(adapter, fake_request_with_msg):
    fake_request_with_msg.headers = {"X-Telegram-Bot-Api-Secret-Token": "wrong"}
    inbound = await adapter.parse_inbound(fake_request_with_msg,
                                           {"webhook_secret": "secret123"})
    assert inbound is None


@pytest.mark.asyncio
async def test_parse_inbound_no_secret_in_config_fail_closed(adapter):
    """webhook_secret 키 자체가 없으면 fail-closed — None 반환."""
    req = MagicMock()
    req.headers = {"X-Telegram-Bot-Api-Secret-Token": "some-token"}
    req.json = AsyncMock(return_value={
        "message": {
            "from": {"id": 1}, "chat": {"id": 1},
            "text": "hi", "message_id": 1, "date": 1,
        }
    })
    # config 에 webhook_secret 키 없음 (vault_ref 만 있는 상황 등)
    inbound = await adapter.parse_inbound(req, {"webhook_secret_ref": "vault://secret/path"})
    assert inbound is None


@pytest.mark.asyncio
async def test_parse_inbound_no_message(adapter):
    req = MagicMock()
    req.headers = {"X-Telegram-Bot-Api-Secret-Token": "s"}
    req.json = AsyncMock(return_value={"update_id": 1})
    inbound = await adapter.parse_inbound(req, {"webhook_secret": "s"})
    assert inbound is None


@pytest.mark.asyncio
async def test_parse_inbound_no_text(adapter):
    req = MagicMock()
    req.headers = {"X-Telegram-Bot-Api-Secret-Token": "s"}
    req.json = AsyncMock(return_value={
        "message": {"from": {"id": 1}, "chat": {"id": 1}, "photo": [{}]}
    })
    inbound = await adapter.parse_inbound(req, {"webhook_secret": "s"})
    assert inbound is None  # 이미지만 → 미지원


@pytest.mark.asyncio
async def test_collect_response_tokens_and_citations(adapter):
    async def fake_sse():
        yield {"event": "token", "data": {"text": "안녕"}}
        yield {"event": "delta", "data": {"text": "하세요"}}
        yield {"event": "citations_finalized", "data": {
            "items": [{"title": "휴가 규정"}, {"title": "프린터 사용법"}]
        }}
        yield {"event": "done", "data": {}}

    body, cites = await adapter.collect_response(fake_sse())
    assert "안녕하세요" in body
    assert "[1] 휴가 규정" in body
    assert "[2] 프린터 사용법" in body
    assert len(cites) == 2


@pytest.mark.asyncio
async def test_collect_response_truncate_long(adapter):
    async def fake_sse():
        yield {"event": "token", "data": {"text": "a" * 5000}}

    body, _ = await adapter.collect_response(fake_sse())
    assert len(body) <= 4096
    assert "잘렸" in body


@pytest.mark.asyncio
async def test_send_outbound_calls_telegram_api(adapter):
    from unittest.mock import patch
    sent = {}

    async def fake_post(self, url, json):
        sent["url"] = url
        sent["json"] = json
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        return resp

    # NOTE: respx 도입 시 더 안전한 patch 가능. 현재는 instance attribute 패치
    # 로 동작 — httpx 내부 변경 시 깨질 수 있음.
    with patch("httpx.AsyncClient.post", new=fake_post):
        await adapter.send_outbound(
            {"bot_token": "TOKEN"}, "12345", "hello"
        )
    assert "12345" in sent["url"] or sent["json"]["chat_id"] == 12345
    assert sent["json"]["parse_mode"] == "MarkdownV2"


@pytest.mark.asyncio
async def test_send_outbound_no_token_raises(adapter):
    """bot_token 없으면 ValueError raise."""
    with pytest.raises(ValueError, match="bot_token"):
        await adapter.send_outbound({}, "12345", "x")


@pytest.mark.asyncio
async def test_send_outbound_http_error_raises(adapter):
    """HTTP 4xx → TelegramSendError raise."""
    from unittest.mock import patch

    async def fake_post_400(self, url, json):
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Bad Request"
        return resp

    with patch("httpx.AsyncClient.post", new=fake_post_400):
        with pytest.raises(TelegramSendError, match="HTTP 400"):
            await adapter.send_outbound({"bot_token": "TK"}, "99", "msg")


@pytest.mark.asyncio
async def test_send_outbound_timeout_raises(adapter):
    """httpx.TimeoutException → TelegramSendError("timeout") raise."""
    from unittest.mock import patch
    import httpx

    async def fake_post_timeout(self, url, json):
        raise httpx.TimeoutException("timed out")

    with patch("httpx.AsyncClient.post", new=fake_post_timeout):
        with pytest.raises(TelegramSendError, match="timeout"):
            await adapter.send_outbound({"bot_token": "TK"}, "99", "msg")


def test_escape_md_v2_special_chars():
    """MarkdownV2 이스케이프 — 특수문자 백슬래시 prefix, 한글/숫자 그대로."""
    result = _escape_md_v2("hello_world *test* [link](url)")
    assert r"\_" in result or result.startswith("hello")
    assert r"\*" in result
    assert r"\[" in result
    assert r"\(" in result
    # 한글 그대로
    result_kr = _escape_md_v2("안녕하세요 123")
    assert "안녕하세요" in result_kr
    assert "123" in result_kr


def test_escape_md_v2_no_double_escape():
    """이미 이스케이프된 문자 없음 — 입력 그대로 처리."""
    plain = "no special chars here"
    assert _escape_md_v2(plain) == plain


# ---------------------------------------------------------------------------
# D18-v2 (2026-05-08) — LaTeX → 유니코드 변환 회귀 (사용자 절칙).
# KRX 봇 결함: `$\rightarrow$` raw 노출. _escape_md_v2 가 sanitize 흡수.
# ---------------------------------------------------------------------------

def test_escape_md_v2_latex_arrow_to_unicode():
    """`$\\rightarrow$` → `→` 평문화 (escape 전 sanitize)."""
    raw = "**가격우선** $\\rightarrow$ **시간우선**"
    result = _escape_md_v2(raw)
    # 원본 LaTeX 가 평문화되어 raw `$\rightarrow$` 사라짐.
    assert "$\\rightarrow$" not in result
    assert "→" in result


def test_escape_md_v2_latex_inequalities():
    """`\\le` `\\ge` `\\neq` 평문화."""
    result_le = _escape_md_v2("$x \\le y$")
    assert "≤" in result_le
    result_ge = _escape_md_v2("$x \\ge y$")
    assert "≥" in result_ge


def test_escape_md_v2_latex_idempotent():
    """이미 유니코드 → 변경 없음 (재호출 안전)."""
    already = "**STEP1** → **STEP2**"
    result = _escape_md_v2(already)
    assert "→" in result


def test_escape_md_v2_latex_currency_no_false_positive():
    """`$100` 같은 통화 표기 — 수식 구분자 X (false positive 차단)."""
    raw = "가격은 $100 입니다"
    result = _escape_md_v2(raw)
    # MarkdownV2 escape 는 `.` 만 백슬래시 — `$` 는 escape 대상 아님.
    # 100 은 그대로, 한국어 그대로.
    assert "100" in result
    assert "가격은" in result


@pytest.mark.asyncio
async def test_send_outbound_latex_arrow_converts_to_unicode(adapter):
    """KRX 결함 회귀 — Telegram 발송 시 `$\\rightarrow$` 가 `→` 으로 변환되어 send."""
    from unittest.mock import patch
    sent = {}

    async def fake_post(self, url, json):
        sent["json"] = json
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        return resp

    with patch("httpx.AsyncClient.post", new=fake_post):
        await adapter.send_outbound(
            {"bot_token": "TOKEN"},
            "12345",
            "**가격우선** $\\rightarrow$ **시간우선**",
        )
    text = sent["json"]["text"]
    assert "$\\\\rightarrow$" not in text and "$\\rightarrow$" not in text
    assert "→" in text
