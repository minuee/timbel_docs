"""D76 — result_field_spec.py 단위 테스트.

split_result + ToolResultView 의 핵심 invariant 검증:
1. PII / 내부 ID 가 public 에 *절대* 가지 않음.
2. evidence key (confirm_id) 는 private 에만, adversarial_checker 호환.
3. PUBLIC_FIELDS 등록 도구 = strong allowlist.
4. unknown tool = SENSITIVE_PATTERNS + 사이즈 캡.
5. Contract mirror key 양쪽 모두 존재.
6. nested items[] 의 tenant_id 도 deep walk 제거.
"""
from __future__ import annotations

from src.agent_framework.tools.result_field_spec import (
    PRIVATE_FIELDS,
    PUBLIC_FIELDS,
    SENSITIVE_PATTERNS,
    ToolResultView,
    split_result,
)


def test_known_tool_allowlist_keeps_only_public_fields():
    """expense.list — items + total + summary 만 public, 나머지는 private."""
    raw = {
        "success": True,
        "items": [{"amount": 5000, "category": "food"}],
        "total": 5000,
        "summary": "1건",
        "tenant_id": "TENANT_X",  # blocklist
        "_internal_query": "SELECT...",  # underscore prefix → sensitive
    }
    pub, priv = split_result("expense.list", raw)
    assert "items" in pub
    assert pub["total"] == 5000
    assert pub["summary"] == "1건"
    assert "tenant_id" not in pub
    assert "_internal_query" not in pub
    assert priv["tenant_id"] == "TENANT_X"


def test_confirm_id_in_private_only():
    """state-change 결과의 confirm_id 는 private only — LLM 노출 X."""
    raw = {
        "success": True,
        "summary": "지출 5,000원 기록",
        "confirm_id": "CONF-ABC-123",
        "op_type": "create",
        "rows_affected": 1,
    }
    pub, priv = split_result("expense.create", raw)
    assert "confirm_id" not in pub
    assert priv["confirm_id"] == "CONF-ABC-123"
    # op_type / rows_affected 는 contract mirror — 양쪽.
    assert pub["op_type"] == "create"
    assert priv["op_type"] == "create"
    assert pub["rows_affected"] == 1
    assert priv["rows_affected"] == 1


def test_evidence_id_in_private_only():
    """evidence_id 도 confirm_id 와 동일 — private only."""
    raw = {"success": True, "evidence_id": "EV-999", "summary": "완료"}
    pub, priv = split_result("schedule.create", raw)
    assert "evidence_id" not in pub
    assert priv["evidence_id"] == "EV-999"


def test_nested_items_tenant_id_removed():
    """items[].tenant_id 도 deep walk 로 제거 — schedule.list."""
    raw = {
        "success": True,
        "items": [
            {"title": "회의", "start_at": "2026-05-12", "tenant_id": "TENANT_A", "row_id": "RW-1"},
            {"title": "점심", "start_at": "2026-05-13", "user_id": "USR-99"},
        ],
        "total": 2,
    }
    pub, _priv = split_result("schedule.list", raw)
    # allowlist 의 sub_allowlist 가 title/start_at/end_at/location/attendees 만 통과.
    assert pub["items"][0] == {"title": "회의", "start_at": "2026-05-12"}
    assert "tenant_id" not in pub["items"][0]
    assert "row_id" not in pub["items"][0]
    assert "user_id" not in pub["items"][1]


def test_unknown_tool_sensitive_keys_removed():
    """custom_tool (PUBLIC_FIELDS 미등록) — sensitive key 만 제거, 나머지 통과."""
    raw = {
        "success": True,
        "result_data": "응답 본문",
        "audit_hash": "ABCDEF",  # *_hash → sensitive
        "user_email": "test@example.com",  # email pattern
        "api_key": "sk_123",  # api_key pattern
        "phone_number": "010-1234-5678",
        "harmless_field": "정상 값",
    }
    pub, priv = split_result("custom.my_tool", raw)
    assert pub["result_data"] == "응답 본문"
    assert pub["harmless_field"] == "정상 값"
    assert "audit_hash" not in pub
    assert "user_email" not in pub
    assert "api_key" not in pub
    assert "phone_number" not in pub
    # private 에는 원본 보관 (저장 path 용).
    assert priv["audit_hash"] == "ABCDEF"


