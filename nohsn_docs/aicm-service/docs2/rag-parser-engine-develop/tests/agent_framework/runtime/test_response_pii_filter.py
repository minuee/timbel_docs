"""D82-B — response_pii_filter 단위 + 통합 test.

GPT-5.5 사전 검증 요구 사항 (2026-05-11):
- 한글 인접 PII 매칭 (`\\b` 우회 검증)
- streaming chunk split 안전
- exception fallback (fail-closed)
- kill-switch (env)
- idempotence (이미 마스킹된 값 재처리)
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.agent_framework.runtime.response_pii_filter import (
    StreamingPIIRedactor,
    apply_response_pii_filter,
    scrub_response_pii,
)


# ---------------------------------------------------------------------------
# 1. 5 PII type 마스킹 — 10건
# ---------------------------------------------------------------------------

class TestPIIMaskingBasic:
    """5 PII type 각각 기본 매칭."""

    def test_rrn_hyphen(self):
        out, hits = scrub_response_pii("주민번호는 900101-1234567 입니다")
        assert "900101-1234567" not in out
        assert "XXXXXX-XXXXXXX" in out
        assert "rrn" in hits

    def test_rrn_no_hyphen(self):
        # 7번째 자리 = 1 (성별/세대 코드 [1-8])
        out, hits = scrub_response_pii("주민 9001011234567 끝")
        assert "9001011234567" not in out
        assert "rrn" in hits

    def test_card_4_4_4_4_hyphen(self):
        out, hits = scrub_response_pii("카드 1234-5678-9012-3456 결제")
        assert "1234-5678-9012-3456" not in out
        assert "XXXX-XXXX-XXXX-XXXX" in out
        assert "card" in hits

    def test_card_16_continuous(self):
        # safety-first: 16자리 연속 숫자도 마스킹
        out, hits = scrub_response_pii("번호 1234567812345678 끝")
        assert "1234567812345678" not in out
        assert "card" in hits

    def test_phone_010(self):
        out, hits = scrub_response_pii("연락처 010-1234-5678 입니다")
        assert "010-1234-5678" not in out
        assert "010-****-5678" in out
        assert "phone" in hits

    def test_phone_no_separator(self):
        out, hits = scrub_response_pii("전화 01012345678 끝")
        assert "01012345678" not in out
        assert "phone" in hits

    def test_business_hyphen(self):
        out, hits = scrub_response_pii("사업자 123-45-67890 등록")
        assert "123-45-67890" not in out
        assert "XXX-XX-XXXXX" in out
        assert "business" in hits

    def test_business_no_hyphen(self):
        out, hits = scrub_response_pii("사업자 1234567890 등록")
        assert "1234567890" not in out
        assert "business" in hits

    def test_email_normal(self):
        out, hits = scrub_response_pii("메일 hello@example.com 보냄")
        assert "hello@example.com" not in out
        # 짧지 않은 local (5자) → 첫 글자 + ***
        assert "h***@example.com" in out
        assert "email" in hits

    def test_email_short_local(self):
        # GPT-5.5 권고: 1-2자 local 은 전체 마스킹
        out, hits = scrub_response_pii("메일 ab@x.com")
        assert "ab@x.com" not in out
        assert "***@x.com" in out
        assert "email" in hits


# ---------------------------------------------------------------------------
# 2. 한글 인접 PII 매칭 (GPT-5.5 권고 A) — 필수
# ---------------------------------------------------------------------------

class TestKoreanAdjacent:
    """`\\b` 회피 — 한글이 PII 양옆에 붙어도 매칭."""

    def test_rrn_korean_adjacent(self):
        out, hits = scrub_response_pii("주민번호900101-1234567입니다")
        assert "900101-1234567" not in out
        assert "rrn" in hits

    def test_phone_korean_adjacent(self):
        out, hits = scrub_response_pii("전화010-1234-5678입니다")
        assert "010-1234-5678" not in out
        assert "phone" in hits

    def test_email_korean_adjacent(self):
        out, hits = scrub_response_pii("메일test@example.com입니다")
        assert "test@example.com" not in out
        assert "email" in hits

    def test_business_korean_adjacent(self):
        out, hits = scrub_response_pii("사업자번호123-45-67890입니다")
        assert "123-45-67890" not in out
        assert "business" in hits


# ---------------------------------------------------------------------------
# 3. 정상 텍스트 (PII 없음) — 5건
# ---------------------------------------------------------------------------

class TestPassthrough:
    """PII 없는 텍스트는 변형 X."""

    def test_empty(self):
        out, hits = scrub_response_pii("")
        assert out == ""
        assert hits == []

    def test_plain_korean(self):
        text = "안녕하세요. 오늘 회의는 오후 3시 입니다."
        out, hits = scrub_response_pii(text)
        assert out == text
        assert hits == []

    def test_short_numbers(self):
        # 짧은 숫자 (가격/수량) — 매칭 X
        text = "가격 15000원 수량 3개"
        out, hits = scrub_response_pii(text)
        assert out == text
        assert hits == []

    def test_date_no_match(self):
        # 날짜 YYYY-MM-DD 는 RRN regex 안 매칭 (앞 4자리)
        text = "회의일 2026-05-11"
        out, hits = scrub_response_pii(text)
        assert "rrn" not in hits

    def test_url_no_match(self):
        # URL 도메인은 이메일 regex 와 다름 (@ 없음)
        text = "https://example.com/page"
        out, hits = scrub_response_pii(text)
        assert out == text
        assert hits == []


# ---------------------------------------------------------------------------
# 4. 경계 케이스 — 5건
# ---------------------------------------------------------------------------

class TestBoundaryCases:
    """false positive / false negative 경계."""

    def test_rrn_invalid_month(self):
        # 13월 = 무효 RRN → 매칭 X (MM (01-12) 제한)
        text = "ID 901301-1234567"
        out, hits = scrub_response_pii(text)
        assert "rrn" not in hits

    def test_rrn_invalid_day(self):
        # 32일 = 무효 → 매칭 X
        text = "ID 900132-1234567"
        out, hits = scrub_response_pii(text)
        assert "rrn" not in hits

    def test_rrn_invalid_gender(self):
        # 7번째 자리 0 = 무효 (1-8 만 유효)
        text = "ID 900101-0234567"
        out, hits = scrub_response_pii(text)
        assert "rrn" not in hits

    def test_phone_not_korean_mobile(self):
        # 02 (서울) — 현재 KR_PHONE 매칭 X (01x 전용)
        text = "전화 02-1234-5678"
        out, hits = scrub_response_pii(text)
        assert "phone" not in hits

    def test_business_inside_longer_number(self):
        # 사업자 10자리가 더 긴 숫자 안에 있으면 매칭 X (lookaround)
        text = "ref 12345678901234"  # 14자리
        out, hits = scrub_response_pii(text)
        # CARD regex (16자리)도 안 잡고 BUSINESS (10자리 정확) 도 안 잡음
        # 단, CARD 의 separator-optional 로 16자리 매칭 시도 → 14자리는 매칭 X.
        # 14자리 통째로 통과.
        assert out == text


# ---------------------------------------------------------------------------
# 5. Idempotence — 이미 마스킹된 값 재처리 안전
# ---------------------------------------------------------------------------

class TestIdempotence:
    """멱등 — 이미 마스킹된 값은 재매칭 안 됨."""

    def test_masked_rrn(self):
        text = "ID XXXXXX-XXXXXXX 입니다"
        out, hits = scrub_response_pii(text)
        assert out == text
        assert hits == []

    def test_masked_phone(self):
        text = "010-****-5678 입니다"
        # 010-****-5678 은 \d{3,4} 영역에 * 가 있어 매칭 안 됨
        out, hits = scrub_response_pii(text)
        assert out == text
        assert hits == []

    def test_masked_email(self):
        text = "***@example.com 입니다"
        out, hits = scrub_response_pii(text)
        # local 이 *** 면 `[\w.+-]+` 매칭 X (* 는 word 아님)
        assert out == text

    def test_masked_card(self):
        text = "XXXX-XXXX-XXXX-XXXX 입니다"
        out, hits = scrub_response_pii(text)
        assert out == text
        assert hits == []

    def test_double_apply(self):
        # apply -> apply -> 동일 결과
        text = "주민번호 900101-1234567 카드 1234-5678-9012-3456"
        out1 = apply_response_pii_filter(text)
        out2 = apply_response_pii_filter(out1)
        assert out1 == out2


# ---------------------------------------------------------------------------
# 5b. D82-residual #D — apply_response_pii_filter idempotency (path 중첩 안전)
# ---------------------------------------------------------------------------
# GPT-5.5 사전 verdict §D 권고:
# _persist_turn path 와 chat_v1.INSERT path 가 *같은 응답에 순차 적용*
# 될 수 있음. 마스킹된 token 이 다시 다른 format 으로 변형되면 payload 불안정.
# failure placeholder 도 다시 마스킹돼 변형되면 안 됨.
# → 각 PII type 별로 1회 vs 2회 apply 결과가 byte-for-byte 동일한지 fixate.
# ---------------------------------------------------------------------------


class TestApplyIdempotencyByType:
    """``apply_response_pii_filter`` 가 PII type 별로 멱등 — D82-residual #D."""

    def test_response_pii_filter_idempotent_phone(self):
        """전화 1회 → "010-****-5678". 2회 → 동일 (재마스킹 없음)."""
        original = "고객 전화 010-1234-5678 입니다"
        once = apply_response_pii_filter(original)
        twice = apply_response_pii_filter(once)
        assert once == twice
        # 1회 적용 후 결과 형식 확인.
        assert "010-1234-5678" not in once
        assert "010-****-5678" in once
        # 2회 적용해도 last4 / prefix 가 보존된 형태 그대로.
        assert "010-****-5678" in twice

    def test_response_pii_filter_idempotent_rrn(self):
        """주민번호 1회 → "XXXXXX-XXXXXXX". 2회 → 동일."""
        original = "주민 900101-1234567 확인했습니다"
        once = apply_response_pii_filter(original)
        twice = apply_response_pii_filter(once)
        assert once == twice
        assert "900101-1234567" not in once
        assert "XXXXXX-XXXXXXX" in once
        assert "XXXXXX-XXXXXXX" in twice

    def test_response_pii_filter_idempotent_card(self):
        """카드 1회 → "XXXX-XXXX-XXXX-XXXX". 2회 → 동일."""
        original = "카드 1234-5678-9012-3456 결제 완료"
        once = apply_response_pii_filter(original)
        twice = apply_response_pii_filter(once)
        assert once == twice
        assert "1234-5678-9012-3456" not in once
        assert "XXXX-XXXX-XXXX-XXXX" in once

    def test_response_pii_filter_idempotent_email(self):
        """이메일 1회 → "h***@example.com". 2회 → 동일.

        masked local "h***" 는 ``[\\w.+-]+`` 매칭 X (``*`` 가 word char 아님) →
        재매칭 안 됨.
        """
        original = "메일 hello@example.com 보냄"
        once = apply_response_pii_filter(original)
        twice = apply_response_pii_filter(once)
        assert once == twice
        assert "hello@example.com" not in once
        assert "h***@example.com" in once
        assert "h***@example.com" in twice

    def test_response_pii_filter_idempotent_business(self):
        """사업자번호 1회 → "XXX-XX-XXXXX". 2회 → 동일."""
        original = "사업자 123-45-67890 등록"
        once = apply_response_pii_filter(original)
        twice = apply_response_pii_filter(once)
        assert once == twice
        assert "123-45-67890" not in once
        assert "XXX-XX-XXXXX" in once

    def test_response_pii_filter_placeholder_remains_stable(self):
        """``[REDACTED: response blocked by PII filter failure]`` placeholder
        가 다시 filter 를 거쳐도 변형/재마스킹되지 않음.

        D82-B filter 실패 fail-closed path 의 wire format 안정성 보장.
        """
        # response_pii_filter 모듈의 실제 placeholder 상수 import.
        from src.agent_framework.runtime.response_pii_filter import (
            _FAILSAFE_PLACEHOLDER,
        )
        once = apply_response_pii_filter(_FAILSAFE_PLACEHOLDER)
        twice = apply_response_pii_filter(once)
        # placeholder 는 PII regex 어디에도 매칭되지 않아야 함.
        assert once == _FAILSAFE_PLACEHOLDER
        assert twice == _FAILSAFE_PLACEHOLDER


