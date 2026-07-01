"""Chokepoint 4 — Citation type boundary.

응답에 노출되는 *모든* 인용 (citation) 은 이 모듈의 ``Citation`` frozen
dataclass 인스턴스만 통과한다. dict/str/Any 가 누설되면 5 봇 cross-leak 에서
관찰된 "system prompt 텍스트가 출처로 표시" 결함이 재발한다.

원칙:
- ``Citation`` 은 immutable (frozen=True) — 한번 만들어진 후 mutate 불가.
- ``CitationsBuilder`` 는 *허용된 source* (KMS chunk / web search hit) 만
  Citation 으로 변환. 다른 source (system prompt, tool stdout, free text 등)
  를 변환하려 하면 ``CitationConversionRefused`` raise.
- engine / response_renderer / channel adapter 가 citations list 를 다룰 때
  반드시 ``ensure_citations`` 를 거쳐 dict mix 차단.

2026-05-07 — samchully_voc 봇 → "가스비 몇달 밀리면 끊겨?" 발화에서
출처 [4] = "[stub] '[에이전트 컨텍스트] [BINDING POLICY ...'" 가 노출된 사건의
*직접 차단* layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


class CitationConversionRefused(ValueError):
    """허용되지 않은 source 를 Citation 으로 변환 시도 시 raise.

    예:
    - web.search 의 stub fallback (source="stub") → 거절. stub 결과는 사용자
      에게 *출처* 로 노출되어선 안 된다 (백엔드 미설정 안내일 뿐).
    - title/snippet 에 system prompt 마커 ([BINDING POLICY], [에이전트
      컨텍스트], "## current agent:") 가 들어 있는 경우 → 거절.
    - title 이 빈 문자열만 / 길이 0 → 거절.
    """


# Chokepoint 3 와 동일 sentinel — system prompt / binding policy 텍스트 차단.
_PROMPT_MARKERS: tuple[str, ...] = (
    "[BINDING POLICY",
    "[/BINDING POLICY]",
    "[에이전트 컨텍스트]",
    "## current agent:",
    "### goal",
    "### guidelines",
    "### allowed_tools",
    "### done_when",
)


def _looks_like_prompt_text(s: str) -> bool:
    """문자열이 system prompt 의 일부로 보이는지 휴리스틱 검사."""
    if not s:
        return False
    return any(m in s for m in _PROMPT_MARKERS)


@dataclass(frozen=True)
class Citation:
    """단일 인용 — engine 의 _citations_acc 와 channel adapter 의 출처 리스트가
    오직 이 타입의 인스턴스만 받는다.

    Attributes:
        chunk_id: KMS chunk 의 UUID. web 인용이면 None (url 만 식별자).
        doc_id: KMS document 의 UUID. web 인용이면 None.
        repo_id: KMS repository 의 UUID. web 인용이면 None.
        title: 사용자에게 노출될 제목 (빈 값 금지 — fallback "(제목 없음)").
        score: ranking score (0.0 ~ 1.0 권장). web 결과는 -1.0 가능.
        snippet: 인용 요약 (length 200 권장). 본문 일부.
        url: web 인용의 외부 URL. KMS 인용이면 None.
        kind: ``kms_chunk`` / ``web_url`` 둘 중 하나. 다른 값이면 거절됨.
        number: 본문의 [N] 마커와 매칭되는 1-based 시퀀스 번호.
    """

    title: str
    snippet: str
    score: float
    kind: str  # "kms_chunk" | "web_url"
    number: int
    chunk_id: UUID | None = None
    doc_id: UUID | None = None
    repo_id: UUID | None = None
    url: str | None = None

    def to_event_dict(self) -> dict[str, Any]:
        """SSE event=citations 의 data.items 항목으로 변환.

        frontend / channel adapter 가 dict 를 요구하므로 *event 직전* 에만
        dict 화. 내부 흐름은 항상 Citation 객체.
        """
        return {
            "id": str(self.chunk_id or self.url or f"cite-{self.number}"),
            "number": self.number,
            "kind": self.kind,
            "title": self.title,
            "snippet": self.snippet[:200] if self.snippet else "",
            "score": self.score,
            "source": {
                "tool": "kms_rag.search" if self.kind == "kms_chunk" else "web.search",
                "document_id": str(self.doc_id) if self.doc_id else None,
                "url": self.url,
            },
            "full_uri": self.url,
        }


@dataclass
class CitationsBuilder:
    """KMS document chunk / web hit → Citation 변환 단일 entry.

    plan executor 에서 tool 결과를 받을 때마다 ``add_kms_hits`` /
    ``add_web_hits`` 로 누적. 빌드 종료 후 ``items`` 가 list[Citation].
    """

    items: list[Citation] = field(default_factory=list)
    _seq: int = 0

    def _next_number(self) -> int:
        self._seq += 1
        return self._seq

    def add_kms_hits(self, hits: list[dict[str, Any]] | None) -> list[Citation]:
        """KMS chunk 결과 → Citation. 변환된 list 반환 (caller 가 SSE emit 용도).

        hits 가 None / 빈 list / dict 외 항목 → 무시 (raise X).
        title/snippet 이 prompt marker 를 포함하면 *그 항목만* 거절 + 로그.
        """
        out: list[Citation] = []
        if not hits:
            return out
        for h in hits:
            if not isinstance(h, dict):
                continue
            title = str(h.get("title") or h.get("document_title") or h.get("name") or "").strip()
            if not title:
                title = "(제목 없음)"
            snippet = str(h.get("content") or h.get("snippet") or h.get("description") or "")
            if _looks_like_prompt_text(title) or _looks_like_prompt_text(snippet):
                # 보안 — system prompt 누설. 본 항목 거절.
                from src.common.logging import get_logger
                _log = get_logger(__name__)
                _log.warning(
                    "citation_refused_prompt_text",
                    title=title[:120],
                    snippet_preview=snippet[:80],
                )
                continue
            chunk_id = _coerce_uuid(h.get("id") or h.get("chunk_id"))
            doc_id = _coerce_uuid(h.get("document_id") or h.get("doc_id"))
            repo_id = _coerce_uuid(h.get("repository_id") or h.get("repo_id"))
            try:
                score = float(h.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            cit = Citation(
                title=title,
                snippet=snippet[:200],
                score=score,
                kind="kms_chunk",
                number=self._next_number(),
                chunk_id=chunk_id,
                doc_id=doc_id,
                repo_id=repo_id,
                url=None,
            )
            self.items.append(cit)
            out.append(cit)
        return out

    def add_web_hits(self, hits: list[dict[str, Any]] | None) -> list[Citation]:
        """web.search 결과 → Citation. **stub source 는 절대 거절** — Chokepoint
        4 의 핵심 차단 (samchully_voc 사건 직접 원인).

        title/link 가 prompt marker 를 포함해도 거절.
        """
        out: list[Citation] = []
        if not hits:
            return out
        for h in hits:
            if not isinstance(h, dict):
                continue
            source = str(h.get("source") or "").strip().lower()
            if source == "stub":
                # 백엔드 미설정 stub 결과 — 사용자에게 출처로 노출 금지.
                continue
            title = str(h.get("title") or "").strip() or "(제목 없음)"
            snippet = str(h.get("snippet") or h.get("description") or "")
            if _looks_like_prompt_text(title) or _looks_like_prompt_text(snippet):
                from src.common.logging import get_logger
                _log = get_logger(__name__)
                _log.warning(
                    "citation_refused_prompt_text",
                    source="web",
                    title=title[:120],
                )
                continue
            url = str(h.get("link") or h.get("url") or "").strip() or None
            try:
                score = float(h.get("score") or -1.0)
            except (TypeError, ValueError):
                score = -1.0
            cit = Citation(
                title=title,
                snippet=snippet[:200],
                score=score,
                kind="web_url",
                number=self._next_number(),
                chunk_id=None,
                doc_id=None,
                repo_id=None,
                url=url,
            )
            self.items.append(cit)
            out.append(cit)
        return out


def _coerce_uuid(v: Any) -> UUID | None:
    """str/UUID/None → UUID 또는 None. 실패는 None (raise X)."""
    if v is None or v == "":
        return None
    if isinstance(v, UUID):
        return v
    try:
        return UUID(str(v))
    except (ValueError, TypeError):
        return None


def ensure_citations(items: Any) -> list[Citation]:
    """채널 adapter / response_renderer 가 받기 직전 type 검증.

    list[Citation] 만 통과. 하나라도 dict / str / 다른 타입이 섞이면 raise.
    None / 빈 list 는 [] 반환.
    """
    if items is None:
        return []
    if not isinstance(items, list):
        raise TypeError(
            f"citations must be list[Citation], got {type(items).__name__}"
        )
    out: list[Citation] = []
    for i, it in enumerate(items):
        if not isinstance(it, Citation):
            raise TypeError(
                f"citations[{i}] must be Citation instance, got {type(it).__name__}"
            )
        out.append(it)
    return out


__all__ = [
    "Citation",
    "CitationsBuilder",
    "CitationConversionRefused",
    "ensure_citations",
]
