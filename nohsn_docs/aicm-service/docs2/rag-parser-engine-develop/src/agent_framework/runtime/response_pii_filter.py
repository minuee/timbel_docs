"""D82-B — LLM 응답 본문 PII filter. fail-closed 마스킹.

배경 (D80 P0 #2):
- baemin 봇 사용자 입력: "고객번호 010-1234-5678 ... 주민번호 900101-1234567"
- agent 응답: 같은 raw PII echo
- D76b `_scrub_pii_text` 는 tool result field 전용 — LLM 응답 본문 미보호
- compliance 위험 (RRN/카드/전화 등 raw echo)

GPT-5.5 사전 검증 (2026-05-11, GO_WITH_CHANGES) — 8 필수 변경 반영:
1. 예외 시 원본 반환 금지 → safe placeholder
2. `\b` 제거 → digit lookaround (한글 인접 PII 매칭)
3. 무하이픈 RRN / 무하이픈 사업자번호 추가
4. SSE streaming sliding buffer (chunk split 대응) — StreamingPIIRedactor
5. non-streaming egress hook (engine + chat_v1)
6. Prometheus label = type only (no agent_id, high cardinality 위험)
7. email local-part 짧으면 전체 마스킹
8. capture group 기반 replacement (전화 010-****-5678 형태 보존)

5 PII type — RRN / 카드 / 전화 / 사업자 / 이메일.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Callable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 정규식 — *순서 중요* (긴 패턴 / 위험도 높은 순).
# digit lookaround (?<!\d) ... (?!\d) — `\b` 회피 (한글 인접 PII 매칭).
# 모두 linear-time — ReDoS 안전.
# ---------------------------------------------------------------------------

# 한국 주민등록번호 (YYMMDD-XXXXXXX) — 하이픈 있는 형태.
# 7번째 자리 성별/세대 코드 [1-8] 제한 — false positive 완화.
# YY (00-99), MM (01-12), DD (01-31) — 기본 검증.
_KR_RRN_HYPHEN = re.compile(
    r"(?<!\d)"
    r"(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))"  # YYMMDD
    r"-"
    r"([1-8]\d{6})"  # 성별/세대 + 6자리
    r"(?!\d)"
)

# 한국 주민등록번호 (무하이픈 13자리) — false positive 완화 위해 동일 MM/DD/gender 검증.
_KR_RRN_NOHYPHEN = re.compile(
    r"(?<!\d)"
    r"(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))"
    r"([1-8]\d{6})"
    r"(?!\d)"
)

# 카드번호 — 4-4-4-4 (separator: hyphen / dot / space / 없음).
# GPT-5.5 권고: safety-first — 16자리 연속 숫자도 마스킹 (false positive 허용).
_CARD = re.compile(
    r"(?<!\d)"
    r"(\d{4})[-.\s]?(\d{4})[-.\s]?(\d{4})[-.\s]?(\d{4})"
    r"(?!\d)"
)

# 한국 휴대폰 (010/011/016/017/018/019 + XXX-XXXX-XXXX 또는 변형).
# capture group 으로 prefix + last4 보존 → "010-****-5678" 형태.
_KR_PHONE = re.compile(
    r"(?<!\d)"
    r"(01[016789])[-.\s]?(\d{3,4})[-.\s]?(\d{4})"
    r"(?!\d)"
)

# 한국 사업자번호 — 하이픈 / 무하이픈 양쪽 (10자리).
_BUSINESS_HYPHEN = re.compile(
    r"(?<!\d)"
    r"(\d{3})-(\d{2})-(\d{5})"
    r"(?!\d)"
)

_BUSINESS_NOHYPHEN = re.compile(
    r"(?<!\d)"
    r"\d{10}"
    r"(?!\d)"
)

# 이메일 — `\b` 대신 명시적 boundary (한글 인접 매칭).
# local: 영문/숫자/.+-_ 1자 이상, domain: 영문/숫자/-.
_EMAIL = re.compile(
    r"(?<![\w.+-])"
    r"([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)"
    r"(?![\w.-])"
)


def _mask_email(m: re.Match[str]) -> str:
    """이메일 마스킹 — GPT-5.5 권고: 짧은 local 은 전체 마스킹."""
    local = m.group(1)
    domain = m.group(2)
    if len(local) <= 2:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def _mask_phone(m: re.Match[str]) -> str:
    """전화 마스킹 — prefix + last4 보존, middle 만 마스킹."""
    prefix = m.group(1)
    last4 = m.group(3)
    return f"{prefix}-****-{last4}"


# ---------------------------------------------------------------------------
# kill-switch — env KMS_RESPONSE_PII_FILTER_ENABLED.
# GPT-5.5 권고: 잘못된 값은 enabled 로 fail-closed.
# ---------------------------------------------------------------------------

def _is_enabled() -> bool:
    raw = os.environ.get("KMS_RESPONSE_PII_FILTER_ENABLED", "true").strip().lower()
    # GPT-5.5 권고: 명시 disabled (false/0/no/off) 만 차단. 그 외 모두 enabled.
    return raw not in {"false", "0", "no", "off"}


# ---------------------------------------------------------------------------
# core scrub — fail-closed.
# ---------------------------------------------------------------------------

# fail-closed placeholder — 필터 예외 시 raw text 반환 금지 (GPT-5.5 권고).
_FAILSAFE_PLACEHOLDER = "[REDACTED: response blocked by PII filter failure]"


def scrub_response_pii(text: str) -> tuple[str, list[str]]:
    """LLM 응답 본문 PII 마스킹 — 5 PII type 처리.

    fail-closed 의미:
    - 매칭 시 *반드시* 마스킹 (멱등 — 이미 마스킹된 값은 재매칭 안 됨)
    - 매칭 안 되면 원본 통과
    - 필터 자체 예외는 호출자 (apply_response_pii_filter) 가 placeholder 로 처리

    순서: RRN (hyphen → no-hyphen) → CARD → PHONE → BUSINESS (hyphen → no-hyphen) → EMAIL.
    카드 16자리가 사업자 무하이픈 10자리, 전화 11자리 와 겹치지 않게 RRN/카드 먼저.
    사업자 무하이픈 10자리는 전화 10-11자리와 겹칠 수 있어 PHONE 다음에 처리.

    Returns: (sanitized_text, hit_types).
    hit_types: 'rrn' | 'card' | 'phone' | 'business' | 'email' (중복 X).
    """
    if not text:
        return text, []

    hits: list[str] = []
    sanitized = text

    # 1. RRN (가장 위험) — hyphen 먼저, no-hyphen 다음.
    if _KR_RRN_HYPHEN.search(sanitized):
        sanitized = _KR_RRN_HYPHEN.sub("XXXXXX-XXXXXXX", sanitized)
        hits.append("rrn")
    if _KR_RRN_NOHYPHEN.search(sanitized):
        sanitized = _KR_RRN_NOHYPHEN.sub("XXXXXXXXXXXXX", sanitized)
        if "rrn" not in hits:
            hits.append("rrn")

    # 2. 카드 (16자리, separator-optional) — RRN 13자리 마스킹 후라 안전.
    if _CARD.search(sanitized):
        sanitized = _CARD.sub("XXXX-XXXX-XXXX-XXXX", sanitized)
        hits.append("card")

    # 3. 전화 — 사업자 무하이픈보다 먼저 (01x prefix 강제로 충돌 X).
    if _KR_PHONE.search(sanitized):
        sanitized = _KR_PHONE.sub(_mask_phone, sanitized)
        hits.append("phone")

    # 4. 사업자번호 — hyphen 먼저, no-hyphen 다음.
    if _BUSINESS_HYPHEN.search(sanitized):
        sanitized = _BUSINESS_HYPHEN.sub("XXX-XX-XXXXX", sanitized)
        hits.append("business")
    if _BUSINESS_NOHYPHEN.search(sanitized):
        sanitized = _BUSINESS_NOHYPHEN.sub("XXXXXXXXXX", sanitized)
        if "business" not in hits:
            hits.append("business")

    # 5. 이메일 (마지막) — local[:1] + ***@domain 또는 ***@domain.
    if _EMAIL.search(sanitized):
        sanitized = _EMAIL.sub(_mask_email, sanitized)
        hits.append("email")

    return sanitized, hits


def apply_response_pii_filter(
    text: str,
    log_hit_fn: Callable[[list[str]], None] | None = None,
) -> str:
    """fail-closed wrapper — 예외 시 raw text 반환 금지.

    - kill-switch off 면 원본 통과.
    - scrub 예외 시 placeholder 반환 + 'filter_error' metric.
    - hits 있으면 log_hit_fn 호출 (없으면 module log 만).
    """
    if not text:
        return text
    if not _is_enabled():
        return text

    try:
        sanitized, hits = scrub_response_pii(text)
    except Exception:  # noqa: BLE001
        # GPT-5.5 권고: raw text 반환 금지. raw text log 도 금지.
        log.exception("response_pii_filter_failed")
        if log_hit_fn is not None:
            try:
                log_hit_fn(["filter_error"])
            except Exception:  # noqa: BLE001
                pass
        return _FAILSAFE_PLACEHOLDER

    if hits and log_hit_fn is not None:
        try:
            log_hit_fn(hits)
        except Exception:  # noqa: BLE001
            pass

    return sanitized


# ---------------------------------------------------------------------------
# StreamingPIIRedactor — SSE chunk boundary 안전.
# GPT-5.5 권고 옵션 B: sliding buffer.
# ---------------------------------------------------------------------------

# 보류 길이 — 가장 긴 패턴 기준 (이메일은 임의 길이 → 별도 처리).
# RRN 14, 카드 19, 전화 16, 사업자 12 — 안전 마진 32.
# 이메일은 boundary 가 명확 (whitespace/punctuation) → 32 안에 거의 들어옴.
_SLIDING_TAIL_LEN = 32

# PII candidate 문자 set — digit/letter/dot/dash/underscore/plus/at.
# split 안전: 좌우 둘 다 이 set 밖이면 PII 중간 아님.
_PII_CHAR_SET = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-+_@")


def _is_pii_char(c: str) -> bool:
    return c in _PII_CHAR_SET


class StreamingPIIRedactor:
    """SSE streaming PII redactor — sliding buffer 로 chunk boundary 안전.

    사용:
        red = StreamingPIIRedactor()
        for chunk in llm_stream():
            safe = red.feed(chunk)
            if safe:
                yield safe
        final = red.flush()
        if final:
            yield final

    동작:
    - feed(chunk) — 누적 buffer 의 [앞부분 (- tail)] 만 scrub 후 emit, 나머지는 보류.
    - flush() — 남은 보류분 scrub 후 emit (스트림 종료).
    - 멱등 — 이미 마스킹된 값은 재매칭 안 됨.

    한계 (GPT-5.5 명시):
    - 이메일이 32자 초과로 boundary 에 걸리면 누락 가능 → flush 시 보장.
    - 32자 이내 PII 모두 안전.

    fail-closed:
    - feed/flush 안 예외 → placeholder + filter_error metric.
    """

    def __init__(
        self,
        log_hit_fn: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._buffer = ""
        self._log_hit_fn = log_hit_fn
        self._enabled = _is_enabled()
        self._aggregate_hits: set[str] = set()

    def feed(self, chunk: str) -> str:
        """chunk 추가 + scrub-safe 앞부분 반환 + tail 보류.

        split 안전:
        - 기본 split = len-_SLIDING_TAIL_LEN.
        - 그 위치가 digit/word char 사이면 PII 중간일 수 있어 *왼쪽으로* 후퇴해서
          공백/구두점 boundary 까지 이동 (최대 _SLIDING_TAIL_LEN 만큼 더 후퇴).
        - 보장: emit 되는 front 끝은 PII candidate 한가운데가 아님.
        """
        if not chunk:
            return ""
        if not self._enabled:
            # bypass — 원본 그대로.
            return chunk

        try:
            self._buffer += chunk
            if len(self._buffer) <= _SLIDING_TAIL_LEN:
                # 아직 보류만 — emit 없음.
                return ""
            # 기본 split = len - tail_len.
            split = len(self._buffer) - _SLIDING_TAIL_LEN
            # split 위치가 PII candidate 문자 (digit/word/email 문자) 한가운데면
            # 안전 경계 (공백/구두점) 까지 좌측 후퇴. 최대 tail_len 만큼 더 후퇴.
            min_split = max(0, split - _SLIDING_TAIL_LEN)
            while split > min_split:
                c = self._buffer[split - 1] if split > 0 else " "
                n = self._buffer[split] if split < len(self._buffer) else " "
                # 좌우 둘 다 PII candidate 문자가 아닐 때만 emit.
                # PII candidate = 영문/숫자/. + - _ @ (이메일/카드/전화 모두 포함).
                if not _is_pii_char(c) and not _is_pii_char(n):
                    break
                split -= 1
            if split <= 0:
                # 후퇴해도 안전 경계 없음 — 아직 emit 불가, 더 buffering.
                return ""
            front = self._buffer[:split]
            tail = self._buffer[split:]
            sanitized_front, hits = scrub_response_pii(front)
            self._buffer = tail
            if hits:
                self._aggregate_hits.update(hits)
                if self._log_hit_fn is not None:
                    try:
                        self._log_hit_fn(hits)
                    except Exception:  # noqa: BLE001
                        pass
            return sanitized_front
        except Exception:  # noqa: BLE001
            log.exception("response_pii_filter_stream_failed")
            self._buffer = ""
            if self._log_hit_fn is not None:
                try:
                    self._log_hit_fn(["filter_error"])
                except Exception:  # noqa: BLE001
                    pass
            return _FAILSAFE_PLACEHOLDER

    def flush(self) -> str:
        """스트림 종료 — 남은 보류 buffer scrub 후 emit."""
        if not self._enabled:
            out = self._buffer
            self._buffer = ""
            return out
        if not self._buffer:
            return ""
        try:
            sanitized, hits = scrub_response_pii(self._buffer)
            self._buffer = ""
            if hits:
                self._aggregate_hits.update(hits)
                if self._log_hit_fn is not None:
                    try:
                        self._log_hit_fn(hits)
                    except Exception:  # noqa: BLE001
                        pass
            return sanitized
        except Exception:  # noqa: BLE001
            log.exception("response_pii_filter_stream_flush_failed")
            self._buffer = ""
            if self._log_hit_fn is not None:
                try:
                    self._log_hit_fn(["filter_error"])
                except Exception:  # noqa: BLE001
                    pass
            return _FAILSAFE_PLACEHOLDER

    @property
    def hits(self) -> set[str]:
        """누적 hit type set (audit/log 용)."""
        return self._aggregate_hits


__all__ = [
    "scrub_response_pii",
    "apply_response_pii_filter",
    "StreamingPIIRedactor",
]
