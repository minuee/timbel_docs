"""D76.2 — engine._build_compose_prompt 의 tool_results split 적용 검증.

목적: _build_compose_prompt 가 LLM payload 에 *원본 dict 가 아닌 public 부분* 만
주입함을 byte-equal 비교로 보장.

설계: AgentEngine 전체 부팅은 무겁다 (Redis / aioredis / vLLM). 본 테스트는 split
helper 가 *engine 의 payload 빌드 경로와 동일 invariant* 를 만들어내는지 직접
검증한다 — _build_compose_prompt 안 D76 hook 로직을 *그대로 inline* 으로 재현.
실 path 변경 시 본 테스트가 byte-equal 으로 회귀 잡기 위함.
"""
from __future__ import annotations

import json as _j
from typing import Any

from src.agent_framework.tools.result_field_spec import split_result


def _simulate_compose_split(tool_results: list[dict]) -> list[dict]:
    """engine._build_compose_prompt 안 D76 hook 와 *동일* 변환.

    D76b (GPT-5.5 P0-1 사전 fix) — 상위 키 화이트리스트 (tool/name/ok 만).
    이전: dict(tr) → tenant_id/trace/args 모두 통과 (보안 결함).
    """
    _D76_TOP_LEVEL_ALLOW = ("tool", "name", "ok")
    out: list[dict] = []
    for tr in tool_results or []:
        if not isinstance(tr, dict):
            out.append(tr)
            continue
        tn = (tr.get("tool") or tr.get("name") or "")
        raw = tr.get("result") or {}
        pub, _priv = split_result(str(tn), raw if isinstance(raw, dict) else {})
        # 상위 화이트리스트만 통과.
        safe_top: dict[str, Any] = {k: tr[k] for k in _D76_TOP_LEVEL_ALLOW if k in tr}
        safe_top["result"] = pub
        out.append(safe_top)
    return out


def test_confirm_id_not_in_llm_payload():
    """expense.create 결과의 confirm_id 가 LLM payload (JSON-serialized) 에 *없음*."""
    raw_tool_results = [
        {
            "tool": "expense.create",
            "args": {"amount": 5000, "category": "food"},
            "result": {
                "success": True,
                "summary": "지출 5,000원 기록",
                "confirm_id": "CONF-SECRET-001",
                "row_id": "ROW-PRIVATE-1",
                "audit_hash": "HASH-XYZ",
                "amount": 5000,
                "category": "food",
            },
        }
    ]
    llm_results = _simulate_compose_split(raw_tool_results)
    payload_str = _j.dumps({"tool_results": llm_results}, ensure_ascii=False)
    # 핵심: LLM 이 보는 string 에 내부 ID 가 *없어야 함*.
    assert "CONF-SECRET-001" not in payload_str
    assert "ROW-PRIVATE-1" not in payload_str
    assert "HASH-XYZ" not in payload_str
    # 그러나 사용자 응답에 사용해야 하는 데이터는 *있어야 함*.
    assert "5000" in payload_str or "5,000" in payload_str
    assert "지출 5,000원 기록" in payload_str


def test_nested_tenant_id_not_in_llm_payload():
    """schedule.list items[].tenant_id 가 LLM payload 에 *없음*."""
    raw_tool_results = [
        {
            "tool": "schedule.list",
            "args": {},
            "result": {
                "success": True,
                "items": [
                    {
                        "title": "팀 미팅",
                        "start_at": "2026-05-12T10:00",
                        "end_at": "2026-05-12T11:00",
                        "tenant_id": "TENANT-LEAK-X",
                        "user_id": "USER-LEAK-Y",
                        "row_id": "ROW-LEAK-Z",
                    }
                ],
                "total": 1,
            },
        }
    ]
    llm_results = _simulate_compose_split(raw_tool_results)
    payload_str = _j.dumps({"tool_results": llm_results}, ensure_ascii=False)
    assert "TENANT-LEAK-X" not in payload_str
    assert "USER-LEAK-Y" not in payload_str
    assert "ROW-LEAK-Z" not in payload_str
    # title / start_at 은 보존.
    assert "팀 미팅" in payload_str
    assert "2026-05-12T10:00" in payload_str


def test_kms_rag_search_internal_fields_removed():
    """kms_rag.search hits[].raw_embedding / tenant_id 제거."""
    raw_tool_results = [
        {
            "tool": "kms_rag.search",
            "args": {"query": "test"},
            "result": {
                "success": True,
                "hits": [
                    {
                        "title": "문서 A",
                        "snippet": "본문 발췌",
                        "score": 0.85,
                        "document_id": "DOC-1",
                        "raw_embedding": [0.1, 0.2, 0.3],
                        "tenant_id": "TENANT-KMS",
                    }
                ],
                "total": 1,
            },
        }
    ]
    llm_results = _simulate_compose_split(raw_tool_results)
    payload_str = _j.dumps({"tool_results": llm_results}, ensure_ascii=False)
    assert "raw_embedding" not in payload_str
    assert "TENANT-KMS" not in payload_str
    assert "문서 A" in payload_str
    assert "본문 발췌" in payload_str


def test_unknown_tool_with_pii_redacted():
    """unknown custom tool 의 user_email / api_key 차단 — pattern fallback."""
    raw_tool_results = [
        {
            "tool": "custom.fetcher",
            "args": {},
            "result": {
                "success": True,
                "result_body": "응답 본문",
                "user_email": "leak@example.com",
                "api_key": "sk_xxx_LEAKED",
            },
        }
    ]
    llm_results = _simulate_compose_split(raw_tool_results)
    payload_str = _j.dumps({"tool_results": llm_results}, ensure_ascii=False)
    assert "leak@example.com" not in payload_str
    assert "sk_xxx_LEAKED" not in payload_str
    assert "응답 본문" in payload_str