class TestApplyIdempotencyCombined:
    """모든 PII type 이 섞인 입력 — 1회 vs 2회 결과 byte-exact 동일."""

    def test_response_pii_filter_idempotent_all_types_combined(self):
        original = (
            "전화 010-1234-5678, 주민 900101-1234567, "
            "카드 1234-5678-9012-3456, 사업자 123-45-67890, "
            "메일 hello@example.com 확인했습니다"
        )
        once = apply_response_pii_filter(original)
        twice = apply_response_pii_filter(once)
        assert once == twice
        # raw token 모두 사라졌는지 sanity.
        for raw in [
            "010-1234-5678",
            "900101-1234567",
            "1234-5678-9012-3456",
            "123-45-67890",
            "hello@example.com",
        ]:
            assert raw not in once, f"{raw} 가 1회 적용 후 잔존"
            assert raw not in twice, f"{raw} 가 2회 적용 후 잔존"

    def test_response_pii_filter_triple_apply_stable(self):
        """3회 적용도 동일 — _persist_turn / chat_v1.INSERT / 추가 layer 가
        동시에 적용돼도 payload 안정성 보장."""
        original = "전화 010-1234-5678 주민 900101-1234567"
        once = apply_response_pii_filter(original)
        twice = apply_response_pii_filter(once)
        thrice = apply_response_pii_filter(twice)
        assert once == twice == thrice


