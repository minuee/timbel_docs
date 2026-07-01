"""D32 §3 — tenant isolation instrumentation 단위 test."""
from __future__ import annotations

import pytest

from src.search.tenant_isolation import (
    CrossTenantSearchError,
    assert_tenant_namespace,
    parse_namespace_slug,
)


class TestParseNamespaceSlug:
    def test_valid_namespace(self) -> None:
        assert parse_namespace_slug("aicm_locus_blocks") == "locus"

    def test_with_hyphen(self) -> None:
        assert parse_namespace_slug("aicm_my-tenant_blocks") == "my-tenant"

    def test_with_underscore(self) -> None:
        assert parse_namespace_slug("aicm_my_tenant_blocks") == "my_tenant"

    def test_invalid_pattern(self) -> None:
        assert parse_namespace_slug("foo_bar") is None
        assert parse_namespace_slug("aicm_blocks") is None
        assert parse_namespace_slug("") is None


class TestAssertTenantNamespace:
    def test_match_passes(self) -> None:
        assert_tenant_namespace(
            namespace="aicm_locus_blocks",
            caller_slug="locus",
        )

    def test_mismatch_raises(self) -> None:
        with pytest.raises(CrossTenantSearchError) as exc:
            assert_tenant_namespace(
                namespace="aicm_evil_blocks",
                caller_slug="locus",
                scope="admin",
            )
        assert exc.value.caller_slug == "locus"
        assert exc.value.target_namespace == "aicm_evil_blocks"
        assert exc.value.scope == "admin"

    def test_unknown_pattern_raises(self) -> None:
        with pytest.raises(CrossTenantSearchError):
            assert_tenant_namespace(
                namespace="raw_collection",
                caller_slug="locus",
                scope="agent",
            )

    def test_superadmin_allow_cross_passes(self) -> None:
        # superadmin + allow_cross_namespace=True → cross-tenant 허용 (admin global view).
        assert_tenant_namespace(
            namespace="aicm_evil_blocks",
            caller_slug="locus",
            scope="superadmin",
            allow_cross_namespace=True,
        )

    def test_system_allow_cross_passes(self) -> None:
        # background worker / cron — system scope.
        assert_tenant_namespace(
            namespace="aicm_evil_blocks",
            caller_slug="locus",
            scope="system",
            allow_cross_namespace=True,
        )

    def test_admin_allow_cross_blocked(self) -> None:
        # admin scope 는 allow_cross_namespace=True 라도 차단 (안전 기본값).
        with pytest.raises(CrossTenantSearchError):
            assert_tenant_namespace(
                namespace="aicm_evil_blocks",
                caller_slug="locus",
                scope="admin",
                allow_cross_namespace=True,
            )

    def test_agent_allow_cross_blocked(self) -> None:
        with pytest.raises(CrossTenantSearchError):
            assert_tenant_namespace(
                namespace="aicm_evil_blocks",
                caller_slug="locus",
                scope="agent",
                allow_cross_namespace=True,
            )

    def test_superadmin_no_allow_blocks(self) -> None:
        # superadmin scope 라도 allow_cross_namespace=False (기본) 면 차단.
        with pytest.raises(CrossTenantSearchError):
            assert_tenant_namespace(
                namespace="aicm_evil_blocks",
                caller_slug="locus",
                scope="superadmin",
                allow_cross_namespace=False,
            )
