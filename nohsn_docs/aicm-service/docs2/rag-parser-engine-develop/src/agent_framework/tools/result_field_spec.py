"""D76 — Tool result public/private 필드 split (Phase 1.5 spec § 18 #8).

목적
----
도구 호출 결과 (`tool_result.data`) 가 *전체 dict* 그대로 LLM context 에 노출 + 저장.
- 내부 ID / hash / metadata / 민감 데이터 (PII / 개인정보 fragment) → 모델이
  사용자 응답에 그대로 인용 위험.
- chat_messages DB 도 동일 노출 — 향후 read path 에서 재노출 가능.

본 모듈 (D76) = *split layer*. split_result(tool_name, result) 가 (public, private)
2-튜플 반환:
- public: LLM context (compose path) 에 노출 OK + 저장 OK.
- private: 저장만 OK (adversarial_checker 등 *내부 검증* path 에서만 접근).

설계 원칙 (GPT-5 사전 검증 권고 — Option C 하이브리드)
-----------------------------------------------------
1. **Hybrid policy**:
   - Known tool (PUBLIC_FIELDS 등록) = strong allowlist (서브필드까지).
   - Unknown / custom tool = SENSITIVE_PATTERNS + 사이즈 캡으로 안전 통과 (품질 유지).
2. **Deep-walk**: items[].tenant_id / row_id 등 nested key 까지 재귀 정화.
3. **Contract key mirror**: success / summary / meta / error / op_type 등은 양쪽 모두에 미러.
   *단* confirm_id / evidence_id 는 *private only* — LLM 응답에 노출 시 위험.
4. **adversarial_checker 호환**: ToolResultView wrapper 의 `.for_checker()` 가
   public ∪ private 머지 view 반환 — confirm_id / evidence_id / rows_affected 등
   evidence key 정상 검사.
5. **_legacy: prefix 노출 차단**: D73 result_adapter 의 stash 가 LLM 에 가지 않도록.
6. **성능**: SENSITIVE_PATTERNS 컴파일 캐시 + payload 사이즈 캡 (UNKNOWN_VALUE_CAP_CHARS).

본 모듈은 *prod path 무영향* — caller 가 명시적으로 split_result 호출해야 적용됨.
D76.2 (engine.py compose path) 에서 적용. dual-write 단계 — log only.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


# ---------------------------------------------------------------------------
# 1. Contract key — 도구 contract (outcomes.py / result_adapter.py) 의 표준 key.
# ---------------------------------------------------------------------------
# 양쪽 (public + private) 모두에 *미러* — adversarial_checker / LLM compose 둘 다 필요.
# 단 confirm_id / evidence_id 는 *private only* (LLM 노출 시 ID 인용 위험).
_CONTRACT_MIRROR_KEYS = (
    "success",
    "ok",
    "status",
    "summary",
    "error",
    "error_ref",
    "meta",
    "tool_name",
    "op_type",
    "rows_affected",
    "_structured_card",
    "multimodal_blocks",
)

# adversarial_checker._has_state_change_evidence 가 검사 — *private only*.
# public 에 포함 시 LLM 응답에 confirm_id 같은 내부 ID 그대로 인용 위험.
_EVIDENCE_PRIVATE_KEYS = (
    "confirm_id",
    "evidence_id",
)


# ---------------------------------------------------------------------------
# 2. PUBLIC_FIELDS — 도구별 public 필드 (LLM context + 저장 OK).
# ---------------------------------------------------------------------------
# *서브필드까지 명시* (items[]/hits[] 안의 row 도 allowlist 기반 정화).
# (key 이름, *_sub_allowlist) 형식 — sub_allowlist 가 None 이면 nested dict 도 전체 통과.
#
# 주의: 등록되지 않은 도구는 UNKNOWN PATH (SENSITIVE_PATTERNS + 캡) 로 처리.
PUBLIC_FIELDS: dict[str, dict[str, list[str] | None]] = {
    # --- expense ---
    "expense.create": {
        "summary": None,
        "amount": None,
        "category": None,
        "description": None,
        "spent_at": None,
    },
    "expense.list": {
        "items": ["amount", "category", "description", "spent_at", "payment_method"],
        "total": None,
        "summary": None,
        "categories": None,
        "count": None,
    },
    "expense.sum_by_category": {
        "total": None,
        "by_category": None,
        "count": None,
        "summary": None,
        "period_start": None,
        "period_end": None,
    },
    "expense.delete": {
        "summary": None,
        "deleted_count": None,
    },
    "expense.update": {
        "summary": None,
        "updated_count": None,
    },
    # --- schedule ---
    "schedule.create": {
        "summary": None,
        "title": None,
        "start_at": None,
        "end_at": None,
        "location": None,
    },
    "schedule.list": {
        "items": ["title", "start_at", "end_at", "location", "attendees"],
        "total": None,
        "summary": None,
        "count": None,
    },
    "schedule.delete": {"summary": None, "deleted_count": None},
    "schedule.delete_duplicates": {"summary": None, "deleted_count": None},
    "schedule.delete_all": {"summary": None, "deleted_count": None},
    "schedule.update": {"summary": None, "updated_count": None},
    "schedule.availability": {"summary": None, "available": None, "conflicts": None},
    "schedule.suggest_slots": {"summary": None, "slots": None, "items": ["start_at", "end_at"]},
    # --- reservation ---
    "reservation.create": {
        "summary": None,
        "title": None,
        "start_at": None,
        "end_at": None,
        "location": None,
        "attendee_count": None,
    },
    "reservation.cancel": {"summary": None, "cancelled_count": None},
    "reservation.check_availability": {"summary": None, "available": None},
    "reservation.reschedule": {"summary": None, "updated_count": None},
    # --- payment / inventory / delivery ---
    "payment.refund": {"summary": None, "order_id": None, "amount": None, "status": None, "reason": None},
    "inventory.check": {"summary": None, "item": None, "current_qty": None, "status": None, "last_updated": None},
    "delivery.track": {"summary": None, "status": None, "last_updated": None, "eta": None},
    # --- memo ---
    "memo.create": {"summary": None, "title": None, "deadline_at": None, "alarm_at": None},
    "memo.list": {
        "items": ["title", "note", "deadline_at", "alarm_at", "status"],
        "total": None,
        "summary": None,
    },
    "memo.update": {"summary": None, "updated_count": None},
    "memo.delete": {"summary": None, "deleted_count": None},
    "memo.complete": {"summary": None, "title": None, "status": None},
    # --- mail ---
    "mail.send": {"summary": None, "to": None, "subject": None, "sent_at": None},
    "mail.search": {
        # 메일 검색 결과는 sender 주소/제목/본문 포함 — email 패턴 매칭 X (allowlist 명시).
        "items": ["subject", "sender", "date", "snippet", "preview", "has_attachment"],
        "total": None,
        "summary": None,
    },
    "mail.compose": {"summary": None, "draft": ["to", "subject", "body_text"]},
    # --- diary ---
    "diary.save": {"summary": None, "date": None},
    "diary.search": {
        "items": ["date", "body", "mood"],
        "total": None,
        "summary": None,
    },
    # --- inbox / reminder ---
    "inbox.summary": {
        "summary": None,
        "categories": None,
        "_structured_card": None,
        "total": None,
        "since": None,
        "until": None,
    },
    "reminder.schedule": {"summary": None, "title": None, "time": None, "recurrence_kind": None},
    "reminder.list": {
        "items": ["title", "time", "recurrence_kind", "weekday", "every_n", "status"],
        "total": None,
        "summary": None,
    },
    "reminder.cancel": {"summary": None, "action": None, "matched_count": None},
    # --- news ---
    "news.add_subscription": {"summary": None, "title": None, "schedule": None},
    "news.remove_subscription": {"summary": None, "removed_count": None},
    "news.list_subscriptions": {
        "items": ["title", "schedule", "category"],
        "total": None,
        "summary": None,
    },
    "news.fetch_and_summarize": {"summary": None, "report": None},
    "news.list_recent_reports": {
        "items": ["title", "published_at", "summary"],
        "total": None,
        "summary": None,
    },
    "news.search": {
        "items": ["title", "url", "published_at", "summary", "source"],
        "total": None,
        "summary": None,
    },
    # --- KMS / RAG ---
    "kms_rag.search": {
        # D85c-잔존 (2026-05-13) — citation full_url/section/page 표시용 필드 동기.
        # 누락 시 split_result 가 hit 에서 제거 → engine citation 빌드가 None.
        "hits": [
            "title", "document_title", "snippet", "content", "score",
            "document_id", "url", "page", "page_number", "name",
            "block_id", "repository_id", "section_title", "section", "block_type",
        ],
        "total": None,
        "evidence_count": None,
        "multimodal_blocks": None,
        "summary": None,
    },
    "kms_sop.search": {
        "hits": ["title", "snippet", "content", "score", "document_id"],
        "total": None,
        "summary": None,
    },
    "kms_inventory.get_summary": {
        "summary": None,
        "total_documents": None,
        "categories": None,
        "repos": None,
    },
    "kms_inventory.list_documents": {
        "items": ["title", "status", "size", "updated_at", "doc_type", "source_type"],
        "total": None,
        "summary": None,
    },
    "kms_meta.get_my_inventory": {
        "summary": None,
        "documents": None,
        "skills": None,
        "subscriptions": None,
        "totals": None,
    },
    "kms.save_research": {"summary": None, "title": None, "saved_at": None},
    # --- weather / web ---
    "weather.lookup": {
        "summary": None,
        "date": None,
        "location": None,
        "temperature": None,
        "weather": None,
        "humidity": None,
        "wind": None,
    },
    "web.search": {
        "items": ["title", "url", "snippet", "source"],
        "hits": ["title", "url", "snippet", "source"],
        "total": None,
        "summary": None,
    },
    "web.fetch": {"summary": None, "title": None, "content": None, "url": None},
    # --- stock ---
    "stock.quote": {"summary": None, "symbol": None, "name": None, "price": None, "close": None, "change": None, "change_pct": None, "volume": None, "trade_date": None},
    "stock.predict": {"summary": None, "symbol": None, "prediction": None, "confidence": None},
    "stock.market_movers": {"summary": None, "gainers": None, "losers": None, "volume_top": None, "market": None},
    "stock.analyze": {"summary": None, "symbol": None, "analysis": None, "indicators": None},
    "stock.add_watch": {"summary": None, "symbol": None, "name": None},
    "stock.list_watch": {
        "items": ["symbol", "name", "added_at"],
        "total": None,
        "summary": None,
    },
    "stock.update_watch": {"summary": None, "updated_count": None},
    "stock.delete_watch": {"summary": None, "deleted_count": None},
    # --- lifestyle stubs ---
    "restaurant.search": {"items": ["name", "address", "rating", "price_range", "menu"], "total": None, "summary": None},
    "movie.lookup": {"summary": None, "title": None, "release_date": None, "rating": None, "genre": None},
    "movie.boxoffice": {"items": ["rank", "title", "audience", "revenue"], "summary": None},
    "fx.rate": {"summary": None, "base": None, "target": None, "rate": None, "date": None},
    "transit.status": {"summary": None, "line": None, "status": None, "delay": None},
    "flight.price": {"summary": None, "origin": None, "destination": None, "price": None, "carrier": None, "date": None},
    "concert.schedule": {"items": ["artist", "venue", "date", "price"], "summary": None},
    "menu.recommend": {"summary": None, "items": ["name", "description", "price"]},
    "streaming.lookup": {"summary": None, "title": None, "platforms": None, "url": None},
    "air.quality": {"summary": None, "location": None, "pm10": None, "pm25": None, "grade": None, "measured_at": None},
    # --- calendar mock ---
    "calendar.check_availability": {"summary": None, "available": None, "time": None},
    "calendar.book": {"summary": None, "doctor": None, "time": None},
    "calendar.list_doctors": {"items": ["name", "specialty"], "summary": None},
    "calendar.list_available_slots": {"items": ["start", "end", "doctor"], "summary": None},
}


# ---------------------------------------------------------------------------
# 3. PRIVATE_FIELDS — 도구별 private 필드 (저장만 OK, LLM context X).
# ---------------------------------------------------------------------------
# "*" 키는 *모든 도구 공통* (cross-cutting).
PRIVATE_FIELDS: dict[str, list[str]] = {
    "*": [
        "confirm_id",
        "evidence_id",
        "tenant_id",
        "user_id",
        "row_id",
        "audit_hash",
        "session_id",
        "account_id",
        "device_id",
        "raw_payload",
        "invocation_id",
        "request_id",
    ],
    # 도구별 추가 — state-change 도구의 ID 류.
    "expense.create": ["row_id", "audit_hash"],
    "expense.update": ["row_id", "audit_hash"],
    "expense.delete": ["row_id"],
    "schedule.create": ["row_id"],
    "schedule.update": ["row_id"],
    "schedule.delete": ["row_id"],
    "memo.create": ["row_id"],
    "memo.update": ["row_id"],
    "memo.delete": ["row_id"],
    "mail.send": ["smtp_response", "message_id"],
    "reservation.create": ["row_id"],
    "reservation.cancel": ["row_id"],
    "payment.refund": ["transaction_id", "row_id"],
    "kms.save_research": ["row_id", "document_id"],
}


# ---------------------------------------------------------------------------
# 4. SENSITIVE_PATTERNS — 정규식 fallback (unknown tool / nested key).
# ---------------------------------------------------------------------------
# *키 이름 기반* 매칭. 값 기반 PII 스캔은 본 모듈 범위 외 (별도 PR).
#
# GPT-5 권고 — `_legacy:` prefix 노출 차단 (D73 stash 가 LLM 에 가지 않도록).
# `_structured_card` 는 화이트리스트 (rich card UI 용 — emit path 와 분리).
SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r".*_hash$"),
    re.compile(r"^_(?!structured_card$).*"),  # _structured_card 제외, _legacy: 등은 모두 차단
    re.compile(r"(?:^|_)(email|e_mail|phone|tel|mobile|ssn|jumin|rrn|passport|driver|license|iban|swift|routing|tax_id)(?:$|_)", re.IGNORECASE),
    re.compile(r"(?:access|refresh)_token$", re.IGNORECASE),
    re.compile(r"api[_-]?key$", re.IGNORECASE),
    re.compile(r"(?:^|_)secret(?:$|_)", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# 5. 사이즈 캡 — unknown tool 의 무한 payload 방지.
# ---------------------------------------------------------------------------
UNKNOWN_VALUE_CAP_CHARS = 2000  # 단일 string value 의 최대 길이
UNKNOWN_LIST_CAP = 50  # list items 최대 길이
# D76b — summary/error 같은 자유 텍스트 영역 짧은 cap (LLM context flood / 잔여 PII 방어).
SUMMARY_ERROR_CAP = 500


# ---------------------------------------------------------------------------
# Core: split_result
# ---------------------------------------------------------------------------

# D76b — 키 정규화 (GPT-5.5 사전 P0-2/P0-3/P0-4 권고).
# camelCase / kebab-case / fullwidth / zero-width 우회 차단.
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _normalize_key_variants(key: str) -> set[str]:
    """키 정규화 → variant set (snake + compact).

    1. NFKC normalize (fullwidth/half 통일).
    2. Cf category 제거 (zero-width / variation selector 우회 차단).
    3. camelCase 경계에 `_` 삽입 (userId → user_Id).
    4. casefold.
    5. non-alnum → `_` 통일 (kebab/dot/bracket).
    6. 다중 `_` 압축.

    Returns:
        {snake_form, compact_form} — exact 비교에서 둘 다 시도.

    Examples:
        'User-ID' → {'user_id', 'userid'}
        'userId' → {'user_id', 'userid'}
        'tenant.id' → {'tenant_id', 'tenantid'}
        'user[id]' → {'user_id', 'userid'}
        'u\\u200bser_id' → {'user_id', 'userid'}
    """
    if not isinstance(key, str):
        return {""}
    s = unicodedata.normalize("NFKC", key)
    # Cf (format/zero-width) 제거.
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    # camelCase boundary.
    s = _CAMEL_BOUNDARY_RE.sub(r"\1_\2", s)
    s = s.casefold()
    # non-alnum 통일.
    s = _NON_ALNUM_RE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return {s, s.replace("_", "")}


# 사전 계산 — PRIVATE_FIELDS["*"] 의 variant set (성능).
# 모듈 로드 시 한 번.
_FORBIDDEN_KEY_VARIANTS: set[str] = set()  # 첫 호출 시 lazy init.


def _build_forbidden_key_variants() -> set[str]:
    """PRIVATE_FIELDS["*"] 의 모든 변형 — 한 번 계산 후 캐시."""
    out: set[str] = set()
    for forbidden in PRIVATE_FIELDS.get("*", []):
        out |= _normalize_key_variants(forbidden)
    return out


# ---------------------------------------------------------------------------
# D76b — PII value scrub (GPT-5.5 사전 P0-2 권고).
# summary/error 같은 자유 텍스트 안 PII substring 마스킹.
# ---------------------------------------------------------------------------

# 정규식 — *순서 중요* (긴 패턴 우선).
# ReDoS 완화 위해 모두 linear-time. 입력은 cap 후 적용 (D76b.7 권고 반영 X — scrub
# 먼저 → 그 다음 truncate. GPT-5.5 P0-7).
_PII_VALUE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # JWT (eyJ...)
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "<jwt>",
    ),
    # Bearer token
    (
        re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b", re.IGNORECASE),
        "Bearer <token>",
    ),
    # Authorization: Basic
    (
        re.compile(r"\b(?:Basic)\s+[A-Za-z0-9+/=_-]{16,}\b", re.IGNORECASE),
        "Basic <token>",
    ),
    # AWS access key
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "<aws_key>"),
    # GitHub PAT
    (re.compile(r"\bghp_[A-Za-z0-9]{16,}\b"), "<gh_pat>"),
    # Slack
    (re.compile(r"\bxox[bpoars]-[A-Za-z0-9-]{8,}\b"), "<slack_token>"),
    # OpenAI-style (sk_ or sk-)
    (re.compile(r"\bsk[-_][A-Za-z0-9_\-]{16,}\b"), "<api_key>"),
    # 주민등록번호 (외국인등록번호 포함 — [1-8])
    (re.compile(r"\b\d{6}[-\s]?[1-8]\d{6}\b"), "<rrn>"),
    # 한국 휴대폰 (010-/+82-) — dash/space/dot 모두.
    (
        re.compile(r"(?:\+82[-\s]?)?(?:0?1[0-9])[-\s.]?\d{3,4}[-\s.]?\d{4}\b"),
        "<phone_kr>",
    ),
    # 일반 휴대폰/유선 (3-4-4)
    (re.compile(r"\b\d{2,3}[-\s.]\d{3,4}[-\s.]\d{4}\b"), "<phone>"),
    # 이메일 (자연어 안 leak@x.com 도 잡힘).
    (re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+"), "<email>"),
]


def _bucket_rows_affected(v: Any) -> Any:
    """rows_affected 버킷팅 — exact count membership inference 완화.

    GPT-5.5 D76b 사전 P0-9 — fail-closed minimal 만이 아닌 normal split path 도 동일 적용.
    bool 은 그대로 (P0-10).
    GPT-5.5 D76b pre-commit 사후 P0-6 — 음수 sentinel 도 명시 처리.
    """
    if isinstance(v, bool):
        return v
    if not isinstance(v, int):
        return v
    if v < 0:
        return "<invalid>"
    if v == 0:
        return 0
    if v == 1:
        return 1
    if v <= 10:
        return "2-10"
    return ">10"


def _scrub_pii_text(text: str) -> str:
    """문자열 안 PII 추정 substring 마스킹.

    GPT-5.5 P0-7: scrub *먼저* 적용 후 caller 가 truncate. cap 경계에서 PII 끝부분만
    잘려 마스킹 우회되는 회귀 차단.
    """
    if not isinstance(text, str):
        return text
    for pat, replacement in _PII_VALUE_PATTERNS:
        text = pat.sub(replacement, text)
    return text


def _scrub_pii_recursive(value: Any, depth: int = 0) -> Any:
    """summary/error 가 dict/list/object 일 때 재귀 마스킹 (GPT-5.5 P0-5).

    error 가 {"message": "failed for leak@example.com", "stack": "...", "sql": "..."} 같이
    nested 구조면 모든 leaf 문자열에 PII scrub. SENSITIVE_KEY 도 함께 제거.
    D76b — nested string 길이 cap (SUMMARY_ERROR_CAP) 도 적용 (P0-5 후속).
    """
    if depth > 8:
        return "<truncated:depth>"
    if isinstance(value, str):
        scrubbed = _scrub_pii_text(value)
        if len(scrubbed) > SUMMARY_ERROR_CAP:
            scrubbed = scrubbed[:SUMMARY_ERROR_CAP] + "...<truncated>"
        return scrubbed
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        # D76b pre-commit P0-4 — dict size cap (LLM context flood 방어).
        # 처음 UNKNOWN_LIST_CAP 개 key 까지만 처리.
        count = 0
        for k, v in value.items():
            if count >= UNKNOWN_LIST_CAP:
                break
            # stack/sql/internal_path 같은 노출 위험 키는 제거.
            if isinstance(k, str) and _normalize_key_variants(k) & {
                "stack",
                "stacktrace",
                "traceback",
                "sql",
                "query",
                "rawpayload",
                "raw_payload",
                "internalpath",
                "internal_path",
                "hostname",
            }:
                continue
            if _is_sensitive_key(str(k)):
                continue
            # D76b pre-commit P0-3 — key 이름 자체에 PII 포함 시 마스킹.
            safe_key = _scrub_pii_text(str(k)) if isinstance(k, str) else k
            out[safe_key] = _scrub_pii_recursive(v, depth + 1)
            count += 1
        return out
    if isinstance(value, list):
        return [_scrub_pii_recursive(v, depth + 1) for v in value[:UNKNOWN_LIST_CAP]]
    return value


def _is_sensitive_key(key: str) -> bool:
    """key 이름이 SENSITIVE_PATTERNS 어디든 매치되거나 PRIVATE_FIELDS["*"] 에 있으면 True.

    GPT-5.5 사전 P0-2/P0-3/P0-4 — 키 정규화 (NFKC + casefold + camelCase + zero-width
    제거) 적용. PRIVATE_FIELDS["*"] 의 *모든 variant* 와 exact + compact 비교.
    GPT-5.5 D76b pre-commit P0-7 — SENSITIVE_PATTERNS 도 *정규화 variant* 에 매칭
    (pass\\u200bword / api-key 등 우회 차단).

    Examples:
        'userId' → user_id 와 매칭 → True.
        'User-ID' → user_id 와 매칭 → True.
        'u\\u200bser_id' → Cf 제거 후 user_id 와 매칭 → True.
        'tenant.id' → tenant_id 와 매칭 → True.
        'pass\\u200bword' → password normalize → SENSITIVE_PATTERNS 매칭 → True.
    """
    if not isinstance(key, str):
        return False
    global _FORBIDDEN_KEY_VARIANTS
    if not _FORBIDDEN_KEY_VARIANTS:
        _FORBIDDEN_KEY_VARIANTS = _build_forbidden_key_variants()
    variants = _normalize_key_variants(key)
    # PRIVATE_FIELDS["*"] variant 와 교집합 → sensitive.
    if variants & _FORBIDDEN_KEY_VARIANTS:
        return True
    # 정규식 패턴 매칭 — 원본, casefold, *정규화 variant* 모두 시도.
    candidates = {key, key.casefold()} | variants
    for p in SENSITIVE_PATTERNS:
        for cand in candidates:
            if p.search(cand):
                return True
    return False


def _deep_scrub_unknown(
    value: Any, depth: int = 0, *, pii_scrub: bool = False
) -> Any:
    """unknown tool 의 payload — deep walk + sensitive key 제거 + 사이즈 캡.

    재귀 깊이 한계 8 (cycle 방지 + 비현실적 깊이 차단).

    D76b — `pii_scrub`:
        False (default): known-tool allowlist 경로 — 도메인이 허용한 string 은 그대로
                         (mail.search items[].sender 같은 email 필드 통과).
        True: unknown tool 경로 — 값 기반 PII (email/phone/JWT/RRN 등) 까지 마스킹.
    """
    if depth > 8:
        return "<truncated:depth>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        count = 0
        for k, v in value.items():
            if count >= UNKNOWN_LIST_CAP:
                break  # D76b pre-commit P0-4 — dict cap.
            if _is_sensitive_key(str(k)):
                continue
            # D76b pre-commit P0-3 — key 이름이 PII 일 수 있음 (예: "leak@x.com": ...).
            safe_key = (
                _scrub_pii_text(str(k))
                if pii_scrub and isinstance(k, str)
                else k
            )
            out[safe_key] = _deep_scrub_unknown(v, depth + 1, pii_scrub=pii_scrub)
            count += 1
        return out
    if isinstance(value, list):
        capped = value[:UNKNOWN_LIST_CAP]
        return [_deep_scrub_unknown(item, depth + 1, pii_scrub=pii_scrub) for item in capped]
    if isinstance(value, str):
        # D76b — pii_scrub 시 scrub *먼저* (P0-7) → truncate.
        if pii_scrub:
            value = _scrub_pii_text(value)
        if len(value) > UNKNOWN_VALUE_CAP_CHARS:
            return value[:UNKNOWN_VALUE_CAP_CHARS] + "...<truncated>"
        return value
    return value


def _filter_list_by_subfield_allowlist(
    items: list[Any], sub_allowlist: list[str] | None
) -> list[Any]:
    """items 안 각 row 의 *서브필드 allowlist* 적용 — deep clean.

    sub_allowlist = None 이면 원본 그대로 (도구가 dict 전체 통과 허용).
    """
    if sub_allowlist is None:
        # 그래도 sensitive key 제거 (defense-in-depth).
        return [
            _deep_scrub_unknown(item, depth=1) if isinstance(item, (dict, list)) else item
            for item in items
        ]

    filtered: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            filtered.append(item)
            continue
        row_public: dict[str, Any] = {}
        for sub_k in sub_allowlist:
            if sub_k in item:
                v = item[sub_k]
                # nested string/value 도 길이 캡 (deep_scrub 통해).
                row_public[sub_k] = _deep_scrub_unknown(v, depth=2)
        filtered.append(row_public)
    return filtered


def split_result(
    tool_name: str, result: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """도구 호출 결과 → (public, private) 2-튜플.

    public = LLM context (compose path) 노출 + 저장 OK.
    private = 저장만 OK (adversarial_checker 등 *내부* path 에서만).

    구현 원칙 (GPT-5 권고 — Option C 하이브리드):
    1. result is None / 비-dict → 둘 다 빈 dict.
    2. Contract mirror key (success/summary/meta/error/op_type/...) 는 양쪽 모두에 미러.
    3. _EVIDENCE_PRIVATE_KEYS (confirm_id/evidence_id) → private only.
    4. PUBLIC_FIELDS 등록 도구 → strong allowlist (서브필드까지 deep filter).
    5. PUBLIC_FIELDS 미등록 도구 → SENSITIVE_PATTERNS + 사이즈 캡 (deep scrub).
    6. PRIVATE_FIELDS 명시 key → public 에서 제외 (단, private 보관).

    Args:
        tool_name: 도구 이름 (예: "expense.list").
        result: 도구 반환 dict.

    Returns:
        (public, private) — 둘 다 dict.
    """
    if not isinstance(result, dict):
        return {}, {}

    public: dict[str, Any] = {}
    private: dict[str, Any] = {}

    # 1. Contract mirror — 양쪽 모두.
    # GPT-5 사후 P1 fix — _structured_card / multimodal_blocks 의 *내부 자유 텍스트*
    # 가 PII / 비밀 포함 가능. 단순 mirror 가 아닌 *deep scrub* 적용 (sensitive key
    # 재귀 제거 + 사이즈 캡). private 에는 원본 보관 (저장 path 용).
    # GPT-5.5 D76b 사전 P0-2/P0-5 — summary/error 도 자유 텍스트 → PII scrub.
    # error 는 dict/list 가능 → recursive scrub.
    _SCRUBBED_MIRROR_KEYS = ("_structured_card", "multimodal_blocks")
    _PII_SCRUB_MIRROR_KEYS = ("summary", "error")
    for k in _CONTRACT_MIRROR_KEYS:
        if k in result:
            v = result[k]
            if k in _SCRUBBED_MIRROR_KEYS:
                # deep scrub (sensitive key 제거 + 문자열 캡 + PII 마스킹).
                # _structured_card / multimodal_blocks 의 nested 자유 텍스트 안전.
                public[k] = _deep_scrub_unknown(v, depth=0, pii_scrub=True)
            elif k in _PII_SCRUB_MIRROR_KEYS:
                # PII 마스킹 + cap (D76b GPT-5.5 P0-2/P0-5/P0-7).
                if isinstance(v, str):
                    scrubbed = _scrub_pii_text(v)
                    if len(scrubbed) > SUMMARY_ERROR_CAP:
                        scrubbed = scrubbed[:SUMMARY_ERROR_CAP] + "...<truncated>"
                    public[k] = scrubbed
                else:
                    # dict/list — recursive scrub (이미 nested string cap 적용됨).
                    public[k] = _scrub_pii_recursive(v)
            elif k == "rows_affected":
                # D76b GPT-5.5 P0-9 — 정상 path 도 버킷팅 (membership inference).
                public[k] = _bucket_rows_affected(v)
            else:
                public[k] = v
            private[k] = v  # 원본 그대로 저장 (exact rows_affected 등).

    # 2. Evidence keys → private only.
    for k in _EVIDENCE_PRIVATE_KEYS:
        if k in result:
            private[k] = result[k]

    # 3. PRIVATE_FIELDS 명시 — private only.
    # D76b GPT-5.5 P0-3 (pre-commit) — *정규화 variant* 기반 매칭.
    # tool-specific private key 의 camelCase / kebab / fullwidth / zero-width 우회 차단.
    blocklist_raw = set(PRIVATE_FIELDS.get("*", [])) | set(PRIVATE_FIELDS.get(tool_name, []))
    blocklist_variants: set[str] = set()
    for forbidden in blocklist_raw:
        blocklist_variants |= _normalize_key_variants(forbidden)

    def _in_blocklist(key: str) -> bool:
        if key in blocklist_raw:
            return True
        return bool(_normalize_key_variants(key) & blocklist_variants)

    for k in list(result.keys()):
        if _in_blocklist(str(k)):
            private[k] = result[k]

    # 4. PUBLIC_FIELDS — 등록 도구 (allowlist 기반).
    if tool_name in PUBLIC_FIELDS:
        allowlist = PUBLIC_FIELDS[tool_name]
        # D76b — contract mirror 이미 처리된 키 (특히 summary/error PII scrub 적용된)
        # 는 PUBLIC_FIELDS 처리에서 *덮어쓰지 않음*. 그렇지 않으면 PII scrub 결과 손실.
        _mirror_handled = set(_CONTRACT_MIRROR_KEYS) & set(result.keys())
        for k, sub_allow in allowlist.items():
            if k not in result:
                continue
            if _in_blocklist(str(k)):
                continue  # blocklist 우선 (절대 public 안 가도록).
            if k in _mirror_handled:
                continue  # contract mirror 가 이미 처리 (PII scrub 등) — 보존.
            v = result[k]
            # items / hits 류는 서브필드 allowlist 적용.
            if isinstance(v, list) and sub_allow is not None:
                public[k] = _filter_list_by_subfield_allowlist(v, sub_allow)
            elif isinstance(v, list):
                public[k] = [
                    _deep_scrub_unknown(item, depth=1) if isinstance(item, (dict, list)) else item
                    for item in v
                ]
            elif isinstance(v, dict) and sub_allow is not None:
                # dict 단일 (mail.compose.draft 같은) — sub_allow 적용.
                drow: dict[str, Any] = {}
                for sub_k in sub_allow:
                    if sub_k in v:
                        drow[sub_k] = _deep_scrub_unknown(v[sub_k], depth=2)
                public[k] = drow
            elif isinstance(v, dict):
                # dict 일반 — deep scrub (sensitive key 제거).
                public[k] = _deep_scrub_unknown(v, depth=1)
            elif isinstance(v, str):
                # known tool allowlist 의 string — domain 이 명시 허용한 영역이므로
                # 길이 캡만 적용 (PII scrub 은 summary/error 의 자유 텍스트 영역에만).
                if len(v) > UNKNOWN_VALUE_CAP_CHARS:
                    public[k] = v[:UNKNOWN_VALUE_CAP_CHARS] + "...<truncated>"
                else:
                    public[k] = v
            else:
                public[k] = v
        # 등록 도구의 나머지 (allowlist 미포함) key → private.
        handled = set(_CONTRACT_MIRROR_KEYS) | set(_EVIDENCE_PRIVATE_KEYS) | set(allowlist.keys())
        for k, v in result.items():
            if k in handled or _in_blocklist(str(k)):
                continue
            private[k] = v
    else:
        # 5. UNKNOWN TOOL — sensitive pattern + 사이즈 캡으로 안전 통과.
        handled = set(_CONTRACT_MIRROR_KEYS) | set(_EVIDENCE_PRIVATE_KEYS)
        for k, v in result.items():
            if k in handled or _in_blocklist(str(k)):
                # blocklist 면 private 만 (이미 위에서 처리됨).
                continue
            if _is_sensitive_key(str(k)):
                private[k] = v
                continue
            # public 에 deep scrub 적용 + PII 마스킹 (unknown tool = 신뢰 불가).
            public[k] = _deep_scrub_unknown(v, depth=0, pii_scrub=True)
            # private 에도 원본 보관 (저장 path 에서 사용 가능).
            private[k] = v

    return public, private


# ---------------------------------------------------------------------------
# 6. ToolResultView — adversarial_checker 호환 wrapper.
# ---------------------------------------------------------------------------

class ToolResultView:
    """split 결과를 사용처별로 다른 view 제공.

    - ``.for_llm()`` — public dict (compose path).
    - ``.for_checker()`` — public ∪ private 머지 (adversarial_checker / 내부 검증).
    - ``.for_storage()`` — public ∪ private 머지 (DB 저장).

    LLM 경로에서 .for_checker / .for_storage 호출 절대 금지 (API 노출 X).
    """

    __slots__ = ("tool_name", "_public", "_private")

    def __init__(self, tool_name: str, public: dict[str, Any], private: dict[str, Any]):
        self.tool_name = tool_name
        self._public = public
        self._private = private

    @classmethod
    def from_raw(cls, tool_name: str, raw: dict[str, Any] | None) -> ToolResultView:
        pub, priv = split_result(tool_name, raw)
        return cls(tool_name, pub, priv)

    def for_llm(self) -> dict[str, Any]:
        """LLM compose path 노출용 — public 만."""
        return dict(self._public)

    def for_checker(self) -> dict[str, Any]:
        """adversarial_checker 등 *내부* 검증 path 용 — public ∪ private 머지.

        private 가 public 키를 *덮어쓰지 않음* (contract mirror 일치 유지).
        """
        merged = dict(self._public)
        for k, v in self._private.items():
            if k not in merged:
                merged[k] = v
        return merged

    def for_storage(self) -> dict[str, Any]:
        """DB / 저장 path 용 — public ∪ private 머지 (현재 PR = dual-write, 원본 그대로)."""
        return self.for_checker()


__all__ = [
    "PUBLIC_FIELDS",
    "PRIVATE_FIELDS",
    "SENSITIVE_PATTERNS",
    "SUMMARY_ERROR_CAP",
    "split_result",
    "ToolResultView",
    # D76b — helper exports for engine.py SSE / fail-closed path 사용.
    "_scrub_pii_text",
    "_scrub_pii_recursive",
    "_normalize_key_variants",
    "_is_sensitive_key",
    "_bucket_rows_affected",
]