# ---------------------------------------------------------------------------
# 6. fail-closed (예외 처리)
# ---------------------------------------------------------------------------

class TestFailClosed:
    """필터 예외 시 raw text 반환 금지 (placeholder)."""

    def test_scrub_exception_returns_placeholder(self):
        with patch(
            "src.agent_framework.runtime.response_pii_filter.scrub_response_pii"
        ) as m:
            m.side_effect = RuntimeError("simulated")
            out = apply_response_pii_filter("주민 900101-1234567")
            assert "900101-1234567" not in out
            assert "[REDACTED" in out

    def test_log_fn_exception_does_not_break(self):
        def bad_log(types):
            raise RuntimeError("log fail")

        # log_fn 예외 → swallow, 정상 sanitize 반환
        out = apply_response_pii_filter(
            "ID 900101-1234567", log_hit_fn=bad_log
        )
        assert "900101-1234567" not in out

    def test_empty_input(self):
        assert apply_response_pii_filter("") == ""
        assert apply_response_pii_filter(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 7. kill-switch (env)
# ---------------------------------------------------------------------------

class TestKillSwitch:
    """env KMS_RESPONSE_PII_FILTER_ENABLED."""

    def test_default_enabled(self):
        # env 미설정 시 enabled
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KMS_RESPONSE_PII_FILTER_ENABLED", None)
            out = apply_response_pii_filter("주민 900101-1234567")
            assert "900101-1234567" not in out

    def test_disabled_false(self):
        with patch.dict(
            os.environ, {"KMS_RESPONSE_PII_FILTER_ENABLED": "false"}
        ):
            out = apply_response_pii_filter("주민 900101-1234567")
            # disabled 시 원본 통과
            assert "900101-1234567" in out

    def test_disabled_zero(self):
        with patch.dict(os.environ, {"KMS_RESPONSE_PII_FILTER_ENABLED": "0"}):
            out = apply_response_pii_filter("주민 900101-1234567")
            assert "900101-1234567" in out

    def test_invalid_value_fails_closed(self):
        # GPT-5.5 권고: 잘못된 값은 enabled (fail-closed)
        with patch.dict(
            os.environ, {"KMS_RESPONSE_PII_FILTER_ENABLED": "garbage"}
        ):
            out = apply_response_pii_filter("주민 900101-1234567")
            assert "900101-1234567" not in out


# ---------------------------------------------------------------------------
# 8. Streaming (sliding buffer)
# ---------------------------------------------------------------------------

class TestStreaming:
    """SSE chunk split 안전."""

    def test_single_chunk_short(self):
        red = StreamingPIIRedactor()
        # 32자 이하 — buffer 에 머묾, emit 없음
        out = red.feed("hi")
        assert out == ""
        final = red.flush()
        assert final == "hi"

    def test_pii_split_across_chunks(self):
        # GPT-5.5 권고 B: streaming chunk split 테스트 필수
        red = StreamingPIIRedactor()
        # 길이 50 정도 일반 텍스트 prefix → 일부 emit, RRN 은 tail 에 들어감
        prefix = "안녕하세요 회의는 다음과 같이 진행됩니다. 주민번호 900101-"
        chunk2 = "1234567 입니다 끝"
        out1 = red.feed(prefix)
        out2 = red.feed(chunk2)
        final = red.flush()
        full = out1 + out2 + final
        assert "900101-1234567" not in full

    def test_long_stream_aggregate(self):
        red = StreamingPIIRedactor()
        chunks = [
            "이메일은 test@example.com ",
            "전화 010-1234-5678 ",
            "주민 900101-1234567 ",
            "끝.",
        ]
        out = []
        for c in chunks:
            out.append(red.feed(c))
        out.append(red.flush())
        full = "".join(out)
        assert "test@example.com" not in full
        assert "010-1234-5678" not in full
        assert "900101-1234567" not in full

    def test_disabled_passthrough(self):
        with patch.dict(
            os.environ, {"KMS_RESPONSE_PII_FILTER_ENABLED": "false"}
        ):
            red = StreamingPIIRedactor()
            out = red.feed("주민 900101-1234567 끝")
            final = red.flush()
            full = out + final
            assert "900101-1234567" in full


# ---------------------------------------------------------------------------
# 9. D80 baemin 사례 재현 — 통합
# ---------------------------------------------------------------------------

class TestD80BaeminScenario:
    """D80 P0 #2 결함 재현 + 마스킹 검증."""

    def test_baemin_combined_pii(self):
        # D80 baemin 사용자 입력 그대로 + LLM 이 echo 한다고 가정
        text = "고객번호 010-1234-5678 이고 주민번호 900101-1234567 확인했습니다"
        out = apply_response_pii_filter(text)
        # phone 마스킹: 010-****-5678
        assert "010-1234-5678" not in out
        assert "010-****-5678" in out
        # rrn 마스킹: XXXXXX-XXXXXXX
        assert "900101-1234567" not in out
        assert "XXXXXX-XXXXXXX" in out

    def test_all_5_types_combined(self):
        text = (
            "RRN 900101-1234567, 카드 1234-5678-9012-3456, "
            "전화 010-1234-5678, 사업자 123-45-67890, "
            "메일 hello@example.com"
        )
        out, hits = scrub_response_pii(text)
        for raw in [
            "900101-1234567",
            "1234-5678-9012-3456",
            "010-1234-5678",
            "123-45-67890",
            "hello@example.com",
        ]:
            assert raw not in out, f"{raw} 가 마스킹 안 됨"
        assert {"rrn", "card", "phone", "business", "email"} <= set(hits)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
