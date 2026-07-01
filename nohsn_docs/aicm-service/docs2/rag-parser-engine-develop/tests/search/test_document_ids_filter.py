"""document_ids payload 필터 단위 테스트.

QdrantDenseSearcher._build_conditions 를 직접 호출해 document_id FieldCondition 이
올바르게 생성되는지 검증한다.
"""
from src.search.hybrid.qdrant_dense import QdrantDenseSearcher


def test_document_ids_builds_field_condition():
    searcher = QdrantDenseSearcher.__new__(QdrantDenseSearcher)
    conditions, _ = searcher._build_conditions(
        tenant_id=None,
        repository_ids=None,
        category_ids=None,
        document_type_ids=None,
        block_types=None,
        nature_filter=None,
        validity_filter="all",
        entity_filter=None,
        document_status_filter="all",
        document_ids=["docA", "docB"],
    )
    keys = [c.key for c in conditions]
    assert "document_id" in keys


def test_no_document_ids_no_condition():
    searcher = QdrantDenseSearcher.__new__(QdrantDenseSearcher)
    conditions, _ = searcher._build_conditions(
        tenant_id=None,
        repository_ids=None,
        category_ids=None,
        document_type_ids=None,
        block_types=None,
        nature_filter=None,
        validity_filter="all",
        entity_filter=None,
        document_status_filter="all",
        document_ids=None,
    )
    keys = [c.key for c in conditions]
    assert "document_id" not in keys


def test_empty_document_ids_no_condition():
    searcher = QdrantDenseSearcher.__new__(QdrantDenseSearcher)
    conditions, _ = searcher._build_conditions(
        tenant_id=None,
        repository_ids=None,
        category_ids=None,
        document_type_ids=None,
        block_types=None,
        nature_filter=None,
        validity_filter="all",
        entity_filter=None,
        document_status_filter="all",
        document_ids=[],
    )
    keys = [c.key for c in conditions]
    assert "document_id" not in keys


def test_document_ids_combined_with_repository_ids():
    searcher = QdrantDenseSearcher.__new__(QdrantDenseSearcher)
    conditions, _ = searcher._build_conditions(
        tenant_id=None,
        repository_ids=["repo1"],
        category_ids=None,
        document_type_ids=None,
        block_types=None,
        nature_filter=None,
        validity_filter="all",
        entity_filter=None,
        document_status_filter="all",
        document_ids=["docA"],
    )
    keys = [c.key for c in conditions]
    assert "repository_id" in keys
    assert "document_id" in keys
