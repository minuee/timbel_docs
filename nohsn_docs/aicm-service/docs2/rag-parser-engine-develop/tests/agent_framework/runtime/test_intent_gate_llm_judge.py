"""#80 — intent_gate LLM judge 단위 테스트.

검증 범위:
1. in_domain query → reject=False (pass-through).
2. 명백 out_of_domain + LLM confidence >= 0.75 → reject=True, reason=llm_judge_out_of_domain.
3. 경계 query (SaaS 수수료) + LLM in_domain → reject=False.
4. LLM confidence < 0.75 (모호) → reject=False (false-positive 회피).
5. LLM 호출 실패 → fail-open (reject=False).
6. oos_keywords 매칭 시 LLM judge 호출 없이 즉시 reject (keyword fast path).
7. guidelines_md 없으면 LLM judge 건너뜀 → pass-through.
8. KMS_INTENT_GATE_LLM_JUDGE_ENABLED=0 → LLM judge 스킵.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.agent_framework.runtime.intent_gate import (
    intent_gate_check_async,
    intent_gate_llm_judge,
)


# ---- 공통 fixture ----

def _saas_agent(*, oos_keywords=None, guidelines_md: str | None = None):
    """공공기관 SaaS 도입 자문 봇 (oos_keywords 없음, guidelines 있음)."""
    ctx = MagicMock()
    ctx.is_admin = False
    ctx.kind = "role"
    ctx.name = "공공기관 SaaS 도입 자문 봇"
    ctx.goal = "공공기관 클라우드 SaaS 도입 절차, CSAP 인증, 계약 안내"
    ctx.oos_keywords = oos_keywords or []
    ctx.guidelines_md = guidelines_md if guidelines_md is not None else (
        "## 역할\n공공기관 SaaS 도입·CSAP 인증·계약 관련 질의만 응대.\n\n"
        "## 도메인 외 발화 정책\n"
        "SaaS 도입과 무관한 주제는 거절."
    )
    return ctx


def _fake_llm_response(domain: str, confidence: float, reason: str = "") -> MagicMock:
    import json
    text = json.dumps({"domain": domain, "confidence": confidence, "reason": reason})
    return MagicMock(text=text)


# ---- 1. in_domain query → pass-through ----

@pytest.mark.asyncio
async def test_in_domain_query_pass_through(monkeypatch):
    """CSAP 인증 관련 query → in_domain → reject=False."""
    ctx = _saas_agent()
    fake_resp = _fake_llm_response("in_domain", 0.90, "CSAP 인증은 SaaS 도입 핵심")
    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock(return_value=fake_resp)
        result = await intent_gate_check_async("공공기관 클라우드 CSAP 인증 절차 알려줘", ctx)
    assert result["reject"] is False
    assert result["reason"] in ("in_domain_likely", "no_keywords")


# ---- 2. 명백 out_of_domain + confidence >= 0.75 → reject ----

@pytest.mark.asyncio
async def test_obvious_oos_high_confidence_rejected(monkeypatch):
    """주식 매매 수수료 query → out_of_domain, conf=0.95 → reject=True."""
    ctx = _saas_agent()
    fake_resp = _fake_llm_response("out_of_domain", 0.95, "금융 거래 도메인 — SaaS 자문 외")
    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock(return_value=fake_resp)
        result = await intent_gate_check_async("주식 매매 수수료가 얼마예요?", ctx)
    assert result["reject"] is True
    assert result["reason"] == "llm_judge_out_of_domain"
    assert result["llm_judge_confidence"] == 0.95


# ---- 3. 경계 케이스 (SaaS 수수료) → in_domain ----

@pytest.mark.asyncio
async def test_boundary_saas_fee_in_domain(monkeypatch):
    """'SaaS 이용 수수료' — 수수료 단어 있어도 SaaS 도메인 → in_domain."""
    ctx = _saas_agent()
    fake_resp = _fake_llm_response("in_domain", 0.82, "SaaS 계약 비용 맥락 — in-scope")
    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock(return_value=fake_resp)
        result = await intent_gate_check_async("SaaS 이용 수수료 기준이 어떻게 돼요?", ctx)
    assert result["reject"] is False


# ---- 4. out_of_domain but confidence < 0.75 → pass-through (모호) ----

@pytest.mark.asyncio
async def test_oos_low_confidence_pass_through(monkeypatch):
    """LLM 이 out_of_domain 이지만 confidence 0.6 → 경계 모호 → reject=False."""
    ctx = _saas_agent()
    fake_resp = _fake_llm_response("out_of_domain", 0.60, "모호한 경계")
    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock(return_value=fake_resp)
        result = await intent_gate_check_async("클라우드 비용 산정 기준", ctx)
    assert result["reject"] is False


# ---- 5. LLM 호출 실패 → fail-open ----

@pytest.mark.asyncio
async def test_llm_failure_fail_open(monkeypatch):
    """LLM 예외 → fail-open: reject=False (회귀 최소화)."""
    ctx = _saas_agent()
    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        result = await intent_gate_check_async("주식 가격 알려줘", ctx)
    assert result["reject"] is False


# ---- 6. oos_keywords 매칭 → 즉시 reject (LLM judge 미호출) ----

@pytest.mark.asyncio
async def test_keyword_match_fast_path_no_llm():
    """oos_keywords 매칭 → keyword fast path, LLM judge 호출 없음."""
    ctx = _saas_agent(oos_keywords=["코스피"])
    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock()
        result = await intent_gate_check_async("코스피 지수 오늘 얼마야?", ctx)
    assert result["reject"] is True
    assert result["reason"] == "oos_keyword_match"
    mock_router.route.assert_not_called()


# ---- 7. guidelines_md 없으면 LLM judge skip → pass-through ----

@pytest.mark.asyncio
async def test_no_guidelines_skip_llm_judge():
    """guidelines_md 비어 있으면 LLM judge 생략 → pass-through."""
    ctx = _saas_agent(guidelines_md="")
    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock()
        result = await intent_gate_check_async("아무 질문이나", ctx)
    assert result["reject"] is False
    mock_router.route.assert_not_called()


# ---- 8. KMS_INTENT_GATE_LLM_JUDGE_ENABLED=0 → judge skip ----

@pytest.mark.asyncio
async def test_llm_judge_kill_switch(monkeypatch):
    """KMS_INTENT_GATE_LLM_JUDGE_ENABLED=0 → LLM judge 완전 비활성."""
    monkeypatch.setenv("KMS_INTENT_GATE_LLM_JUDGE_ENABLED", "0")
    ctx = _saas_agent()
    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock()
        result = await intent_gate_check_async("주식 매매 수수료 알려줘", ctx)
    assert result["reject"] is False
    mock_router.route.assert_not_called()
    monkeypatch.delenv("KMS_INTENT_GATE_LLM_JUDGE_ENABLED", raising=False)


# ---- 9. intent_gate_llm_judge 직접 테스트 — JSON ````json``` 래핑 파싱 ----

@pytest.mark.asyncio
async def test_llm_judge_json_fenced_parsing():
    """LLM 이 ```json ... ``` 래핑으로 응답해도 올바르게 파싱."""
    ctx = _saas_agent()
    fenced_text = '```json\n{"domain": "out_of_domain", "confidence": 0.88, "reason": "test"}\n```'
    fake_resp = MagicMock(text=fenced_text)
    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock(return_value=fake_resp)
        result = await intent_gate_llm_judge("주식 가격", ctx)
    assert result["domain"] == "out_of_domain"
    assert result["confidence"] == 0.88
    assert result["error"] is None