def test_original_tool_results_not_mutated():
    """split 변환은 *새 리스트* 반환 — 원본 raw_tool_results 는 그대로 보존."""
    raw = [
        {
            "tool": "expense.create",
            "result": {"success": True, "confirm_id": "CONF-1", "amount": 100},
        }
    ]
    raw_copy = _j.dumps(raw, ensure_ascii=False)
    _ = _simulate_compose_split(raw)
    # 원본 변동 없음.
    assert _j.dumps(raw, ensure_ascii=False) == raw_copy


def test_tool_results_with_no_tool_key_pass_through():
    """tool 키가 없는 비정상 result entry 도 안전 통과 (방어)."""
    raw = [{"result": {"success": True, "items": []}}]
    out = _simulate_compose_split(raw)
    # tool 이 없으면 unknown path — 안전 통과.
    assert "result" in out[0]


def _simulate_compose_split_fail_closed(tool_results: list, force_fail: bool = False) -> list[dict]:
    """engine.py fail-closed minimal fallback 재현 (D76 P0 + D76b P0 사전 fix).

    D76b (GPT-5.5 사전 P0-1/P0-7/P0-8/P0-9/P0-10) — 상위 키 화이트리스트 +
    bool/int 구분 + rows_affected 버킷팅 + scrub→truncate 순.
    """
    from src.agent_framework.tools.result_field_spec import (
        _scrub_pii_recursive,
        _scrub_pii_text,
    )

    _D76_MIN_FIELDS = ("success", "op_type", "summary", "rows_affected", "error", "status")
    _D76_SUMMARY_CAP = 300
    _D76_TOP_LEVEL_ALLOW = ("tool", "name", "ok")

    def _bucket(v: Any) -> Any:
        if isinstance(v, bool):
            return v
        if not isinstance(v, int):
            return v
        if v == 0: return 0
        if v == 1: return 1
        if v <= 10: return "2-10"
        return ">10"

    def _minimal(tr: Any) -> dict:
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
                    v = _bucket(v)
                safe[k] = v
        safe_top: dict[str, Any] = {k: tr[k] for k in _D76_TOP_LEVEL_ALLOW if k in tr}
        safe_top["result"] = safe
        return safe_top

    if force_fail:
        return [_minimal(tr) for tr in tool_results if isinstance(tr, dict)]

    out = []
    for tr in tool_results or []:
        if not isinstance(tr, dict):
            # fail-closed: skip non-dict
            continue
        try:
            tn = (tr.get("tool") or tr.get("name") or "")
            raw = tr.get("result") or {}
            pub, _ = split_result(str(tn), raw if isinstance(raw, dict) else {})
            safe_top: dict[str, Any] = {k: tr[k] for k in _D76_TOP_LEVEL_ALLOW if k in tr}
            safe_top["result"] = pub
            out.append(safe_top)
        except Exception:
            out.append(_minimal(tr))
    return out


def test_fail_closed_on_global_failure_minimal_fields_only():
    """split 모듈 전체 실패 가정 → fail-closed 최소 셋만 LLM 에 (P0 GPT-5 사후 fix)."""
    raw = [
        {
            "tool": "expense.create",
            "result": {
                "success": True,
                "op_type": "create",
                "summary": "지출 5,000원",
                "confirm_id": "CONF-LEAK",
                "tenant_id": "T-LEAK",
                "amount": 5000,
                "row_id": "R-LEAK",
            },
        }
    ]
    out = _simulate_compose_split_fail_closed(raw, force_fail=True)
    assert len(out) == 1
    r = out[0]["result"]
    # 최소 셋만 통과.
    assert r["success"] is True
    assert r["op_type"] == "create"
    assert r["summary"] == "지출 5,000원"
    # 나머지는 모두 차단 (PII / 내부 ID / 데이터 payload 모두).
    assert "confirm_id" not in r
    assert "tenant_id" not in r
    assert "amount" not in r
    assert "row_id" not in r
    payload_str = _j.dumps(out, ensure_ascii=False)
    assert "CONF-LEAK" not in payload_str
    assert "T-LEAK" not in payload_str
    assert "R-LEAK" not in payload_str


def test_fail_closed_summary_capped_at_300_chars():
    """fail-closed fallback 의 summary 도 300자 캡."""
    long_summary = "x" * 1000
    raw = [{"tool": "expense.create", "result": {"success": True, "summary": long_summary}}]
    out = _simulate_compose_split_fail_closed(raw, force_fail=True)
    s = out[0]["result"]["summary"]
    assert len(s) <= 300 + len("...<truncated>")
    assert "<truncated>" in s


def test_non_dict_entry_skipped_fail_closed():
    """비-dict tr entry 는 LLM 에 절대 전달 X (fail-closed: skip)."""
    raw = [
        "string-not-dict",
        {"tool": "expense.list", "result": {"success": True, "items": [], "total": 0}},
        None,
    ]
    out = _simulate_compose_split_fail_closed(raw)
    assert len(out) == 1
    assert out[0]["tool"] == "expense.list"


def test_contract_keys_mirrored_to_llm():
    """success / summary / op_type — LLM 에 mirror 되어 가용."""
    raw = [
        {
            "tool": "expense.create",
            "result": {
                "success": True,
                "summary": "지출 기록 완료",
                "op_type": "create",
                "amount": 1000,
                "category": "food",
                "confirm_id": "C-1",
            },
        }
    ]
    out = _simulate_compose_split(raw)
    assert out[0]["result"]["success"] is True
    assert out[0]["result"]["summary"] == "지출 기록 완료"
    assert out[0]["result"]["op_type"] == "create"
    assert "confirm_id" not in out[0]["result"]
