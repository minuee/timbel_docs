"""Table normalizer — 다양한 형식 표 → 일관된 markdown.

구조 추출은 라이브러리 (tabula/camelot 등 외부) 가 한 결과를 받아서,
헤더·셀 의미 추론과 일관성은 LLM 에 위임한다. rule X.

P0 검색 품질 업그레이드:
- 같은 문서 내에서 한 표는 markdown, 다른 표는 공백 나열로 혼재되는 문제 해결
- 표 안 정보 검색 정확도 상승
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.common.logging import get_logger

log = get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "table_normalize.txt"


@dataclass(frozen=True)
class NormalizedTable:
    """정규화된 표 — markdown 렌더 직전 중간 표현."""

    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "headers": list(self.headers),
            "rows": [list(r) for r in self.rows],
        }


class TableNormalizer:
    """raw 2D 표 → markdown 변환기.

    LLM 으로 헤더 결정·셀 의미 추론·일관성 정리, 코드는 markdown 렌더만.
    """

    def __init__(self, llm_client):
        self.llm = llm_client
        self._prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    async def normalize(
        self, *, raw_table: list[list[str]], context: str = ""
    ) -> str:
        """raw 2D 배열 → 정규화된 markdown 표 문자열.

        Args:
            raw_table: 행 × 셀 2D 배열. 빈 배열이면 "" 반환.
            context: 표 앞뒤 문서 본문 (헤더 추론에 활용).

        Returns:
            Markdown 표 문자열. LLM 실패 시 빈 문자열.
        """
        if not raw_table or not any(raw_table):
            return ""

        try:
            structured = await self._llm_normalize(raw_table, context)
        except Exception as exc:  # noqa: BLE001
            log.warning("table_normalize_llm_failed", error=str(exc))
            return ""

        if not structured.headers:
            return ""
        return self._render_markdown(structured)

    async def normalize_to_struct(
        self, *, raw_table: list[list[str]], context: str = ""
    ) -> NormalizedTable | None:
        """markdown 대신 구조 dict 가 필요할 때."""
        if not raw_table or not any(raw_table):
            return None
        try:
            return await self._llm_normalize(raw_table, context)
        except Exception as exc:  # noqa: BLE001
            log.warning("table_normalize_llm_failed", error=str(exc))
            return None

    # ─── 내부 ──────────────────────────────────────────────────────

    async def _llm_normalize(
        self, raw_table: list[list[str]], context: str
    ) -> NormalizedTable:
        prompt = self._prompt_template.replace(
            "{raw_table}", json.dumps(raw_table, ensure_ascii=False)
        ).replace("{context}", context or "(없음)")

        raw = await self._call_llm(prompt)
        return self._parse_response(raw)

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
                LLMRequest(prompt=prompt, response_format="json", max_tokens=2000)
            )
        if isinstance(result, str):
            return result
        text = getattr(result, "text", None)
        if text is None:
            raise RuntimeError("LLM response missing .text attribute")
        return text

    def _parse_response(self, raw: str) -> NormalizedTable:
        cleaned = _strip_json_envelope(raw)
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("table_normalize_decode_failed", preview=cleaned[:120])
            return NormalizedTable(headers=(), rows=())

        headers_raw = obj.get("headers", [])
        rows_raw = obj.get("rows", [])
        if not isinstance(headers_raw, list) or not isinstance(rows_raw, list):
            return NormalizedTable(headers=(), rows=())

        headers = tuple(str(h) for h in headers_raw)
        rows = tuple(
            tuple(str(c) for c in row)
            for row in rows_raw
            if isinstance(row, list)
        )
        return NormalizedTable(headers=headers, rows=rows)

    @staticmethod
    def _render_markdown(t: NormalizedTable) -> str:
        """structured 표 → markdown 문자열.

        |로 escape — 셀에 | 들어가면 &#124; 로 치환.
        """
        if not t.headers:
            return ""
        n = len(t.headers)

        def _esc(c: str) -> str:
            return c.replace("|", "&#124;").replace("\n", " ").strip()

        out = "| " + " | ".join(_esc(h) for h in t.headers) + " |\n"
        out += "|" + "---|" * n + "\n"
        for row in t.rows:
            # 컬럼 수 맞추기 — 부족하면 ""로, 넘치면 자름
            cells = list(row[:n])
            while len(cells) < n:
                cells.append("")
            out += "| " + " | ".join(_esc(c) for c in cells) + " |\n"
        return out


def _strip_json_envelope(raw: str) -> str:
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
