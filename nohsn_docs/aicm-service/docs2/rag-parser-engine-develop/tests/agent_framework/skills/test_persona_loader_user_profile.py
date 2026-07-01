"""persona_loader user_profile 우선 합성 — PR-A ❹.

증상: 사용자가 실무자/상담사인데 skill 페르소나 (학생/일반인) 가 사용자 페르소나를
덮어써서 hallucination ("저도 진로 고민하는 학생이라…") 발생.

해결: build_system_prompt 에 ``user_profile`` (account profile_type / 호칭 / 톤) 을
키워드 인자로 받아 *베이스* 로 두고, skill.role 은 도메인 전문성만 보강.

본 모듈은 단위 검증 — 합성된 system prompt 에 사용자 컨텍스트가 skill 페르소나보다
우선 표시되는지, 사용자 프로필에 명시된 호칭/역할이 직접 반영되는지 확인.
규칙/regex/키워드 매칭 금지 (memory: feedback_pattern_core_not_case) — prompt 에는
의도/원칙만 표현하고 LLM 의 일반화 능력에 위임한다.
"""

from __future__ import annotations

import asyncio

from src.agent_framework.skills.persona_loader import build_system_prompt
from src.agent_framework.skills.schema_v2 import SkillRole, SkillV2


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_user_profile_appears_before_skill_persona_section():
    """사용자 컨텍스트가 skill 페르소나 위에 (베이스 자리에) 합성된다."""
    skill = SkillV2(
        name="career_guide",
        description="진로 가이드",
        role=SkillRole(
            persona="진로 상담을 도와주는 또래 친구",
            tone="공감 + 친근",
        ),
    )
    user_profile = {
        "profile_type": "professional",
        "honorific": "선생님",
        "preferred_tone": "정중한 존댓말",
        "role_description": "10년차 공정 엔지니어",
    }

    prompt = _run(build_system_prompt(skill, user_profile=user_profile))

    # 사용자 컨텍스트가 prompt 에 명시
    assert "선생님" in prompt
    assert "공정 엔지니어" in prompt or "professional" in prompt
    # 사용자 컨텍스트 블록이 skill 페르소나 블록보다 먼저 나옴
    user_idx = prompt.find("선생님")
    skill_idx = prompt.find("진로 상담을 도와주는 또래 친구")
    assert user_idx >= 0 and skill_idx >= 0
    assert user_idx < skill_idx, (
        "사용자 컨텍스트는 skill 페르소나 위에 베이스로 와야 한다 "
        f"(user@{user_idx} skill@{skill_idx})\n{prompt}"
    )


def test_user_profile_signals_skill_persona_is_domain_only():
    """사용자 프로필이 들어왔을 때 prompt 본문에 'skill 페르소나는 도메인 전문성 보강'
    이라는 의도가 자연어로 표시돼 LLM 이 사용자 페르소나를 우선시하도록 가이드."""
    skill = SkillV2(
        name="career_guide",
        description="진로 가이드",
        role=SkillRole(persona="또래 친구", tone="친근한 반말"),
    )
    user_profile = {"profile_type": "professional", "honorific": "선생님"}

    prompt = _run(build_system_prompt(skill, user_profile=user_profile))

    # 자연어 의도 신호 — 키워드 매칭 아닌 "사용자 정체성 우선" 의 표현이 들어가야
    # LLM 이 일반화한다. 신호어 후보: 사용자/실제/우선/유지/덮어쓰지/도메인 보강.
    assert any(
        marker in prompt
        for marker in (
            "사용자 정체성",
            "사용자의 정체성",
            "사용자 페르소나",
            "사용자 컨텍스트",
            "실제 사용자",
        )
    ), f"사용자 우선 신호어가 prompt 에 없음:\n{prompt}"


def test_no_user_profile_falls_back_to_legacy_render():
    """user_profile=None — 기존 거동 (skill role 만 합성) 회귀 보존."""
    skill = SkillV2(
        name="x",
        description="y",
        role=SkillRole(persona="페르소나", tone="톤"),
    )
    prompt_legacy = _run(build_system_prompt(skill, base_prompt="너는 보조 LLM."))
    assert "당신은 페르소나." in prompt_legacy
    assert "선생님" not in prompt_legacy


def test_user_profile_none_means_legacy_path():
    """user_profile=None 지정 시도 legacy 경로 그대로."""
    skill = SkillV2(
        name="x",
        description="y",
        role=SkillRole(persona="페르소나", tone="톤"),
    )
    prompt = _run(build_system_prompt(skill, base_prompt="", user_profile=None))
    assert prompt.startswith("당신은 페르소나.")
