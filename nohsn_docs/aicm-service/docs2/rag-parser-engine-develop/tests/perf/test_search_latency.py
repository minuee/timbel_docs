"""Search latency benchmark.

측정 대상:
- POST /api/v1/search          (하이브리드 검색 — p50/p95/p99)
- POST /api/v1/rag/retrieve    (RAG 컨텍스트 — 토큰 예산 기반)

시나리오 셋:
- single   : 단일 쿼리 반복
- filtered : document_type filter 적용
- multi_turn: 3턴 follow-up
- out_of_domain: intent_gate SKIP 동작 (latency 측정 + 응답 형태 확인)

결과: PERF_OUTPUT_DIR/<date>-search-latency.json
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from tests.perf.conftest import LatencySamples, StopWatch


pytestmark = [pytest.mark.perf, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# 내부 helpers
# ---------------------------------------------------------------------------


async def _measure_one(
    client: httpx.AsyncClient,
    path: str,
    payload: dict,
) -> tuple[float, bool]:
    """단일 요청 측정 — (elapsed_ms, ok)."""
    with StopWatch() as sw:
        try:
            r = await client.post(path, json=payload)
            ok = r.status_code < 500
        except Exception:
            ok = False
    return sw.elapsed_ms, ok


async def _run_samples(
    client: httpx.AsyncClient,
    path: str,
    payload: dict,
    *,
    warmup: int,
    measure: int,
    label: str,
) -> LatencySamples:
    samples = LatencySamples(label=label)

    # warmup — 측정에서 제외
    for _ in range(warmup):
        await _measure_one(client, path, payload)

    for _ in range(measure):
        ms, ok = await _measure_one(client, path, payload)
        if ok:
            samples.add(ms)
        else:
            samples.add_error()

    return samples


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_search_latency_full_sweep(
    perf_client: httpx.AsyncClient,
    scenarios: dict,
    report_writer,
) -> None:
    """모든 search 시나리오를 한 번에 측정해 단일 JSON report 생성."""
    cfg = scenarios.get("search", {})
    reps = scenarios.get("repetitions", {})
    warmup = int(reps.get("warmup", 2))
    measure = int(reps.get("measure", 10))

    report_blocks: list[dict] = []

    # single queries
    for case in cfg.get("single", []):
        payload = {
            "query": case["query"],
            "top_k": case.get("top_k", 10),
        }
        s = await _run_samples(
            perf_client, "/api/v1/search", payload,
            warmup=warmup, measure=measure, label=f"single::{case['id']}",
        )
        report_blocks.append(s.summary())

    # filtered queries — POST 검색 with filter dict
    for case in cfg.get("filtered", []):
        payload = {
            "query": case["query"],
            "top_k": case.get("top_k", 5),
            "filters": case.get("filters", {}),
        }
        s = await _run_samples(
            perf_client, "/api/v1/search", payload,
            warmup=warmup, measure=measure, label=f"filtered::{case['id']}",
        )
        report_blocks.append(s.summary())

    # multi-turn — 같은 conversation 안에서 3 query 순차 실행 (turn-by-turn 측정)
    for case in cfg.get("multi_turn", []):
        turn_samples: list[LatencySamples] = []
        for turn_idx, query in enumerate(case.get("turns", [])):
            payload = {"query": query, "top_k": 10}
            label = f"multi_turn::{case['id']}::turn{turn_idx + 1}"
            s = await _run_samples(
                perf_client, "/api/v1/search", payload,
                warmup=warmup, measure=measure, label=label,
            )
            turn_samples.append(s)
            report_blocks.append(s.summary())

    # out-of-domain — intent_gate 가 SKIP 처리해 빠른 응답 기대
    for case in cfg.get("out_of_domain", []):
        payload = {"query": case["query"], "top_k": 10}
        s = await _run_samples(
            perf_client, "/api/v1/search", payload,
            warmup=warmup, measure=measure, label=f"ood::{case['id']}",
        )
        s.extra["expect_intent_gate_skip"] = case.get("expect_intent_gate_skip", False)
        report_blocks.append(s.summary())

    # Phase 5 T5.4 — cold_unique: 각 호출에 random nonce → server cache 우회
    # warm-cache 측정의 본질적 한계 보완. 실제 cold-call latency 측정용.
    for case in cfg.get("cold_unique", []):
        cold_samples = LatencySamples(label=f"cold::{case['id']}")
        # warmup 없음 — 각 호출이 cold 여야 함
        for _ in range(measure):
            payload = {
                "query": case["query"],
                "top_k": case.get("top_k", 10),
                # nonce 는 query string param — 서버 cache 키에 영향
                "_nonce": uuid.uuid4().hex,
            }
            ms, ok = await _measure_one(perf_client, "/api/v1/search", payload)
            if ok:
                cold_samples.add(ms)
            else:
                cold_samples.add_error()
        cold_samples.extra["cache_bypass"] = "nonce_per_call"
        report_blocks.append(cold_samples.summary())

    payload_out = {
        "suite": "search_latency",
        "warmup": warmup,
        "measure": measure,
        "results": report_blocks,
    }
    date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"{date_label}-search-latency.json"
    out_path = report_writer(filename, payload_out)
    print(f"\n[perf] search latency report -> {out_path}")

    # 최소한의 sanity: 어떤 블록이라도 측정값이 있어야 통과 (mock 모드 포함)
    assert any(b["count"] > 0 for b in report_blocks), "no samples captured"


async def test_search_concurrent_burst(
    perf_client: httpx.AsyncClient,
    scenarios: dict,
    report_writer,
) -> None:
    """동시 N 요청 burst — tail latency 측정 (multi-turn 패턴 회귀에 필수).

    feedback_validation_must_include_multiturn_patterns — 단발 latency 만 보지 말 것.
    """
    cfg = scenarios.get("search", {})
    singles = cfg.get("single", [])
    if not singles:
        pytest.skip("no single-query scenarios configured")

    case = singles[0]
    concurrency_levels = [1, 4, 8]
    blocks: list[dict] = []

    for cc in concurrency_levels:
        samples = LatencySamples(label=f"concurrent::{cc}")
        payload = {"query": case["query"], "top_k": case.get("top_k", 10)}

        async def _one() -> None:
            ms, ok = await _measure_one(perf_client, "/api/v1/search", payload)
            if ok:
                samples.add(ms)
            else:
                samples.add_error()

        # warmup
        await asyncio.gather(*(_one() for _ in range(cc)))
        # measure
        for _ in range(3):  # 3 batches per level
            await asyncio.gather(*(_one() for _ in range(cc)))

        samples.extra["concurrency"] = cc
        blocks.append(samples.summary())

    payload_out = {"suite": "search_concurrent_burst", "results": blocks}
    date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = report_writer(f"{date_label}-search-concurrent.json", payload_out)
    print(f"\n[perf] search concurrent report -> {out_path}")

    assert any(b["count"] > 0 for b in blocks), "no samples captured"
