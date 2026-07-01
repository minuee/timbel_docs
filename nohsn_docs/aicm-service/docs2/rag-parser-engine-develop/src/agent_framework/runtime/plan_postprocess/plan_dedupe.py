"""plan postprocess — 중복 tool step 압축. 2026-05-06 spec § 4.3 C.

GPT-5.5 권고: plan_generator 가 redundant search 를 짠 trace A 케이스
같은 over-engineering 을 후처리로 흡수. reasoning step 은 흐름 의미
때문에 signature 동일해도 보존.

pre-demo: 어디서도 호출 안 됨. PLAN_DEDUPE flag on 시 dispatcher 가 사용.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import json


@dataclass
class DedupedStep:
    step: int
    kind: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    expr: str | None = None


def from_plan_step(plan_step: Any) -> "DedupedStep":
    """PlanStep → DedupedStep adapter (D28 §2 — DRY).

    plan_dedupe 모듈이 PlanStep.raw 의 키 구조 (tool/args/expr) 를 *내부 책임* 으로
    가지므로, orchestrator 등 caller 는 helper 만 호출하면 된다. raw=None / 비-dict
    인 경우에도 안전하게 정규화 — 기존 list-comp 의 `s.raw.get(...) if s.raw else None`
    동치 + 비-dict (truthy 한 list 등) 에서도 AttributeError 대신 {} 로 하드닝.

    step / kind 는 기본값 없이 직접 접근 — PlanStep 의 필수 필드 이므로 누락 시
    AttributeError 가 *기존 동작과 일치* (byte-equal 의도, GPT-5 §2 권고 반영).

    Args:
        plan_step: ``PlanStep`` 또는 ``.step`` / ``.kind`` / ``.raw`` 속성 객체.

    Returns:
        DedupedStep — tool/args/expr 는 raw dict 에서 안전 추출.
    """
    raw = getattr(plan_step, "raw", None) or {}
    if not isinstance(raw, dict):
        raw = {}
    return DedupedStep(
        step=plan_step.step,
        kind=plan_step.kind,
        tool=raw.get("tool"),
        args=raw.get("args") or {},
        expr=raw.get("expr"),
    )


@dataclass
class DedupeNote:
    removed_step_index: int
    removed_signature: str
    duplicate_of_step: int


def _normalize_args(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in sorted(args.keys()):
        v = args[k]
        if isinstance(v, str):
            v = v.strip().lower()
        out[k.lower()] = v
    return out


def _sig(step: DedupedStep) -> str:
    if step.kind != "tool" or step.tool is None:
        # 비-tool 은 dedupe 대상 아님 — unique signature.
        return f"unique:{id(step)}"
    return f"{step.tool}|{json.dumps(_normalize_args(step.args), ensure_ascii=False, sort_keys=True, default=str)}"


def dedupe_plan(
    plan: list[DedupedStep],
) -> tuple[list[DedupedStep], list[DedupeNote]]:
    """동일 (tool, normalized_args) signature 의 후속 step 제거. 첫 등장 보존."""
    seen: dict[str, int] = {}  # signature -> step index of first occurrence
    out: list[DedupedStep] = []
    notes: list[DedupeNote] = []
    for idx, step in enumerate(plan):
        sig = _sig(step)
        if sig.startswith("unique:") or sig not in seen:
            seen[sig] = idx
            out.append(step)
        else:
            notes.append(DedupeNote(
                removed_step_index=idx,
                removed_signature=sig,
                duplicate_of_step=seen[sig],
            ))
    return out, notes
