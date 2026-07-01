"""Performance benchmark suite — shared fixtures + measurement helpers.

목적: 통합 Locus (src.api.main:app) vs 분리 Lucas-KMS (src.api.main_kms:create_kms_app)
의 응답 시간을 *같은 시나리오 셋* 으로 비교한다.

환경 변수:
- PERF_BASE_URL    측정 대상 URL (default http://localhost:5101)
- PERF_TENANT_ID   X-Tenant-Id 헤더 값 (default test tenant UUID)
- PERF_API_TOKEN   Authorization: Bearer 토큰 (선택)
- PERF_OUTPUT_DIR  결과 JSON 디렉토리 (default Doc/perf)
- PERF_PROFILE     report 안에 라벨로 박힐 식별자 (예: integrated / lucas-kms)
- PERF_MOCK        "1" 이면 mock 응답으로 측정 (CI 환경 의존성 제거)
"""
from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import yaml

# ---------------------------------------------------------------------------
# 환경 변수 helpers — 하드코딩 금지 (feedback_no_hardcoding_first_principle)
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "http://localhost:5101"
DEFAULT_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DEFAULT_OUTPUT_DIR = "Doc/perf"
DEFAULT_PROFILE = "integrated"
PERF_TIMEOUT_S = float(os.environ.get("PERF_TIMEOUT_S", "120"))
# repository_id 는 assist-stream 필수 입력 — env 미지정 시 None (해당 시나리오 skip)
PERF_REPOSITORY_ID_ENV = "PERF_REPOSITORY_ID"

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val else default


