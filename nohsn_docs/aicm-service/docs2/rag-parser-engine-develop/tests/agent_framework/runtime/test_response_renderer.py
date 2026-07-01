"""Phase 1.5C — response_renderer 테스트.

LLM final text → ResponseEnvelope 변환 layer 의 default (TextBlock wrap) +
미래 진화 path (envelope JSON 마커 디코드) 검증.
"""
from __future__ import annotations

import json

import pytest

from src.agent_framework.runtime.response_renderer import (
    ENVELOPE_JSON_PREFIX,
    ENVELOPE_JSON_SUFFIX,
    append_structured_blocks_to_envelope,
    parse_envelope_dict,
    render_response,
)
from src.integration.external_agent.response_blocks import (
    AlertBlock,
    ButtonBlock,
    CardBlock,
    CarouselBlock,
    ImageBlock,
    LinkBlock,
    ListCardBlock,
    QuickReplyBlock,
    ResponseEnvelope,
    TableBlock,
    TextBlock,
)


# ---------------------------------------------------------------------------
# Default — plain text → TextBlock
# ---------------------------------------------------------------------------


def test_render_plain_text_wraps_to_single_text_block():
    e = render_response("안녕하세요")
    assert isinstance(e, ResponseEnvelope)
    assert len(e.blocks) == 1
    assert isinstance(e.blocks[0], TextBlock)
    assert e.blocks[0].text == "안녕하세요"
    assert e.blocks[0].parse_mode == "plain"


def test_render_empty_text_returns_empty_envelope():
    e = render_response("")
    assert e.is_empty()


def test_render_markdown_mode_passes_through():
    e = render_response("*굵게*", parse_mode="markdown")
    assert e.blocks[0].parse_mode == "markdown"


# ---------------------------------------------------------------------------
# Envelope JSON 마커 디코드 (Phase 1.5C 후속 prep)
# ---------------------------------------------------------------------------


def test_envelope_json_marker_decodes_text_block():
    payload = json.dumps({"blocks": [{"type": "text", "text": "안녕"}]})
    text = f"{ENVELOPE_JSON_PREFIX}\n{payload}\n{ENVELOPE_JSON_SUFFIX}"
    e = render_response(text)
    assert len(e.blocks) == 1
    assert isinstance(e.blocks[0], TextBlock)
    assert e.blocks[0].text == "안녕"


def test_envelope_json_marker_decodes_card_block():
    payload = json.dumps({
        "blocks": [{
            "type": "card",
            "title": "공지",
            "description": "오늘은 점검",
            "image_url": "https://x/p.jpg",
            "buttons": [
                {"label": "자세히", "action": "url", "payload": "https://x/d"},
            ],
        }]
    })
    text = f"{ENVELOPE_JSON_PREFIX}{payload}{ENVELOPE_JSON_SUFFIX}"
    e = render_response(text)
    assert len(e.blocks) == 1
    assert isinstance(e.blocks[0], CardBlock)
    assert e.blocks[0].title == "공지"
    assert len(e.blocks[0].buttons) == 1
    assert e.blocks[0].buttons[0].action == "url"


def test_envelope_json_marker_decodes_quick_reply():
    payload = json.dumps({
        "blocks": [{
            "type": "quick_reply",
            "text": "선택해주세요",
            "options": ["예", "아니오"],
        }]
    })
    text = f"{ENVELOPE_JSON_PREFIX}{payload}{ENVELOPE_JSON_SUFFIX}"
    e = render_response(text)
    assert isinstance(e.blocks[0], QuickReplyBlock)
    assert e.blocks[0].options == ["예", "아니오"]


def test_envelope_json_marker_decodes_carousel():
    payload = json.dumps({
        "blocks": [{
            "type": "carousel",
            "cards": [
                {"title": "A"},
                {"title": "B", "description": "B-desc"},
            ],
        }]
    })
    text = f"{ENVELOPE_JSON_PREFIX}{payload}{ENVELOPE_JSON_SUFFIX}"
    e = render_response(text)
    assert isinstance(e.blocks[0], CarouselBlock)
    assert len(e.blocks[0].cards) == 2
    assert e.blocks[0].cards[0].title == "A"


