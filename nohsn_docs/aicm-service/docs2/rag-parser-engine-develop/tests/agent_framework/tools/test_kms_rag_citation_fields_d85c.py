"""D85c-잔존 (2026-05-13) — kms_rag.search hit_dict + result_field_spec 동기.

사용자 보고 "citation full_url None / title 빈 값" 의 hot path:
- ``KMSRagTool.__call__`` 가 SearchHit → hit_dict 변환 시 ``repository_id`` /
  ``block_id`` / ``section_title`` / ``page_number`` 누락 → engine 의 citation
  빌드가 ``_h.get('repository_id')`` = None → full_url 계산 실패.
- ``PUBLIC_FIELDS['kms_rag.search']['hits']`` 화이트리스트 누락 시 split_result
  가 hit 에서 해당 필드를 제거.

본 테스트는 두 layer 의 정합성을 fixture-free 로 검증.
"""
from __future__ import annotations

from uuid import UUID

from src.agent_framework.tools.kms_rag import _search_hit_to_public_hit_dict
from src.agent_framework.tools.result_field_spec import PUBLIC_FIELDS, split_result
from src.search.models import SearchHit, SourceLocation


_CITATION_REQUIRED_FIELDS = (
    "block_id",
    "repository_id",
    "section_title",
    "section",  # legacy alias — backward-compat
    "page_number",
    "block_type",
)

_CITATION_LEGACY_FIELDS = (
    "title",
    "document_title",
    "snippet",
    "content",
    "score",
    "document_id",
    "url",
    "page",
    "name",
)


class TestKmsRagWhitelist:
    """PUBLIC_FIELDS['kms_rag.search']['hits'] 화이트리스트 동기."""

    def test_citation_fields_present_in_whitelist(self) -> None:
        spec = PUBLIC_FIELDS.get("kms_rag.search")
        assert spec is not None, "kms_rag.search spec 자체 누락"
        hits_fields = set(spec["hits"])  # type: ignore[arg-type]
        missing = set(_CITATION_REQUIRED_FIELDS) - hits_fields
        assert not missing, f"화이트리스트 누락 필드: {missing}"

    def test_legacy_fields_preserved(self) -> None:
        spec = PUBLIC_FIELDS.get("kms_rag.search")
        assert spec is not None
        hits_fields = set(spec["hits"])  # type: ignore[arg-type]
        missing = set(_CITATION_LEGACY_FIELDS) - hits_fields
        assert not missing, f"legacy 필드 회귀 누락: {missing}"


class TestSplitResultRoundtrip:
    """split_result(public, private) 가 citation 필드를 보존하는지."""

    @staticmethod
    def _build_hit() -> dict:
        return {
            "id": "h1",
            "document_id": "d1",
            "block_id": "b1",
            "repository_id": "r1",
            "title": "Q1 보고서",
            "document_title": "Q1 보고서",
            "section_title": "2장",
            "section": "2장",
            "page_number": 5,
            "block_type": "paragraph",
            "content": "본문",
            "score": 0.9,
        }

    def test_split_result_keeps_repository_id(self) -> None:
        public, _ = split_result(
            "kms_rag.search",
            {"hits": [self._build_hit()], "total": 1, "summary": "ok"},
        )
        hit = public["hits"][0]
        assert hit.get("repository_id") == "r1"

    def test_split_result_keeps_block_id(self) -> None:
        public, _ = split_result(
            "kms_rag.search",
            {"hits": [self._build_hit()], "total": 1, "summary": "ok"},
        )
        assert public["hits"][0].get("block_id") == "b1"

    def test_split_result_keeps_section_title_and_page(self) -> None:
        public, _ = split_result(
            "kms_rag.search",
            {"hits": [self._build_hit()], "total": 1, "summary": "ok"},
        )
        hit = public["hits"][0]
        assert hit.get("section_title") == "2장"
        assert hit.get("page_number") == 5


