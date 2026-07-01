"""Persona Loader — SkillV2.role + base_prompt → 합성된 LLM system prompt.

Phase 8.5 — 신입 상담사 교육 패턴 중 '톤·금기·역할' 차원을 LLM 의 system 메시지로
주입한다. 본 모듈은 LLM 호출이 없는 순수 문자열 합성기 — 의도적으로 단순하다.
LLM 판단이 필요한 곳(매칭/슬롯필/분기)은 별도 모듈(auto_loader/process_runner)이 담당.

PR-A — ❹ 사용자 페르소나가 skill 페르소나에 덮이는 hallucination 차단.
``user_profile`` 인자가 들어오면 사용자 컨텍스트를 *베이스* 로 두고, skill.role 은
도메인 전문성만 보강한다. 사용자 우선 합성 의도는 자연어로 prompt 본문에 표현 —
LLM 이 일반화한다 (memory: feedback_pattern_core_not_case, feedback_llm_driven_everywhere).
"""

from __future__ import annotations

from typing import Any

from src.agent_framework.skills.schema_v2 import FewShotExample, SkillV2


def _format_few_shot(example: FewShotExample) -> str:
    if not example.turns:
        return ""
    lines: list[str] = []
    if example.source:
        lines.append(f"(출처: {example.source})")
    for turn in example.turns:
        lines.append(f"- [{turn.role}] {turn.text}")
    return "\n".join(lines)


def _format_user_profile_block(user_profile: dict[str, Any]) -> str:
    """사용자 컨텍스트 블록 — system prompt 의 베이스로 들어간다.

    프로필 키는 자유 (호출자 측 — context_v1 router / SettingsPage):
    profile_type / honorific / preferred_tone / role_description / 등.
    빈 값은 생략. 형태는 자연어 dict-like — LLM 가 읽고 페르소나로 변신.
    """
    lines: list[str] = ["[실제 사용자 정체성 — 답변 시 반드시 우선 유지]"]
    profile_type = str(user_profile.get("profile_type") or "").strip()
    honorific = str(user_profile.get("honorific") or "").strip()
    role_desc = str(user_profile.get("role_description") or "").strip()
    pref_tone = str(user_profile.get("preferred_tone") or "").strip()
    if profile_type:
        lines.append(f"- 사용자 유형: {profile_type}")
    if role_desc:
        lines.append(f"- 사용자 역할: {role_desc}")
    if honorific:
        lines.append(f"- 호칭: {honorific}")
    if pref_tone:
        lines.append(f"- 사용자가 선호하는 어시스턴트 어투: {pref_tone}")
    # 추가 임의 키도 노출 (자연어 dict-like)
    skip_keys = {"profile_type", "honorific", "role_description", "preferred_tone"}
    extras = {k: v for k, v in user_profile.items() if k not in skip_keys and v}
    for k, v in extras.items():
        lines.append(f"- {k}: {v}")
    lines.append(
        "당신은 어시스턴트다 — 사용자의 정체성을 흉내내거나 사용자 본인이라고 자칭하지 말 것. "
        "사용자 페르소나는 그대로 유지하고, 아래 skill 페르소나는 *도메인 전문성 보강* 으로만 사용."
    )
    return "\n".join(lines)


async def build_system_prompt(
    skill: SkillV2,
    base_prompt: str = "",
    *,
    user_profile: dict[str, Any] | None = None,
) -> str:
    """skill.role + base_prompt → 합성된 LLM system prompt.

    형태 (user_profile 미주입 시 — legacy):
        [base]
        ---
        당신은 {persona}.
        말투: {tone}.
        참조 지식: {knowledge_scope}.
        절대 금기:
        - {safety_constraint_1}
        - ...
        대화 예시 (참고):
        {few_shot turns}

    user_profile 주입 시 (PR-A ❹):
        [실제 사용자 정체성 — 답변 시 반드시 우선 유지]
        - 사용자 유형: ...
        - 사용자 역할: ...
        - ...
        당신은 어시스턴트다 — 사용자 정체성 흉내 금지. skill 페르소나는 도메인 보강용.
        ---
        [skill 페르소나 — 도메인 전문성 보강]
        당신은 {persona}.
        ...

    role 이 None 이면 base_prompt (또는 user_profile) 만 반환.
    base_prompt 가 빈 문자열이면 합성된 페르소나 본문만 반환.

    LLM 호출 없는 순수 합성. 사용자 우선 의도는 자연어로 표시 — 분기는 LLM 이 결정.
    """
    role = skill.role

    sections: list[str] = []

    if user_profile:
        sections.append(_format_user_profile_block(user_profile))
        if base_prompt.strip():
            sections.append("---")
            sections.append(base_prompt.strip())
        if role is not None:
            sections.append("---")
            sections.append("[skill 페르소나 — 도메인 전문성 보강]")
    else:
        if role is None:
            return base_prompt.strip()
        if base_prompt.strip():
            sections.append(base_prompt.strip())
            sections.append("---")

    if role is not None:
        if role.persona.strip():
            sections.append(f"당신은 {role.persona.strip()}.")
        if role.tone.strip():
            sections.append(f"말투: {role.tone.strip()}.")
        if role.knowledge_scope:
            scope = ", ".join(s.strip() for s in role.knowledge_scope if s.strip())
            if scope:
                sections.append(f"참조 지식: {scope}.")
        if role.safety_constraints:
            sections.append("절대 금기:")
            for c in role.safety_constraints:
                c = c.strip()
                if c:
                    sections.append(f"- {c}")

        if skill.few_shot_examples:
            sections.append("")
            sections.append("대화 예시 (참고):")
            for ex in skill.few_shot_examples:
                block = _format_few_shot(ex)
                if block:
                    sections.append(block)

    return "\n".join(sections).strip()