def test_legacy_prefix_blocked_for_llm():
    """D73 의 _legacy:<key> stash 가 LLM 에 노출되지 않음."""
    raw = {
        "success": True,
        "summary": "조회 완료",
        "_legacy:confirm_id": "STASH-1",
        "_structured_card": {"type": "expense"},  # 화이트리스트 — 통과.
    }
    pub, _priv = split_result("custom.unknown_tool", raw)
    assert "_legacy:confirm_id" not in pub
    # _structured_card 는 contract mirror — 양쪽.
    assert pub["_structured_card"] == {"type": "expense"}


def test_contract_keys_mirrored():
    """success / summary / meta / op_type / status — 양쪽 모두 미러."""
    raw = {
        "success": True,
        "summary": "test",
        "meta": {"outcome": "ok"},
        "op_type": "update",
        "status": "ok",
        "items": [],
        "total": 0,
    }
    pub, priv = split_result("schedule.list", raw)
    for k in ("success", "summary", "meta", "op_type", "status"):
        assert pub[k] == raw[k], f"{k} missing in public"
        assert priv[k] == raw[k], f"{k} missing in private"


def test_unknown_tool_long_string_truncated():
    """unknown tool 의 긴 문자열 — 사이즈 캡 적용."""
    long_text = "x" * 5000
    raw = {"success": True, "body": long_text}
    pub, _priv = split_result("custom.fetcher", raw)
    assert len(pub["body"]) < 5000
    assert pub["body"].endswith("...<truncated>")


def test_tool_result_view_for_checker_has_evidence():
    """ToolResultView.for_checker() — adversarial_checker 가 confirm_id 정상 접근."""
    raw = {"success": True, "confirm_id": "CONF-X", "op_type": "create", "summary": "OK"}
    view = ToolResultView.from_raw("expense.create", raw)
    llm_view = view.for_llm()
    check_view = view.for_checker()
    assert "confirm_id" not in llm_view
    assert check_view["confirm_id"] == "CONF-X"
    # success/op_type 는 양쪽 동일.
    assert llm_view["success"] is True
    assert check_view["success"] is True


def test_email_in_known_tool_passes_via_allowlist():
    """mail.search — items[].sender 가 email pattern 이지만 *서브 allowlist* 에 명시 → public.

    이게 known tool 의 강점 — domain 별로 명확히 `허용` 결정.
    """
    raw = {
        "success": True,
        "items": [
            {"sender": "alice@example.com", "subject": "회의", "date": "2026-05-12", "tenant_id": "T"},
        ],
        "total": 1,
    }
    pub, _priv = split_result("mail.search", raw)
    # sender 는 allowlist → public 통과.
    assert pub["items"][0]["sender"] == "alice@example.com"
    # tenant_id 는 allowlist 외 → 제거.
    assert "tenant_id" not in pub["items"][0]


def test_none_or_invalid_result_returns_empty_dicts():
    """result is None or 비-dict → 둘 다 빈 dict."""
    pub, priv = split_result("expense.list", None)
    assert pub == {}
    assert priv == {}
    pub2, priv2 = split_result("expense.list", "string-not-dict")  # type: ignore[arg-type]
    assert pub2 == {}
    assert priv2 == {}


def test_known_tool_extra_field_goes_to_private():
    """expense.list 결과에 allowlist 미포함 새 field 추가 → private 으로 격리."""
    raw = {
        "success": True,
        "items": [],
        "total": 0,
        "experimental_data": {"foo": "bar"},
    }
    pub, priv = split_result("expense.list", raw)
    assert "experimental_data" not in pub
    assert priv["experimental_data"] == {"foo": "bar"}


def test_blocklist_overrides_potential_public_match():
    """expense.create — row_id 가 blocklist 명시 → public 절대 X."""
    raw = {
        "success": True,
        "amount": 5000,
        "row_id": "R-1",  # blocklist
        "audit_hash": "H-1",  # blocklist
        "summary": "OK",
    }
    pub, priv = split_result("expense.create", raw)
    assert "row_id" not in pub
    assert "audit_hash" not in pub
    assert priv["row_id"] == "R-1"
    assert priv["audit_hash"] == "H-1"


