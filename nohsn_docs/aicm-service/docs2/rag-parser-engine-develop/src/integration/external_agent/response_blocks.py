"""채널 응답 블록 5종 표준 — text / card / carousel / quick_reply / list_card.

Phase 1.5C — KakaoTalk for Business 25 컨셉의 *응답 설정 (Setup Answer)* 매핑.
KakaoTalk / Slack / Discord / LINE / Telegram 등 채널마다 native 카드/캐러셀/
빠른답변 포맷이 다르지만, 우리 시스템은 *abstract* 한 ``ResponseEnvelope`` 만
다루고 채널 어댑터가 native format 으로 변환한다.

설계 원칙:
- LLM 출력 = 단순 plain text 일 때 ``ResponseEnvelope([TextBlock(text)])`` 로
  자동 wrap (호환). 향후 LLM 이 직접 envelope JSON 을 생성하도록 prompt 진화.
- dataclass 만 사용 — pydantic / 외부 의존성 없음.
- 채널 native 미지원 type 은 어댑터가 안전 fallback (예: Telegram 의 carousel
  은 native 없음 — 순차 sendPhoto). 절대 raise 하지 않음.

블록 5종:
1. ``TextBlock``       — 기본 텍스트.
2. ``CardBlock``       — 단일 카드 (제목 + 설명 + 이미지 + 버튼).
3. ``CarouselBlock``   — 가로 슬라이드 카드 묶음.
4. ``QuickReplyBlock`` — 사용자 빠른답변 버튼 (one-tap reply).
5. ``ListCardBlock``   — 항목 리스트 (FAQ / 메뉴 / 검색결과).

"하드코딩 금지" 원칙: 본 모듈은 *데이터 컨테이너* 만 정의. 채널별 변환 정책은
어댑터에, LLM → envelope 변환은 ``response_renderer`` 에 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union


# ---------------------------------------------------------------------------
# 공통 atoms
# ---------------------------------------------------------------------------


ButtonAction = Literal["url", "postback", "phone", "share"]
"""버튼 액션 종류 — 채널마다 native 매핑이 다름.

- ``url``      → 외부 링크 열기 (대부분 채널 native 지원).
- ``postback`` → 클릭 시 봇에 callback_data 전송 (Telegram inline keyboard,
                 KakaoTalk action.message, Slack interactive button 등).