def test_envelope_json_marker_decodes_list_card():
    payload = json.dumps({
        "blocks": [{
            "type": "list_card",
            "title": "FAQ",
            "items": [
                {"text": "환불", "callback": "faq:refund"},
                {"text": "배송"},
            ],
        }]
    })
    text = f"{ENVELOPE_JSON_PREFIX}{payload}{ENVELOPE_JSON_SUFFIX}"
    e = render_response(text)
    assert isinstance(e.blocks[0], ListCardBlock)
    assert len(e.blocks[0].items) == 2
    assert e.blocks[0].items[0].callback == "faq:refund"


# ---------------------------------------------------------------------------
# Fallback — 잘못된 JSON / 미지원 type → TextBlock fallback
# ---------------------------------------------------------------------------


def test_invalid_json_falls_back_to_text():
    text = f"{ENVELOPE_JSON_PREFIX}NOT JSON{ENVELOPE_JSON_SUFFIX}"
    e = render_response(text)
    # 마커는 stripped + 본문 비면 빈 envelope.
    # parse 실패 → marker 제거 → "NOT JSON" 만 남음 → TextBlock fallback.
    assert len(e.blocks) == 1
    assert isinstance(e.blocks[0], TextBlock)
    assert "NOT JSON" in e.blocks[0].text


def test_unknown_block_type_returns_none_strict():
    """schema 위반은 보수적으로 None — 부분 렌더 X."""
    data = {"blocks": [{"type": "image", "url": "..."}]}
    assert parse_envelope_dict(data) is None


def test_button_invalid_action_strict():
    data = {"blocks": [{
        "type": "card",
        "title": "x",
        "buttons": [{"label": "y", "action": "INVALID", "payload": "z"}],
    }]}
    assert parse_envelope_dict(data) is None


def test_text_block_missing_text_strict():
    data = {"blocks": [{"type": "text"}]}
    assert parse_envelope_dict(data) is None


def test_blocks_not_list_returns_none():
    assert parse_envelope_dict({"blocks": "not a list"}) is None
    assert parse_envelope_dict({}) is None
    assert parse_envelope_dict("string") is None


# ---------------------------------------------------------------------------
# 호환성 — engine integration 시나리오
# ---------------------------------------------------------------------------


def test_engine_integration_default_path_no_change():
    """시연 path: engine 이 plain text 응답 → render_response → adapter.

    어댑터가 ``response`` 키워드로 ResponseEnvelope 받아 정확히 1개 sendMessage.
    """
    final_text = "오늘 일정은 3건 있어요."
    e = render_response(final_text)
    # 어댑터 호환 — TextBlock 1개로 wrap.
    assert len(e.blocks) == 1
    assert e.blocks[0].text == final_text


# ---------------------------------------------------------------------------
# KMS-Plus 2026-05-07 — append_structured_blocks_to_envelope (GPT-5 P0-2 fix)
# ---------------------------------------------------------------------------


def test_append_table_structured_block_kind_payload_schema():
    """multimodal kind/payload schema → TableBlock 추가."""
    base = render_response("표 자료를 첨부합니다.")
    events = [
        {
            "kind": "table",
            "title": "단가표",
            "payload": {"markdown": "| a | b |\n|---|---|\n| 1 | 2 |"},
        }
    ]
    e = append_structured_blocks_to_envelope(base, events)
    assert len(e.blocks) == 2
    assert isinstance(e.blocks[0], TextBlock)
    assert isinstance(e.blocks[1], TableBlock)
    assert e.blocks[1].title == "단가표"
    assert "| 1 | 2 |" in (e.blocks[1].markdown or "")


