# KMS 마크다운 FAQ 결정적 세그멘터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 마크다운 구조(`#`/`##`/`###`)로 작성된 FAQ 문서를 gemma LLM 세그멘터를 우회해 결정적으로 분할, 질문=`qna_title`·답변=`content`(마커 없음)인 깨끗한 qna 블럭을 생성한다.

**Architecture:** 신규 순수 함수 모듈(`markdown_faq.py`)이 텍스트 → 블럭 변환을 담당한다. "가장 깊은 헤딩 레벨 L = 질문 레벨"(레벨 L 헤딩 다수가 질문형일 때) 규칙으로 레벨 L은 qna, 얕은 레벨(`#`/`##`)은 heading 블럭으로 만든다. `LLMBlockSegmenter.segment()` 초입에서 마크다운 구조가 감지되면 이 경로로 분기하고, 아니면 기존 gemma 경로를 그대로 탄다.

**Tech Stack:** Python 3.11, pydantic v2 (`BlockObject`/`BlockType`), pytest. 외부 의존성 추가 없음(표준 `re`만).

## Global Constraints

- **불변식**: 질문 텍스트는 `metadata.qna_title` **단 한 곳**에만 존재한다. qna 블럭의 `content`에는 질문·마크다운 마커(`#`/`##`/`###`/`Q.`)가 **들어가지 않는다**.
- **비침투**: 마크다운 구조가 아니거나 질문 레벨이 감지되지 않는 문서는 **기존 gemma/fallback 경로를 그대로** 탄다(동작 변경 0).
- **블럭 생성 규약**: 모든 블럭은 `BlockObject(document_id=, block_type=, content=, block_index=, token_count=len(content), source_location=, metadata=)` 로 만들고 직후 `block.compute_hash()` 호출(기존 `FallbackSegmenter` 패턴과 동일). `block_index`는 생성 순서대로 0부터.
- **대상 repo / 브랜치**: rag-parser-engine, 작업 브랜치 `develop`.
- **임포트 규약**: 소스는 `from src.pipeline...`, 테스트도 `from src.pipeline...`.
- **테스트 위치**: `tests/pipeline/segmenters/`.

---

### Task 1: 판별 헬퍼 — 질문형 / 마크다운 구조 / 질문 레벨

**Files:**
- Create: `src/pipeline/segmenters/markdown_faq.py`
- Test: `tests/pipeline/segmenters/test_markdown_faq.py`

**Interfaces:**
- Produces:
  - `_question_form(text: str) -> bool`
  - `is_markdown_structured(text: str, min_headings: int = 3) -> bool`
  - `detect_question_level(text: str) -> int | None`
  - 모듈 상수 `_HEADING_RE`, `_Q_PREFIX_RE`, `_DIVIDER_RE`, `_Q_ENDINGS`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/pipeline/segmenters/test_markdown_faq.py`:

```python
from __future__ import annotations

from src.pipeline.segmenters.markdown_faq import (
    _question_form,
    detect_question_level,
    is_markdown_structured,
)


def test_question_form_q_prefix():
    assert _question_form("Q. CMA수익률은 어떻게 되나요") is True


def test_question_form_question_mark():
    assert _question_form("매장 칭찬하기가 무엇인가요?") is True


def test_question_form_korean_ending_no_qmark():
    # 다이소: 물음표 없이 평서형 어미로 끝나는 질문
    assert _question_form("다이소 모바일 상품권 유효기간을 연장하고 싶어요.") is True


def test_question_form_declarative_answer_is_false():
    assert _question_form("다이소 모바일상품권은 카드결제만 가능합니다.") is False


def test_is_markdown_structured_true():
    assert is_markdown_structured("### a\n### b\n### c") is True


def test_is_markdown_structured_false_plain():
    assert is_markdown_structured("그냥 평문\n두 번째 줄\n세 번째 줄") is False


