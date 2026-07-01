"""Synthesizer — 여러 sub-skill 결과를 한국어 자연 답변으로 통합.

Wave 6 (C 코스) 시그니처 확장:
- 입력: user_text, sub_results, persona, domain_summary, grounding_docs_merged, ledger_snapshot
- 출력: SynthesizeResult (answer_text + confidence + missing_info + used_blocks)
- D 코스 hook 자리: confidence 가 0.7 미만이면 engine 의 confidence 분기 hook 이 유도 질문으로 분기.

Backward compat: 옛 호출자가 ``await synthesize(user_text=..., sub_results=..., llm_client=...)``
형태로 부르면 str 만 반환되도록 ``return_legacy_str`` 옵션 (default False — Wave 6 부터 dataclass).
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agent_framework.llm.json_parse import extract_json

_PROMPT_PATH = Path(__file__).parent.parent.parent / "agent_framework" / "runtime" / "orchestrator" / "prompts" / "synthesize.md"
# 위 경로가 안 먹히면 직접 패키지 기반 fallback
try:
    if not _PROMPT_PATH.exists():
        _PROMPT_PATH = Path(__file__).resolve().parents[2] / "agent_framework" / "runtime" / "orchestrator" / "prompts" / "synthesize.md"
except Exception:  # noqa: BLE001
    pass


@dataclass
class SynthesizeResult:
    answer_text: str
    confidence: float = 0.0
    missing_info: str | None = None
    used_blocks: list[str] = field(default_factory=list)


def _load_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        # 인라인 fallback (deployment 시 prompt md 누락 방어)
        return (
            "여러 sub-skill 결과를 한국어 자연 답변으로 통합. JSON 출력: "
            "{answer_text, confidence(0~1), missing_info, used_blocks}."
        )


async def synthesize(
    *,
    user_text: str,
    sub_results: list[dict],
    llm_client: Any,
    persona: dict | None = None,
    domain_summary: str | None = None,
    grounding_docs_merged: list[dict] | None = None,
    ledger_snapshot: dict | None = None,
    return_legacy_str: bool = False,
) -> SynthesizeResult | str:
    """sub_results 를 통합 답변 + confidence 로 합성.

    sub_results 형식:
    ```
    [
      {"name": "schedule_personal", "result": {...}, "grounding_docs": [...],
       "answer_fragment": "...", "fragment_confidence": 0.0~1.0, "used_blocks": [...]},
      {"name": "diary_personal", "error": "..."},
      ...
    ]
    ```
    """
    sub_text = _format_sub_results(sub_results)
    prompt = _build_synthesis_prompt(
        user_text=user_text,
        sub_text=sub_text,
        persona=persona,
        domain_summary=domain_summary,
        grounding_docs_merged=grounding_docs_merged,
        ledger_snapshot=ledger_snapshot,
    )
    raw = await _call_llm(llm_client, prompt)
    parsed: dict[str, Any] | None = None
    try:
        parsed = extract_json(raw)
    except Exception:  # noqa: BLE001
        parsed = None

    if isinstance(parsed, dict) and parsed.get("answer_text"):
        result = SynthesizeResult(
            answer_text=str(parsed.get("answer_text")),
            confidence=float(parsed.get("confidence") or 0.0),
            missing_info=(str(parsed.get("missing_info")) if parsed.get("missing_info") else None),
            used_blocks=[str(b) for b in (parsed.get("used_blocks") or [])][:20],
        )
    else:
        # JSON parse 실패 — raw 텍스트 그대로 + confidence 0
        result = SynthesizeResult(answer_text=str(raw), confidence=0.0)

    if return_legacy_str:
        return result.answer_text
    return result


def _format_sub_results(sub_results: list[dict]) -> str:
    if not sub_results:
        return "(서브 스킬 결과 없음)"
    blocks: list[str] = []
    for r in sub_results:
        name = r.get("name", "(unknown)")
        if "error" in r:
            blocks.append(f"[{name}]\nERROR: {r['error']}")
            continue
        parts: list[str] = []
        if r.get("grounding_docs"):
            for i, g in enumerate(r["grounding_docs"][:3]):
                parts.append(
                    f"  자료 {i+1}: [{g.get('title','')}] § {g.get('heading','')}"
                    f"{(' (기준일 ' + str(g.get('effective_date'))[:10] + ')') if g.get('effective_date') else ''}\n"
                    f"  {(g.get('snippet') or '')[:400]}"
                )
        if r.get("answer_fragment"):
            parts.append(f"  답변 단편: {r['answer_fragment'][:600]}")
        if r.get("result") and not parts:
            try:
                body = json.dumps(r["result"], ensure_ascii=False, indent=2, default=str)
            except (TypeError, ValueError):
                body = str(r["result"])
            parts.append(body[:800])
        fc = r.get("fragment_confidence")
        if fc is not None:
            parts.append(f"  fragment_confidence: {fc:.2f}")
        blocks.append(f"[{name}]\n" + "\n".join(parts))
    return "\n\n".join(blocks)


def _build_synthesis_prompt(
    *,
    user_text: str,
    sub_text: str,
    persona: dict | None,
    domain_summary: str | None,
    grounding_docs_merged: list[dict] | None,
    ledger_snapshot: dict | None,
) -> str:
    base = _load_prompt()
    persona_block = "(없음)"
    if persona:
        persona_block = json.dumps({
            "kind": persona.get("kind"),
            "tone": persona.get("tone"),
            "safety": persona.get("safety"),
        }, ensure_ascii=False, indent=2)

    grounding_block = "(없음)"
    if grounding_docs_merged:
        rows: list[str] = []
        for g in grounding_docs_merged[:8]:
            tag = ""
            for rel in (g.get("relations") or []):
                if rel.get("relation") == "supersedes" and rel.get("from") == g.get("block_id"):
                    tag = " [신본]"
                elif rel.get("relation") == "supersedes" and rel.get("to") == g.get("block_id"):
                    tag = f" [구본 — superseded]"
                elif rel.get("relation") == "conflicts":
                    tag = " [모순주의]"
            rows.append(
                f"- [{g.get('title','')}] § {g.get('heading','')}"
                f"{tag}{(' (기준일 ' + str(g.get('effective_date'))[:10] + ')') if g.get('effective_date') else ''}\n"
                f"  {(g.get('snippet') or '')[:400]}"
            )
        grounding_block = "\n".join(rows)

    domain_summary_block = (domain_summary or "(없음)")
    ledger_block = "(없음)"
    if ledger_snapshot:
        try:
            ledger_block = json.dumps(ledger_snapshot, ensure_ascii=False, indent=2)[:1500]
        except (TypeError, ValueError):
            ledger_block = "(직렬화 실패)"

    return f"""{base}

