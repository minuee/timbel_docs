"""D85c-잔존 reprocess (2026-05-14) — retry endpoint cleanup helper smoke.

`_reset_blocks_and_indexes_for_reprocess` 의 *외부 의존 부재 시 graceful
degrade* + *반환 shape* + *retry from_stage='parsing' 분기에서 호출되는지*
의 minimal smoke. 실제 ES/Qdrant integration 은 별도 fixture (Phase D 검증
영역).
"""
from __future__ import annotations

import inspect

from src.api.routers import documents as _documents_mod


class TestCleanupHelperContract:
    """helper 가 retry endpoint 의 spec 에 맞게 export 되어 있는지."""

    def test_helper_function_exists(self) -> None:
        assert hasattr(_documents_mod, "_reset_blocks_and_indexes_for_reprocess"), (
            "retry 의 from_stage='parsing' cleanup helper 가 module 에 없음"
        )

    def test_helper_signature_matches_retry_call_site(self) -> None:
        """retry endpoint 가 호출하는 kwargs 와 helper signature 일치."""
        helper = _documents_mod._reset_blocks_and_indexes_for_reprocess
        sig = inspect.signature(helper)
        expected_kwargs = {"doc_id", "tenant_id", "repository_id", "db"}
        params = set(sig.parameters.keys())
        missing = expected_kwargs - params
        assert not missing, f"helper signature 누락 인자: {missing}"

    def test_retry_endpoint_calls_cleanup_on_parsing_stage(self) -> None:
        """retry_document 의 from_stage='parsing' 분기 코드 path 에 cleanup
        호출 라인이 보존되는지 — 리팩토링 회귀 가드."""
        src = inspect.getsource(_documents_mod.retry_document)
        # cleanup helper 호출 + parsing 분기 직접 명시.
        assert "_reset_blocks_and_indexes_for_reprocess" in src, (
            "retry_document body 에 cleanup helper 호출 누락"
        )
        # publish 직전에 cleanup 호출 (순서 보장 — duplicate 차단의 핵심).
        cleanup_idx = src.index("_reset_blocks_and_indexes_for_reprocess")
        publish_idx = src.index("_publish_upload_event")
        assert cleanup_idx < publish_idx, (
            "cleanup 호출이 _publish_upload_event 후에 위치 — 순서 잘못"
        )


class TestCleanupReturnShape:
    """반환 dict 의 shape — GPT-5.5 verdict v1 권고 #1 반영."""

    def test_return_has_ok_errors_counts(self) -> None:
        src = inspect.getsource(_documents_mod._reset_blocks_and_indexes_for_reprocess)
        assert '"ok": True' in src or '"ok": False' in src
        assert '"errors"' in src
        assert '"counts"' in src

    def test_counts_contains_three_targets(self) -> None:
        src = inspect.getsource(_documents_mod._reset_blocks_and_indexes_for_reprocess)
        for k in ('"db_blocks"', '"es"', '"qdrant"'):
            assert k in src, f"반환 counts key {k} 가 helper body 에 없음"


class TestCleanupFailFast:
    """critical 실패 시 fast-return — GPT-5.5 verdict v1 권고 #2."""

    def test_db_cleanup_failure_returns_ok_false(self) -> None:
        src = inspect.getsource(_documents_mod._reset_blocks_and_indexes_for_reprocess)
        # except 분기에서 ok=False 명시 반환.
        assert 'errors.append(f"db_blocks:' in src
        # DB 실패 시 fast-return 명시.
        assert "DB cleanup 실패는 critical" in src

    def test_tenant_lookup_failure_returns_ok_false(self) -> None:
        src = inspect.getsource(_documents_mod._reset_blocks_and_indexes_for_reprocess)
        assert "tenant_slug_unresolved" in src


class TestCleanupGuards:
    """각 외부 호출 (DB / ES / Qdrant) 가 try/except 로 격리되어 *한 곳 실패가
    전체 retry 를 무력화* 하지 않는지."""

    def test_db_blocks_delete_isolated(self) -> None:
        src = inspect.getsource(_documents_mod._reset_blocks_and_indexes_for_reprocess)
        assert "reprocess_cleanup_db_blocks_failed" in src

    def test_es_cleanup_isolated(self) -> None:
        src = inspect.getsource(_documents_mod._reset_blocks_and_indexes_for_reprocess)
        assert "reprocess_cleanup_es_failed" in src

    def test_qdrant_cleanup_isolated(self) -> None:
        src = inspect.getsource(_documents_mod._reset_blocks_and_indexes_for_reprocess)
        assert "reprocess_cleanup_qdrant_failed" in src

    def test_es_delete_uses_repository_id_guard(self) -> None:
        """ES delete_by_query 가 repository_id + document_id guard 모두 적용
        (GPT-5.5 reprocess verdict #2 — tenant/repo guard + refresh + conflicts)."""
        src = inspect.getsource(_documents_mod._reset_blocks_and_indexes_for_reprocess)
        assert '"term": {"repository_id"' in src
        assert '"term": {"document_id"' in src
        # verdict #2 의 refresh + conflicts 명시.
        assert "refresh=True" in src
        assert 'conflicts="proceed"' in src

    def test_qdrant_async_safe_wrap(self) -> None:
        """sync QdrantClient.delete 가 asyncio.to_thread 로 격리됐는지 — verdict v1 권고 #6."""
        src = inspect.getsource(_documents_mod._reset_blocks_and_indexes_for_reprocess)
        assert "_asyncio.to_thread" in src or "asyncio.to_thread" in src

    def test_qdrant_filter_includes_repository_id(self) -> None:
        """Qdrant filter 도 repository_id + document_id 두 조건 — verdict v1 권고 #5."""
        src = inspect.getsource(_documents_mod._reset_blocks_and_indexes_for_reprocess)
        # Qdrant delete 의 filter must clause 안에 두 key.
        qdrant_section = src.split("# 4) Qdrant")[1] if "# 4) Qdrant" in src else src
        assert 'key="repository_id"' in qdrant_section
        assert 'key="document_id"' in qdrant_section


class TestRetryEndpointCleanupFailureHandling:
    """retry_document 가 cleanup 실패 시 publish skip + status=failed 기록."""

    def test_cleanup_ok_false_skips_publish(self) -> None:
        src = inspect.getsource(_documents_mod.retry_document)
        # cleanup.get("ok") False 분기에서 publish 호출 전 raise.
        assert 'cleanup.get("ok")' in src
        # status='failed' 전환 + processing_meta 기록.
        assert 'target_status="failed"' in src
        assert "reprocess_cleanup" in src

    def test_cleanup_failure_raises_500(self) -> None:
        src = inspect.getsource(_documents_mod.retry_document)
        # GPT-5.5 verdict v1 권고 #8 — publish 실패 시 API 실패 반환.
        assert "재처리 사전 정리 실패" in src
        assert "status_code=500" in src
