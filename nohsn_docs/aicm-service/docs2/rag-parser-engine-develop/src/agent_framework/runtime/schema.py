"""Skill YAML 스키마 — 설계 문서 섹션 2 의 pydantic 정의.

v1.1 (Task 32) 변경:
- SlotDef.must_be_specific — 모호한 값 (예: "내일 저녁") 을 "미충족" 으로 처리
- SlotDef.validators — 이름 기반 명시적 validator 참조 (time_of_day_required, future_only, ...)
- SkillAvailability.business_type — 자유문자열 → Enum 제약
- SKILL_SCHEMA_CURRENT_VERSION — 새 스킬의 기본값
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SlotType = Literal["text", "date", "datetime", "phone", "enum", "rrule", "email", "number"]

BusinessType = Literal[
    "general",
    "medical",
    "finance",
    "retail",
    "manufacturing",
    "legal",
    "education",
    "public",
]
"""Task 32 — SkillAvailability.business_type 허용 값."""


SKILL_SCHEMA_CURRENT_VERSION = "1.1"
"""Task 32 — 새로운 skill YAML 이 명시해야 할 스키마 버전.

기존 0.1 / 0.3 등 과거 버전 YAML 은 그대로 로드된다 (pydantic 은 version 문자열을 검증하지 않음).
새 스킬을 작성할 때만 이 상수를 참조한다.
"""


class SkillMeta(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    version: str
    domain: str
    description: str


class Trigger(BaseModel):
    intent: str


class SlotDef(BaseModel):
    name: str
    type: SlotType
    required: bool = False
    values: list[str] | None = None
    values_from: str | None = None
    source: Literal["identity", "user"] | None = None
    # v1.1 (Task 32)
    must_be_specific: bool = False
    """True 일 때 모호한 값(예: HH:MM 없는 "내일 저녁")을 "미충족" 으로 간주."""
    validators: list[str] = Field(default_factory=list)
    """이름 기반 validator 목록. runtime.validators 에 정의된 함수 이름을 참조."""


class OnEnter(BaseModel):
    llm_respond: dict[str, Any] | None = None
    push_to: str | None = None


class OnExit(BaseModel):
    llm_respond: dict[str, Any] | None = None


class Transition(BaseModel):
    when: str | None = None
    to: str | None = None
    llm_fallback: bool = False

    @model_validator(mode="after")
    def _one_of(self):
        if not self.to and not self.llm_fallback:
            raise ValueError("transition must have `to` or `llm_fallback: true`")
        return self


class StateDef(BaseModel):
    id: str
    on_enter: OnEnter | None = None
    on_exit: OnExit | None = None
    llm_slot_fill: list[str] = Field(default_factory=list)
    tool: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    transitions: list[Transition] = Field(default_factory=list)


class Guardrails(BaseModel):
    pre_llm: list[str] = Field(default_factory=list)
    post_llm: list[str] = Field(default_factory=list)


class SkillAvailability(BaseModel):
    """스킬 활성화 범위 메타데이터 (optional).

    None 또는 필드 일부 생략 시 기본: scope=all, visibility=auto.

    - scope: 어떤 tenant_type 에 노출 가능한가
        - all: 개인/비즈니스 양쪽
        - personal: 개인 tenant 전용
        - business_only: 비즈니스 tenant 전용 (병원/매장 등)
    - business_type: business_only 일 때 추가 필터 (예: "medical", "retail")
    - visibility:
        - auto: 해당 scope 의 tenant 가 만들어지면 자동으로 enable
        - opt-in: 관리자가 명시적으로 enable 해야 활성
    """
    scope: Literal["all", "personal", "business_only"] = "all"
    business_type: BusinessType | None = None
    visibility: Literal["auto", "opt-in"] = "auto"


class Skill(BaseModel):
    meta: SkillMeta = Field(alias="skill")
    triggers: list[Trigger]
    trigger_type: Literal["intent", "scheduled"] = "intent"
    schedule: str | None = None  # cron, scheduled trigger 일 때
    slots: list[SlotDef] = Field(default_factory=list)
    initial_state: str
    states: list[StateDef]
    guardrails: Guardrails = Field(default_factory=Guardrails)
    tenant_config_schema: dict[str, Any] = Field(default_factory=dict)
    availability: SkillAvailability = Field(default_factory=SkillAvailability)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _initial_state_exists(self):
        ids = {s.id for s in self.states}
        if self.initial_state not in ids:
            raise ValueError(f"initial_state '{self.initial_state}' not in states")
        return self
