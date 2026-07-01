from types import SimpleNamespace

from src.pipeline.workers.embed_worker import (
    _clean_doc_title,
    _embedding_text_with_context,
)


class _StubBlock:
    """BlockObject 덕타이핑 스텁 — 헬퍼가 쓰는 속성/메서드만 노출."""

    def __init__(self, *, content="본문내용", heading_path=None, contextual_prefix=None):
        self.contextual_prefix = contextual_prefix
        self.source_location = SimpleNamespace(heading_path=heading_path or [])
        self._content = content

    def embedding_text(self):
        return self._content


def test_clean_doc_title_strips_known_extension():
    assert _clean_doc_title("미래에셋차세대Fun인덱스증권자투자신탁.docx") == "미래에셋차세대Fun인덱스증권자투자신탁"


def test_clean_doc_title_keeps_non_extension_dot():
    # 확장자가 아닌 점은 보존(예: 버전·배수 표기)
    assert _clean_doc_title("1.5배 레버리지 안내") == "1.5배 레버리지 안내"


def test_clean_doc_title_none_and_blank():
    assert _clean_doc_title(None) == ""
    assert _clean_doc_title("   ") == ""


def test_prefix_title_and_section():
    b = _StubBlock(content="| 구분 | 15시 30분 |", heading_path=["환매수수료"])
    out = _embedding_text_with_context(b, "미래에셋차세대Fun인덱스증권자투자신탁.docx")
    assert out == "미래에셋차세대Fun인덱스증권자투자신탁 > 환매수수료\n\n| 구분 | 15시 30분 |"


def test_prefix_section_empty_uses_title_only():
    b = _StubBlock(content="본문", heading_path=[])
    out = _embedding_text_with_context(b, "미래에셋.docx")
    assert out == "미래에셋\n\n본문"


def test_prefix_title_empty_uses_section_only():
    b = _StubBlock(content="본문", heading_path=["환매수수료", "지급시점"])
    out = _embedding_text_with_context(b, "")
    assert out == "환매수수료 > 지급시점\n\n본문"


def test_prefix_both_empty_returns_base():
    b = _StubBlock(content="본문", heading_path=[])
    assert _embedding_text_with_context(b, "") == "본문"


def test_contextual_prefix_present_skips_prepend():
    b = _StubBlock(content="본문", heading_path=["환매수수료"], contextual_prefix="[문서: X | 섹션: Y]")
    # contextual_prefix 가 있으면 embedding_text() 원본 그대로(이중 문서맥락 회피)
    assert _embedding_text_with_context(b, "미래에셋.docx") == "본문"


def test_heading_path_filters_empty_segments():
    b = _StubBlock(content="본문", heading_path=["", "환매수수료", ""])
    out = _embedding_text_with_context(b, "미래에셋")
    assert out == "미래에셋 > 환매수수료\n\n본문"
