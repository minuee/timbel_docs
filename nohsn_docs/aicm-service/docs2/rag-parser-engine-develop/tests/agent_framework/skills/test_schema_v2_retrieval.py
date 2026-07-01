"""SkillV2 retrieval 메타 — none|kms|tool 키 도입 테스트 (PR-A).

❼ 일정 도메인에 KMS RAG citations 가 강제 첨부되는 버그 차단을 위해
스킬 메타에 ``retrieval`` 한 키를 추가. 사례 yaml 추가 금지 — 메타 한 키로 일반화.
"""

from __future__ import annotations

import pytest

from src.agent_framework.skills.schema_v2 import (
    SkillV2,
    SkillV2LoadError,
    from_dict,
)


def test_retrieval_default_is_kms():
    """retrieval 미지정 시 default="kms" — 기존 거동 유지 (회귀 안전)."""
    skill = from_dict({"name": "x", "description": "y"})
    assert skill.retrieval == "kms"


def test_retrieval_none_loads():
    """retrieval=none 명시 시 그대로 로드. 일정/캘린더 같은 비검색 스킬용."""
    skill = from_dict(
        {"name": "schedule", "description": "일정", "retrieval": "none"}
    )
    assert skill.retrieval == "none"


def test_retrieval_tool_loads():
    """retrieval=tool — tool 호출이 검색을 대체하는 스킬용."""
    skill = from_dict(
        {"name": "stock", "description": "주식", "retrieval": "tool"}
    )
    assert skill.retrieval == "tool"


def test_retrieval_invalid_value_rejected():
    """none|kms|tool 외 값은 SkillV2LoadError."""
    with pytest.raises(SkillV2LoadError):
        from_dict({"name": "x", "description": "y", "retrieval": "anything"})