def test_append_image_structured_block_with_caption():
    base = render_response("이미지 첨부.")
    events = [
        {
            "kind": "image",
            "title": "지점 안내도",
            "payload": {
                "image_url": "/api/v1/preview/images/tmp/aicm_x/p1.png",
                "caption": "강남역 2번 출구",
            },
        }
    ]
    e = append_structured_blocks_to_envelope(base, events)
    assert len(e.blocks) == 2
    assert isinstance(e.blocks[1], ImageBlock)
    assert e.blocks[1].image_url.endswith("/p1.png")
    assert e.blocks[1].caption == "강남역 2번 출구"


def test_append_image_no_url_falls_back_to_text():
    """GPT-5 P0-3 — image_url 빈 문자열이면 caption 만 TextBlock 으로 fallback."""
    base = render_response("응답.")
    events = [
        {"kind": "image", "payload": {"image_url": "", "caption": "이미지 누락 안내"}}
    ]
    e = append_structured_blocks_to_envelope(base, events)
    assert len(e.blocks) == 2
    # ImageBlock 이 아니라 TextBlock 으로 fallback.
    assert isinstance(e.blocks[1], TextBlock)
    assert "이미지 누락 안내" in e.blocks[1].text


def test_append_caption_truncated_to_900():
    """GPT-5 P1-2 — caption 1024 한도 안전 margin (900자) truncate."""
    long_cap = "가" * 2000
    base = render_response("긴 caption.")
    events = [
        {"kind": "image", "payload": {"image_url": "https://x/y.png", "caption": long_cap}}
    ]
    e = append_structured_blocks_to_envelope(base, events)
    img = e.blocks[1]
    assert isinstance(img, ImageBlock)
    assert len(img.caption or "") <= 900


def test_append_dedup_image_by_url():
    """GPT-5 P1-5 — 같은 image_url 두 번 들어와도 1개만."""
    base = render_response(".")
    events = [
        {"kind": "image", "payload": {"image_url": "https://x/y.png"}},
        {"kind": "image", "payload": {"image_url": "https://x/y.png", "caption": "again"}},
    ]
    e = append_structured_blocks_to_envelope(base, events)
    image_blocks = [b for b in e.blocks if isinstance(b, ImageBlock)]
    assert len(image_blocks) == 1


def test_append_max_5_blocks():
    """GPT-5 P1-4 — 6 events 들어와도 5 block 까지만 append."""
    base = render_response(".")
    events = [
        {"kind": "image", "payload": {"image_url": f"https://x/img{i}.png"}}
        for i in range(8)
    ]
    e = append_structured_blocks_to_envelope(base, events)
    image_blocks = [b for b in e.blocks if isinstance(b, ImageBlock)]
    assert len(image_blocks) == 5


def test_append_legacy_type_data_schema_normalized():
    """legacy PR-Z15 schema (type/data) 도 dispatch — 호환 path."""
    base = render_response(".")
    events = [
        {
            "type": "table",
            "data": {"title": "표", "markdown": "| a | b |\n|---|---|\n| 1 | 2 |"},
        }
    ]
    e = append_structured_blocks_to_envelope(base, events)
    tables = [b for b in e.blocks if isinstance(b, TableBlock)]
    assert len(tables) == 1
    assert "| 1 | 2 |" in (tables[0].markdown or "")


def test_append_link_and_alert():
    base = render_response(".")
    events = [
        {"kind": "link", "title": "공식", "payload": {"url": "https://x.com/a"}},
        {"kind": "alert", "payload": {"text": "주의 안내", "level": "warning"}},
    ]
    e = append_structured_blocks_to_envelope(base, events)
    kinds = [type(b).__name__ for b in e.blocks]
    assert "LinkBlock" in kinds
    assert "AlertBlock" in kinds


def test_append_empty_events_returns_same():
    base = render_response("hi")
    e = append_structured_blocks_to_envelope(base, [])
    assert len(e.blocks) == len(base.blocks)


def test_append_unknown_kind_skipped():
    base = render_response("hi")
    events = [{"kind": "unknown_xyz", "payload": {}}]
    e = append_structured_blocks_to_envelope(base, events)
    assert len(e.blocks) == 1  # 변화 없음
