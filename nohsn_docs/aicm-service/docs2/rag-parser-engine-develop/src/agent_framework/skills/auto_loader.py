"""Auto Loader — 자연어 발화 + 등록 스킬 목록 → LLM 으로 best-fit 스킬 선택.

Phase 8.5. Rule/regex 절대 사용 금지 — 모든 매칭은 prompt + LLM 판단.

KMS-Plus 확장: account/tenant scope 1차 필터 (`_scope_matches`) 가 LLM 매칭
*전에* 후보 skill 을 줄인다. 이는 rule 분기가 아니라 메타데이터 필터 — LLM 의
의도/매칭 판단은 그대로 보존.

threshold (기본 0.5) 미달 시 None 반환 → 호출자가 fallback 결정.
빈 skill 목록 → 즉시 None.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from src.agent_framework.llm.json_parse import extract_json
from src.agent_framework.skills.schema_v2 import SkillV2
from src.common.logging import get_logger

log = get_logger(__name__)


_PROMPT_PATH = Path(__file__).parent / "prompts" / "skill_selection.md"

_ROLE_RANKS = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


class LLMClient(Protocol):
    async def complete(
        self, system: str, user: str, *, response_format: str | None = None
    ) -> str: ...


def _attr_or_key(obj: Any, key: str, default: Any = None) -> Any:
    """dict-like 또는 attr 객체에서 값 꺼내기."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _scope_matches(
    skill: SkillV2, *, account: Any = None, tenant: Any = None
) -> bool:
    """SkillRole 의 tenant_scope/persona_required/role_min 1차 매칭.

    빈 리스트 / 미지정 = 제약 없음 (통과). role 자체가 없으면 통과.

    인수:
    - ``account``: dict 또는 객체. ``persona``, ``role`` 키 사용.
    - ``tenant``: dict 또는 객체. ``kind`` 키 사용.

    반환: 통과 여부 (bool).
    """
    role = getattr(skill, "role", None)
    if role is None:
        return True

    # tenant_scope
    tenant_scope = list(getattr(role, "tenant_scope", []) or [])
    if tenant_scope:
        tenant_kind = _attr_or_key(tenant, "kind", "personal") or "personal"
        if tenant_kind not in tenant_scope and "*" not in tenant_scope:
            return False

    # persona_required —
    # tenant_scope 가 통과한 시점에 "이 skill 이 적합한 도메인" 은 이미 입증됨.
    # persona_required 는 사람 인적 역할의 더 정밀한 추가 매칭 (예: tutor, teacher).
    # account 에 인적 persona 정보가 없거나 generic 한 경우 (chat 진입에 OAuth 미적용
    # 등 시드 한계 상황) persona_required 매칭은 soft pass — tenant_scope 통과로 도메인
    # 호환은 이미 보장되었으므로 추가 차단하지 않음.
    persona_required = list(getattr(role, "persona_required", []) or [])
    if persona_required:
        persona = _attr_or_key(account, "persona", None)
        tenant_kind = _attr_or_key(tenant, "kind", None)
        match_keys = {persona, tenant_kind}
        match_keys.discard(None)
        # any → 모두 통과
        # generic ('any', tenant_kind 자체) 만 가지고 있으면 인적 매칭 정보 부재로 soft pass
        if "any" in persona_required:
            pass
        elif match_keys & set(persona_required):
            pass  # 정확 매칭
        elif persona in (None, "any") and tenant_kind in tenant_scope:
            # 인적 persona 정보 없음 + tenant_scope 통과 → 도메인 호환 입증 → soft pass
            pass
        else:
            return False

    # role_min
    role_min = str(getattr(role, "role_min", "viewer") or "viewer")
    if role_min and role_min in _ROLE_RANKS:
        my_role = str(_attr_or_key(account, "role", "viewer") or "viewer")
        if _ROLE_RANKS.get(my_role, 0) < _ROLE_RANKS.get(role_min, 0):
            return False

    return True


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _format_available_skills(skills: list[SkillV2]) -> str:
    """LLM 이 읽기 좋은 plain-text 카탈로그로 직렬화."""
    if not skills:
        return "(등록된 스킬 없음)"
    blocks: list[str] = []
    for s in skills:
        triggers = "\n".join(f"    - {t}" for t in s.trigger_examples) or "    - (없음)"
        blocks.append(
            f"- name: {s.name}\n"
            f"  description: {s.description}\n"
            f"  trigger_examples:\n{triggers}"
        )
    return "\n".join(blocks)


