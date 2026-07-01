"""Ingest pipeline throughput benchmark.

측정: PDF 업로드 → document.status == 'active' 까지의 wall-clock 시간.

시나리오:
- 단일 (concurrency=1) 의 30p / 150p PDF
- 동시 업로드 (concurrency=[2,4,8]) 의 throughput

샘플 파일이 없으면 skip — CI 환경 친화.

결과: PERF_OUTPUT_DIR/<date>-ingest-throughput.json
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.perf.conftest import (
    LatencySamples,
    REPO_ROOT,
    StopWatch,
    perf_is_mock,
)


pytestmark = [pytest.mark.perf, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_sample(relative_path: str) -> Path | None:
    """scenarios.yml 의 relative_path 를 절대 경로로 변환 + 존재 확인."""
    p = Path(relative_path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p if p.exists() else None


async def _upload_one(
    client: httpx.AsyncClient,
    sample_path: Path,
) -> str | None:
    """단일 PDF 업로드 — document_id 반환 또는 None."""
    try:
        with sample_path.open("rb") as fh:
            files = {"file": (sample_path.name, fh, "application/pdf")}
            r = await client.post("/api/v1/documents", files=files)
        if r.status_code >= 400:
            return None
        data = r.json().get("data", {})
        return data.get("document_id") or data.get("id")
    except Exception:
        return None


async def _wait_for_active(
    client: httpx.AsyncClient,
    document_id: str,
    timeout_s: float,
    poll_interval_s: float = 2.0,
) -> bool:
    """document.status == 'active' 또는 'failed' 까지 polling."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = await client.get(f"/api/v1/documents/{document_id}")
            if r.status_code < 400:
                status = (r.json().get("data") or {}).get("status")
                if status == "active":
                    return True
                if status in {"failed", "error"}:
                    return False
        except Exception:
            pass
        await asyncio.sleep(poll_interval_s)
    return False


async def _measure_doc_ingest(
    client: httpx.AsyncClient,
    sample_path: Path,
    timeout_s: float,
) -> float | None:
    """1 문서 업로드 → active. 실패 시 None."""
    with StopWatch() as sw:
        doc_id = await _upload_one(client, sample_path)
        if not doc_id:
            return None
        ok = await _wait_for_active(client, doc_id, timeout_s=timeout_s)
        if not ok:
            return None
    return sw.elapsed_ms


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_ingest_single_document_latency(
    perf_client: httpx.AsyncClient,
    scenarios: dict,
    report_writer,
) -> None:
    """30p / 150p 단일 문서 ingest 시간 측정."""
    cfg = scenarios.get("ingest", {})
    docs = cfg.get("documents", [])
    timeout_s = float(cfg.get("timeout_seconds", 600))

    blocks: list[dict] = []
    skipped: list[str] = []

    for doc in docs:
        sample = _resolve_sample(doc["relative_path"])
        if sample is None and not perf_is_mock():
            skipped.append(doc["id"])
            continue

        # mock 모드면 임시 1KB 파일 사용
        if sample is None:
            sample = Path(REPO_ROOT) / "tests" / "perf" / f".tmp_{doc['id']}.pdf"
            sample.parent.mkdir(parents=True, exist_ok=True)
            sample.write_bytes(b"%PDF-1.4\n%mock\n")

        samples = LatencySamples(label=f"ingest_single::{doc['id']}")
        # 반복 횟수는 낮게 — 실제 ingest 는 비용이 크다
        repeats = int(os.environ.get("PERF_INGEST_REPEATS", "3"))

        for _ in range(repeats):
            ms = await _measure_doc_ingest(perf_client, sample, timeout_s)
            if ms is None:
                samples.add_error()
            else:
                samples.add(ms)

        samples.extra["pages"] = doc.get("pages")
        samples.extra["label"] = doc.get("label")
        blocks.append(samples.summary())

    payload_out: dict[str, Any] = {
        "suite": "ingest_single",
        "results": blocks,
        "skipped_missing_samples": skipped,
    }
    date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = report_writer(f"{date_label}-ingest-single.json", payload_out)
    print(f"\n[perf] ingest single report -> {out_path}")

    if not blocks and skipped:
        pytest.skip(f"no ingest samples available — skipped: {skipped}")


async def test_ingest_concurrent_throughput(
    perf_client: httpx.AsyncClient,
    scenarios: dict,
    report_writer,
) -> None:
    """동시 업로드 — N=[2,4,8] throughput 측정 (작은 문서 우선)."""
    cfg = scenarios.get("ingest", {})
    docs = cfg.get("documents", [])
    timeout_s = float(cfg.get("timeout_seconds", 600))
    levels = cfg.get("concurrency_levels", [2, 4, 8])

    # 가장 작은 문서로 동시 측정
    small = next((d for d in docs if d.get("pages", 999) <= 50), docs[0] if docs else None)
    if small is None:
        pytest.skip("no ingest documents configured")

    sample = _resolve_sample(small["relative_path"])
    if sample is None and not perf_is_mock():
        pytest.skip(f"missing sample: {small['relative_path']}")
    if sample is None:
        sample = Path(REPO_ROOT) / "tests" / "perf" / f".tmp_{small['id']}.pdf"
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_bytes(b"%PDF-1.4\n%mock\n")

    blocks: list[dict] = []

    for cc in levels:
        samples = LatencySamples(label=f"ingest_cc::{cc}")
        with StopWatch() as sw:
            results = await asyncio.gather(
                *(_measure_doc_ingest(perf_client, sample, timeout_s) for _ in range(cc)),
            )
        for r in results:
            if r is None:
                samples.add_error()
            else:
                samples.add(r)
        samples.extra["concurrency"] = cc
        samples.extra["batch_wall_ms"] = round(sw.elapsed_ms, 2)
        samples.extra["throughput_docs_per_min"] = (
            round(cc / (sw.elapsed_ms / 60_000.0), 3) if sw.elapsed_ms > 0 else 0.0
        )
        blocks.append(samples.summary())

    payload_out = {
        "suite": "ingest_concurrent",
        "results": blocks,
        "sample_id": small["id"],
    }
    date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = report_writer(f"{date_label}-ingest-concurrent.json", payload_out)
    print(f"\n[perf] ingest concurrent report -> {out_path}")

    assert blocks, "no concurrency blocks produced"
