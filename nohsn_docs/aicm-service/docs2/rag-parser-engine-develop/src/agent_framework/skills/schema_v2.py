"""SkillV2 — Phase 8.5 Skill = Pipeline Starter Schema.

사람 신입 상담사 교육 패턴(SOP·매뉴얼·톤·금기·인계·사례) 6 차원으로 skill 을 표현.

기존 v1 (``src.agent_framework.runtime.schema.Skill``) 과 별개의 dataclass 기반 모델.
v1 loader 는 신규 필드(``role``, ``few_shot_examples``, ``delegate_when``, ``process``)를
읽지 않으므로 하위 호환은 자동으로 유지된다 (v1 yaml 은 SkillV2 로딩에서도 무시됨).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


@dataclass
class SkillRole:
    """상담사 페르소나 — system prompt 합성에 직접 사용.

    추가 필드 (계정 분리 / scope 매칭):
    - ``tenant_scope``: 어떤 tenant 종류에서 활성. 예: ``["personal"]``,
      ``["kb_callcenter", "hospital"]``, ``["*"]`` (제약 없음).
    - ``persona_required``: 어떤 페르소나만. 예: ``["doctor"]``,
      ``["any"]`` (제약 없음).
    - ``role_min``: 최소 권한. ``viewer`` < ``member`` < ``admin`` < ``owner``.

    빈 리스트/기본값 = 제약 없음 (하위 호환). auto_loader 의 ``_scope_matches``
    가 1차 필터로 사용한다.
    """

    persona: str
    tone: str
    knowledge_scope: list[str] = field(default_factory=list)
    safety_constraints: list[str] = field(default_factory=list)
    tenant_scope: list[str] = field(default_factory=list)
    persona_required: list[str] = field(default_factory=list)
    role_min: str = "viewer"


@dataclass
class SkillProcessStep:
    """프로세스 단일 step. ``kind`` 종류:

    - ``elicit``: slot fill (LLM 추출 + 부족 시 재질문)
    - ``run``: tool 호출 (engine.tool_loop 위임)
    - ``render``: LLM 답변 생성 (template + slot 값)
    - ``approve_request``: 사용자 yes/no 분기
    - ``notify``: 단순 결과 메시지
    - ``delegate``: 다른 skill 로 인계
    """

    kind: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillProcess:
    steps: list[SkillProcessStep] = field(default_factory=list)


@dataclass
class FewShotTurn:
    """role: 'customer' 또는 'counselor' 등 자유문자열."""

    role: str
    text: str


@dataclass
class FewShotExample:
    source: str | None = None
    turns: list[FewShotTurn] = field(default_factory=list)


@dataclass
class DelegateRule:
    """자연어 condition. LLM 평가용. 코드의 if/regex 분기 금지."""

    condition: str
    to: str


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


@dataclass
class SkillV2:
    name: str
    description: str
    side_effect_level: str = "read_only"
    """``read_only`` / ``write_external`` / ``irreversible`` — 사용자 컨펌 정책 결정에 사용."""

    consequential: bool = False
    role: SkillRole | None = None
    trigger_examples: list[str] = field(default_factory=list)
    few_shot_examples: list[FewShotExample] = field(default_factory=list)
    delegate_when: list[DelegateRule] = field(default_factory=list)
    process: SkillProcess | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    retrieval: str = "kms"
    """KMS RAG retrieval 정책. 페르소나 답변 분기 + chat_v1 citations 빌드 게이트.

    - ``none``: 검색 없이 페르소나만으로 응대 (일정/캘린더/대화-비검색 도메인).
    - ``kms``: KMS 검색을 수행 (기본값 — 회귀 안전).
    - ``tool``: tool 호출이 검색을 대체 (외부 API/ DB 조회로 사실 확보).

    PR-A — ❼ 일정 도메인에 KMS citations 강제 첨부 차단을 위한 메타 한 키.
    사례 yaml 추가 금지 — 메타로 일반화 (feedback_pattern_core_not_case).
    """


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


class SkillV2LoadError(Exception):
    """yaml 로딩/파싱 실패 시 raise."""


def _coerce_role(raw: Any) -> SkillRole | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SkillV2LoadError(f"role must be mapping, got {type(raw).__name__}")
    return SkillRole(
        persona=str(raw.get("persona", "")),
        tone=str(raw.get("tone", "")),
        knowledge_scope=list(raw.get("knowledge_scope", []) or []),
        safety_constraints=list(raw.get("safety_constraints", []) or []),
        tenant_scope=list(raw.get("tenant_scope", []) or []),
        persona_required=list(raw.get("persona_required", []) or []),
        role_min=str(raw.get("role_min", "viewer") or "viewer"),
    )


def _coerce_few_shot(raw: Any) -> list[FewShotExample]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise SkillV2LoadError("few_shot_examples must be a list")
    out: list[FewShotExample] = []
    for ex in raw:
        if not isinstance(ex, dict):
            raise SkillV2LoadError("few_shot example must be a mapping")
        turns_raw = ex.get("turns") or []
        if not isinstance(turns_raw, list):
            raise SkillV2LoadError("few_shot turns must be a list")
        turns = [
            FewShotTurn(role=str(t.get("role", "")), text=str(t.get("text", "")))
            for t in turns_raw
            if isinstance(t, dict)
        ]
        out.append(FewShotExample(source=ex.get("source"), turns=turns))
    return out


def _coerce_delegate(raw: Any) -> list[DelegateRule]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise SkillV2LoadError("delegate_when must be a list")
    out: list[DelegateRule] = []
    for r in raw:
        if not isinstance(r, dict):
            raise SkillV2LoadError("delegate rule must be mapping")
        if "condition" not in r or "to" not in r:
            raise SkillV2LoadError("delegate rule needs `condition` and `to`")
        out.append(DelegateRule(condition=str(r["condition"]), to=str(r["to"])))
    return out


def _coerce_process(raw: Any) -> SkillProcess | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SkillV2LoadError("process must be mapping")
    steps_raw = raw.get("steps") or []
    if not isinstance(steps_raw, list):
        raise SkillV2LoadError("process.steps must be a list")
    steps: list[SkillProcessStep] = []
    for s in steps_raw:
        if not isinstance(s, dict):
            raise SkillV2LoadError("process step must be a mapping")
        kind = s.get("kind")
        if not kind:
            raise SkillV2LoadError("process step missing `kind`")
        steps.append(SkillProcessStep(kind=str(kind), config=dict(s.get("config") or {})))
    return SkillProcess(steps=steps)


def from_dict(raw: dict[str, Any]) -> SkillV2:
    """dict → SkillV2 변환. 필수 필드 미존재 시 SkillV2LoadError."""
    if not isinstance(raw, dict):
        raise SkillV2LoadError(f"skill yaml root must be mapping, got {type(raw).__name__}")
    if "name" not in raw or "description" not in raw:
        raise SkillV2LoadError("skill yaml requires `name` and `description`")
    side_effect_level = str(raw.get("side_effect_level", "read_only"))
    if side_effect_level not in {"read_only", "write_external", "irreversible"}:
        raise SkillV2LoadError(
            f"side_effect_level must be one of read_only/write_external/irreversible, "
            f"got {side_effect_level!r}"
        )
    retrieval = str(raw.get("retrieval", "kms"))
    if retrieval not in {"none", "kms", "tool"}:
        raise SkillV2LoadError(
            f"retrieval must be one of none/kms/tool, got {retrieval!r}"
        )
    return SkillV2(
        name=str(raw["name"]),
        description=str(raw["description"]),
        side_effect_level=side_effect_level,
        consequential=bool(raw.get("consequential", False)),
        role=_coerce_role(raw.get("role")),
        trigger_examples=list(raw.get("trigger_examples", []) or []),
        few_shot_examples=_coerce_few_shot(raw.get("few_shot_examples")),
        delegate_when=_coerce_delegate(raw.get("delegate_when")),
        process=_coerce_process(raw.get("process")),
        tools=list(raw.get("tools", []) or []),
        retrieval=retrieval,
    )


def load_skill_v2(path: Path) -> SkillV2:
    """yaml 파일 → SkillV2."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise SkillV2LoadError(f"skill v2 file not found: {path}") from e
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SkillV2LoadError(f"invalid YAML at {path}: {e}") from e
    return from_dict(raw or {})


def load_all_v2(dir_path: Path) -> dict[str, SkillV2]:
    """디렉토리 안 *.yaml 전부 SkillV2 로 로드. 실패 파일은 skip 후 로그."""
    from src.common.logging import get_logger

    log = get_logger(__name__)
    out: dict[str, SkillV2] = {}
    if not dir_path.exists():
        return out
    for yaml_file in sorted(dir_path.glob("*.yaml")):
        try:
            skill = load_skill_v2(yaml_file)
            out[skill.name] = skill
        except SkillV2LoadError as e:
            log.error("skill_v2 load failed", path=str(yaml_file), error=str(e))
    return out