def perf_base_url() -> str:
    return _env("PERF_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def perf_tenant_id() -> str:
    return _env("PERF_TENANT_ID", DEFAULT_TENANT_ID)


def perf_output_dir() -> Path:
    raw = _env("PERF_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
    p = Path(raw)
    if not p.is_absolute():
        p = REPO_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def perf_profile() -> str:
    return _env("PERF_PROFILE", DEFAULT_PROFILE)


def perf_is_mock() -> bool:
    return os.environ.get("PERF_MOCK", "0") == "1"


def perf_repository_id() -> str | None:
    """assist-stream 등 repository_id 필수 endpoint 용 — env 가 없으면 None.

    None 이면 해당 시나리오는 skip 처리되어야 한다 (정확한 측정만).
    """
    val = os.environ.get(PERF_REPOSITORY_ID_ENV)
    if not val:
        return None
    try:
        UUID(val)
    except ValueError:
        return None
    return val


@pytest.fixture(scope="session")
def repository_id() -> str | None:
    return perf_repository_id()


# ---------------------------------------------------------------------------
# YAML 로더 — scenarios + thresholds
# ---------------------------------------------------------------------------


def _load_yaml(name: str) -> dict[str, Any]:
    path = Path(__file__).resolve().parent / name
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@pytest.fixture(scope="session")
def scenarios() -> dict[str, Any]:
    return _load_yaml("scenarios.yml")


@pytest.fixture(scope="session")
def thresholds() -> dict[str, Any]:
    return _load_yaml("thresholds.yml")


# ---------------------------------------------------------------------------
# Auth + httpx client
# ---------------------------------------------------------------------------


def _auth_headers() -> dict[str, str]:
    headers = {"X-Tenant-Id": perf_tenant_id()}
    token = os.environ.get("PERF_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


@pytest.fixture(scope="session")
def auth_headers() -> dict[str, str]:
    return _auth_headers()


@pytest.fixture(scope="session")
def base_url() -> str:
    return perf_base_url()


@pytest.fixture
async def perf_client(base_url: str, auth_headers: dict[str, str]):
    """Async httpx client with auth + perf-tuned timeouts.

    Mock mode (PERF_MOCK=1) routes through an in-memory transport that fakes
    a 50ms latency so output schema is exercised without a live API.
    """
    if perf_is_mock():
        transport = httpx.MockTransport(_mock_handler)
        async with httpx.AsyncClient(
            base_url=base_url,
            headers=auth_headers,
            timeout=PERF_TIMEOUT_S,
            transport=transport,
        ) as client:
            yield client
        return

    async with httpx.AsyncClient(
        base_url=base_url,
        headers=auth_headers,
        timeout=PERF_TIMEOUT_S,
    ) as client:
        yield client


def _mock_handler(request: httpx.Request) -> httpx.Response:
    """Deterministic mock for PERF_MOCK=1 mode."""
    # 50ms 작업 흉내 — perf_counter 가 측정값에 반영되도록 sleep
    time.sleep(0.05)
    path = request.url.path
    if path.endswith("/assist-stream"):
        body = (
            b'event: intent\ndata: {"intent":"qa"}\n\n'
            b'event: sources\ndata: {"sources":[]}\n\n'
            b'event: token\ndata: {"text":"mock"}\n\n'
            b'event: done\ndata: {}\n\n'
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    if "/documents" in path and request.method == "POST":
        return httpx.Response(202, json={"data": {"document_id": "00000000-0000-0000-0000-000000000001"}})
    if "/documents/" in path and request.method == "GET":
        return httpx.Response(200, json={"data": {"status": "active"}})
    return httpx.Response(200, json={"data": {"results": [], "total": 0}})


# ---------------------------------------------------------------------------
# Measurement primitive — 통계 누적기
# ---------------------------------------------------------------------------


@dataclass
class LatencySamples:
    label: str
    samples_ms: list[float] = field(default_factory=list)
    errors: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def add(self, elapsed_ms: float) -> None:
        self.samples_ms.append(elapsed_ms)

    def add_error(self) -> None:
        self.errors += 1

    def percentile(self, p: float) -> float:
        if not self.samples_ms:
            return 0.0
        # statistics.quantiles 는 n>=2 필요 — 단일 샘플은 그대로 반환
        if len(self.samples_ms) == 1:
            return self.samples_ms[0]
        sorted_s = sorted(self.samples_ms)
        # 보간 없는 nearest-rank — 작은 표본에서 안정적
        k = max(0, min(len(sorted_s) - 1, int(round(p / 100.0 * (len(sorted_s) - 1)))))
        return sorted_s[k]

    def summary(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "count": len(self.samples_ms),
            "errors": self.errors,
            "mean_ms": round(statistics.fmean(self.samples_ms), 2) if self.samples_ms else 0.0,
            "p50_ms": round(self.percentile(50), 2),
            "p95_ms": round(self.percentile(95), 2),
            "p99_ms": round(self.percentile(99), 2),
            "min_ms": round(min(self.samples_ms), 2) if self.samples_ms else 0.0,
            "max_ms": round(max(self.samples_ms), 2) if self.samples_ms else 0.0,
            "extra": self.extra,
        }


class StopWatch:
    """Context manager — perf_counter 기반 wall clock 측정."""

    def __init__(self) -> None:
        self.start_ns: int = 0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> "StopWatch":
        self.start_ns = time.perf_counter_ns()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.elapsed_ms = (time.perf_counter_ns() - self.start_ns) / 1_000_000.0


# ---------------------------------------------------------------------------
# Report 출력 — JSON
# ---------------------------------------------------------------------------


def write_report(filename: str, payload: dict[str, Any]) -> Path:
    out_dir = perf_output_dir()
    out_path = out_dir / filename
    payload.setdefault("profile", perf_profile())
    payload.setdefault("base_url", perf_base_url())
    payload.setdefault("tenant_id", perf_tenant_id())
    payload.setdefault("generated_at_utc", datetime.now(timezone.utc).isoformat())
    payload.setdefault("mock", perf_is_mock())
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


@pytest.fixture(scope="session")
def report_writer():
    return write_report


# ---------------------------------------------------------------------------
# tenant uuid 검증
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _validate_tenant_id() -> None:
    try:
        UUID(perf_tenant_id())
    except ValueError as exc:
        pytest.fail(f"PERF_TENANT_ID is not a valid UUID: {exc}")


# ---------------------------------------------------------------------------
# pytest 마커 등록
# ---------------------------------------------------------------------------


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "perf: performance benchmark — runs against PERF_BASE_URL, skip with PERF_MOCK=1 friendly",
    )
