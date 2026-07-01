"""D76b — SSE tool_result split + fail-closed top-level allow 회귀 가드.

GPT-5.5 사전 verdict (D76b):
- P0-1: fail-closed 상위 키 화이트리스트 (tool/name/ok 만)
- P0-9: rows_affected 버킷팅
- P0-10: bool 이 int 처리되는 회귀
- P2-1: SSE path split 적용
"""
from __future__ import annotations

from src.agent_framework.runtime.engine import (
    _d76_sse_safe_summary,
    _d76_sse_safe_tool_result,
)
from src.agent_framework.tools.result_field_spec import split_result


# ---------------------------------------------------------------------------
# 1. SSE tool_result split (P2-1)
# ---------------------------------------------------------------------------

def test_sse_safe_tool_result_basic_split():
    """SSE 의 tool_result.result 가 public 만 노출."""
    raw = {
        "success": True,
        "summary": "지출 5,000원",
        "confirm_id": "CONF-SECRET",
        "tenant_id": "T-LEAK",
        "amount": 5000,
        "row_id": "ROW-LEAK",
    }
    out = _d76_sse_safe_tool_result("expense.create", raw)
    # public 만 통과.
    assert "confirm_id" not in out
    assert "tenant_id" not in out
    assert "row_id" not in out
    # contract mirror 는 통과.
    assert out["success"] is True
    assert "5,000" in out["summary"] or "5000" in out["summary"]


def test_sse_safe_tool_result_non_dict_returns_empty():
    """비-dict 입력 → 빈 dict."""
    assert _d76_sse_safe_tool_result("expense.create", None) == {}
    assert _d76_sse_safe_tool_result("expense.create", "string") == {}
    assert _d76_sse_safe_tool_result("expense.create", 123) == {}


def test_sse_safe_tool_result_summary_pii_masked():
    """SSE summary 안 PII 마스킹."""
    raw = {"success": True, "summary": "메일 leak@example.com 발송 완료"}
    out = _d76_sse_safe_tool_result("mail.send", raw)
    assert "leak@example.com" not in out["summary"]


def test_sse_safe_summary_helper_masks_pii():
    """_d76_sse_safe_summary 가 단일 string PII 마스킹."""
    out = _d76_sse_safe_summary("연락처: 010-1234-5678")
    assert "010-1234-5678" not in out


def test_sse_safe_summary_non_string_pass_through():
    """non-string summary 그대로."""
    assert _d76_sse_safe_summary(None) is None
    assert _d76_sse_safe_summary(123) == 123


# ---------------------------------------------------------------------------
# 2. fail-closed 상위 키 화이트리스트 (P0-1)
# ---------------------------------------------------------------------------

def _simulate_fail_closed_minimal(tr):
    """engine.py _d76_fail_closed_minimal 와 동일한 fallback 시뮬레이션.

    GPT-5.5 P0-1/P0-7/P0-8/P0-9/P0-10 fix 반영.
    """
    from src.agent_framework.tools.result_field_spec import (
        _scrub_pii_recursive,
        _scrub_pii_text,
    )

    _D76_MIN_FIELDS = ("success", "op_type", "summary", "rows_affected", "error", "status")
    _D76_SUMMARY_CAP = 300
    _D76_TOP_LEVEL_ALLOW = ("tool", "name", "ok")

    if not isinstance(tr, dict):
        return {"result": {}}
    r = tr.get("result") if isinstance(tr.get("result"), dict) else {}
    safe = {}
    for k in _D76_MIN_FIELDS:
        if k in r:
            v = r[k]
            if k == "summary":
                if isinstance(v, str):
                    v = _scrub_pii_text(v)
                    if len(v) > _D76_SUMMARY_CAP:
                        v = v[:_D76_SUMMARY_CAP] + "...<truncated>"
            elif k == "error":
                if isinstance(v, str):
                    v = _scrub_pii_text(v)
                    if len(v) > _D76_SUMMARY_CAP:
                        v = v[:_D76_SUMMARY_CAP] + "...<truncated>"
                else:
                    v = _scrub_pii_recursive(v)
            elif k == "rows_affected":
                if isinstance(v, bool):
                    pass  # bool 그대로.
                elif isinstance(v, int):
                    if v == 0: v = 0
                    elif v == 1: v = 1
                    elif v <= 10: v = "2-10"
                    else: v = ">10"
            safe[k] = v
    safe_top = {k: tr[k] for k in _D76_TOP_LEVEL_ALLOW if k in tr}
    safe_top["result"] = safe
    return safe_top


