from src.pipeline.stages.doc_type_map import to_slug


def test_korean_doc_types_map_to_slugs():
    assert to_slug("발표자료") == "slide"
    assert to_slug("매뉴얼") == "manual"
    assert to_slug("보고서") == "report"
    assert to_slug("FAQ") == "faq"
    assert to_slug("자주 묻는 질문") == "faq"


def test_unknown_doc_type_falls_back_to_generic():
    assert to_slug("") == "generic"
    assert to_slug("듣도보도못한문서") == "generic"
