"""DraftComposer — 대화 맥락에서 skill YAML draft 를 LLM 으로 생성.

Task 34 (Scenario Extractor).

엔진의 ``_skill_draft_request`` sentinel 경로에서 호출된다. 사용자 대화와
최신 발화를 모아 LLM 에게 "표준 skill YAML" 을 JSON wrapper 로 내도록 시키고,
Skill pydantic 모델로 검증한다. 파싱 실패 시 에러를 LLM 에 피드백해서 한 번
더 시도 (retry-once). 두 번째 실패는 ``DraftError``.

Protocol 친화적: LLMClient / Renderer 를 주입받아 테스트에서 stub 가능.
Phase B / fine-tuned 모델 교체는 llm 주입만 바꾸면 됨.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError

from src.agent_framework.llm.json_parse import extract_json
from src.agent_framework.runtime.schema import Skill
from src.agent_framework.storage.skill_draft_store import SkillDraft
from src.common.logging import get_logger

log = get_logger(__name__)

# 기본 prompts 경로 — ResponseGenerator 와 동일 규칙.
_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "prompts"
_COMPOSE_TEMPLATE = "skill_draft_compose.md"

# LLM 이 참조할 수 있는 tool 목록 (등록되지 않은 tool 발명을 막기 위해 주입).
# dependencies.ToolRegistry 에 맞춰 수동 유지 — 새 tool 추가 시 이 리스트도 갱신.
# (정적 리스트로 두는 이유: runtime 에 ToolRegistry 를 주입하면 순환 import 위험.)
KNOWN_TOOLS: list[str] = [
    "schedule.create",
    "schedule.list",
    "schedule.delete",
    "diary.save",
    "diary.search",
    "reminder.schedule",
    "news.add_subscription",
    "news.remove_subscription",
    "news.list_subscriptions",
    "news.fetch_and_summarize",
    "news.list_recent_reports",
    "kms_rag.search",
    "calendar.check_availability",
    "calendar.book",
    "calendar.list_doctors",
    "calendar.list_available_slots",
]


class DraftError(Exception):
    """Draft 생성/검증 실패. 엔진이 잡아 안내 메시지로 fallback."""


class LLMClient(Protocol):
    """chat_completion_json 을 가진 최소 LLM 인터페이스."""

    async def chat_completion_json(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str: ...


def _slugify_id(candidate: str) -> str:
    """Skill meta.id 패턴 ``^[a-z][a-z0-9_]+$`` 에 맞게 정규화."""
    s = re.sub(r"[^a-z0-9_]+", "_", (candidate or "").lower()).strip("_")
    if not s or not s[0].isalpha():
        s = f"user_defined_{s}" if s else "user_defined_skill"
    return s[:60]


class DraftComposer:
    """대화에서 Skill YAML draft 를 생성해 ``SkillDraft`` 로 반환."""

    def __init__(
        self,
        llm_client: LLMClient,
        renderer: Any | None = None,
        *,
        prompts_dir: Path = _PROMPTS_DIR,
        known_tools: list[str] | None = None,
    ):
        self.llm = llm_client
        self.known_tools = known_tools if known_tools is not None else KNOWN_TOOLS
        # renderer 는 Jinja2 env — DI 가능하되 기본은 직접 구성.
        if renderer is None:
            self._env = Environment(
                loader=FileSystemLoader(prompts_dir),
                autoescape=select_autoescape(enabled_extensions=()),
            )
        else:
            self._env = renderer

    def _render_prompt(
        self,
        history: list[dict],
        user_message: str,
        *,
        previous_error: str | None = None,
    ) -> str:
        """compose prompt 를 Jinja2 로 렌더. retry 시 previous_error 주입."""
        tpl = self._env.get_template(_COMPOSE_TEMPLATE)
        # history 는 최근 10턴만 (prefill 비용 관리).
        recent = (history or [])[-10:]
        return tpl.render(
            history=recent,
            user_message=user_message,
            known_tools=self.known_tools,
            previous_error=previous_error,
        )

    async def _call_llm(self, prompt_text: str) -> dict[str, Any]:
        """LLM 호출 + JSON 파싱. 실패 시 DraftError 발생."""
        messages = [
            {"role": "system", "content": "너는 skill YAML 설계 도우미다."},
            {"role": "user", "content": prompt_text},
        ]
        try:
            raw = await self.llm.chat_completion_json(
                messages, temperature=0.2, max_tokens=1536
            )
        except Exception as e:  # pragma: no cover — 네트워크/가용성 오류
            raise DraftError(f"LLM call failed: {e}") from e
        try:
            data = extract_json(raw)
        except (json.JSONDecodeError, TypeError) as e:
            raise DraftError(f"LLM JSON parse failed: {e}; raw={raw[:200]!r}") from e
        if not isinstance(data, dict):
            raise DraftError(f"LLM returned non-object JSON: {type(data).__name__}")
        return data

    def _validate_and_normalize(self, data: dict[str, Any]) -> SkillDraft:
        """LLM output → Skill pydantic 검증 → SkillDraft 반환.

        title/yaml/rationale 누락, YAML 파싱 실패, Skill 스키마 위반 모두 DraftError.
        id 는 필요 시 slugify 보정해서 다시 덤프.
        """
        title = (data.get("title") or "").strip()
        yaml_text = (data.get("yaml") or "").strip()
        rationale = (data.get("rationale") or "").strip() or None
        if not title or not yaml_text:
            raise DraftError("LLM output missing title or yaml")

        try:
            raw = yaml.safe_load(yaml_text)
        except yaml.YAMLError as e:
            raise DraftError(f"YAML parse failed: {e}") from e
        if not isinstance(raw, dict):
            raise DraftError("YAML root must be a mapping")

        # id 정규화 — pydantic 의 ^[a-z][a-z0-9_]+$ 를 만족시키기 위한 방어선.
        meta = raw.get("skill") or {}
        if isinstance(meta, dict) and meta.get("id"):
            meta["id"] = _slugify_id(str(meta["id"]))
            raw["skill"] = meta
            # LLM 이 이미 정상 id 를 줬으면 _slugify 는 idempotent 라 무해.
            yaml_text = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)

        try:
            Skill.model_validate(raw)
        except ValidationError as e:
            raise DraftError(f"Skill schema validation failed: {e}") from e

        return SkillDraft(title=title, yaml_text=yaml_text, rationale=rationale)

    async def compose(
        self,
        history: list[dict],
        user_message: str,
        *,
        account_id: UUID,
        tenant_id: UUID,
    ) -> SkillDraft:
        """대화 → Skill YAML draft. retry-once on validation failure.

        account_id / tenant_id 는 현재 본 composer 에서 직접 쓰지 않지만
        (감사 로그 / tenant 별 customization 지점) 시그니처로 남겨 둔다.
        """
        _ = account_id, tenant_id  # future-proofing; keep in signature

        prompt = self._render_prompt(history, user_message)
        try:
            data = await self._call_llm(prompt)
            return self._validate_and_normalize(data)
        except DraftError as first_err:
            log.warning(
                "skill_draft_first_attempt_failed", error=str(first_err)
            )
            # retry once with error feedback
            retry_prompt = self._render_prompt(
                history,
                user_message,
                previous_error=str(first_err),
            )
            try:
                data = await self._call_llm(retry_prompt)
                return self._validate_and_normalize(data)
            except DraftError as second_err:
                log.warning(
                    "skill_draft_retry_failed",
                    first_error=str(first_err),
                    second_error=str(second_err),
                )
                raise DraftError(
                    f"YAML invalid after retry: {second_err}"
                ) from second_err
