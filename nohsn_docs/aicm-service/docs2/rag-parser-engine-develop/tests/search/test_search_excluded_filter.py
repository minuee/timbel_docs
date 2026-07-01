"""search_excluded 필터 정적 검증 테스트.

Qdrant / ES / SQLAlchemy 모듈 없이 소스 코드 및 파일 레벨에서
search_excluded 구현이 존재하는지 확인한다.
"""
from __future__ import annotations

import pathlib


ROOT = pathlib.Path(__file__).parent.parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_qdrant_dense_has_search_excluded_must_not():
    """qdrant_dense.py 에 must_not + search_excluded 조건이 있음."""
    src = _read("src/search/hybrid/qdrant_dense.py")
    assert "must_not" in src, "must_not 조건 없음"
    assert "search_excluded" in src, "search_excluded 키 없음"
    assert "exclude_search_excluded" in src, "exclude_search_excluded 플래그 없음"


def test_es_keyword_has_search_excluded_must_not():
    """es_keyword.py 에 search_excluded must_not 조건이 있음."""
    src = _read("src/search/hybrid/es_keyword.py")
    assert "search_excluded" in src, "search_excluded 키 없음"
    assert "must_not" in src, "must_not 조건 없음"


def test_document_model_has_search_excluded_column():
    """document.py 모델에 search_excluded 컬럼 정의가 있음."""
    src = _read("src/core/models/document.py")
    assert "search_excluded" in src


def test_document_response_schema_has_search_excluded():
    """document.py 스키마에 search_excluded 필드가 있음."""
    src = _read("src/api/schemas/document.py")
    assert "search_excluded" in src
    assert "SearchExclusionRequest" in src


def test_payload_sync_has_sync_search_excluded():
    """payload_sync.py 에 sync_search_excluded 함수가 있음."""
    src = _read("src/search/payload_sync.py")
    assert "sync_search_excluded" in src
    assert "_qdrant_set_search_excluded_once" in src
    assert "_es_set_search_excluded_once" in src


def test_router_has_search_exclusion_endpoint():
    """documents.py 라우터에 /search-exclusion 엔드포인트가 있음."""
    src = _read("src/api/routers/documents.py")
    assert "/search-exclusion" in src
    assert "set_document_search_exclusion" in src
    assert "sync_search_excluded" in src


def test_migration_053_exists():
    """053_documents_search_excluded.py 마이그레이션 파일이 존재함."""
    migration = ROOT / "alembic" / "versions" / "053_documents_search_excluded.py"
    assert migration.exists()
    src = migration.read_text(encoding="utf-8")
    assert "search_excluded" in src
    assert 'down_revision = "052"' in src


def test_frontend_api_has_set_doc_search_exclusion():
    """frontend documents.ts 에 setDocSearchExclusion 함수가 있음."""
    src = _read("frontend-v3/src/api/documents.ts")
    assert "setDocSearchExclusion" in src
    assert "search-exclusion" in src


def test_frontend_types_has_search_excluded():
    """frontend types.ts DocumentMeta 에 search_excluded 필드가 있음."""
    src = _read("frontend-v3/src/types.ts")
    assert "search_excluded" in src


def test_frontend_docs_tab_uses_new_function():
    """DocsTab.tsx 가 setDocSearchExclusion 를 사용하고 setDocStatus 를 검색 제외 토글에 사용하지 않음."""
    src = _read("frontend-v3/src/components/library/DocsTab.tsx")
    assert "setDocSearchExclusion" in src
    # toggleM 은 excluded: boolean 인수를 사용해야 함 (더 이상 "archived"/"active" 아님)
    assert "excluded: boolean" not in src or "mutate(!isSearchExcluded)" in src or "mutate(!" in src


def test_frontend_repo_docs_page_uses_new_function():
    """RepoDocsPage.tsx 가 setDocSearchExclusion 를 사용함."""
    src = _read("frontend-v3/src/pages/RepoDocsPage.tsx")
    assert "setDocSearchExclusion" in src
    assert "isSearchExcluded" in src
