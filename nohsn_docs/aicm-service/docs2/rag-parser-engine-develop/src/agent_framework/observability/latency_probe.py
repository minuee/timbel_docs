"""챗 latency 측정 — 2026-05-06 spec § 4.1.

dispatcher 가 phase 진입/종료 시 record_phase 호출. plan executor 의
SSE plan_step 이벤트는 mirror 로 consume_step_event 호출. probe 자체는
caller 의 흐름을 막지 않도록 단순 누적기 — 예외 격리는 caller 책임.

flag `LATENCY_PROBE_SSE` 가 false 이면 dispatcher 는 to_sse_payload 호출도
안 함 — 사용자 SSE 영향 0.

engine.py 0-byte 유지 제약: intent_classifier / plan_generator /
answer_compose_finalize 같은 sub-phase 는 engine.turn() 내부에서 발생하므로
직접 wrap 불가. consume_event() + finalize_derived_phases() 를 통해 SSE
event timestamp 기반으로 derived phase 를 산출한다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Phase:
    name: str
    wall_ms: float
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanStepEvent:
    step: int
    kind: str          # tool / reasoning / ask_user_clarify
    tool: str | None
    args: dict[str, Any]
    ts: float          # epoch s
    ok: bool


def _args_signature(tool: str | None, args: dict[str, Any]) -> str:
    """tool + 정규화 args 의 결정론적 hash 입력. 공백/대소문자/key 순서 무관."""
    if tool is None:
        return ""
    norm: dict[str, Any] = {}
    for k in sorted(args.keys()):
        v = args[k]
        if isinstance(v, str):
            v = v.strip().lower()
        norm[k.lower()] = v
    return f"{tool}|{json.dumps(norm, ensure_ascii=False, sort_keys=True, default=str)}"


def _sanitize_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """SSE 송출 직전 non-JSON 값을 str() 로 변환. dispatcher 가 직접
    json.dumps 호출 시 raise 안 나도록."""
    out: dict[str, Any] = {}
    for k, v in meta.items():
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            out[k] = str(v)
    return out


class LatencyProbe:
    def __init__(self) -> None:
        self.phases: list[Phase] = []
        self._step_events: list[PlanStepEvent] = []
        self._event_timeline: list[tuple[str, float]] = []

    def record_phase(
        self,
        name: str,
        started_at: float,
        ended_at: float,
        **meta: Any,
    ) -> None:
        wall_ms = (ended_at - started_at) * 1000.0
        self.phases.append(Phase(name=name, wall_ms=wall_ms, meta=dict(meta)))

    def consume_step_event(self, ev: PlanStepEvent) -> None:
        self._step_events.append(ev)

    def consume_event(self, ev: dict) -> None:
        """모든 SSE event dict 를 받아 timestamp 기반 phase timeline 에 누적.

        plan_step event → consume_step_event 로 위임 (기존 dupe 카운트 로직 유지).
        그 외 event → (event_name, ts) 를 _event_timeline 에 기록.

        finalize_derived_phases() 호출 전까지 phases 에 반영되지 않음.
        """
        event_name = ev.get("event") or ""
        data = ev.get("data") or {}
        ts: float = data.get("ts") or time.time()

        if event_name == "plan_step":
            self.consume_step_event(PlanStepEvent(
                step=data.get("step", 0),
                kind=data.get("kind", ""),
                tool=data.get("tool"),
                args=data.get("args") or {},
                ts=ts,
                ok=bool(data.get("ok", True)),
            ))
            return

        self._event_timeline.append((event_name or "unknown", ts))

    def finalize_derived_phases(self, turn_started_at: float) -> None:
        """SSE event timeline 에서 sub-phase wall_ms 를 계산해 phases 에 추가.

        engine.py 0-byte 유지 제약 하에서 sub-phase 측정의 유일한 방법.

        event marker → derived phase 매핑:
          intent                → intent_classifier
          plan_generated        → plan_generator
          citations_finalized   → answer_compose_finalize
          done                  → after_compose

        각 phase 의 started_at 은 이전 marker 의 ts (첫 phase 는 turn_started_at).
        중복 phase 이름은 첫 발생만 기록.
        """
        if not self._event_timeline:
            return

        EVENT_TO_PHASE: dict[str, str] = {
            "intent": "intent_classifier",
            "plan_generated": "plan_generator",
            "citations_finalized": "answer_compose_finalize",
            "done": "after_compose",
        }

        timeline = sorted(self._event_timeline, key=lambda x: x[1])
        prev_ts = turn_started_at
        seen_phases: set[str] = set()

        for event_name, ts in timeline:
            phase = EVENT_TO_PHASE.get(event_name)
            if phase and phase not in seen_phases:
                self.record_phase(phase, prev_ts, ts)
                seen_phases.add(phase)
                prev_ts = ts

    def compute_signature_dupe_count(self) -> int:
        """동일 (tool, normalized args) signature 가 2회 이상 나타난 횟수의 합 - 고유 signature 수."""
        seen: dict[str, int] = {}
        for ev in self._step_events:
            if ev.kind != "tool" or ev.tool is None:
                continue
            sig = _args_signature(ev.tool, ev.args or {})
            seen[sig] = seen.get(sig, 0) + 1
        dupes = 0
        for n in seen.values():
            if n > 1:
                dupes += (n - 1)
        return dupes

    def to_sse_payload(self) -> dict[str, Any]:
        return {
            "phases": [
                {"name": p.name, "wall_ms": round(p.wall_ms, 3),
                 "meta": _sanitize_meta(p.meta)}
                for p in self.phases
            ],
            "dupes": self.compute_signature_dupe_count(),
            "n_steps": len(self._step_events),
        }
