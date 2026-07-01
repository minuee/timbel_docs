"""Synonym normalizer — 동일 의미 변형 표기 정규화 (LLM 기반).

rule/키워드 리스트 X. LLM 이 도메인별 동의어·약어·변형을 자동 검출.

P0 검색 품질 업그레이드의 일환:
- 검색 쿼리 확장 ("T+3" → ["결제일", "정산일", "D+2"])
- 두 문서 사이 표기 충돌 감지 ("T+3" vs "T+2" → conflict)

LLM 호출 비용 방어 — in-process LRU 캐시 (영속 X). 영속이 필요하면
Redis 로 확장 가능하나 본 모듈은 단순 stub.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.common.logging import get_logger

log = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_NORMALIZE_PROMPT = _PROMPTS_DIR / "synonym_normalize.txt"
_CONFLICT_PROMPT = _PROMPTS_DIR / "synonym_conflict.txt"


@dataclass(frozen=True)
class SynonymResult:
    """동의어 정규화 결과."""

    canonical: str
    variants: tuple[str, ...]
    domain: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical": self.canonical,
            "variants": list(self.variants),
            "domain": self.domain,
        }


@dataclass(frozen=True)
class ConflictReport:
    """두 문서 사이 동의어 충돌 보고."""

    has_conflict: bool
    conflicts: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_conflict": self.has_conflict,
            "conflicts": [dict(c) for c in self.conflicts],
        }


class SynonymNormalizer:
    """LLM 으로 query 동의어를 정규화하고 검색 확장 keyword 를 반환.

    rule/regex 절대 사용 X — 모든 판단을 LLM 에 위임. 변형 표기/약어/도메인
    추론은 prompt 한 곳에서 일반화.
    """

    def __init__(self, llm_client, cache_size: int = 1000):
        self.llm = llm_client
        self._cache: OrderedDict[tuple[str, str | None], SynonymResult] = OrderedDict()
        self._cache_size = cache_size
        self._normalize_template = _NORMALIZE_PROMPT.read_text(encoding="utf-8")
        self._conflict_template = _CONFLICT_PROMPT.read_text(encoding="utf-8")

    async def normalize(
        self, *, query: str, domain_hint: str | None = None
    ) -> SynonymResult:
        """query 의 동의어·변형을 정규화 + 검색 확장 키워드 반환.

        Returns:
            SynonymResult (canonical / variants / domain).

        Notes:
            실패 시 fallback 으로 query 자체를 canonical 로, variants 빈 결과.
        """
        if not query or not query.strip():
            return SynonymResult(canonical="", variants=(), domain="general")

        key = (query.strip(), domain_hint)
        if key in self._cache:
            # LRU touch
            self._cache.move_to_end(key)
            return self._cache[key]

        prompt = self._normalize_template.replace("{query}", query).replace(
            "{domain_hint}", domain_hint or "(없음)"
        )

        try:
            raw = await self._call_llm(prompt)
            result = self._parse_normalize(raw, fallback_query=query)
        except Exception as exc:  # noqa: BLE001
            log.warning("synonym_llm_failed", error=str(exc), query=query[:80])
            result = SynonymResult(canonical=query, variants=(), domain="general")

        # LRU 캐시 삽입
        self._cache[key] = result
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return result

    async def detect_conflicts(
        self, *, doc_a_text: str, doc_b_text: str
    ) -> ConflictReport:
        """두 문서 사이 동의어 표기 충돌 감지.

        예: doc_a 는 'T+3', doc_b 는 'T+2' → conflict (영업일 수 불일치).
        """
        if not doc_a_text or not doc_b_text:
            return ConflictReport(has_conflict=False, conflicts=())

        prompt = self._conflict_template.replace("{doc_a_text}", doc_a_text).replace(
            "{doc_b_text}", doc_b_text
        )
        try:
            raw = await self._call_llm(prompt)
            return self._parse_conflict(raw)
        except Exception as exc:  # noqa: BLE001
            log.warning("synonym_conflict_llm_failed", error=str(exc))
            return ConflictReport(has_conflict=False, conflicts=())

    # ─── 내부 ──────────────────────────────────────────────────────

    async def _call_llm(self, prompt: str) -> str:
        import inspect
        if callable(self.llm):
            try:
                maybe = self.llm(prompt)
                if inspect.isawaitable(maybe):
                    direct = await maybe
                    if isinstance(direct, str):
                        return direct
                    t = getattr(direct, "text", None)
                    if isinstance(t, str):
                        return t
            except (TypeError, AttributeError):
                pass
        gen = getattr(self.llm, "generate", None)
        if gen is None or not callable(gen):
            raise RuntimeError("llm_client has no usable generate() method")
        try:
            result = await gen(prompt)  # type: ignore[misc]
        except TypeError:
            from src.common.llm.base import LLMRequest

            result = await gen(
                LLMRequest(prompt=prompt, response_format="json", max_tokens=800)
            )
        if isinstance(result, str):
            return result
        text = getattr(result, "text", None)
        if text is None:
            raise RuntimeError("LLM response missing .text attribute")
        return text

    def _parse_normalize(self, raw: str, *, fallback_query: str) -> SynonymResult:
        cleaned = _strip_json_envelope(raw)
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("synonym_normalize_decode_failed", preview=cleaned[:120])
            return SynonymResult(canonical=fallback_query, variants=(), domain="general")

        canonical = (obj.get("canonical") or fallback_query).strip()
        variants_raw = obj.get("variants", [])
        if not isinstance(variants_raw, list):
            variants_raw = []
        variants = tuple(
            str(v).strip()
            for v in variants_raw
            if v and str(v).strip() and str(v).strip() != canonical
        )
        domain = (obj.get("domain") or "general").strip() or "general"
        return SynonymResult(canonical=canonical, variants=variants, domain=domain)

    def _parse_conflict(self, raw: str) -> ConflictReport:
        cleaned = _strip_json_envelope(raw)
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("synonym_conflict_decode_failed", preview=cleaned[:120])
            return ConflictReport(has_conflict=False, conflicts=())

        has_conflict = bool(obj.get("has_conflict", False))
        conflicts_raw = obj.get("conflicts", [])
        if not isinstance(conflicts_raw, list):
            conflicts_raw = []
        conflicts: list[dict[str, str]] = []
        for c in conflicts_raw:
            if not isinstance(c, dict):
                continue
            entry = {
                "term_a": str(c.get("term_a", "")).strip(),
                "term_b": str(c.get("term_b", "")).strip(),
                "reason": str(c.get("reason", "")).strip(),
            }
            if entry["term_a"] and entry["term_b"]:
                conflicts.append(entry)
        return ConflictReport(has_conflict=has_conflict, conflicts=tuple(conflicts))


def _strip_json_envelope(raw: str) -> str:
    """```json ...``` 펜스나 잡음 제거. 첫 '{' ~ 마지막 '}' 슬라이스."""
    s = (raw or "").strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.endswith("```"):
            s = s[: -3]
        s = s.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return s
    return s[start : end + 1]
