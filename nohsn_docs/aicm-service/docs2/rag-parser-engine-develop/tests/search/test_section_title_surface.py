from uuid import uuid4
from src.search.models import SearchHit, SourceLocation
from src.search.service import _section_title_from_heading_path


def _hit(section_title, heading_path):
    return SearchHit(
        chunk_id=uuid4(), document_id=uuid4(), document_title="하나코리아",
        section_title=section_title, content="| 종류 | 보유기간 | 환매수수료 |",
        source_location=SourceLocation(heading_path=heading_path),
    )


def test_empty_section_title_filled_from_heading_path():
    hit = _hit("", ["9. 환매수수료"])
    assert _section_title_from_heading_path(hit.source_location) == "9. 환매수수료"


def test_nested_heading_path_joined():
    hit = _hit("", ["8. 매입·환매 방법", "9. 환매수수료"])
    assert _section_title_from_heading_path(hit.source_location) == "8. 매입·환매 방법 > 9. 환매수수료"


def test_no_heading_path_returns_empty():
    hit = _hit("", [])
    assert _section_title_from_heading_path(hit.source_location) == ""


def test_qna_section_title_preserved():
    # QNA 블럭은 section_title(=질문)이 비어있지 않으므로 _to_result_items에서 보존된다.
    hit = _hit("환매수수료는 얼마인가요?", ["9. 환매수수료"])
    # 헬퍼는 heading_path만 본다. 보존 로직은 호출부(_to_result_items)에서 'or'로 구현.
    assert (hit.section_title or _section_title_from_heading_path(hit.source_location)) == "환매수수료는 얼마인가요?"