async def select_skill(
    *,
    user_utterance: str,
    available_skills: list[SkillV2],
    llm_client: LLMClient,
    threshold: float = 0.5,
    account: Any = None,
    tenant: Any = None,
    out: dict[str, Any] | None = None,
) -> SkillV2 | None:
    """LLM 으로 적합 skill 선택. confidence < threshold 면 None.

    LLM 은 모든 skill 의 (name, description, trigger_examples) 를 본 뒤
    JSON ``{skill_name, confidence, reason}`` 한 객체를 반환한다.

    KMS-Plus: ``account`` 또는 ``tenant`` 가 주어지면 LLM 매칭 *전에*
    ``_scope_matches`` 로 1차 필터링. role.tenant_scope / persona_required /
    role_min 메타데이터로 후보 skill 목록을 좁힌다.

    fail-safe:
    - 빈 목록 → None
    - 1차 필터로 모두 탈락 → None (LLM 호출 X)
    - LLM 응답 파싱 실패 → None (로그)
    - skill_name 이 목록 밖 값 → None (할루시네이션 차단)
    - skill_name 이 빈 문자열 → None (LLM 이 '매칭 없음' 표시)
    """
    if not available_skills:
        return None
    if not user_utterance or not user_utterance.strip():
        return None

    # 1차 scope 필터 — account/tenant 정보가 주어졌을 때만 적용
    eligible: list[SkillV2]
    if account is not None or tenant is not None:
        eligible = [
            s for s in available_skills if _scope_matches(s, account=account, tenant=tenant)
        ]
        if not eligible:
            log.info(
                "auto_loader scope filter eliminated all skills",
                total=len(available_skills),
                account_persona=_attr_or_key(account, "persona"),
                account_role=_attr_or_key(account, "role"),
                tenant_kind=_attr_or_key(tenant, "kind"),
            )
            return None
    else:
        eligible = list(available_skills)

    system = _load_prompt()
    user = (
        f"[사용자 발화]\n{user_utterance.strip()}\n\n"
        f"[선택 가능한 스킬 목록]\n{_format_available_skills(eligible)}\n"
    )

    try:
        raw = await llm_client.complete(system, user, response_format="json_object")
    except Exception as e:  # noqa: BLE001  -- 외부 LLM 장애는 fallback
        log.error("auto_loader llm call failed", error=str(e))
        return None

    try:
        parsed = extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        log.error("auto_loader json parse failed", raw=raw[:200], error=str(e))
        return None

    if not isinstance(parsed, dict):
        log.error("auto_loader response not a dict", parsed=str(parsed)[:200])
        return None

    # PR-Q — out dict 가 주어지면 LLM 응답 전체를 거기 stash. 호출자가
    # needs_plan_orchestration / plan_orchestration_reason 등 추가 필드 read.
    if out is not None:
        try:
            out.update(parsed)
        except Exception:  # noqa: BLE001
            pass

    skill_name = str(parsed.get("skill_name", "") or "").strip()
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    if not skill_name:
        return None
    if confidence < threshold:
        log.info(
            "auto_loader below threshold",
            picked=skill_name,
            confidence=confidence,
            threshold=threshold,
        )
        return None

    by_name = {s.name: s for s in eligible}
    matched = by_name.get(skill_name)
    if matched is None:
        log.error(
            "auto_loader hallucinated skill_name",
            picked=skill_name,
            available=list(by_name.keys()),
        )
        return None
    return matched