- ``phone``    → 전화 걸기 (모바일 한정 native; PC 는 텍스트 fallback).
- ``share``    → 공유 — 채널마다 처리 다름 (텍스트 fallback 안전).
"""


@dataclass
class ButtonBlock:
    """버튼 한 개 — Card / ListCard / QuickReply 안에서 사용.

    Attributes:
        label: 버튼 표면 라벨 (사용자가 보는 문구).
        action: 액션 종류 — ``ButtonAction`` 참고.
        payload: 액션 인자.
            - ``url``: 외부 URL ("https://...").
            - ``postback``: callback_data (봇이 받을 문자열, 채널 한도 주의 —
              Telegram 64 byte).
            - ``phone``: 전화번호 ("010-1234-5678" 또는 E.164).
            - ``share``: 공유할 텍스트 / URL.
    """

    label: str
    action: ButtonAction
    payload: str


@dataclass
class ListItem:
    """ListCardBlock 의 한 항목.

    Attributes:
        text: 본문 (필수).
        description: 설명 (선택, 한 줄 부연).
        image_url: 썸네일 이미지 URL (선택).
        callback: 항목 클릭 시 callback_data (선택, postback). None 이면 정보
            표시 only.
    """

    text: str
    description: str | None = None
    image_url: str | None = None
    callback: str | None = None


# ---------------------------------------------------------------------------
# 5 종 블록
# ---------------------------------------------------------------------------


@dataclass
class TextBlock:
    """기본 텍스트 응답.

    ``parse_mode``:
    - ``"plain"``    — 평문. 채널이 알아서 escape.
    - ``"markdown"`` — markdown. 채널 native 변환 (Telegram 은 MarkdownV2).
    """

    text: str
    parse_mode: Literal["plain", "markdown"] = "plain"


@dataclass
class CardBlock:
    """단일 카드 — 제목 + 설명 + 이미지 + 버튼 (모두 선택).

    KakaoTalk basicCard / commerceCard 매핑 후보. Telegram 은 sendPhoto +
    caption + InlineKeyboardMarkup 으로 변환.
    """

    title: str
    description: str | None = None
    image_url: str | None = None
    buttons: list[ButtonBlock] = field(default_factory=list)


@dataclass
class CarouselBlock:
    """가로 슬라이드 카드 묶음.

    KakaoTalk carouselCard 매핑. native 미지원 채널 (Telegram 등) 은
    어댑터가 순차 sendPhoto 로 fallback.
    """

    cards: list[CardBlock] = field(default_factory=list)


@dataclass
class QuickReplyBlock:
    """사용자 빠른답변 버튼 (one-tap reply).

    KakaoTalk quickReplies / Telegram ReplyKeyboardMarkup / Slack
    interactive blocks 매핑. ``options`` 의 각 항목은 사용자가 탭하면
    그대로 입력 텍스트로 전송된다.
    """

    text: str
    options: list[str] = field(default_factory=list)


@dataclass
class ListCardBlock:
    """항목 리스트 카드 — FAQ 후보 / 메뉴 / 검색결과.

    KakaoTalk listCard 매핑. Telegram 은 sendMessage + markdown list +
    InlineKeyboardMarkup 으로 변환.
    """

    title: str
    items: list[ListItem] = field(default_factory=list)
    buttons: list[ButtonBlock] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Multimodal blocks (KMS-Plus 2026-05-07)
# ---------------------------------------------------------------------------
#
# 사용자 절칙: "표나 그림 등의 자료를 보여줘야 할수 있고 답변을 해야할수 있기
#              때문이야. 비전 처리 및 OCR도 필요하면 전부 풀옵션으로".
#
# 답변에 *표 / 그림 / 외부 링크 / 경고박스* 가 같이 첨부되어야 사용자가 시각
# 정보 확인 가능. 채널 어댑터별 native 매핑:
# - Telegram: ImageBlock → sendPhoto, TableBlock → sendMessage(markdown table),
#             LinkBlock → sendMessage(text+url 버튼), AlertBlock → sendMessage 아이콘.
# - Web chat: 각각 <img> / <table> / <a> / 색상 박스로 렌더 (frontend MessageBlocks).


@dataclass
class ImageBlock:
    """그림/이미지 첨부 — 검색 결과의 image_ref 블럭, OCR 결과 첨부 등.

    Attributes:
        image_url: 이미지 URL (필수). 내부 storage 경로 또는 외부 URL.
        caption: 한 줄 설명 (옵션). 이미지 위/아래 노출.
        alt_text: 접근성 라벨 (옵션). frontend img alt 속성.
        width / height: hint 픽셀 크기 (옵션). frontend lazy-load 시 layout shift 방지.
        source_citation: 인용 [N] 번호 (옵션). 답변 본문 [N] 마커와 연결.
    """

    image_url: str
    caption: str | None = None
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None
    source_citation: int | None = None


@dataclass
class TableBlock:
    """표 첨부 — 검색 결과의 table 블럭, 표/단가표 응답.

    두 표현 모두 지원 — caller 편의:
    - ``markdown``: GFM markdown 표 (한 번에 렌더). 비전 OCR 결과 첨부 시 사용.
    - ``headers`` + ``rows``: 구조화 데이터 (frontend 가 <table> 직접 렌더).

    Attributes:
        title: 표 제목 (옵션).
        markdown: GFM markdown 표 (옵션 — headers/rows 와 둘 중 하나 이상).
        headers: 컬럼 헤더 (옵션).
        rows: 데이터 행 (옵션). 각 row 는 cell 문자열 list.
        source_citation: 인용 [N] 번호 (옵션).
    """

    title: str | None = None
    markdown: str | None = None
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    source_citation: int | None = None


@dataclass
class LinkBlock:
    """외부 링크 첨부 — 인용 출처, 추가 정보, 외부 자료.

    Attributes:
        url: 링크 URL.
        title: 표시 라벨 (옵션, 미지정 시 url 노출).
        description: 부연 설명 (옵션).
        source_citation: 인용 [N] 번호 (옵션).
    """

    url: str
    title: str | None = None
    description: str | None = None
    source_citation: int | None = None


@dataclass
class AlertBlock:
    """경고/주의/정보 박스 — 색상 구분 안내.

    Attributes:
        text: 본문 (필수).
        level: ``"info"`` | ``"warning"`` | ``"error"`` | ``"success"``. 기본 ``"info"``.
        title: 헤더 라벨 (옵션).
    """

    text: str
    level: Literal["info", "warning", "error", "success"] = "info"
    title: str | None = None


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


# Block union — Python 3.10 호환 (runtime isinstance 검사 가능).
Block = Union[
    TextBlock,
    CardBlock,
    CarouselBlock,
    QuickReplyBlock,
    ListCardBlock,
    ImageBlock,
    TableBlock,
    LinkBlock,
    AlertBlock,
]


@dataclass
class ResponseEnvelope:
    """채널에 보낼 응답 묶음 — 0개 이상의 블록을 순서대로 발송.

    빈 envelope (``blocks=[]``) 는 ``no-op`` (어댑터가 발송 skip). 시연 path 의
    plain text 응답은 ``ResponseEnvelope([TextBlock(text)])`` 로 wrap 되어
    기존 동작과 동일.
    """

    blocks: list[Block] = field(default_factory=list)

    @classmethod
    def from_text(
        cls,
        text: str,
        parse_mode: Literal["plain", "markdown"] = "plain",
    ) -> ResponseEnvelope:
        """편의 팩토리 — 평문 → TextBlock 1개.

        engine / orchestrator 가 final text 를 envelope 로 wrap 할 때 사용.
        ``text`` 가 빈 문자열이면 빈 envelope 반환 (no-op).
        """
        if not text:
            return cls(blocks=[])
        return cls(blocks=[TextBlock(text=text, parse_mode=parse_mode)])

    def is_empty(self) -> bool:
        return not self.blocks


__all__ = [
    "ButtonAction",
    "ButtonBlock",
    "ListItem",
    "TextBlock",
    "CardBlock",
    "CarouselBlock",
    "QuickReplyBlock",
    "ListCardBlock",
    "ImageBlock",
    "TableBlock",
    "LinkBlock",
    "AlertBlock",
    "Block",
    "ResponseEnvelope",
]
