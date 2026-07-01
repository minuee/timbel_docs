"""Skills Catalog endpoint — admin 의 커스텀 도구 관리 UI 가 사용.

스킬은 *도구 셋 + 페르소나 packaged*. 자체 도구·커스텀 웹훅 카드와 동일 UI 에서
일관 관리할 수 있도록 read-only 메타데이터 (yaml 파일 직접 read) 노출.

read 대상: ``src/agent_framework/skills/yaml/*.yaml`` (v2 format).
- name / description / role.persona / role.knowledge_scope / role.tenant_scope
- trigger_examples (도메인 keyword 추정용)
- tools (list[str] | list[{name, internal}]) → 정규화된 list[str]

캐싱: 인메모리 60초 TTL. 운영 중 yaml 핫리로드는 거의 없음.

별도 DB X — yaml 가 곧 source of truth. 응답에 raw 파일 경로/auth_headers 등 절대
노출하지 않음 (스킬 정의는 read-only public metadata).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter
from pydantic import BaseModel

from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/skills-catalog", tags=["skills-catalog"])


# yaml 디렉터리 — auto_loader 가 사용하는 v2 format 위치와 동일.
_SKILLS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "agent_framework"
    / "skills"
    / "yaml"
)

# 캐시 — 60초 TTL. 운영 중 skill yaml 변경은 deploy 단위라 60s 충분.
_CACHE_TTL = 60.0
_cache: dict[str, Any] = {"ts": 0.0, "items": []}


class SkillCatalogItem(BaseModel):
    id: str
    name: str
    description: str
    persona: str
    system_prompt: str  # role.persona + tone + safety_constraints 합성
    category: str
    allowed_tools: list[str]
    tool_count: int
    is_legacy: bool  # 폐기 단계 표시 (true = 신규 RAG-driven 으로 대체 권장)
    version: str
    domain_keywords: list[str]
    tenant_scope: list[str]
    persona_required: list[str]
    trigger_examples: list[str]


class SkillCatalogResponse(BaseModel):
    items: list[SkillCatalogItem]


def _normalize_tools(raw: Any) -> list[str]:
    """tools 필드 정규화 — list[str] 또는 list[{name, internal}] 모두 list[str] 로."""
    if not raw:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item.strip())
        elif isinstance(item, dict):
            n = item.get("name")
            if isinstance(n, str) and n.strip():
                out.append(n.strip())
    return out


def _infer_category(name: str, role: dict[str, Any] | None) -> str:
    """skill name + role.knowledge_scope 첫 항목으로 카테고리 추정.

    rule/하드코딩 분류 X — yaml 메타데이터 (knowledge_scope, persona_required) 가
    이미 도메인 분류를 담고 있으므로 그것을 그대로 사용. 후속 PR 에서 yaml 에
    explicit ``category`` 필드 추가 시 우선순위로 read.
    """
    if isinstance(role, dict):
        ks = role.get("knowledge_scope") or []
        if isinstance(ks, list) and ks:
            first = ks[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
        # tenant_scope 가 personal 만이면 "개인", 그 외는 첫 scope.
        ts = role.get("tenant_scope") or []
        if isinstance(ts, list) and ts:
            first_ts = ts[0]
            if isinstance(first_ts, str) and first_ts.strip() and first_ts != "*":
                return first_ts.strip()
    # fallback — name prefix
    if "_" in name:
        return name.split("_", 1)[0]
    return "기타"


def _build_system_prompt(role: dict[str, Any] | None, description: str) -> str:
    """role + description 으로 system_prompt 합성. yaml 에 explicit system_prompt 가
    있으면 그것을 우선. 없으면 persona/tone/safety 결합."""
    if not isinstance(role, dict):
        return description.strip()

    parts: list[str] = []
    persona = str(role.get("persona") or "").strip()
    tone = str(role.get("tone") or "").strip()
    safety = role.get("safety_constraints") or []

    if persona:
        parts.append(persona)
    if tone:
        parts.append(f"말투: {tone}")
    if isinstance(safety, list) and safety:
        bullets = "\n".join(f"- {s}" for s in safety if isinstance(s, str))
        if bullets:
            parts.append("제약:\n" + bullets)
    if description:
        parts.append("설명: " + description.strip())
    return "\n\n".join(parts)


def _is_legacy(data: dict[str, Any]) -> bool:
    """legacy 판정 — yaml 에 explicit ``deprecated: true`` 가 있거나, side_effect_level
    이 read_only 에 retrieval 도 미정 (= 단순 KB 검색 wrapper) 인 경우.

    현재 모든 v2 yaml skill 은 RAG-driven 아키텍처로 점진적 대체 예정 (handoff
    20260506 v6 spec). UI 에서 단계적 폐기 명시를 위해 ``is_legacy=True`` 기본.
    """
    if data.get("deprecated") is True:
        return True
    # 점진적 폐기 — 모든 skill yaml 은 legacy 로 표시. 신규 패턴은 RAG-driven.
    return True


def _extract_skill(path: Path) -> SkillCatalogItem | None:
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except Exception as e:  # noqa: BLE001
        log.warning("skills_catalog yaml parse failed", path=str(path), error=str(e))
        return None

    if not isinstance(data, dict):
        return None

    name = str(data.get("name") or path.stem).strip()
    description = str(data.get("description") or "").strip()
    role = data.get("role") if isinstance(data.get("role"), dict) else None
    persona = ""
    if isinstance(role, dict):
        persona = str(role.get("persona") or "").strip()

    tools = _normalize_tools(data.get("tools"))
    triggers = data.get("trigger_examples") or []
    triggers = [str(t).strip() for t in triggers if isinstance(t, str) and t.strip()]

    # domain_keywords — knowledge_scope + name 토큰
    domain_keywords: list[str] = []
    if isinstance(role, dict):
        ks = role.get("knowledge_scope") or []
        if isinstance(ks, list):
            for k in ks:
                if isinstance(k, str) and k.strip():
                    domain_keywords.append(k.strip())
    # name 의 _ 토큰도 keyword 로 (e.g. "schedule_personal" → ["schedule", "personal"])
    for tok in name.split("_"):
        tok = tok.strip()
        if tok and tok not in domain_keywords:
            domain_keywords.append(tok)

    tenant_scope: list[str] = []
    persona_required: list[str] = []
    if isinstance(role, dict):
        ts = role.get("tenant_scope") or []
        if isinstance(ts, list):
            tenant_scope = [str(s) for s in ts if isinstance(s, str)]
        pr = role.get("persona_required") or []
        if isinstance(pr, list):
            persona_required = [str(s) for s in pr if isinstance(s, str)]

    version = str(data.get("version") or "1.0")
    category = _infer_category(name, role)
    system_prompt = _build_system_prompt(role, description)
    legacy = _is_legacy(data)

    return SkillCatalogItem(
        id=name,
        name=name,
        description=description,
        persona=persona,
        system_prompt=system_prompt,
        category=category,
        allowed_tools=tools,
        tool_count=len(tools),
        is_legacy=legacy,
        version=version,
        domain_keywords=domain_keywords,
        tenant_scope=tenant_scope,
        persona_required=persona_required,
        trigger_examples=triggers[:8],  # UI 표시용 제한
    )


def _load_catalog() -> list[SkillCatalogItem]:
    """yaml 디렉터리 read → SkillCatalogItem 리스트. 60s 캐시."""
    now = time.time()
    if _cache["items"] and (now - float(_cache["ts"])) < _CACHE_TTL:
        return _cache["items"]  # type: ignore[return-value]

    if not _SKILLS_DIR.exists():
        log.warning("skills_catalog dir missing", path=str(_SKILLS_DIR))
        _cache["items"] = []
        _cache["ts"] = now
        return []

    items: list[SkillCatalogItem] = []
    for path in sorted(_SKILLS_DIR.glob("*.yaml")):
        item = _extract_skill(path)
        if item is not None:
            items.append(item)

    _cache["items"] = items
    _cache["ts"] = now
    return items


@router.get("", response_model=SkillCatalogResponse)
async def list_skills_catalog() -> SkillCatalogResponse:
    """등록된 skill yaml 의 read-only 메타데이터 카탈로그.

    UI 카드 grid 에서 표시 — 도구 수 / 카테고리 / persona / legacy 표식.
    """
    items = _load_catalog()
    return SkillCatalogResponse(items=items)
