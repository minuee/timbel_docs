"""Phase 1.5C — LLM 응답 (현재 plain text) → ResponseEnvelope 변환 layer.

`engine.turn` 또는 `plan_orchestrator` 의 응답 phase 에서 final text 를
``ResponseEnvelope`` 로 wrap 한다. 어댑터가 ``str`` 도 받으면 자동 wrap 하므로
이 모듈은 *명시적 entry point* 역할 — 향후 LLM 이 직접 envelope JSON 을 생성
하도록 prompt 진화할 때 (Phase 1.5C 후속) 단일 진입점에서 변경.

설계 원칙:
- 현재: *모든 LLM 응답을 TextBlock 1개로 wrap* (default). 시연 path 무영향.
- 향후: LLM 이 ``{"blocks": [...]}`` JSON 을 생성하면 ``parse_envelope_json``
  으로 강타입 dataclass 로 디코드. JSON parse 실패는 fallback (TextBlock).
- "하드코딩 금지" — 본 모듈은 *변환* 레이어. 응답 본문 결정은 LLM, 채널 매핑은
  어댑터에 둠.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from src.integration.external_agent.response_blocks import (
    AlertBlock,
    ButtonBlock,
    CardBlock,
    CarouselBlock,
    ImageBlock,
    LinkBlock,
    ListCardBlock,
    ListItem,
    QuickReplyBlock,
    ResponseEnvelope,
    TableBlock,
    TextBlock,
)

log = logging.getLogger(__name__)


# JSON 마커 — LLM 이 envelope 으로 응답하고 싶을 때 응답 본문이 이 prefix 로
# 시작하면 JSON 으로 해석. plain text 응답과 안전 분리.
ENVELOPE_JSON_PREFIX = "<<<RESPONSE_ENVELOPE_JSON>>>"
ENVELOPE_JSON_SUFFIX = "<<<END_RESPONSE_ENVELOPE_JSON>>>"


# ---------------------------------------------------------------------------
# Markdown table auto-extract (2026-05-08, 사용자 절칙: "표도 만들고")
# ---------------------------------------------------------------------------
#
# LLM 이 본문 안에 GFM markdown 표를 emit 하면 정규식 detect → TableBlock 으로
# 추출. Telegram 어댑터가 native 매핑 (HTML <pre>) 으로 발송. Web 은 frontend
# 의 react-markdown remark-gfm 이 이미 표 렌더 가능 — 본 helper 는 *Telegram*
# 한정 의미가 큼. 일관성 위해 envelope 양쪽 다 들어가게 한다.
#
# GPT-5 P1 fix:
# - 코드블록 (``` ... ```) 안 표는 detect 무시 — placeholder 로 빼낸 뒤 검사.
# - escaped pipe (\|) 는 cell 구분 X — 정규식 negative lookbehind.
# - header / sep / data row 최소 1줄씩 + sep 의 :?-+: 만 허용.

_CODE_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+\-]*\n.*?```", re.DOTALL)

# table 정규식: header row + sep row + 최소 1 data row.
# - header row: |...|
# - sep row:    |[-: ]+|[-: ]+|... — 각 cell 은 :?---+:? 패턴.
# - data row:   |...|
_TABLE_RE = re.compile(
    r"(?m)"
    r"^[ \t]*\|.+\|[ \t]*\n"            # header row
    r"^[ \t]*\|[\s\-:|]+\|[ \t]*\n"     # separator row
    r"(?:^[ \t]*\|.+\|[ \t]*(?:\n|$))+",  # 1+ data rows
)


def _split_markdown_row(row: str) -> list[str]:
    """markdown table row → cell list.

    escaped pipe (\\|) 는 cell 안 문자로 취급 — split X.
    leading / trailing pipe 는 제거.
    """
    # 임시 escape: \\| → \x01 으로 치환 후 split, 다시 복원.
    safe = row.replace("\\|", "\x01")
    parts = safe.split("|")
    # leading/trailing 빈 문자열 제거 (\| ... |\ 형태).
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [p.strip().replace("\x01", "|") for p in parts]


def extract_markdown_tables(text: str) -> tuple[str, list[TableBlock]]:
    """LLM 본문 안 markdown 표를 detect → TableBlock list 로 추출.

    Args:
        text: LLM final text. 코드블록 안 표는 무시.

    Returns:
        (cleaned_text, table_blocks). cleaned_text 는 표가 제거된 본문.
        table_blocks 는 발견 순서 보존.

    Edge cases:
    - 단일 열 / sep row 위반 → detect false 거부 (정규식 단계에서 거름).
    - escaped pipe (\\|) → cell 내 문자 (split X).
    - 코드블록 (```) 안 표 → 무시.
    """
    if not text or "|" not in text:
        return text, []

    # 1) 코드블록 placeholder 로 빼냄 (안 표는 detect 안 됨).
    code_blocks: list[str] = []

    def _stash(m: re.Match) -> str:
        code_blocks.append(m.group(0))
        return f"\x02CODEFENCE{len(code_blocks)-1}\x02"

    body_no_code = _CODE_FENCE_RE.sub(_stash, text)

    # 2) 표 detect.
    tables: list[TableBlock] = []
    cleaned_parts: list[str] = []
    last_end = 0
    for m in _TABLE_RE.finditer(body_no_code):
        # 본문에서 표 *바로 위* 까지 수집.
        cleaned_parts.append(body_no_code[last_end:m.start()])
        last_end = m.end()
        raw_table = m.group(0).strip()
        rows = [r for r in raw_table.split("\n") if r.strip()]
        if len(rows) < 3:
            # header + sep + 1 data 미만 — 무시.
            continue
        header_cells = _split_markdown_row(rows[0])
        # rows[1] 은 separator — skip.
        data_cells = [_split_markdown_row(r) for r in rows[2:]]
        # 빈 헤더 / 모든 cell 빈 행 → 무시.
        if not any(c.strip() for c in header_cells):
            continue
        data_cells = [r for r in data_cells if any(c.strip() for c in r)]
        if not data_cells:
            continue
        # 컬럼 수 정규화 — 짧은 row 는 빈 cell 로 채움, 긴 row 는 자름.
        n_cols = len(header_cells)
        normalized_rows: list[list[str]] = []
        for r in data_cells:
            if len(r) < n_cols:
                r = list(r) + [""] * (n_cols - len(r))
            elif len(r) > n_cols:
                r = list(r)[:n_cols]
            normalized_rows.append(r)
        tables.append(
            TableBlock(
                title=None,
                markdown=raw_table,
                headers=header_cells,
                rows=normalized_rows,
            )
        )
    cleaned_parts.append(body_no_code[last_end:])
    cleaned = "".join(cleaned_parts)

    # 3) 코드블록 placeholder 복원.
    def _restore(m: re.Match) -> str:
        idx = int(m.group(1))
        return code_blocks[idx] if 0 <= idx < len(code_blocks) else ""

    cleaned = re.sub(r"\x02CODEFENCE(\d+)\x02", _restore, cleaned)
    # 표 제거로 생긴 연속 빈 줄 정리 (3+ 빈 줄 → 2 빈 줄).
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, tables


def render_response(
    text: str,
    *,
    parse_mode: Literal["plain", "markdown"] = "plain",
) -> ResponseEnvelope:
    """LLM final text → ResponseEnvelope.

    현재 동작: 모든 응답을 TextBlock 1개로 wrap (시연 path 와 동일).
    빈 텍스트는 빈 envelope (어댑터 측 no-op).

    Phase 1.5C 후속: LLM 이 envelope JSON 마커로 감싸 보내면 ``parse_envelope_json``
    이 dataclass 로 디코드. 마커 없으면 TextBlock fallback.

    Args:
        text: LLM 이 생성한 final text (token stream 누적 결과).
        parse_mode: 채널이 markdown 으로 해석해야 할 때 ``"markdown"`` 지정.
            기본 ``"plain"`` — 채널 어댑터가 알아서 escape.

    Returns:
        ResponseEnvelope.
    """
    if not text:
        return ResponseEnvelope(blocks=[])

    # 향후 진화 path — envelope JSON 마커 감지.
    if ENVELOPE_JSON_PREFIX in text:
        envelope = _try_parse_envelope_json(text)
        if envelope is not None:
            return envelope
        # parse 실패 → fallback. 마커가 노이즈로 남는 게 더 안 좋으니 제거.
        text = text.replace(ENVELOPE_JSON_PREFIX, "").replace(
            ENVELOPE_JSON_SUFFIX, ""
        ).strip()
        if not text:
            return ResponseEnvelope(blocks=[])

    # 2026-05-08 — markdown mode 일 때 본문 안 표 자동 추출 → TableBlock.
    # 사용자 절칙: "표도 만들고". Telegram 어댑터가 native 매핑 (HTML <pre>)
    # 으로 발송. 본문에선 표 제거 (2번 출력 방지).
    if parse_mode == "markdown":
        cleaned_text, tables = extract_markdown_tables(text)
        blocks: list[Any] = []
        if cleaned_text:
            blocks.append(TextBlock(text=cleaned_text, parse_mode="markdown"))
        # 최대 3 표 까지 envelope 에 첨부 (대화 freeze 방지). 그 이상은 무시 +
        # 본문에 그대로 남게 두지 X — extract_markdown_tables 가 이미 본문에서
        # 제거했으므로, 잘림은 receiver 가 자료 다시 묻게 하는 편이 낫다.
        for t in tables[:3]:
            blocks.append(t)
        return ResponseEnvelope(blocks=blocks)

    return ResponseEnvelope.from_text(text, parse_mode=parse_mode)


def _try_parse_envelope_json(text: str) -> ResponseEnvelope | None:
    """LLM 이 envelope JSON 마커로 감싼 응답을 dataclass 로 디코드.

    형식 (Phase 1.5C 후속 prompt 가 따를 컨벤션):
        <<<RESPONSE_ENVELOPE_JSON>>>
        {"blocks": [{"type": "text", "text": "...", "parse_mode": "plain"}]}
        <<<END_RESPONSE_ENVELOPE_JSON>>>

    parse 실패 / 미지원 type / 잘못된 schema → None (caller 가 plain fallback).
    """
    try:
        start = text.index(ENVELOPE_JSON_PREFIX) + len(ENVELOPE_JSON_PREFIX)
        end_idx = text.find(ENVELOPE_JSON_SUFFIX, start)
        if end_idx == -1:
            # suffix 없음 — JSON 끝까지 사용 시도.
            payload = text[start:].strip()
        else:
            payload = text[start:end_idx].strip()
        if not payload:
            return None
        data = json.loads(payload)
    except (ValueError, json.JSONDecodeError) as e:
        log.warning("envelope_json parse failed: %s", e)
        return None

    return parse_envelope_dict(data)


def parse_envelope_dict(data: Any) -> ResponseEnvelope | None:
    """dict (LLM JSON 출력) → ResponseEnvelope dataclass.

    공개 — 외부 caller 가 직접 decoded JSON 을 envelope 로 변환할 때 사용.
    schema 위반 / 미지원 type → None (caller fallback). 부분적 위반은 무시
    하지 않고 보수적으로 None — 잘못된 응답을 부분 렌더하지 않도록.
    """
    if not isinstance(data, dict):
        return None
    blocks_raw = data.get("blocks")
    if not isinstance(blocks_raw, list):
        return None

    blocks: list[Any] = []
    for raw in blocks_raw:
        block = _parse_block_dict(raw)
        if block is None:
            return None  # 한 블록이라도 위반 → 전체 fallback (보수적).
        blocks.append(block)
    return ResponseEnvelope(blocks=blocks)


def _parse_block_dict(raw: Any) -> Any | None:
    if not isinstance(raw, dict):
        return None
    block_type = raw.get("type")
    if block_type == "text":
        text = raw.get("text")
        if not isinstance(text, str):
            return None
        parse_mode = raw.get("parse_mode") or "plain"
        if parse_mode not in ("plain", "markdown"):
            parse_mode = "plain"
        return TextBlock(text=text, parse_mode=parse_mode)

    if block_type == "card":
        title = raw.get("title")
        if not isinstance(title, str):
            return None
        buttons = _parse_buttons(raw.get("buttons") or [])
        if buttons is None:
            return None
        return CardBlock(
            title=title,
            description=raw.get("description"),
            image_url=raw.get("image_url"),
            buttons=buttons,
        )

    if block_type == "carousel":
        cards_raw = raw.get("cards") or []
        if not isinstance(cards_raw, list):
            return None
        cards: list[CardBlock] = []
        for c in cards_raw:
            cb = _parse_block_dict({**c, "type": "card"}) if isinstance(c, dict) else None
            if not isinstance(cb, CardBlock):
                return None
            cards.append(cb)
        return CarouselBlock(cards=cards)

    if block_type == "quick_reply":
        text = raw.get("text")
        options = raw.get("options")
        if not isinstance(text, str) or not isinstance(options, list):
            return None
        if not all(isinstance(o, str) for o in options):
            return None
        return QuickReplyBlock(text=text, options=options)

    if block_type == "list_card":
        title = raw.get("title")
        if not isinstance(title, str):
            return None
        items_raw = raw.get("items") or []
        if not isinstance(items_raw, list):
            return None
        items: list[ListItem] = []
        for it in items_raw:
            if not isinstance(it, dict):
                return None
            text = it.get("text")
            if not isinstance(text, str):
                return None
            items.append(
                ListItem(
                    text=text,
                    description=it.get("description"),
                    image_url=it.get("image_url"),
                    callback=it.get("callback"),
                )
            )
        buttons = _parse_buttons(raw.get("buttons") or [])
        if buttons is None:
            return None
        return ListCardBlock(title=title, items=items, buttons=buttons)

    return None  # 알 수 없는 type


def _parse_buttons(raw: Any) -> list[ButtonBlock] | None:
    if not isinstance(raw, list):
        return None
    out: list[ButtonBlock] = []
    for b in raw:
        if not isinstance(b, dict):
            return None
        label = b.get("label")
        action = b.get("action")
        payload = b.get("payload")
        if not isinstance(label, str):
            return None
        if action not in ("url", "postback", "phone", "share"):
            return None
        if not isinstance(payload, str):
            return None
        out.append(ButtonBlock(label=label, action=action, payload=payload))
    return out


def append_structured_blocks_to_envelope(
    envelope: ResponseEnvelope,
    structured_block_events: list[dict],
) -> ResponseEnvelope:
    """SSE structured_block events → ResponseEnvelope 확장 (KMS-Plus 2026-05-07).

    GPT-5 검증 P0-2 fix — Telegram 등 non-Web 채널이 SSE structured_block 을
    못 받으니 webhook layer 가 capture 한 list 를 envelope 에 append 한다.
    Web 은 SSE 직접 수신하므로 webhook layer 는 영향 X.

    schema 정규화 — engine emit 두 종류 호환:
    1. {kind: "table"|"image", payload: {...}, title?, source_citation?}
       → multimodal_blocks 경로 (KMS-Plus 표준).
    2. {type: "table"|"image", data: {...}, tool?}
       → legacy PR-Z15 _structured_card 경로.

    GPT-5 P0-3 — image_url 빈 문자열 / raw 내부 경로면 ImageBlock 자체를 만들지
    않음 (Telegram sendPhoto 실패 차단). caption 만 있으면 TextBlock fallback.

    GPT-5 P1-2 — caption 1024자 cap (Telegram sendPhoto 한도).
    GPT-5 P1-4 — 최대 5 block (chat freeze 차단).
    GPT-5 P1-5 — (kind, image_url|markdown_hash) dedup.

    Args:
        envelope: render_response 결과 (대개 TextBlock 1개).
        structured_block_events: webhook tee 가 모아둔 SSE data dict list.

    Returns:
        새 ResponseEnvelope — 기존 blocks + multimodal blocks. 입력 변경 X (immutable).
    """
    if not structured_block_events:
        return envelope

    MAX_APPEND = 5
    MAX_CAPTION = 900  # Telegram sendPhoto caption 1024 한도 - safe margin.
    new_blocks = list(envelope.blocks)
    seen: set[tuple] = set()
    appended = 0

    for ev in structured_block_events:
        if appended >= MAX_APPEND:
            break
        if not isinstance(ev, dict):
            continue
        # schema 정규화 — kind/payload (multimodal) 우선, type/data (legacy) 폴백.
        kind = ev.get("kind") or ev.get("type")
        if not isinstance(kind, str):
            continue
        kind = kind.strip().lower()
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else (
            ev.get("data") if isinstance(ev.get("data"), dict) else {}
        )
        title = ev.get("title")
        if not isinstance(title, str):
            title = payload.get("title") if isinstance(payload, dict) else None
        if not isinstance(title, str):
            title = None
        src_cite = ev.get("source_citation")
        if not isinstance(src_cite, int):
            src_cite = None

        if kind == "table":
            md = payload.get("markdown") if isinstance(payload, dict) else None
            headers = payload.get("headers") if isinstance(payload, dict) else None
            rows = payload.get("rows") if isinstance(payload, dict) else None
            md_str = md.strip() if isinstance(md, str) else ""
            if not md_str and not (
                isinstance(headers, list) and headers
                and isinstance(rows, list) and rows
            ):
                continue  # 빈 표 — emit 안 함.
            dedup_key = (
                "table",
                hash(md_str[:512]) if md_str else hash(repr((headers, rows))[:512]),
            )
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            new_blocks.append(
                TableBlock(
                    title=title,
                    markdown=md_str or None,
                    headers=list(headers) if isinstance(headers, list) else [],
                    rows=[list(r) for r in rows] if isinstance(rows, list) else [],
                    source_citation=src_cite,
                )
            )
            appended += 1
        elif kind == "image":
            iurl = payload.get("image_url") if isinstance(payload, dict) else None
            cap = payload.get("caption") if isinstance(payload, dict) else None
            iurl_str = iurl.strip() if isinstance(iurl, str) else ""
            cap_str = cap.strip() if isinstance(cap, str) else ""
            # GPT-5 P0-3 — empty/local-only image URL fallback to TextBlock.
            if not iurl_str:
                if cap_str:
                    new_blocks.append(TextBlock(text=cap_str[:MAX_CAPTION]))
                    appended += 1
                continue
            dedup_key = ("image", iurl_str)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            new_blocks.append(
                ImageBlock(
                    image_url=iurl_str,
                    caption=cap_str[:MAX_CAPTION] if cap_str else None,
                    source_citation=src_cite,
                )
            )
            appended += 1
        elif kind == "link":
            url = payload.get("url") if isinstance(payload, dict) else None
            if not isinstance(url, str) or not url.strip():
                continue
            dedup_key = ("link", url.strip())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            new_blocks.append(
                LinkBlock(
                    url=url.strip(),
                    title=title,
                    description=(
                        payload.get("description")
                        if isinstance(payload, dict) else None
                    ),
                    source_citation=src_cite,
                )
            )
            appended += 1
        elif kind == "alert":
            text = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(text, str) or not text.strip():
                continue
            level = payload.get("level") if isinstance(payload, dict) else None
            if level not in ("info", "warning", "error", "success"):
                level = "info"
            new_blocks.append(
                AlertBlock(text=text.strip(), level=level, title=title)
            )
            appended += 1
        # 그 외 kind (chart/card_list/file_preview 등) 는 Telegram 매핑 X — skip.

    return ResponseEnvelope(blocks=new_blocks)


__all__ = [
    "render_response",
    "parse_envelope_dict",
    "append_structured_blocks_to_envelope",
    "extract_markdown_tables",
    "ENVELOPE_JSON_PREFIX",
    "ENVELOPE_JSON_SUFFIX",
]