def test_detect_question_level_hantoo_three_levels():
    text = "# 제목\n## CMA\n### Q. 수익률은 어떻게 되나요\n답변\n### Q. 유형 변경하고 싶어요\n답변2"
    assert detect_question_level(text) == 3


def test_detect_question_level_daiso_single_level():
    text = "### 결제수단은 무엇인가요?\n답변A\n---\n### 유효기간을 연장하고 싶어요.\n답변B"
    assert detect_question_level(text) == 3


def test_detect_question_level_general_doc_returns_none():
    # 일반 문서: 가장 깊은 레벨 헤딩이 질문형이 아님 → None
    text = "# 매뉴얼\n## 설치\n### 사전 준비\n내용\n### 설치 절차\n내용"
    assert detect_question_level(text) is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/pipeline/segmenters/test_markdown_faq.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pipeline.segmenters.markdown_faq'`

- [ ] **Step 3: 헬퍼 구현**

Create `src/pipeline/segmenters/markdown_faq.py`:

```python
"""마크다운 구조 FAQ 문서를 결정적으로 블럭 분할한다.

gemma LLM 세그멘터가 원본의 마크다운 구조(`#`/`##`/`###`)를 비일관적으로
재해석(질문/답변 오타입·마커 누출·qna 미생성)하는 문제를 우회한다.

규칙: 가장 깊은 헤딩 레벨 L = 질문 레벨(레벨 L 헤딩 다수가 질문형일 때).
  - 레벨 < L 헤딩(`#`/`##`)  → 제목/카테고리 heading 블럭
  - 레벨 L 헤딩              → qna 블럭(qna_title=질문, content=답변, 마커 없음)
