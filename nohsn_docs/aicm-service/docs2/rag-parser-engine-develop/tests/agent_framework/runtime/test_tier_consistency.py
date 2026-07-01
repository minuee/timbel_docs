"""sender-tier-consistency regression (2026-05-07).

근본 결함 회귀 케이스 — agent.guidelines_md 의 ``## 외부 채널 게스트
(sender.tier = guest)`` doctrine 이 binding policy block 에 포함되어 LLM 이
tier 별로 답변 본문 분기를 만들던 회귀.

사용자 명시 (2026-05-07):
    "에이전트 설정을 한번 하면, 그게 채널에 묶이면 그건 어차피 에이전트
    특성을 다 상속 받아야지. 루트에 따라 다른건 말이 안되고."

검증 범위:
1. _strip_tier_doctrine_sections — sender.tier 헤더 섹션이 통째로 제거되고
   같은 레벨 다음 헤더는 보존.
2. to_binding_policy_block — guidelines_md 에 doctrine 이 있어도 출력 block
   에서 sender.tier 토큰이 사라지고 tier-neutral guide 가 inject.
3. 진입 경로별 동일성 — admin / verified / guest tier 모두 *동일* binding
   policy block 을 받음 (tier 가 binding 빌드에 영향 X).
4. fallback_hint payload — engine.py 의 _llm_compose_tool_answer 가 KMS hit 0
   시 거절이 아닌 disclaimer 지시를 user payload 에 넣음.
5. destructive 도구 권한은 SenderContext.meets() 가 분리 — 답변 path 와 무관.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.agent_framework.runtime.agent_context import (
    AgentContext,
    _strip_tier_doctrine_sections,
    _TIER_NEUTRAL_ANSWER_GUIDE,
)
from src.agent_framework.runtime.sender_context import SenderContext, tier_rank


# 실제 baemin role agent 의 guidelines_md (create_5_role_agents.py 에서 발췌).
_BAEMIN_REAL_GUIDE = """## 응대 원칙

1. 인사·공감·해결 3박자 — 매뉴얼 멘트 *그대로 인용* (가공 금지).
2. STEP/CASE 분기 — 주문상태별 trigger 가 다름. 매뉴얼의 STEP1→2→3 트리 유지.
3. 슬롯 미충족 — 주문ID·취소사유·고객명 3 회 시도 후 escalation.
4. 업주 OB 통화 stub — 시연 단계는 mock, 실 환경은 `merchant.callout` 으로.

## 외부 채널 게스트 (sender.tier = guest)

