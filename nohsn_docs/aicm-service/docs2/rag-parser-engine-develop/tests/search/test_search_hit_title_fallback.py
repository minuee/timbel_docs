"""D85c-잔존 (2026-05-13) — SearchHit document_title 빈 값 fallback validator.

KMS ingest 시 parse_result.metadata.title 추출 실패 / 업로드 title 미지정으로
ES/Qdrant payload 의 document_title 이 빈 string 으로 저장된 chunk 가 존재.
citation 빌드 단계에서 "(제목 없음)" 노출 → 사용자 보고 "근거문서 제목 누락".

본 테스트는 SearchHit 의 model_validator(mode='after') 가 빈 document_title
을 source_location.file_path / file_url 의 stem 으로 fallback 채우는 동작을
fixture-free 로 검증.
"""
from __future__ import annotations

from uuid import UUID

from src.search.models import SearchHit, SourceLocation


_C = UUID("00000000-0000-0000-0000-000000000001")
_D = UUID("00000000-0000-0000-0000-000000000002")
_R = UUID("00000000-0000-0000-0000-000000000003")


def _build(document_title: str, *, file_path: str = "", file_url: str | None = None) -> SearchHit:
    return SearchHit(
        chunk_id=_C,
        document_id=_D,
        document_title=document_title,
        content="x",
        repository_id=_R,
        source_location=SourceLocation(file_path=file_path, file_url=file_url),
    )


class TestDocumentTitleFallback:
    """Pydantic v2 model_validator(mode='after') 가 빈 document_title 을 채우는지."""

    def test_blank_title_falls_back_to_file_path_stem(self) -> None:
        h = _build("", file_path="/uploads/2026/품질평가표.pdf")
        assert h.document_title == "품질평가표"

    def test_blank_title_falls_back_to_file_url_stem(self) -> None:
        h = _build("", file_url="https://cdn.example/uploads/공지문.docx?ver=2")
        assert h.document_title == "공지문"

    def test_existing_title_preserved(self) -> None:
        h = _build("실제 제목", file_path="/u/도큐.pdf")
        assert h.document_title == "실제 제목"

    def test_whitespace_only_title_falls_back(self) -> None:
        h = _build("   ", file_path="/u/제안서.pdf")
        assert h.document_title == "제안서"

    def test_no_fallback_source_keeps_empty(self) -> None:
        h = _build("")  # no file_path, no file_url
        assert h.document_title == ""

    def test_repository_id_preserved_through_validator(self) -> None:
        """validator 가 repository_id 등 다른 필드를 건드리지 않는지 회귀 가드."""
        h = _build("", file_path="/u/test.pdf")
        assert h.repository_id == _R
        assert h.document_id == _D
        assert h.chunk_id == _C

    def test_url_query_string_stripped(self) -> None:
        """URL 의 query string 이 stem 에 포함되지 않는지."""
        h = _build("", file_url="https://x.com/path/공지/2026_분기보고서.pdf?token=abc&v=1")
        assert h.document_title == "2026_분기보고서"

    def test_no_extension_filename(self) -> None:
        """확장자 없는 파일명도 그대로 stem 으로 사용."""
        h = _build("", file_path="/u/Q1_REPORT")
        assert h.document_title == "Q1_REPORT"


class TestDocumentTitleSanitization:
    """GPT-5.5 D85c-잔존 P1 — path sanitization 강화 검증."""

    def test_fragment_in_url_stripped(self) -> None:
        h = _build("", file_url="https://x.com/uploads/공지문.pdf#page=5")
        assert h.document_title == "공지문"

    def test_query_and_fragment_in_url_both_stripped(self) -> None:
        h = _build("", file_url="https://x.com/u/Q1_REPORT.docx?v=2#frag")
        assert h.document_title == "Q1_REPORT"

    def test_percent_encoded_korean_unquoted(self) -> None:
        # urllib.parse.quote("연간보고서") = "%EC%97%B0%EA%B0%84%EB%B3%B4%EA%B3%A0%EC%84%9C"
        h = _build(
            "",
            file_url="https://x.com/uploads/%EC%97%B0%EA%B0%84%EB%B3%B4%EA%B3%A0%EC%84%9C.pdf",
        )
        assert h.document_title == "연간보고서"

    def test_windows_backslash_normalized(self) -> None:
        h = _build("", file_path=r"C:\uploads\2026\계약서.docx")
        assert h.document_title == "계약서"

    def test_corrupt_file_path_does_not_raise(self) -> None:
        """corrupt / 빈 segment 만 있는 경로도 안전하게 빈 값으로 처리."""
        h = _build("", file_path="///")
        # stem 추출 실패 — 빈 값 그대로 (caller 가 (제목 없음) placeholder).
        assert h.document_title == ""

    def test_url_with_only_host_no_path(self) -> None:
        h = _build("", file_url="https://example.com")
        # path 가 없음 — fallback 안 함.
        assert h.document_title == ""