---

## user_text
{user_text}

## persona
{persona_block}

## domain_summary
{domain_summary_block}

## grounding_docs_merged
{grounding_block}

## ledger_snapshot
{ledger_block}

## sub_results
{sub_text}

## 출력 (JSON only — answer_text/confidence/missing_info/used_blocks)
"""


async def _call_llm(llm_client: Any, prompt: str) -> str:
    if llm_client is None:
        return "{}"
    if callable(llm_client) and not hasattr(llm_client, "generate") and not hasattr(llm_client, "complete"):
        maybe = llm_client(prompt)
        if inspect.isawaitable(maybe):
            return await maybe
        return str(maybe)
    gen = getattr(llm_client, "generate", None)
    if callable(gen):
        maybe = gen(prompt)
        if inspect.isawaitable(maybe):
            return await maybe
        return str(maybe)
    comp = getattr(llm_client, "complete", None)
    if callable(comp):
        maybe = comp("JSON 형식으로만 응답.", prompt, response_format="json_object")
        if inspect.isawaitable(maybe):
            return await maybe
        return str(maybe)
    if callable(llm_client):
        maybe = llm_client(prompt)
        if inspect.isawaitable(maybe):
            return await maybe
        return str(maybe)
    raise RuntimeError("llm_client not usable")
