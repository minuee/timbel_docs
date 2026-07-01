"""RAG end-to-end latency — assist-stream SSE.

측정 항목:
- first_token_ms : SSE 첫 token event 까지의 시간 (UX critical)
- full_response_ms : 전체 stream 완료까지의 시간
- intent_event_ms : intent event 까지의 시간 (gate 응답성)

공공 SaaS 시나리오: 단일 / multi-turn follow-up / 표 인용.

결과: PERF_OUTPUT_DIR/<date>-rag-e2e-latency.json
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from tests.perf.conftest import LatencySamples, StopWatch


pytestmark = [pytest.mark.perf, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# SSE 파서 — first token / intent / done 시점 추출
# ---------------------------------------------------------------------------


async def _measure_assist_stream(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> dict[str, float] | None:
    """단일 assist-stream 호출의 단계별 latency 측정.

    returns: {"intent_ms", "first_token_ms", "full_ms"} 또는 None (실패).
    """
    intent_ms: float | None = None
    first_token_ms: float | None = None
    full_ms: float | None = None

    with StopWatch() as sw:
        try:
            async with client.stream("POST", "/api/v1/rag/assist-stream", json=payload) as resp:
                if resp.status_code >= 400:
                    return None
                cur_event: str | None = None
                async for raw in resp.aiter_lines():
                    if raw.startswith("event:"):
                        cur_event = raw.split(":", 1)[1].strip()
                        now_ms = (
                            __import__("time").perf_counter_ns() - sw.start_ns
                        ) / 1_000_000.0
                        if cur_event == "intent" and intent_ms is None:
                            intent_ms = now_ms
                        elif cur_event == "token" and first_token_ms is None:
                            first_token_ms = now_ms
                        elif cur_event == "done":
                            full_ms = now_ms
        except Exception:
            return None

    if full_ms is None:
        full_ms = sw.elapsed_ms if sw.elapsed_ms else 0.0

    return {
        "intent_ms": intent_ms or 0.0,
        "first_token_ms": first_token_ms or 0.0,
        "full_ms": full_ms,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_rag_assist_stream_e2e(
    perf_client: httpx.AsyncClient,
    scenarios: dict,
    report_writer,
    repository_id: str | None,
) -> None:
    """assist-stream 각 시나리오의 first-token + full-response latency.

    repository_id 는 assist-stream 필수 — env PERF_REPOSITORY_ID 미지정 시 skip.
    """
    if repository_id is None:
        pytest.skip("PERF_REPOSITORY_ID env 미설정 — assist-stream 측정 skip")

    cfg = scenarios.get("rag_assist", {})
    reps = scenarios.get("repetitions", {})
    warmup = int(reps.get("warmup", 2))
    measure = int(reps.get("measure", 10))

    blocks: list[dict] = []

    for case in cfg.get("scenarios", []):
        intent_s = LatencySamples(label=f"intent::{case['id']}")
        first_s = LatencySamples(label=f"first_token::{case['id']}")
        full_s = LatencySamples(label=f"full_response::{case['id']}")

        payload = {
            "query": case["query"],
            "conversation_history": case.get("history", []),
            "repository_id": repository_id,
        }

        # warmup
        for _ in range(warmup):
            await _measure_assist_stream(perf_client, payload)

        # measure
        for _ in range(measure):
            res = await _measure_assist_stream(perf_client, payload)
            if res is None:
                intent_s.add_error()
                first_s.add_error()
                full_s.add_error()
                continue
            intent_s.add(res["intent_ms"])
            first_s.add(res["first_token_ms"])
            full_s.add(res["full_ms"])

        blocks.append(intent_s.summary())
        blocks.append(first_s.summary())
        blocks.append(full_s.summary())

    payload_out = {
        "suite": "rag_assist_e2e",
        "warmup": warmup,
        "measure": measure,
        "results": blocks,
    }
    date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = report_writer(f"{date_label}-rag-e2e-latency.json", payload_out)
    print(f"\n[perf] rag e2e report -> {out_path}")

    assert any(b["count"] > 0 for b in blocks), "no samples captured"
