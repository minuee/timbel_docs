"""persona_loader 테스트 — role → system prompt 합성 검증."""

from __future__ import annotations

import asyncio

from src.agent_framework.skills.persona_loader import build_system_prompt
from src.agent_framework.skills.schema_v2 import (
    FewShotExample,
    FewShotTurn,
    SkillRole,
    SkillV2,
)


def _run(coro):
    # 새 event loop 를 매번 생성해서 cross-test pollution 방지.
    # asyncio_mode=auto 인 다른 테스트가 loop 를 닫으면
    # asyncio.get_event_loop() 가 RuntimeError 를 던지기 때문.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_full_role_renders_all_sections():
    skill = SkillV2(
        name="kb",
        description="d",
        role=SkillRole(
            persona="KB 5년차 상담사",
            tone="친절·존댓말",
            knowledge_scope=["kb_soldiers", "policy_2026"],
            safety_constraints=["추측 금지", "개인정보 요구 금지"],
        ),
        few_shot_examples=[
            FewShotExample(
                source="demo.xlsx",
                turns=[
                    FewShotTurn(role="customer", text="가입하려고요"),
                    FewShotTurn(role="counselor", text="복무 중이신가요?"),
                ],
            )
        ],
    )
    prompt = _run(build_system_prompt(skill, base_prompt="너는 보조 LLM."))
    assert "너는 보조 LLM." in prompt
    assert "당신은 KB 5년차 상담사." in prompt
    assert "말투: 친절·존댓말." in prompt
    assert "kb_soldiers" in prompt and "policy_2026" in prompt
    assert "절대 금기:" in prompt
    assert "- 추측 금지" in prompt
    assert "- 개인정보 요구 금지" in prompt
    assert "대화 예시 (참고):" in prompt
    assert "[customer] 가입하려고요" in prompt
    assert "[counselor] 복무 중이신가요?" in prompt
    # base 와 분리자
    assert "---" in prompt


def test_no_role_returns_only_base():
    skill = SkillV2(name="x", description="y", role=None)
    prompt = _run(build_system_prompt(skill, base_prompt="  base only  "))
    assert prompt == "base only"


def test_role_without_base_renders_persona_only():
    skill = SkillV2(
        name="x",
        description="y",
        role=SkillRole(persona="페르소나", tone="톤"),
    )
    prompt = _run(build_system_prompt(skill, base_prompt=""))
    assert prompt.startswith("당신은 페르소나.")
    assert "말투: 톤." in prompt
    assert "---" not in prompt  # base 없으면 분리자도 없음