def test_sensitive_patterns_match_known_keys():
    """SENSITIVE_PATTERNS 의 핵심 매칭 검증 (재귀 검사 helper 용)."""
    from src.agent_framework.tools.result_field_spec import _is_sensitive_key

    # _hash$ 패턴
    assert _is_sensitive_key("audit_hash")
    assert _is_sensitive_key("checksum_hash")
    # underscore prefix
    assert _is_sensitive_key("_internal_query")
    # _structured_card 는 예외
    assert not _is_sensitive_key("_structured_card")
    # PII patterns
    assert _is_sensitive_key("user_email")
    assert _is_sensitive_key("phone_number")
    assert _is_sensitive_key("phone")
    assert _is_sensitive_key("ssn")
    # api_key
    assert _is_sensitive_key("api_key")
    assert _is_sensitive_key("apikey")
    # access/refresh token
    assert _is_sensitive_key("access_token")
    assert _is_sensitive_key("refresh_token")
    # 정상 key (false positive 없어야)
    assert not _is_sensitive_key("title")
    assert not _is_sensitive_key("amount")
    assert not _is_sensitive_key("summary")
    assert not _is_sensitive_key("items")


def test_legacy_prefix_blocked_by_pattern():
    """_legacy:<key> (D73 stash) 가 SENSITIVE_PATTERNS 의 underscore prefix 패턴에 매치."""
    from src.agent_framework.tools.result_field_spec import _is_sensitive_key

    assert _is_sensitive_key("_legacy:confirm_id")
    assert _is_sensitive_key("_legacy:op_type")


def test_kms_rag_hits_allowlist():
    """kms_rag.search — hits[].title/snippet/score 만 public, internal fields 제거."""
    raw = {
        "success": True,
        "hits": [
            {
                "title": "문서 A",
                "snippet": "본문 ...",
                "score": 0.85,
                "document_id": "DOC-1",
                "tenant_id": "T",  # 제거
                "raw_embedding": [0.1, 0.2, 0.3],  # 제거
            }
        ],
        "total": 1,
    }
    pub, _priv = split_result("kms_rag.search", raw)
    assert pub["hits"][0]["title"] == "문서 A"
    assert pub["hits"][0]["score"] == 0.85
    assert "tenant_id" not in pub["hits"][0]
    assert "raw_embedding" not in pub["hits"][0]


def test_compiled_patterns_are_pattern_objects():
    """SENSITIVE_PATTERNS 가 *컴파일된* 정규식 — performance 보장."""
    import re

    for p in SENSITIVE_PATTERNS:
        assert isinstance(p, re.Pattern)


def test_structured_card_deep_scrub_removes_nested_pii():
    """GPT-5 사후 P1 fix — _structured_card 내부 자유 텍스트 PII 도 deep scrub."""
    raw = {
        "success": True,
        "summary": "조회",
        "_structured_card": {
            "type": "inbox",
            "data": {
                "items": [
                    {
                        "title": "메일 1",
                        "sender_email": "leak@example.com",
                        "user_id": "USR-LEAK",
                        "audit_hash": "HASH-X",
                    }
                ]
            },
        },
    }
    pub, _priv = split_result("inbox.summary", raw)
    card = pub.get("_structured_card")
    assert card is not None
    # type 은 보존.
    assert card["type"] == "inbox"
    # nested email / user_id / hash 는 제거.
    card_str = str(card)
    assert "leak@example.com" not in card_str
    assert "USR-LEAK" not in card_str
    assert "HASH-X" not in card_str


def test_multimodal_blocks_deep_scrub():
    """multimodal_blocks 안의 nested 데이터도 deep scrub."""
    raw = {
        "success": True,
        "hits": [],
        "multimodal_blocks": [
            {
                "kind": "table",
                "markdown": "| col1 |",
                "tenant_id": "T-LEAK",
                "internal_meta": {"audit_hash": "AH"},
            }
        ],
    }
    pub, _priv = split_result("kms_rag.search", raw)
    mm = pub.get("multimodal_blocks")
    assert mm is not None
    s = str(mm)
    assert "T-LEAK" not in s
    # nested AH 도 (audit_hash 키 자체가 sensitive — 자식 dict 의 그 키도 제거됨)
    assert "AH" not in s


def test_public_private_fields_have_known_tools():
    """PUBLIC_FIELDS / PRIVATE_FIELDS 의 도구 이름이 실제 등록 도구와 매핑."""
    # 최소한의 sanity check — 주요 도구 등록 여부.
    must_have = ["expense.list", "schedule.list", "kms_rag.search", "stock.quote"]
    for t in must_have:
        assert t in PUBLIC_FIELDS, f"missing in PUBLIC_FIELDS: {t}"
    assert "*" in PRIVATE_FIELDS
