"""auto_loader 테스트 — mock LLM 으로 매칭/threshold/할루시네이션 차단 검증."""

from __future__ import annotations

import asyncio
import json

from src.agent_framework.skills.auto_loader import select_skill, _scope_matches
from src.agent_framework.skills.schema_v2 import SkillV2, SkillRole


def _run(coro):
    # 새 event loop 를 매번 생성해서 cross-test pollution 방지.
    # asyncio_mode=auto 인 다른 테스트가 loop 를 닫으면
    # asyncio.get_event_loop() 가 RuntimeError 를 던지기 때문.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _StubLLM:
    """미리 정해진 JSON 문자열을 반환하는 가짜 LLM."""

    def __init__(self, payload: dict | str | Exception):
        self._payload = payload
        self.last_system: str | None = None
        self.last_user: str | None = None

    async def complete(
        self, system: str, user: str, *, response_format: str | None = None
    ) -> str:
        self.last_system = system
        self.last_user = user
        if isinstance(self._payload, Exception):
            raise self._payload
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload, ensure_ascii=False)


def _two_skills() -> list[SkillV2]:
    return [
        SkillV2(
            name="kb_soldiers_counselor",
            description="KB 장병내일준비적금 상담",
            trigger_examples=["군적금 가입", "장병적금 금리"],
        ),
        SkillV2(
            name="news_daily_brief",
            description="국내 뉴스 일일 요약",
            trigger_examples=["오늘 뉴스 요약해줘"],
        ),
    ]


def test_picks_correct_skill_above_threshold():
    llm = _StubLLM({"skill_name": "kb_soldiers_counselor", "confidence": 0.92, "reason": "직접 매칭"})
    picked = _run(
        select_skill(
            user_utterance="장병내일준비적금 가입하려고요",
            available_skills=_two_skills(),
            llm_client=llm,
        )
    )
    assert picked is not None
    assert picked.name == "kb_soldiers_counselor"


def test_returns_none_when_below_threshold():
    llm = _StubLLM({"skill_name": "kb_soldiers_counselor", "confidence": 0.3, "reason": "약함"})
    picked = _run(
        select_skill(
            user_utterance="모호한 발화",
            available_skills=_two_skills(),
            llm_client=llm,
            threshold=0.5,
        )
    )
    assert picked is None


def test_returns_none_when_skill_name_empty():
    llm = _StubLLM({"skill_name": "", "confidence": 0.0, "reason": "잡담"})
    picked = _run(
        select_skill(
            user_utterance="안녕하세요 반갑습니다",
            available_skills=_two_skills(),
            llm_client=llm,
        )
    )
    assert picked is None


def test_filters_hallucinated_skill_name():
    llm = _StubLLM(
        {"skill_name": "this_skill_does_not_exist", "confidence": 0.99, "reason": "환각"}
    )
    picked = _run(
        select_skill(
            user_utterance="뭐든지",
            available_skills=_two_skills(),
            llm_client=llm,
        )
    )
    assert picked is None


def test_matches_paraphrased_utterance():
    """변형 표현 — LLM 이 동의어 매칭 결정. 우리 코드는 그 결과를 그대로 사용."""
    llm = _StubLLM(
        {"skill_name": "kb_soldiers_counselor", "confidence": 0.78, "reason": "동의어"}
    )
    picked = _run(
        select_skill(
            user_utterance="저 군대 가는데 적금 하나 들어볼까 해서요",
            available_skills=_two_skills(),
            llm_client=llm,
        )
    )
    assert picked is not None
    assert picked.name == "kb_soldiers_counselor"
    # prompt 가 LLM 에 실제로 전달됐는지 확인 — 모든 skill 정보 포함
    assert "kb_soldiers_counselor" in (llm.last_user or "")
    assert "news_daily_brief" in (llm.last_user or "")


def test_empty_skill_list_returns_none_without_llm_call():
    llm = _StubLLM({"skill_name": "x", "confidence": 1.0})
    picked = _run(
        select_skill(
            user_utterance="아무거나",
            available_skills=[],
            llm_client=llm,
        )
    )
    assert picked is None
    assert llm.last_user is None  # LLM 호출 안 됐음