"""
from __future__ import annotations

import re

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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/pipeline/segmenters/test_markdown_faq.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline/segmenters/markdown_faq.py tests/pipeline/segmenters/test_markdown_faq.py
git commit -m "feat(segmenter): 마크다운 FAQ 질문형/구조/질문레벨 판별 헬퍼 추가

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 결정적 세그멘터 코어 — 텍스트 → 블럭

**Files:**
- Modify: `src/pipeline/segmenters/markdown_faq.py` (함수 추가)
- Test: `tests/pipeline/segmenters/test_markdown_faq.py` (테스트 추가)

**Interfaces:**
- Consumes (Task 1): `_HEADING_RE`, `_DIVIDER_RE`, `detect_question_level`
- Produces:
  - `_parse_segments(text: str) -> list[tuple]` — `("heading", level:int, htext:str)` 또는 `("body", btext:str)` 시퀀스(`---` divider는 경계로 쓰고 버림)
  - `segment_markdown_text(text: str, *, document_id: UUID, source_file_path: str = "", source_file_url: str = "") -> list[BlockObject]`

- [ ] **Step 1: 실패 테스트 작성**

`tests/pipeline/segmenters/test_markdown_faq.py` 끝에 추가:

```python
from uuid import uuid4

from src.pipeline.models.block import BlockType
from src.pipeline.segmenters.markdown_faq import segment_markdown_text


def _types(blocks):
    return [b.block_type for b in blocks]


def test_segment_daiso_single_level_qna_only():
    text = (
        "### 다이소 상품권 구매가능한 결제수단은 무엇인가요?\n"
        "다이소 모바일상품권은 카드결제만 가능합니다.\n"
        "---\n"
        "### 다이소 모바일 상품권 유효기간을 연장하고 싶어요.\n"
        "고객센터(1688-9876)로 신청 가능합니다."
    )
    blocks = segment_markdown_text(text, document_id=uuid4())
    assert _types(blocks) == [BlockType.QNA, BlockType.QNA]
    assert blocks[0].metadata["qna_title"] == "다이소 상품권 구매가능한 결제수단은 무엇인가요?"
    assert blocks[0].content == "다이소 모바일상품권은 카드결제만 가능합니다."
    # 불변식: content에 질문/마커 없음
    assert "###" not in blocks[0].content
    assert "무엇인가요" not in blocks[0].content
    assert blocks[1].metadata["qna_title"] == "다이소 모바일 상품권 유효기간을 연장하고 싶어요."


def test_segment_hantoo_three_levels():
    text = (
        "# 한국투자증권 고객 FAQ — 지식문서 (Part 1)\n"
        "---\n"
        "## CMA\n"
        "### Q. CMA수익률은 어떻게 되나요\n"
        "[분류] 대분류: CMA / 세부분류: 수익률\n"
        "MMW 투자형은 영업점 문의\n"
        "---\n"
        "### Q. CMA유형을 변경하고 싶어요\n"
        "CMA 해지 후 재신청하세요."
    )
    blocks = segment_markdown_text(text, document_id=uuid4())
    assert _types(blocks) == [
        BlockType.HEADING_1,
        BlockType.HEADING_2,
        BlockType.QNA,
        BlockType.QNA,
    ]
    assert blocks[0].content == "한국투자증권 고객 FAQ — 지식문서 (Part 1)"
    assert blocks[1].content == "CMA"
    assert blocks[2].metadata["qna_title"] == "Q. CMA수익률은 어떻게 되나요"
    assert blocks[2].content.startswith("[분류] 대분류: CMA")
    assert "###" not in blocks[2].content
    # block_index 연속
    assert [b.block_index for b in blocks] == [0, 1, 2, 3]
    # hash 채워짐
    assert all(b.block_hash for b in blocks)


def test_segment_general_doc_keeps_headings_and_paragraphs():
    # detect_question_level=None → 모든 헤딩이 heading, 본문은 paragraph
    text = "# 매뉴얼\n## 설치\n### 사전 준비\n준비 내용입니다.\n### 설치 절차\n절차 내용입니다."
    blocks = segment_markdown_text(text, document_id=uuid4())
    assert BlockType.QNA not in _types(blocks)
    assert BlockType.HEADING_3 in _types(blocks)
    assert BlockType.PARAGRAPH in _types(blocks)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/pipeline/segmenters/test_markdown_faq.py -v -k segment`
Expected: FAIL — `ImportError: cannot import name 'segment_markdown_text'`

- [ ] **Step 3: 코어 구현**

`src/pipeline/segmenters/markdown_faq.py` 상단 import에 추가:

```python
from uuid import UUID

from src.pipeline.models.block import BlockObject, BlockType
from src.pipeline.models.document import SourceLocation
```

파일 끝에 추가:

```python
_LEVEL_TO_HEADING = {
    1: BlockType.HEADING_1,
    2: BlockType.HEADING_2,
    3: BlockType.HEADING_3,
}


def _parse_segments(text: str) -> list[tuple]:
    """텍스트를 ('heading', level, htext) / ('body', btext) 시퀀스로 분해.

    `---` divider는 본문 경계로만 쓰고 버린다.
    """
    out: list[tuple] = []
    buf: list[str] = []

    def _flush() -> None:
        body = "\n".join(buf).strip()
        buf.clear()
        if body:
            out.append(("body", body))

    for ln in text.split("\n"):
        s = ln.strip()
        m = _HEADING_RE.match(s)
        if m:
            _flush()
            out.append(("heading", min(len(m.group(1)), 3), m.group(2).strip()))
        elif _DIVIDER_RE.match(s):
            _flush()
        else:
            buf.append(ln)
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

    def _add(btype: BlockType, content: str, qna_title: str | None = None) -> None:
        meta: dict = {"qna_title": qna_title} if qna_title else {}
        sl = SourceLocation(
            file_path=source_file_path or None,
            file_url=source_file_url or None,
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

    i, n = 0, len(segs)
    while i < n:
        seg = segs[i]
        if seg[0] == "heading":
            level, htext = seg[1], seg[2]
            if q_level is not None and level == q_level:
                # 질문 → qna: 다음 헤딩 직전까지의 body 들을 답변으로 묶는다.
                parts: list[str] = []
                j = i + 1
                while j < n and segs[j][0] == "body":
                    parts.append(segs[j][1])
                    j += 1
                _add(BlockType.QNA, "\n".join(parts).strip(), qna_title=htext)
                i = j
                continue
            _add(_LEVEL_TO_HEADING.get(level, BlockType.HEADING_3), htext)
        else:  # ("body", text) — 헤딩에 속하지 않은 본문
            _add(BlockType.PARAGRAPH, seg[1])
        i += 1

    return blocks
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/pipeline/segmenters/test_markdown_faq.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline/segmenters/markdown_faq.py tests/pipeline/segmenters/test_markdown_faq.py
git commit -m "feat(segmenter): 마크다운 구조 결정적 분할 코어(segment_markdown_text)

질문 레벨 헤딩→qna(질문=qna_title, 답변=content, 마커 없음), 얕은 헤딩→heading.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `LLMBlockSegmenter.segment()` 라우팅 통합

**Files:**
- Modify: `src/pipeline/segmenters/llm_block_segmenter.py` (`segment()` 초입 + 표/이미지 부가)
- Test: `tests/pipeline/segmenters/test_markdown_faq.py` (통합 테스트 추가)

**Interfaces:**
- Consumes (Task 1·2): `is_markdown_structured`, `detect_question_level`, `segment_markdown_text`
- Produces: `segment()`가 마크다운 구조 FAQ면 결정적 경로로 분기(gemma 미호출). 그 외엔 기존 동작 유지.

- [ ] **Step 1: 실패 테스트 작성**

`tests/pipeline/segmenters/test_markdown_faq.py` 끝에 추가:

```python
import pytest

from src.pipeline.models.document import ProcessingConfig
from src.pipeline.models.parse_result import PageContent, ParseResult
from src.pipeline.segmenters.llm_block_segmenter import LLMBlockSegmenter


@pytest.mark.asyncio
async def test_segment_routes_markdown_faq_bypassing_llm():
    text = (
        "### 결제수단은 무엇인가요?\n카드결제만 가능합니다.\n"
        "---\n### 환불받고 싶어요\n고객센터로 신청 가능합니다.\n"
        "---\n### 재발급 받고 싶어요\n5회까지 가능합니다."
    )
    pr = ParseResult(pages=[PageContent(page_number=1, text=text)])
    # llm_client 가 있어도 마크다운 FAQ면 호출되지 않아야 한다(결정적 경로).
    class _Boom:
        async def __call__(self, *a, **k):
            raise AssertionError("LLM이 호출되면 안 됨")
    seg = LLMBlockSegmenter(ProcessingConfig(), llm_client=_Boom())
    blocks = await seg.segment(pr, document_id=uuid4())
    assert all(b.block_type == BlockType.QNA for b in blocks)
    assert len(blocks) == 3
    assert blocks[0].metadata["qna_title"] == "결제수단은 무엇인가요?"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/pipeline/segmenters/test_markdown_faq.py::test_segment_routes_markdown_faq_bypassing_llm -v`
Expected: FAIL — gemma 경로로 빠져 `_Boom` 호출 또는 비-QNA 블럭 생성으로 assert 실패

- [ ] **Step 3: `segment()` 초입에 라우팅 추가**

`src/pipeline/segmenters/llm_block_segmenter.py` 의 `segment()` 메서드에서, docstring 직후·`if self._llm_client is None:` **직전**에 삽입:

```python
        # ── 마크다운 구조 FAQ: gemma 우회, 결정적 분할 ──
        # 원본에 명시된 `#`/`##`/`###` 구조를 신뢰해 질문=qna_title·답변=content 로 분할.
        # 비마크다운/일반 문서는 아래 기존 경로 유지.
        from src.pipeline.segmenters.markdown_faq import (
            detect_question_level,
            is_markdown_structured,
            segment_markdown_text,
        )

        _full_text = "\n".join(p.text for p in parse_result.pages if p.text)
        if is_markdown_structured(_full_text) and detect_question_level(_full_text) is not None:
            log.info(
                "markdown_faq_deterministic_segmentation",
                document_id=str(document_id),
            )
            md_blocks = segment_markdown_text(
                _full_text,
                document_id=document_id,
                source_file_path=parse_result.source_file_path or "",
                source_file_url=source_file_url,
            )
            # 표/이미지는 별도 1:1 매핑(기존 경로와 동일 패턴).
            for page in parse_result.pages:
                for table in page.tables:
                    md_blocks.append(
                        self._fallback._table_to_block(
                            table, document_id, parse_result.source_file_path,
                            source_file_url,
                        )
                    )
                for image in page.images:
                    md_blocks.append(
                        self._fallback._image_to_block(
                            image, document_id, parse_result.source_file_path,
                            source_file_url,
                        )
                    )
            for idx, b in enumerate(md_blocks):
                b.block_index = idx
            return md_blocks
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/pipeline/segmenters/test_markdown_faq.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: 회귀 확인 — 기존 세그멘터 테스트**

Run: `python -m pytest tests/pipeline/segmenters/ -v`
Expected: PASS (기존 `test_text_path_strengthening.py` 포함 전체 통과 — 비마크다운 경로 영향 없음)

- [ ] **Step 6: 커밋**

```bash
git add src/pipeline/segmenters/llm_block_segmenter.py tests/pipeline/segmenters/test_markdown_faq.py
git commit -m "feat(segmenter): 마크다운 FAQ 감지 시 gemma 우회 결정적 분할로 라우팅

비마크다운/일반 문서는 기존 LLM/fallback 경로 유지.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 실제 docx 로컬 E2E 검증 (비커밋 sanity)

목적: 실제 한투/다이소 docx로 세그멘터 출력을 눈으로 확인(서버 배포 전 게이트). docx 원본은 repo 밖(`aicm_old/docs/`)이라 커밋 테스트가 아니라 **로컬 검증 스크립트**로 수행한다.

**Files:**
- (임시) `_verify_md_faq.py` (repo 루트, 실행 후 삭제 — 커밋 금지)

**Interfaces:**
- Consumes: `DOCXParser`(`src.pipeline.parsers.docx_parser`), `segment_markdown_text`

- [ ] **Step 1: 검증 스크립트 작성**

Create `_verify_md_faq.py` (rag-parser-engine 루트):

```python
# -*- coding: utf-8 -*-
import asyncio, os, sys
sys.path.insert(0, os.path.abspath("."))
from uuid import uuid4
from src.pipeline.parsers.docx_parser import DOCXParser
from src.pipeline.segmenters.markdown_faq import segment_markdown_text
from src.pipeline.models.block import BlockType

DOCS = {
    "한투": r"C:/Projects/AICC/working/aicm_old/docs/한국투자증권 고객 FAQ1.docx",
    "다이소상품권": r"C:/Projects/AICC/working/aicm_old/docs/sample_data/다이소 상품권.docx",
}

async def main():
    for name, path in DOCS.items():
        pr = await DOCXParser(path).parse()
        text = "\n".join(p.text for p in pr.pages if p.text)
        blocks = segment_markdown_text(text, document_id=uuid4())
        dist = {}
        for b in blocks:
            k = b.block_type.value
            dist[k] = dist.get(k, 0) + 1
        qna = [b for b in blocks if b.block_type == BlockType.QNA]
        leak = [b for b in qna if "###" in b.content or "## " in b.content]
        no_title = [b for b in qna if not b.metadata.get("qna_title")]
        print(f"\n=== {name} ===")
        print("dist:", dist)
        print("qna 마커누출:", len(leak), " / qna 제목없음:", len(no_title))
        for b in qna[:3]:
            print("  Q:", b.metadata.get("qna_title", "")[:45], "| A:", b.content[:50].replace("\n", " "))

asyncio.run(main())
```

- [ ] **Step 2: 실행 및 기대 결과 확인**

Run: `PYTHONIOENCODING=utf-8 python _verify_md_faq.py`
Expected:
- 한투: `qna` ≈ 95, `heading_1` 1, `heading_2` ≈ 22. `마커누출: 0`, `제목없음: 0`.
- 다이소상품권: `qna` ≈ 29, heading 0. `마커누출: 0`, `제목없음: 0`.
- 각 qna 의 Q(질문)·A(답변)가 올바르게 분리되어 출력.

- [ ] **Step 3: 임시 스크립트 삭제**

Run: `rm -f _verify_md_faq.py`
(커밋하지 않는다. 검증 통과만 확인.)

---

## Self-Review

**1. Spec coverage:**
- §5.1 결정적 세그멘터(레벨 기반, FAQ 판정, 분할 규칙) → Task 1·2·3. ✅
- §3 데이터 모델·불변식(질문=qna_title 단일, content 마커 없음) → Task 2 테스트(`"###" not in content`, `"무엇인가요" not in content`)·Task 4 누출 0 검증. ✅
- §5.1 라우팅(마크다운→결정적, 그 외 gemma) → Task 3 + 회귀(Step 5). ✅
- §3 일반 문서 처리(heading+paragraph) → Task 2 `test_segment_general_doc...`. ✅
- §10 잔여(임계치 N, 의문 어미 사전) → Task 1에 기본값(min_headings=3, `_Q_ENDINGS`) 구현, Task 4로 실데이터 검증.
- **범위 밖(별도 후속 플랜):** §5.2 aicm-service 라운드트립(이미 clean qna 블럭을 정상 라운드트립 — 본 플랜으로 충족), §5.3 aicm-web 편집기(수동 타입 선택·QnA 단락 UI), §6 기존 문서 재처리(retry). → "Follow-up plans" 참조.

**2. Placeholder scan:** "TBD/적절히/처리"류 없음. 모든 코드 스텝에 완전한 코드 포함. ✅

**3. Type consistency:** `segment_markdown_text(text, *, document_id, source_file_path, source_file_url)` — Task 2 정의, Task 3 호출 일치. `detect_question_level`/`is_markdown_structured` Task 1 정의, Task 3 사용 일치. `BlockObject`/`BlockType.QNA`/`metadata["qna_title"]` 전 태스크 일관. `self._fallback`(LLMBlockSegmenter `__init__`에서 생성)·`_table_to_block`/`_image_to_block`(FallbackSegmenter staticmethod) Task 3에서 사용 — 기존 코드에 존재(확인됨). ✅

## Follow-up Plans (이 플랜 범위 밖)

1. **aicm-web 편집기**: 수동 섹션 추가 시 "질문(QnA)/제목(일반)" 타입 선택, QnA 섹션 단락 추가 미노출(스펙 §5.3). 별도 플랜.
2. **기존 문서 재처리**: 한투·다이소 등 이미 깨진 문서를 `retry?from_stage=blocking`으로 새 세그멘터 적용(스펙 §6). AICM status 동기화 주의.
3. **(선택) aicm-service**: QnA 섹션 다단락 합치기 가드(수동 편집 예외 대비, 스펙 §5.2). 현 라운드트립이 clean qna를 정상 처리하므로 본 플랜엔 불필요.

## 배포 (구현 완료 후)

- 변경 파일을 `lucas-kms-api` + 워커 컨테이너(`lucas-kms-worker-*`)에 반영(세그멘터는 worker에서 실행). 임시=cp+restart, 영구=이미지 rebuild.
- gemma 서버 가동 시간대에 한투·다이소 재업로드 E2E(스펙 §8): block_type 분포·검색(질문→답변)·편집 저장 무분리.
