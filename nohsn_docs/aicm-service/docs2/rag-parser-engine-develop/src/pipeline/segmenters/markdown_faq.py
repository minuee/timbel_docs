"""마크다운 구조 FAQ 문서를 결정적으로 블럭 분할한다.

gemma LLM 세그멘터가 원본의 마크다운 구조(`#`/`##`/`###`)를 비일관적으로
재해석(질문/답변 오타입·마커 누출·qna 미생성)하는 문제를 우회한다.

규칙: 가장 깊은 헤딩 레벨 L = 질문 레벨(레벨 L 헤딩 다수가 질문형일 때).
  - 레벨 < L 헤딩(`#`/`##`)  → 제목/카테고리 heading 블럭
  - 레벨 L 헤딩              → qna 블럭(qna_title=질문, content=답변, 마커 없음)
"""
from __future__ import annotations

import re
from uuid import UUID

from src.pipeline.models.block import BlockObject, BlockType
from src.pipeline.models.document import SourceLocation

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_Q_PREFIX_RE = re.compile(
    r"^\s*(?:Q\s*[.:]|질문\s*[.:]|문\s*[.:]|Question\s*[.:])", re.IGNORECASE
)
_DIVIDER_RE = re.compile(r"^\s*-{3,}\s*$")
# FAQ 판정(다수결)용 한국어 의문 어미 — 보수적으로 흔한 형태만.
_Q_ENDINGS = (
    "나요", "까요", "은가요", "는가요", "ㄴ가요", "싶어요",
    "하나요", "인가요", "되나요", "있나요", "없나요", "을까요", "ㄹ까요",
)


def _question_form(text: str) -> bool:
    """헤딩 텍스트가 질문형인지 판별(접두 Q. / 물음표 / 한국어 의문 어미)."""
    t = text.strip()
    if not t:
        return False
    if _Q_PREFIX_RE.match(t):
        return True
    if t.endswith("?"):
        return True
    base = t.rstrip("?.!！ ").rstrip()
    return any(base.endswith(e) for e in _Q_ENDINGS)


def is_markdown_structured(text: str, min_headings: int = 3) -> bool:
    """마크다운 헤딩 라인이 임계치 이상이면 마크다운 구조 문서로 본다."""
    count = sum(1 for ln in text.split("\n") if _HEADING_RE.match(ln.strip()))
    return count >= min_headings


def detect_question_level(text: str) -> int | None:
    """가장 깊은 헤딩 레벨을 구하고, 그 레벨 헤딩 다수가 질문형이면 그 레벨을 반환.

    아니면(일반 문서) None.
    """
    levels: dict[int, list[str]] = {}
    for ln in text.split("\n"):
        m = _HEADING_RE.match(ln.strip())
        if m:
            lvl = min(len(m.group(1)), 3)
            levels.setdefault(lvl, []).append(m.group(2).strip())
    if not levels:
        return None
    deepest = max(levels)
    headings = levels[deepest]
    q = sum(1 for h in headings if _question_form(h))
    return deepest if q * 2 > len(headings) else None


_LEVEL_TO_HEADING = {
    1: BlockType.HEADING_1,
    2: BlockType.HEADING_2,
    3: BlockType.HEADING_3,
}


def _parse_segments(text: str) -> list[tuple]:
    """텍스트를 ('heading', level, htext, start, end) / ('body', btext, start, end) 시퀀스로 분해.

    `---` divider는 본문 경계로만 쓰고 버린다.
    start/end는 원문 내 char offset.
    """
    out: list[tuple] = []
    buf: list[str] = []
    buf_start: int | None = None
    pos = 0

    def _flush() -> None:
        nonlocal buf_start
        body = "\n".join(buf).strip()
        buf.clear()
        if body:
            s = buf_start if buf_start is not None else 0
            out.append(("body", body, s, pos))
        buf_start = None

    for ln in text.split("\n"):
        s = ln.strip()
        m = _HEADING_RE.match(s)
        if m:
            _flush()
            out.append(("heading", min(len(m.group(1)), 3), m.group(2).strip(), pos, pos + len(ln)))
        elif _DIVIDER_RE.match(s):
            _flush()
        else:
            if buf_start is None:
                buf_start = pos
            buf.append(ln)
        pos += len(ln) + 1
    _flush()
    return out


def segment_markdown_text(
    text: str,
    *,
    document_id: UUID,
    source_file_path: str = "",
    source_file_url: str = "",
) -> list[BlockObject]:
    """마크다운 구조 텍스트를 결정적으로 블럭 분할한다.

    - 질문 레벨 L 헤딩 → qna 블럭(qna_title=질문, content=다음 헤딩 전까지 본문=답변)
    - 레벨 < L 헤딩       → heading_1/2/3 블럭
    - 헤딩 밖 본문         → paragraph 블럭
    """
    q_level = detect_question_level(text)
    segs = _parse_segments(text)
    blocks: list[BlockObject] = []

    def _add(
        btype: BlockType,
        content: str,
        qna_title: str | None = None,
        heading_path: list[str] | None = None,
        start_offset: int | None = None,
        end_offset: int | None = None,
    ) -> None:
        meta: dict = {"qna_title": qna_title} if qna_title else {}
        sl = SourceLocation(
            file_path=source_file_path or None,
            file_url=source_file_url or None,
            heading_path=list(heading_path or []),
            start_char_offset=start_offset,
            end_char_offset=end_offset,
        )
        block = BlockObject(
            document_id=document_id,
            block_type=btype,
            content=content,
            block_index=len(blocks),
            token_count=len(content),
            source_location=sl,
            metadata=meta,
        )
        block.compute_hash()
        blocks.append(block)

    # 헤딩 계층 추적 — 각 블럭에 상위 헤딩 경로(heading_path)를 부착한다.
    # contextual_retrieval enricher 가 이 경로로 "[문서: … | 섹션: 문서 > 카테고리]" 컨텍스트를
    # 임베딩에 주입하므로, QnA 가 자기 카테고리(예: CMA, ELS/DLS)와 함께 검색된다.
    heading_stack: list[tuple[int, str]] = []  # (level, text) — 현재 블럭의 조상 헤딩들

    i, n = 0, len(segs)
    while i < n:
        seg = segs[i]
        if seg[0] == "heading":
            level, htext = seg[1], seg[2]
            if q_level is not None and level == q_level:
                # 질문 → qna: 다음 헤딩 직전까지의 body 들을 답변으로 묶는다.
                qna_start = seg[-2]
                qna_end = seg[-1]
                parts: list[str] = []
                j = i + 1
                while j < n and segs[j][0] == "body":
                    parts.append(segs[j][1])
                    qna_end = segs[j][-1]
                    j += 1
                _add(
                    BlockType.QNA,
                    "\n".join(parts).strip(),
                    qna_title=htext,
                    heading_path=[t for _, t in heading_stack],
                    start_offset=qna_start,
                    end_offset=qna_end,
                )
                i = j
                continue
            # 일반 헤딩: 같은/더 깊은 레벨을 스택에서 제거 → 조상 경로 부착 → 자신을 push.
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            _add(
                _LEVEL_TO_HEADING.get(level, BlockType.HEADING_3),
                htext,
                heading_path=[t for _, t in heading_stack],
                start_offset=seg[-2],
                end_offset=seg[-1],
            )
            heading_stack.append((level, htext))
        else:  # ("body", btext, start, end) — 헤딩에 속하지 않은 본문
            _add(
                BlockType.PARAGRAPH,
                seg[1],
                heading_path=[t for _, t in heading_stack],
                start_offset=seg[-2],
                end_offset=seg[-1],
            )
        i += 1

    return blocks