class TestEngineCitationLookupChain:
    """engine.py 의 citation 빌드 lookup chain (KMS-Plus 2026-05-13 D85c-B3) 가
    kms_rag hit_dict 의 새 필드로 정상 작동하는지 회귀 가드.

    engine.py:2235-2253 의 logic:
      _block_id = _h.get('block_id') or _h.get('chunk_id') or _h.get('id')
      _doc_id   = _h.get('document_id') or _h.get('doc_id')
      _repo_id  = _h.get('repository_id') or _h.get('repo_id')
      _full_url = f'/repos/{_repo_id}/docs/{_doc_id}' if _repo_id and _doc_id else None
      title = _h.get('title') or _h.get('document_title') or _h.get('name') or '(제목 없음)'
    """

    @staticmethod
    def _kms_rag_hit_shape() -> dict:
        """kms_rag.py 의 hit_dict 출력 shape (D85c-잔존 fix 후) 그대로."""
        return {
            "id": "c-1",
            "document_id": "d-1",
            "block_id": "b-1",
            "repository_id": "r-1",
            "title": "품질평가표",
            "document_title": "품질평가표",
            "section_title": "제 2장",
            "section": "제 2장",
            "page_number": 17,
            "content": "본문",
            "score": 0.85,
        }

    def test_full_url_resolves(self) -> None:
        h = self._kms_rag_hit_shape()
        repo_id = h.get("repository_id") or h.get("repo_id")
        doc_id = h.get("document_id") or h.get("doc_id")
        full_url = f"/repos/{repo_id}/docs/{doc_id}" if repo_id and doc_id else None
        assert full_url == "/repos/r-1/docs/d-1"

    def test_block_id_resolves(self) -> None:
        h = self._kms_rag_hit_shape()
        block_id = h.get("block_id") or h.get("chunk_id") or h.get("id")
        assert block_id == "b-1"

    def test_title_resolves(self) -> None:
        h = self._kms_rag_hit_shape()
        title = (
            str(h.get("title") or h.get("document_title") or h.get("name") or "").strip()
            or "(제목 없음)"
        )
        assert title == "품질평가표"

    def test_missing_repository_id_produces_none_full_url(self) -> None:
        """repository_id 미설정 시 full_url=None 명시 — graceful degrade."""
        h = self._kms_rag_hit_shape()
        h["repository_id"] = None
        repo_id = h.get("repository_id") or h.get("repo_id")
        doc_id = h.get("document_id") or h.get("doc_id")
        full_url = f"/repos/{repo_id}/docs/{doc_id}" if repo_id and doc_id else None
        assert full_url is None


_C = UUID("00000000-0000-0000-0000-000000000001")
_D = UUID("00000000-0000-0000-0000-000000000002")
_R = UUID("00000000-0000-0000-0000-000000000003")


class TestSearchHitToPublicHitDictHelper:
    """GPT-5.5 D85c-잔존 P1 권고 — _search_hit_to_public_hit_dict helper 직접 검증.

    KMSRagTool.__call__ body 에서 분리한 변환 helper. SearchHit → hit_dict
    매핑이 누락 없이 정확한지 회귀 가드.
    """

    @staticmethod
    def _build_hit(**overrides: object) -> SearchHit:
        kwargs: dict[str, object] = dict(
            chunk_id=_C,
            document_id=_D,
            document_title="품질평가표",
            content="본문",
            repository_id=_R,
            section_title="제 2장",
            source_location=SourceLocation(file_path="/u/품질평가표.pdf", page_number=17),
        )
        kwargs.update(overrides)
        return SearchHit(**kwargs)  # type: ignore[arg-type]

    def test_helper_surfaces_repository_id(self) -> None:
        hit = self._build_hit()
        out = _search_hit_to_public_hit_dict(hit, content=hit.content)
        assert out["repository_id"] == str(_R)

    def test_helper_surfaces_block_id_falls_back_to_chunk_id(self) -> None:
        # block_id 명시 없음 — chunk_id 로 fallback (기존 호환).
        hit = self._build_hit()
        out = _search_hit_to_public_hit_dict(hit, content=hit.content)
        assert out["block_id"] == str(_C)

    def test_helper_surfaces_section_title_and_legacy_section_alias(self) -> None:
        hit = self._build_hit()
        out = _search_hit_to_public_hit_dict(hit, content=hit.content)
        assert out["section_title"] == "제 2장"
        assert out["section"] == "제 2장"  # legacy alias

    def test_helper_surfaces_page_number_from_source_location(self) -> None:
        hit = self._build_hit()
        out = _search_hit_to_public_hit_dict(hit, content=hit.content)
        assert out["page_number"] == 17

    def test_helper_surfaces_title_and_document_title_in_parallel(self) -> None:
        hit = self._build_hit()
        out = _search_hit_to_public_hit_dict(hit, content=hit.content)
        assert out["title"] == "품질평가표"
        assert out["document_title"] == "품질평가표"

    def test_helper_caps_content_at_4000(self) -> None:
        long = "가" * 5000
        hit = self._build_hit(content=long)
        out = _search_hit_to_public_hit_dict(hit, content=long)
        assert len(out["content"]) == 4000

    def test_helper_with_no_repository_id_returns_none(self) -> None:
        hit = self._build_hit(repository_id=None)
        out = _search_hit_to_public_hit_dict(hit, content=hit.content)
        assert out["repository_id"] is None

    def test_helper_with_no_source_location_page_number_is_none(self) -> None:
        hit = self._build_hit(source_location=SourceLocation())
        out = _search_hit_to_public_hit_dict(hit, content=hit.content)
        assert out["page_number"] is None

    def test_helper_score_is_float(self) -> None:
        hit = self._build_hit()
        out = _search_hit_to_public_hit_dict(hit, content=hit.content)
        assert isinstance(out["score"], float)