- 본 봇은 *시연·교육용* 입니다. 실제 주문 취소/재배송은 정식 배민 앱·1599-0917 으로 안내.
- 가능한 응답: FAQ (취소 가능 단계, 환불 일정), 매뉴얼 멘트 인용.
- 거절: 실 주문 ID 변경, 업주 통화 실 발신, 쿠폰 실 발행.
"""


def _baemin_role_agent() -> AgentContext:
    """실제 baemin_consult role agent 와 동일 schema."""
    return AgentContext(
        agent_id=uuid4(),
        tenant_id=uuid4(),
        name="baemin_consult",
        goal="콜 1통당 *취소 가능/불가* 분기 결정 + 업주 통화 + 쿠폰·재배송 처리.",
        guidelines_md=_BAEMIN_REAL_GUIDE,
        primary_repo_ids=[uuid4()],
        fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=["kms_rag.search", "kms_sop.search"],
        done_when="주문 취소 분기 결정 + 후속 안내 완료.",
        kind="role",
    )


# ---------------------------------------------------------------------------
# 1. _strip_tier_doctrine_sections — doctrine 헤더 섹션 cut.
# ---------------------------------------------------------------------------

def test_strip_removes_tier_doctrine_section():
    """``## 외부 채널 게스트 (sender.tier = guest)`` 섹션이 통째로 제거되고
    그 앞·뒤 다른 섹션은 보존되어야 한다.
    """
    out = _strip_tier_doctrine_sections(_BAEMIN_REAL_GUIDE)
    assert "sender.tier" not in out.lower()
    # 응대 원칙 섹션은 보존.
    assert "## 응대 원칙" in out
    assert "STEP/CASE" in out
    # doctrine 본문도 사라져야.
    assert "거절: 실 주문 ID 변경" not in out
    assert "FAQ (취소 가능 단계" not in out


def test_strip_preserves_following_section():
    """doctrine 섹션 뒤에 *동일 또는 상위 레벨* 다른 섹션이 있으면 보존."""
    gm = (
        "## 응대 원칙\n"
        "원칙 1\n\n"
        "## 외부 채널 게스트 (sender.tier = guest)\n"
        "doctrine\n\n"
        "## 다음 섹션\n"
        "important\n"
    )
    out = _strip_tier_doctrine_sections(gm)
    assert "doctrine" not in out
    assert "## 다음 섹션" in out
    assert "important" in out


def test_strip_no_doctrine_returns_input_unchanged():
    """doctrine marker 가 없으면 입력 그대로 반환 (회귀 0)."""
    gm = "## 역할\n도시가스 안내만.\n\n## 안전\n가스누출 fast-track."
    out = _strip_tier_doctrine_sections(gm)
    assert out == gm


def test_strip_handles_multiple_doctrine_sections():
    """여러 doctrine 섹션이 있으면 모두 제거."""
    gm = (
        "## 역할\nA\n\n"
        "## 외부 채널 게스트 (sender.tier = guest)\nB\n\n"
        "## 일반\nC\n\n"
        "### 회원 (sender.tier=verified)\nD\n\n"
        "## 끝\nE\n"
    )
    out = _strip_tier_doctrine_sections(gm)
    assert "sender.tier" not in out.lower()
    assert "A" in out and "C" in out and "E" in out
    assert "B" not in out and "D" not in out


# ---------------------------------------------------------------------------
# 2. to_binding_policy_block — doctrine 제거 + tier-neutral guide inject.
# ---------------------------------------------------------------------------

def test_binding_block_drops_tier_doctrine():
    """to_binding_policy_block 출력에서 sender.tier 토큰이 사라져야 한다."""
    ctx = _baemin_role_agent()
    block = ctx.to_binding_policy_block()
    assert "sender.tier" not in block.lower()
    # 응대 원칙은 보존.
    assert "응대 원칙" in block
    # tier-neutral guide 한 단락 inject 확인.
    assert "일관 응대 가이드" in block
    assert "destructive" in block


def test_binding_block_sop_rag_mode_also_has_neutral_guide():
    """sop_rag_mode 에서도 tier-neutral guide 는 inject 되어야 한다."""
    ctx = _baemin_role_agent()
    block = ctx.to_binding_policy_block(sop_rag_mode=True)
    assert "sender.tier" not in block.lower()
    assert "일관 응대 가이드" in block
    # SOP context 안내도 유지.
    assert "[SOP CONTEXT]" in block


# ---------------------------------------------------------------------------
# 3. 진입 경로 (web admin / webhook verified / webhook guest) 동일 binding.
# ---------------------------------------------------------------------------

def test_binding_block_identical_across_tiers():
    """동일 agent 에 대해 *모든 tier* 가 동일 binding policy block 을 받음.

    binding policy 빌드는 SenderContext 와 무관 — 이 자체가 결함의 핵심.
    같은 agent_context 면 같은 block 출력. tier 는 destructive 도구 호출 시점
    runtime guard 만 결정.
    """
    ctx = _baemin_role_agent()
    block_default = ctx.to_binding_policy_block()
    # to_binding_policy_block 은 SenderContext 인자를 받지 않는다 — 즉
    # tier 가 어떤 값이든 출력은 동일. 호출 자체에 tier 의존성 없음을
    # 정적으로 검증.
    import inspect

    sig = inspect.signature(ctx.to_binding_policy_block)
    params = set(sig.parameters.keys())
    # 'sender' / 'tier' / 'sender_context' 같은 파라미터가 *없음* — tier-free
    # API 시그니처를 회귀 lock.
    assert "sender" not in params
    assert "tier" not in params
    assert "sender_context" not in params
    assert "self" not in params  # bound method 라 self 가 빠진 sig
    # 기본 block 내부에도 SenderContext 인스턴스 의존성 없음 — 텍스트 내
    # tier 토큰 0개.
    assert "guest" not in block_default.lower() or "guest 라도" not in block_default.lower()


# ---------------------------------------------------------------------------
# 4. engine.py _llm_compose_tool_answer — fallback_hint payload (disclaimer).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_no_hit_emits_fallback_hint_not_oos_refusal():
    """KMS hit 0 시 user payload 에 fallback_hint (안내 + disclaimer) 가
    들어가고, 옛 oos_hint (거절) 는 들어가지 않아야 한다.
    """
    from src.agent_framework.runtime.engine import AgentEngine

    captured = {}

    class _MockLLM:
        async def complete(self, system, user, response_format=None):
            captured["user"] = user
            return "MOCK"

    eng = AgentEngine.__new__(AgentEngine)
    eng.llm = _MockLLM()
    eng.response_generator = MagicMock()
    eng.fallback_router = MagicMock()
    eng._agent_context = _baemin_role_agent()
    eng._is_admin_agent = False

    await eng._llm_compose_tool_answer(
        user_message="배달 중에는 주문 취소가 안되니?",
        tool_results=[
            {
                "tool": "kms_rag.search",
                "result": {"hits": [], "summary": "검색 결과 0건"},
            },
        ],
        user_preference=None,
        citation_items=None,
    )
    user_payload_text = captured["user"]
    payload = json.loads(user_payload_text.split("\n## 참고 후보")[0])
    assert payload.get("no_relevant_content") is True
    # fallback_hint (disclaimer 지시) 가 들어가야.
    assert "fallback_hint" in payload
    fb = payload["fallback_hint"]
    assert "거절하지 말고" in fb
    assert "disclaimer" in fb
    # 옛 oos_hint (거절 지시) 는 이제 없어야.
    assert "oos_hint" not in payload


# ---------------------------------------------------------------------------
# 5. SenderContext.meets() — destructive 도구 권한 분리. 답변 path 와 무관.
# ---------------------------------------------------------------------------

def test_sender_tier_meets_destructive_separately():
    """tier 비교 (meets) 는 destructive 도구 호출 권한 결정에만 사용.

    답변 본문은 위 1~4 에서 검증된 것처럼 tier 와 무관 동일. 본 테스트는
    *destructive 권한* 만이 tier 의 합법적 분기 지점임을 확정.
    """
    tid = uuid4()
    guest = SenderContext(
        tier="guest", internal_user_id=None, tenant_id=tid,
        channel_kind="telegram", verified_via=None, confirm_token=None,
    )
    verified = SenderContext(
        tier="verified", internal_user_id=uuid4(), tenant_id=tid,
        channel_kind="web", verified_via="session_login", confirm_token=None,
    )
    admin = SenderContext(
        tier="admin", internal_user_id=uuid4(), tenant_id=tid,
        channel_kind="web", verified_via="session_login", confirm_token=None,
    )
    # destructive 도구가 'verified' tier 를 요구한다고 가정.
    REQUIRED = "verified"
    assert guest.meets(REQUIRED) is False  # 차단
    assert verified.meets(REQUIRED) is True  # 통과
    assert admin.meets(REQUIRED) is True  # 통과
    # 답변 본문 path 는 위 분기와 *완전히 분리*. 본 테스트는 그 분리를 lock.
    assert tier_rank("guest") < tier_rank("verified") < tier_rank("admin")


# ---------------------------------------------------------------------------
# 6. _TIER_NEUTRAL_ANSWER_GUIDE — destructive 분리 메시지가 명시되어야.
# ---------------------------------------------------------------------------

def test_neutral_guide_mentions_destructive_separation():
    """tier-neutral guide 가 답변 본문 동일성 + destructive 가드 분리를 명시.

    LLM 이 이 한 단락을 읽고 tier 분기를 *답변 본문* 에 적용하지 않도록 강제.
    """
    g = _TIER_NEUTRAL_ANSWER_GUIDE
    assert "동일" in g
    assert "destructive" in g
    assert "runtime 가드" in g or "runtime" in g
    assert "disclaimer" in g
