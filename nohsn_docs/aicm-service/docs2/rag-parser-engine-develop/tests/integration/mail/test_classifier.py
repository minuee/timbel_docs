"""PR-Z11A — EmailClassifier 단위 테스트 (stub LLM).

검증:
- JSON parse 성공: 카테고리 normalize, 자유 어휘 → guide enum 매핑
- LLM 실패 graceful fallback: category=uncertain, trust=0.5
- HTML-only 메일: body_html → BeautifulSoup → text 변환 후 prompt 포함
- ```json fence``` 제거
- trust_score / priority coercion
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from src.integration.mail.classifier import (
    CATEGORY_GUIDE,
    ClassificationResult,
    EmailClassifier,
    _build_iso_summary,
    _format_iso_human,
    _html_to_text,
    _normalize_category,
)


@dataclass
class _StubEmail:
    uid: str = "1"
    message_id: str | None = "<m1@example.com>"
    from_address: str | None = "Boss <boss@company.com>"
    from_domain: str | None = "company.com"
    to_address: str | None = "me@me.com"
    subject: str | None = "내일 오후 3시 미팅 가능?"
    date_iso: str | None = "Mon, 28 Apr 2026 10:00:00 +0900"
    body_text: str = "내일 오후 3시 회의실 A 에서 미팅합시다. 가능 여부 회신 부탁."
    body_html: str | None = None
    headers: dict[str, str] | None = None
    raw_size: int = 200

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {}


# ---------------------------------------------------------------------------
# normalize / html
# ---------------------------------------------------------------------------


def test_normalize_known_categories():
    for k in CATEGORY_GUIDE:
        assert _normalize_category(k) == k


def test_normalize_synonyms_to_meeting_request():
    assert _normalize_category("meeting") == "meeting_request"
    assert _normalize_category("미팅") == "meeting_request"
    assert _normalize_category("schedule_request") == "meeting_request"


def test_normalize_synonyms_to_advertisement():
    assert _normalize_category("promo") == "advertisement"
    assert _normalize_category("광고") == "advertisement"
    assert _normalize_category("sale") == "advertisement"


def test_normalize_unknown_returns_uncertain():
    assert _normalize_category("xyz_random_label") == "uncertain"
    assert _normalize_category(None) == "uncertain"
    assert _normalize_category("") == "uncertain"


def test_html_to_text_strips_tags_and_scripts():
    html = "<html><body><script>alert(1)</script><p>Hello <b>World</b></p></body></html>"
    out = _html_to_text(html)
    assert "Hello" in out
    assert "World" in out
    assert "alert" not in out


def test_html_to_text_empty():
    assert _html_to_text("") == ""


# ---------------------------------------------------------------------------
# classify — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_meeting_request_happy_path():
    """LLM stub 가 회의 요청 JSON 반환 → category 정규화 + entities 보존."""

    async def _stub_llm(prompt: str) -> str:
        # prompt 에 subject/body 가 포함되어 있는지 가벼운 검증
        assert "내일 오후 3시" in prompt
        return json.dumps(
            {
                "category": "meeting_request",
                "subcategory_reason": "회의 일정 제안 + 회신 요청",
                "trust_score": 0.85,
                "trust_factors": ["sender domain matches company", "explicit time + location"],
                "priority": "high",
                "extracted_entities": {
                    "datetime_iso": "2026-04-29T15:00",
                    "datetime_natural": "내일 오후 3시",
                    "location": "회의실 A",
                    "attendees": ["boss@company.com"],
                    "action_required": "응답",
                    "subject_summary": "내일 3시 미팅 회신 요청",
                },
                "needs_user_attention": True,
                "needs_meeting_prep": True,
            },
            ensure_ascii=False,
        )

    cls = EmailClassifier(llm=_stub_llm)
    result = await cls.classify(_StubEmail())

    assert isinstance(result, ClassificationResult)
    assert result.category == "meeting_request"
    assert result.priority == "high"
    assert 0.0 <= result.trust_score <= 1.0
    assert result.trust_score == 0.85
    assert result.extracted_entities["location"] == "회의실 A"
    assert result.extracted_entities["datetime_natural"] == "내일 오후 3시"
    assert result.needs_user_attention is True
    assert result.needs_meeting_prep is True

    # to_dict 직렬화 가능 (JSONB 저장)
    d = result.to_dict()
    json.dumps(d)  # 예외 없으면 OK


@pytest.mark.asyncio
async def test_classify_freeform_category_normalized():
    """LLM 이 'mtg' 같은 자유 어휘 답해도 meeting_request 로 매핑."""

    async def _stub_llm(prompt: str) -> str:
        return json.dumps(
            {
                "category": "mtg",  # 자유 어휘
                "subcategory_reason": "회의",
                "trust_score": 0.7,
                "trust_factors": [],
                "priority": "normal",
                "extracted_entities": {},
                "needs_user_attention": False,
                "needs_meeting_prep": False,
            }
        )

    cls = EmailClassifier(llm=_stub_llm)
    result = await cls.classify(_StubEmail())
    assert result.category == "meeting_request"


@pytest.mark.asyncio
async def test_classify_with_json_fence_extraction():
    """```json ... ``` fence 가 있어도 파싱 성공."""

    async def _stub_llm(prompt: str) -> str:
        return (
            "```json\n"
            + json.dumps({
                "category": "advertisement",
                "subcategory_reason": "promo email",
                "trust_score": 0.4,
                "trust_factors": ["List-Unsubscribe present"],
                "priority": "low",
                "extracted_entities": {},
                "needs_user_attention": False,
                "needs_meeting_prep": False,
            })
            + "\n```"
        )

    cls = EmailClassifier(llm=_stub_llm)
    result = await cls.classify(_StubEmail())
    assert result.category == "advertisement"
    assert result.priority == "low"


# ---------------------------------------------------------------------------
# fallback paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_no_llm_returns_uncertain():
    cls = EmailClassifier(llm=None)
    result = await cls.classify(_StubEmail())
    assert result.category == "uncertain"
    assert result.trust_score == 0.5
    assert "LLM" in result.subcategory_reason
    assert result.needs_user_attention is True


@pytest.mark.asyncio
async def test_classify_llm_exception_returns_uncertain():
    async def _broken(prompt: str) -> str:
        raise RuntimeError("vllm down")

    cls = EmailClassifier(llm=_broken)
    result = await cls.classify(_StubEmail())
    assert result.category == "uncertain"
    assert result.trust_score == 0.5
    assert "LLM 분류 실패" in result.subcategory_reason


@pytest.mark.asyncio
async def test_classify_llm_returns_garbage_returns_uncertain():
    async def _garbage(prompt: str) -> str:
        return "this is not json at all, sorry"

    cls = EmailClassifier(llm=_garbage)
    result = await cls.classify(_StubEmail())
    assert result.category == "uncertain"
    assert "JSON 파싱 실패" in result.subcategory_reason


@pytest.mark.asyncio
async def test_classify_trust_score_clamped():
    async def _out_of_range(prompt: str) -> str:
        return json.dumps(
            {
                "category": "newsletter",
                "subcategory_reason": "x",
                "trust_score": 5.0,  # > 1.0
                "trust_factors": [],
                "priority": "weird",
                "extracted_entities": {},
                "needs_user_attention": False,
                "needs_meeting_prep": False,
            }
        )

    cls = EmailClassifier(llm=_out_of_range)
    result = await cls.classify(_StubEmail())
    assert result.trust_score == 1.0  # clamped
    assert result.priority == "normal"  # weird → default


# ---------------------------------------------------------------------------
# HTML-only body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_html_only_body_converted_in_prompt():
    """body_text 가 비어있고 body_html 만 있을 때 LLM prompt 에 변환된 텍스트가 들어감."""

    captured: dict[str, str] = {}

    async def _capture(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(
            {
                "category": "advertisement",
                "subcategory_reason": "promo HTML",
                "trust_score": 0.3,
                "trust_factors": [],
                "priority": "low",
                "extracted_entities": {},
                "needs_user_attention": False,
                "needs_meeting_prep": False,
            }
        )

    email = _StubEmail(
        body_text="",
        body_html="<html><body><h1>Big Sale</h1><p>50% off everything</p></body></html>",
        from_address="promo@aliexpress.com",
        from_domain="aliexpress.com",
        subject="Sale!",
    )

    cls = EmailClassifier(llm=_capture)
    result = await cls.classify(email)
    assert result.category == "advertisement"
    assert "Big Sale" in captured["prompt"]
    assert "50% off" in captured["prompt"]
    # script/style 같은 raw HTML 태그는 제거되어야 함
    assert "<h1>" not in captured["prompt"]


# ---------------------------------------------------------------------------
# Datetime v2 — ISO/recurrence/events/entity_summary_iso
# ---------------------------------------------------------------------------


def test_format_iso_human_handles_kst_offset():
    # +09:00 offset 그대로 — KST 변환 후 시각만 추출
    assert _format_iso_human("2026-04-29T15:00:00+09:00") == "2026-04-29 15:00"
    # UTC 입력은 KST (+9h) 환산
    assert _format_iso_human("2026-04-29T06:00:00Z") == "2026-04-29 15:00"
    # naive 는 그대로 — KST 가정
    assert _format_iso_human("2026-04-29T15:00") == "2026-04-29 15:00"
    # date-only 패스스루
    assert _format_iso_human("2026-04-29") == "2026-04-29"
    # 빈 입력
    assert _format_iso_human("") == ""
    # 파싱 실패 → 원문 보존
    assert _format_iso_human("garbage") == "garbage"


def test_build_iso_summary_format():
    # 정상 — datetime + 장소
    s = _build_iso_summary(
        {"datetime_iso": "2026-04-29T15:00:00+09:00", "location": "온라인 웨비나"}
    )
    assert s == "(2026-04-29 15:00 KST, 온라인 웨비나)"

    # date-only — KST 라벨 생략
    s = _build_iso_summary({"datetime_iso": "2026-04-29", "location": ""})
    assert s == "(2026-04-29)"

    # events fallback — datetime_iso 비어있고 events[0].when_iso 사용
    s = _build_iso_summary(
        {
            "datetime_iso": "",
            "events": [
                {"kind": "event", "when_iso": "2026-05-01T14:00:00+09:00"}
            ],
            "location": "Synology Online",
        }
    )
    assert "2026-05-01 14:00 KST" in s
    assert "Synology Online" in s

    # recurrence 부기
    s = _build_iso_summary(
        {
            "datetime_iso": "2026-05-05T09:00:00+09:00",
            "location": "",
            "recurrence": "매주 화요일",
        }
    )
    assert "매주 화요일" in s
    assert "2026-05-05 09:00 KST" in s

    # 시각 정보 없음 — subject_summary fallback
    s = _build_iso_summary(
        {"datetime_iso": "", "events": [], "subject_summary": "fallback 요약"}
    )
    assert s == "fallback 요약"


@pytest.mark.asyncio
async def test_classify_extracts_iso_recurrence_events_summary():
    """LLM 이 v2 ISO/recurrence/events 를 박으면 그대로 보존 + entity_summary_iso 자동 생성."""

    async def _stub_llm(prompt: str) -> str:
        # prompt 에 KST 기준 시각이 포함되어야 함
        assert "now_kst" in prompt
        assert "Asia/Seoul" in prompt or "KST" in prompt
        return json.dumps(
            {
                "category": "conference_info",
                "subcategory_reason": "Synology 웨비나 안내",
                "trust_score": 0.9,
                "trust_factors": ["sender domain matches", "explicit datetime"],
                "priority": "normal",
                "extracted_entities": {
                    "datetime_iso": "2026-04-29T15:00:00+09:00",
                    "datetime_natural": "4월 29일 오후 3시",
                    "deadline_iso": "2026-04-28T23:59:00+09:00",
                    "recurrence": "",
                    "events": [
                        {
                            "kind": "registration_deadline",
                            "when_iso": "2026-04-28T23:59:00+09:00",
                            "when_natural": "등록 마감",
                        },
                        {
                            "kind": "event",
                            "when_iso": "2026-04-29T15:00:00+09:00",
                            "when_natural": "웨비나 본 행사",
                        },
                    ],
                    "timezone": "Asia/Seoul",
                    "location": "온라인 웨비나",
                    "attendees": [],
                    "action_required": "확인",
                    "subject_summary": "Synology 웨비나 안내",
                },
                "needs_user_attention": False,
                "needs_meeting_prep": False,
            },
            ensure_ascii=False,
        )

    cls = EmailClassifier(llm=_stub_llm)
    result = await cls.classify(_StubEmail())

    ents = result.extracted_entities
    assert ents["datetime_iso"] == "2026-04-29T15:00:00+09:00"
    assert ents["deadline_iso"] == "2026-04-28T23:59:00+09:00"
    assert ents["timezone"] == "Asia/Seoul"
    assert len(ents["events"]) == 2
    assert ents["events"][0]["kind"] == "registration_deadline"
    assert ents["events"][1]["kind"] == "event"
    # frontend 목록용 한 줄 — ISO 포맷으로 자동 생성
    assert ents["entity_summary_iso"] == "(2026-04-29 15:00 KST, 온라인 웨비나)"


@pytest.mark.asyncio
async def test_classify_recurrence_appears_in_summary():
    async def _stub_llm(prompt: str) -> str:
        return json.dumps(
            {
                "category": "meeting_request",
                "subcategory_reason": "주간 정기 회의",
                "trust_score": 0.8,
                "trust_factors": [],
                "priority": "normal",
                "extracted_entities": {
                    "datetime_iso": "2026-05-05T14:00:00+09:00",
                    "datetime_natural": "매주 화요일 오후 2시",
                    "recurrence": "FREQ=WEEKLY;BYDAY=TU",
                    "events": [],
                    "timezone": "Asia/Seoul",
                    "location": "Zoom",
                    "attendees": [],
                    "action_required": "확인",
                    "subject_summary": "주간 회의",
                },
                "needs_user_attention": False,
                "needs_meeting_prep": False,
            },
            ensure_ascii=False,
        )

    cls = EmailClassifier(llm=_stub_llm)
    result = await cls.classify(_StubEmail())
    ents = result.extracted_entities
    assert ents["recurrence"] == "FREQ=WEEKLY;BYDAY=TU"
    # summary 에 recurrence 부기 + KST 시각 포함
    summary = ents["entity_summary_iso"]
    assert "FREQ=WEEKLY;BYDAY=TU" in summary
    assert "2026-05-05 14:00 KST" in summary


@pytest.mark.asyncio
async def test_classify_missing_entities_yields_fallback_summary():
    """LLM 이 entities 를 비워도 fallback 키 모두 채워지고 summary 는 빈 문자열."""

    async def _stub_llm(prompt: str) -> str:
        return json.dumps(
            {
                "category": "newsletter",
                "subcategory_reason": "일반 뉴스레터",
                "trust_score": 0.6,
                "trust_factors": [],
                "priority": "low",
                "extracted_entities": {},
                "needs_user_attention": False,
                "needs_meeting_prep": False,
            }
        )

    cls = EmailClassifier(llm=_stub_llm)
    result = await cls.classify(_StubEmail())
    ents = result.extracted_entities
    # v2 키 모두 존재
    for key in (
        "datetime_iso",
        "datetime_natural",
        "deadline_iso",
        "recurrence",
        "events",
        "timezone",
        "location",
        "attendees",
        "action_required",
        "subject_summary",
        "entity_summary_iso",
    ):
        assert key in ents
    assert ents["timezone"] == "Asia/Seoul"
    assert ents["events"] == []
    # 시각 정보 없음 → entity_summary_iso 빈 문자열 (subject_summary 도 빈 입력이므로)
    assert ents["entity_summary_iso"] == ""
