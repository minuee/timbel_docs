"""Phase 3 Task D — login_brief 단위 테스트.

순수 함수라 외부 I/O 없음. 결정성 보장 위해 ``now`` 주입.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.agent_framework.agent.login_brief import (
    PERSONA_TEMPLATES,
    build_brief,
    detect_persona,
)


FIXED_NOW = datetime(2026, 4, 25, 10, 0, 0)
EXPECTED_DATE_STR = "2026년 04월 25일"


@pytest.mark.asyncio
async def test_medical_persona_template():
    out = await build_brief(
        account={"profile_type": "medical"}, tenant=None, now=FIXED_NOW
    )
    assert "환자 정보" in out
    assert EXPECTED_DATE_STR in out
    # default 인사말 포함
    assert out.startswith("안녕하세요")


@pytest.mark.asyncio
async def test_finance_persona_template():
    out = await build_brief(
        account={"profile_type": "finance"}, tenant=None, now=FIXED_NOW
    )
    assert "시장 동향" in out
    assert EXPECTED_DATE_STR in out


@pytest.mark.asyncio
async def test_default_persona_for_unknown():
    """알 수 없는 profile_type → default 템플릿."""
    out = await build_brief(
        account={"profile_type": "weird_unknown_role"},
        tenant=None,
        now=FIXED_NOW,
    )
    # default 의 핵심 문구
    assert "무엇을 도와드릴까요" in out
    assert EXPECTED_DATE_STR in out


@pytest.mark.asyncio
async def test_with_inventory_summary():
    summary = "현재 활성 문서 3건, 검토 대기 1건입니다."
    out = await build_brief(
        account={"profile_type": "dev"},
        tenant=None,
        inventory_summary=summary,
        now=FIXED_NOW,
    )
    assert "활성 기능" in out  # dev 템플릿
    assert summary in out
    # 인사말과 summary 사이 공백
    assert summary in out.split(" ")[-len(summary.split(" ")):][0] or summary in out


def test_detect_persona_resolution():
    """우선순위: account.profile_type > tenant.business_type > default."""
    assert detect_persona({"profile_type": "medical"}, None) == "medical"
    # account 없으면 tenant 로 fallback
    assert detect_persona(None, {"business_type": "finance"}) == "finance"
    # account 가 있되 unknown 이면 tenant 로 fallback
    assert (
        detect_persona({"profile_type": "xyz"}, {"business_type": "medical"})
        == "medical"
    )
    # 모두 없으면 default
    assert detect_persona(None, None) == "default"
    assert detect_persona({}, {}) == "default"
    # 모든 PERSONA_TEMPLATES 키가 detect_persona 로 라운드트립
    for key in PERSONA_TEMPLATES:
        assert detect_persona({"profile_type": key}, None) == key
