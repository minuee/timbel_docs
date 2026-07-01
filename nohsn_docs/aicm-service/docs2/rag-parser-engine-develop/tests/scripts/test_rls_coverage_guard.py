"""D34 §3 — CI 정적 가드 (`scripts/ci/check_rls_coverage.py`) unit test.

양성 (wrap 정상) / 음성 (wrap 누락) / 면제 (마커) 3 fixture 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path

# scripts/ci 를 path 에 추가 (test 환경).
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import check_rls_coverage  # type: ignore[import-not-found]  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "rls_coverage_fixture"


def test_positive_worker_passes():
    """wrap 정상 적용된 fixture — PASS."""
    fails, details = check_rls_coverage.check_coverage(
        ROOT,
        sites=[
            (
                "tests/scripts/fixtures/rls_coverage_fixture/positive_worker.py",
                "handle_event",
            ),
        ],
    )
    assert fails == 0, f"positive fixture should pass: {details}"
    assert any("PASS" in d for d in details)


def test_negative_worker_fails():
    """wrap 누락 fixture — FAIL."""
    fails, details = check_rls_coverage.check_coverage(
        ROOT,
        sites=[
            (
                "tests/scripts/fixtures/rls_coverage_fixture/negative_worker.py",
                "handle_event",
            ),
        ],
    )
    assert fails == 1, f"negative fixture should fail: {details}"
    assert any("FAIL" in d for d in details)
    assert any("no RLS wrap" in d for d in details)


def test_exempt_worker_passes_via_marker():
    """docstring 마커 fixture — PASS (면제)."""
    fails, details = check_rls_coverage.check_coverage(
        ROOT,
        sites=[
            (
                "tests/scripts/fixtures/rls_coverage_fixture/exempt_worker.py",
                "handle_event",
            ),
        ],
    )
    assert fails == 0, f"exempt fixture should pass: {details}"
    assert any("exempt" in d for d in details)


def test_real_repo_sites_all_pass():
    """실제 repo 의 REQUIRED_SITES 가 모두 PASS — 회귀 가드."""
    fails, details = check_rls_coverage.check_coverage(ROOT)
    assert fails == 0, (
        f"real repo RLS coverage 누락 site 발견: "
        + "\n".join(d for d in details if "FAIL" in d)
    )


def test_missing_function_fails():
    """함수가 없으면 FAIL."""
    fails, details = check_rls_coverage.check_coverage(
        ROOT,
        sites=[
            (
                "tests/scripts/fixtures/rls_coverage_fixture/positive_worker.py",
                "nonexistent_function",
            ),
        ],
    )
    assert fails == 1
    assert any("not found" in d for d in details)


def test_missing_file_fails():
    """파일이 없으면 FAIL."""
    fails, details = check_rls_coverage.check_coverage(
        ROOT,
        sites=[
            ("src/no_such_file_xyz.py", "func"),
        ],
    )
    assert fails == 1
    assert any("file not found" in d for d in details)


def test_nested_only_inner_fails():
    """outer 가 wrap 안 하고 inner 만 wrap — FAIL (GPT-5 §3 권고)."""
    fails, details = check_rls_coverage.check_coverage(
        ROOT,
        sites=[
            (
                "tests/scripts/fixtures/rls_coverage_fixture/nested_only_inner.py",
                "handle_event",
            ),
        ],
    )
    assert fails == 1, (
        f"nested-only-inner fixture should FAIL (outer 가 wrap 안 함): {details}"
    )
    assert any("no RLS wrap" in d for d in details)