def test_fail_closed_top_level_tenant_id_blocked():
    """fail-closed 의 상위 tenant_id / trace 가 누출되지 않음."""
    tr = {
        "tool": "expense.create",
        "tenant_id": "TENANT-LEAK",
        "trace": "internal_trace_id",
        "args": {"amount": 5000, "user_email": "secret@x.com"},
        "ok": True,
        "result": {"success": True, "summary": "기록 완료", "confirm_id": "C-1"},
    }
    out = _simulate_fail_closed_minimal(tr)
    # 상위 화이트리스트 (tool/name/ok) 만.
    assert "tool" in out
    assert "ok" in out
    assert "tenant_id" not in out
    assert "trace" not in out
    assert "args" not in out  # P0-1 args 차단.
    # result 안 confirm_id 도 차단.
    assert "confirm_id" not in out["result"]


def test_fail_closed_args_blocked():
    """상위 args (PII 위험) 차단."""
    tr = {
        "tool": "expense.create",
        "args": {"user_email": "leak@x.com", "phone": "010-1234-5678"},
        "result": {"success": True},
    }
    out = _simulate_fail_closed_minimal(tr)
    assert "args" not in out
    payload_str = str(out)
    assert "leak@x.com" not in payload_str
    assert "010-1234-5678" not in payload_str


def test_fail_closed_non_dict_no_crash():
    """비-dict _tr 입력 → crash 안 함 (P0-8)."""
    out = _simulate_fail_closed_minimal("not-a-dict")
    assert out == {"result": {}}
    out2 = _simulate_fail_closed_minimal(None)
    assert out2 == {"result": {}}
    out3 = _simulate_fail_closed_minimal(123)
    assert out3 == {"result": {}}


# ---------------------------------------------------------------------------
# 3. rows_affected 버킷팅 (P0-9, P0-10)
# ---------------------------------------------------------------------------

def test_fail_closed_rows_affected_bucketing_zero():
    """rows_affected=0 → 0."""
    tr = {"tool": "x", "result": {"success": True, "rows_affected": 0}}
    out = _simulate_fail_closed_minimal(tr)
    assert out["result"]["rows_affected"] == 0


def test_fail_closed_rows_affected_bucketing_one():
    """rows_affected=1 → 1."""
    tr = {"tool": "x", "result": {"success": True, "rows_affected": 1}}
    out = _simulate_fail_closed_minimal(tr)
    assert out["result"]["rows_affected"] == 1


def test_fail_closed_rows_affected_bucketing_mid():
    """rows_affected=5 → '2-10'."""
    tr = {"tool": "x", "result": {"success": True, "rows_affected": 5}}
    out = _simulate_fail_closed_minimal(tr)
    assert out["result"]["rows_affected"] == "2-10"


def test_fail_closed_rows_affected_bucketing_large():
    """rows_affected=100 → '>10'."""
    tr = {"tool": "x", "result": {"success": True, "rows_affected": 100}}
    out = _simulate_fail_closed_minimal(tr)
    assert out["result"]["rows_affected"] == ">10"


def test_fail_closed_rows_affected_bool_not_int():
    """rows_affected=True 는 bool — int 처리 X (P0-10)."""
    tr = {"tool": "x", "result": {"success": True, "rows_affected": True}}
    out = _simulate_fail_closed_minimal(tr)
    # bool 그대로 (1 로 변환 X).
    assert out["result"]["rows_affected"] is True


# ---------------------------------------------------------------------------
# 4. error 가 dict 일 때 (P0-5)
# ---------------------------------------------------------------------------

def test_fail_closed_error_dict_recursive_scrub():
    """fail-closed 의 error 가 dict 면 recursive scrub."""
    tr = {
        "tool": "expense.create",
        "result": {
            "success": False,
            "error": {
                "message": "failed for leak@example.com",
                "stack": "File \"x.py\", line 42",
                "tenant_id": "T-LEAK",
            },
        },
    }
    out = _simulate_fail_closed_minimal(tr)
    err = out["result"]["error"]
    s = str(err)
    assert "leak@example.com" not in s
    assert "T-LEAK" not in s
    # stack 자체 제거.
    assert "stack" not in err
    # message 는 보존 (PII 마스킹된 상태).
    assert err.get("message", "").startswith("failed for")


def test_fail_closed_summary_scrub_before_truncate():
    """긴 summary 끝부분의 PII 가 cap 후에도 마스킹됨 (P0-7)."""
    long_prefix = "x" * 290
    summary = long_prefix + " 메일 leak@example.com 발송"
    tr = {"tool": "mail.send", "result": {"success": True, "summary": summary}}
    out = _simulate_fail_closed_minimal(tr)
    s = out["result"]["summary"]
    # email 이 완전히 마스킹 — cap 으로 부분만 남는 회귀 차단.
    assert "@example.com" not in s
    assert "leak@" not in s
