from uuid import uuid4

from src.search.models import SearchHit, SourceLocation
from src.search.service import _drop_empty_heading_hits


def _hit(block_type, content):
    return SearchHit(
        chunk_id=uuid4(), document_id=uuid4(), document_title="d",
        content=content, source_location=SourceLocation(), block_type=block_type,
    )


def test_drops_content_empty_heading():
    hits = [
        _hit("heading_2", "### 9. 환매수수료"),
        _hit("paragraph", "| 종류 | 보유기간 | 환매수수료 |\n| 종류 A | 30일 | 70% |"),
    ]
    out = _drop_empty_heading_hits(hits)
    assert len(out) == 1
    assert out[0].block_type == "paragraph"


def test_keeps_heading_with_absorbed_body():
    h = _hit("heading_2", "## 9. 환매수수료\n| 종류 | 환매수수료 |\n| A | 70% |")
    assert _drop_empty_heading_hits([h]) == [h]


def test_keeps_non_heading_even_if_short():
    h = _hit("paragraph", "환매수수료 없음")
    assert _drop_empty_heading_hits([h]) == [h]


def test_empty_input():
    assert _drop_empty_heading_hits([]) == []