def test_llm_failure_returns_none():
    llm = _StubLLM(RuntimeError("network down"))
    picked = _run(
        select_skill(
            user_utterance="가입하려고요",
            available_skills=_two_skills(),
            llm_client=llm,
        )
    )
    assert picked is None


# ── KMS-Plus scope filter (tenant_scope/persona_required/role_min) ────────


def _scoped_skill(
    name: str,
    *,
    tenant_scope=None,
    persona_required=None,
    role_min: str = "viewer",
) -> SkillV2:
    return SkillV2(
        name=name,
        description=f"{name} desc",
        role=SkillRole(
            persona="P",
            tone="T",
            tenant_scope=list(tenant_scope or []),
            persona_required=list(persona_required or []),
            role_min=role_min,
        ),
        trigger_examples=[f"{name} trigger"],
    )


def test_scope_matches_when_empty_constraints_pass_anything():
    """role.tenant_scope/persona_required 둘 다 비어있으면 모두 통과."""
    s = _scoped_skill("free_for_all")  # 빈 리스트
    assert _scope_matches(s, account={"persona": "anything", "role": "viewer"}, tenant={"kind": "anything"})
    assert _scope_matches(s, account=None, tenant=None)


def test_scope_matches_tenant_kind_mismatch_fails():
    s = _scoped_skill("hospital_only", tenant_scope=["hospital", "clinic"])
    # 일치
    assert _scope_matches(s, tenant={"kind": "hospital"})
    # 불일치
    assert not _scope_matches(s, tenant={"kind": "factory"})
    # wildcard 가 있으면 통과
    s2 = _scoped_skill("anywhere", tenant_scope=["*"])
    assert _scope_matches(s2, tenant={"kind": "anything"})


def test_scope_matches_persona_required_mismatch_fails():
    s = _scoped_skill("doctor_only", persona_required=["doctor", "nurse"])
    assert _scope_matches(s, account={"persona": "doctor"})
    assert not _scope_matches(s, account={"persona": "lawyer"})
    # any 가 포함되면 통과
    s2 = _scoped_skill("anyone", persona_required=["any"])
    assert _scope_matches(s2, account={"persona": "lawyer"})


def test_scope_matches_role_min_below_fails():
    s = _scoped_skill("admin_only", role_min="admin")
    assert _scope_matches(s, account={"role": "admin"})
    assert _scope_matches(s, account={"role": "owner"})
    assert not _scope_matches(s, account={"role": "viewer"})
    assert not _scope_matches(s, account={"role": "member"})


def test_select_skill_filter_eliminates_all_returns_none_without_llm():
    """1차 scope 필터에서 전부 탈락 → LLM 호출 안 하고 None."""
    skills = [
        _scoped_skill("hospital_skill", tenant_scope=["hospital"]),
        _scoped_skill("factory_skill", tenant_scope=["factory"]),
    ]
    llm = _StubLLM({"skill_name": "hospital_skill", "confidence": 0.99})
    picked = _run(
        select_skill(
            user_utterance="아무거나",
            available_skills=skills,
            llm_client=llm,
            tenant={"kind": "personal"},
        )
    )
    assert picked is None
    assert llm.last_user is None  # LLM 호출 안 됐음


def test_select_skill_filter_passes_eligible_to_llm():
    """1차 필터 통과 skill 만 LLM prompt 에 들어간다."""
    skills = [
        _scoped_skill("kb_only", tenant_scope=["kb_callcenter"]),
        _scoped_skill("hospital_only", tenant_scope=["hospital"]),
        _scoped_skill("personal_only", tenant_scope=["personal"]),
    ]
    llm = _StubLLM({"skill_name": "kb_only", "confidence": 0.9})
    picked = _run(
        select_skill(
            user_utterance="콜센터 응대",
            available_skills=skills,
            llm_client=llm,
            tenant={"kind": "kb_callcenter"},
        )
    )
    assert picked is not None and picked.name == "kb_only"
    user_prompt = llm.last_user or ""
    assert "kb_only" in user_prompt
    assert "hospital_only" not in user_prompt
    assert "personal_only" not in user_prompt
