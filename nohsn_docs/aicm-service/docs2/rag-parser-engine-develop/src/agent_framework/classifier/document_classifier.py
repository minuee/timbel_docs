"""문서 자동 분류기 — Stage B-Core-4 (KMS-Plus).

**원칙** (user 피드백):
    "코드 처리보다는 전용화된 정밀 prompt 로 빠르게 LLM 판단을 하고
     그 뒤에 API/코드를 붙여서 빠른 처리를 노리는 것이 좋아보여."

이 모듈은 **message-generation 인접 계층**이다. 파이프라인 composition 은
``src/pipeline/workers/classify_worker.py`` 가 담당하고, 본 모듈은 순수하게
`(title, text_sample, hints) -> JSON dict` 변환만 한다.

Future: fine-tuned 소형 모델로 교체하고 싶으면 ``DocumentClassifier`` 의
``classify`` 시그니처만 유지하면 one-file swap 가능.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.agent_framework.llm.json_parse import extract_json
from src.common.logging import get_logger

log = get_logger(__name__)


_PROMPTS_DIR = (
    Path(__file__).resolve().parents[1] / "skills" / "prompts"
)
_PROMPT_TEMPLATE = "document_auto_classify.md"

# 스키마 기본값 — LLM 실패/malformed 시 fallback.
_FALLBACK: dict[str, Any] = {
    "category_guess": "",
    "domain": "general",
    "tags": [],
    "suggested_repository_name": "",
    "suggested_document_type": "other",
    "confidence": 0.0,
    "rationale": "LLM 실패로 분류 생략",
}

_ALLOWED_DOMAINS = {
    "finance",
    "medical",
    "manufacturing",
    "software",
    "legal",
    "education",
    "hr",
    "sales",
    "customer_support",
    "general",
}

_ALLOWED_DOC_TYPES = {
    "manual",
    "contract",
    "report",
    "policy",
    "faq",
    "specification",
    "presentation",
    "email",
    "other",
}


class _JsonLLM(Protocol):
    """LLM 어댑터 프로토콜 — ``chat_completion_json`` 한 개만 필요."""

    async def chat_completion_json(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str: ...


class DocumentClassifier:
    """LLM 프롬프트 1회로 문서 auto-classification 메타를 만든다.

    :param llm_client: ``chat_completion_json`` 을 제공하는 LLM 어댑터.
        프로덕션에서는 ``VLLMAdapter`` (json_object mode) 를 넣는다.
    :param prompts_dir: 프롬프트 템플릿 디렉토리. 테스트에서 override 가능.
    :param timeout_s: LLM 호출 timeout (초). 초과 시 fallback.
    """

    def __init__(
        self,
        llm_client: _JsonLLM,
        *,
        prompts_dir: Path | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        self._llm = llm_client
        self._timeout_s = timeout_s
        self._env = Environment(
            loader=FileSystemLoader(prompts_dir or _PROMPTS_DIR),
            autoescape=select_autoescape(enabled_extensions=()),
        )

    async def classify(
        self,
        title: str,
        text_sample: str,
        hints: dict | None = None,
    ) -> dict:
        """문서를 분류하고 스키마에 맞는 dict 를 반환한다.

        항상 7개 키가 있는 dict 를 반환한다 (실패 시 fallback).

        :param title: 문서 제목.
        :param text_sample: 파싱된 본문 앞부분 (~3000자).  호출자가 자른다.
        :param hints: 선택적 힌트. ``{"rule_based_domain": str}`` 형태.
        """
        prompt = self._render_prompt(title, text_sample, hints or {})
        messages = [
            {
                "role": "system",
                "content": (
                    "문서 자동 분류 전문가. JSON 한 덩어리만 출력. "
                    "마크다운 코드 펜스, 설명 문장 금지."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        try:
            raw = await asyncio.wait_for(
                self._llm.chat_completion_json(
                    messages,
                    temperature=0.1,
                    max_tokens=500,
                ),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            log.warning(
                "document_classifier_timeout",
                title=title[:80],
                timeout_s=self._timeout_s,
            )
            return dict(_FALLBACK, rationale="LLM 타임아웃으로 분류 생략")
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "document_classifier_llm_error",
                title=title[:80],
                error=str(exc),
            )
            return dict(_FALLBACK)

        try:
            parsed = extract_json(raw)
            if not isinstance(parsed, dict):
                raise ValueError(f"expected JSON object, got {type(parsed).__name__}")
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "document_classifier_parse_failed",
                title=title[:80],
                error=str(exc),
                raw_preview=raw[:200] if isinstance(raw, str) else "",
            )
            return dict(_FALLBACK, rationale="LLM 출력 파싱 실패로 분류 생략")

        return _normalize(parsed)

    # ------------------------------------------------------------------ internals

    def _render_prompt(
        self, title: str, text_sample: str, hints: dict
    ) -> str:
        tpl = self._env.get_template(_PROMPT_TEMPLATE)
        return tpl.render(
            title=title or "(제목 없음)",
            text_sample=text_sample or "(본문 비어있음)",
            hint_domain=hints.get("rule_based_domain") or "(힌트 없음)",
        )


def _normalize(raw: dict) -> dict:
    """LLM 출력을 스키마에 맞게 정규화.

    - 누락 키 → fallback 값.
    - tags 가 str 이면 split.
    - domain / suggested_document_type 은 enum 벗어나면 fallback 값으로 보정.
    - confidence 는 [0, 1] clamp.
    """
    out = dict(_FALLBACK)

    # Strings
    for key in (
        "category_guess",
        "suggested_repository_name",
        "rationale",
    ):
        val = raw.get(key)
        if isinstance(val, str):
            out[key] = val.strip()

    # domain enum
    domain = raw.get("domain")
    if isinstance(domain, str) and domain.strip().lower() in _ALLOWED_DOMAINS:
        out["domain"] = domain.strip().lower()
    else:
        out["domain"] = "general"

    # document_type enum
    doctype = raw.get("suggested_document_type")
    if (
        isinstance(doctype, str)
        and doctype.strip().lower() in _ALLOWED_DOC_TYPES
    ):
        out["suggested_document_type"] = doctype.strip().lower()
    else:
        out["suggested_document_type"] = "other"

    # tags → list[str]
    tags = raw.get("tags")
    if isinstance(tags, list):
        out["tags"] = [str(t).strip() for t in tags if str(t).strip()][:5]
    elif isinstance(tags, str):
        parts = [p.strip() for p in tags.replace(",", " ").split() if p.strip()]
        out["tags"] = parts[:5]
    else:
        out["tags"] = []

    # confidence [0, 1]
    conf = raw.get("confidence")
    try:
        c = float(conf)
        if c < 0.0:
            c = 0.0
        elif c > 1.0:
            c = 1.0
        out["confidence"] = c
    except (TypeError, ValueError):
        out["confidence"] = 0.0

    return out
