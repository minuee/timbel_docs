"""Phase 2.7 — storage_tenant 헬퍼 단위 테스트.

MinIO / Redis / Kafka 격리 헬퍼의 결정적 동작을 검증한다.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.common.storage_tenant import (
    LUCAS_PREFIX,
    SHARED_TENANT_SENTINEL,
    kafka_envelope,
    kafka_payload_get_tenant,
    minio_key,
    minio_key_has_tenant_prefix,
    normalize_tenant_id,
    redis_key,
    redis_key_extract_tenant,
    redis_shared_key,
    require_tenant_id,
)


# ---------------------------------------------------------------------------
# normalize_tenant_id / require_tenant_id
# ---------------------------------------------------------------------------


class TestNormalizeTenantId:
    def test_string_passthrough(self) -> None:
        assert normalize_tenant_id("t1") == "t1"

    def test_uuid_converted_to_string(self) -> None:
        tid = uuid4()
        assert normalize_tenant_id(tid) == str(tid)

    def test_uuid_string_passthrough(self) -> None:
        tid = uuid4()
        assert normalize_tenant_id(str(tid)) == str(tid)

    def test_none_returns_shared_sentinel(self) -> None:
        assert normalize_tenant_id(None) == SHARED_TENANT_SENTINEL

    def test_empty_string_returns_shared_sentinel(self) -> None:
        assert normalize_tenant_id("") == SHARED_TENANT_SENTINEL

    def test_whitespace_string_returns_shared_sentinel(self) -> None:
        assert normalize_tenant_id("   ") == SHARED_TENANT_SENTINEL

    def test_strips_surrounding_whitespace(self) -> None:
        assert normalize_tenant_id("  t1  ") == "t1"


class TestRequireTenantId:
    def test_valid_string(self) -> None:
        assert require_tenant_id("t1") == "t1"

    def test_valid_uuid(self) -> None:
        tid = uuid4()
        assert require_tenant_id(tid) == str(tid)

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id required"):
            require_tenant_id(None)

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id required"):
            require_tenant_id("")

    def test_whitespace_string_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id required"):
            require_tenant_id("   ")


# ---------------------------------------------------------------------------
# MinIO object key helper
# ---------------------------------------------------------------------------


class TestMinioKey:
    def test_single_part(self) -> None:
        assert minio_key("t1", "doc-42") == "t1/doc-42"

    def test_multi_part(self) -> None:
        assert (
            minio_key("t1", "doc-42", "parsed.json")
            == "t1/doc-42/parsed.json"
        )

    def test_uuid_tenant_id(self) -> None:
        tid = UUID("12345678-1234-5678-1234-567812345678")
        assert minio_key(tid, "doc-42") == "12345678-1234-5678-1234-567812345678/doc-42"

    def test_strips_leading_trailing_slashes(self) -> None:
        # parts 에 ``/`` prefix/suffix 가 있으면 정리해야 이중 슬래시 방지.
        assert minio_key("t1", "/doc-42/", "parsed.json/") == "t1/doc-42/parsed.json"

    def test_none_tenant_raises(self) -> None:
        with pytest.raises(ValueError):
            minio_key(None, "doc-42")  # type: ignore[arg-type]

    def test_empty_tenant_raises(self) -> None:
        with pytest.raises(ValueError):
            minio_key("", "doc-42")

    def test_no_parts_raises(self) -> None:
        with pytest.raises(ValueError):
            minio_key("t1")

    def test_all_empty_parts_raises(self) -> None:
        with pytest.raises(ValueError):
            minio_key("t1", "/", "  ")

    def test_cross_tenant_keys_differ(self) -> None:
        # 동일 document_id 라도 tenant 가 다르면 key 가 달라야 격리됨.
        assert minio_key("t1", "doc-42") != minio_key("t2", "doc-42")


class TestMinioKeyHasTenantPrefix:
    def test_matching_prefix(self) -> None:
        assert minio_key_has_tenant_prefix("t1/doc-42/parsed.json", "t1") is True

    def test_different_prefix(self) -> None:
        assert minio_key_has_tenant_prefix("t1/doc-42/parsed.json", "t2") is False

    def test_no_prefix(self) -> None:
        assert minio_key_has_tenant_prefix("doc-42/parsed.json", "t1") is False

    def test_uuid_tenant(self) -> None:
        tid = UUID("12345678-1234-5678-1234-567812345678")
        key = f"{tid}/doc-42"
        assert minio_key_has_tenant_prefix(key, tid) is True

    def test_none_tenant_returns_false(self) -> None:
        assert minio_key_has_tenant_prefix("doc-42", None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Redis key helper
# ---------------------------------------------------------------------------


class TestRedisKey:
    def test_single_part(self) -> None:
        assert redis_key("t1", "cache") == f"{LUCAS_PREFIX}:t1:cache"

    def test_multi_part(self) -> None:
        assert (
            redis_key("t1", "cache", "doc-42")
            == f"{LUCAS_PREFIX}:t1:cache:doc-42"
        )

    def test_uuid_tenant(self) -> None:
        tid = UUID("12345678-1234-5678-1234-567812345678")
        assert redis_key(tid, "cache") == f"{LUCAS_PREFIX}:{tid}:cache"

    def test_strips_colons_in_parts(self) -> None:
        assert redis_key("t1", ":cache:", "doc-42") == f"{LUCAS_PREFIX}:t1:cache:doc-42"

    def test_none_tenant_raises(self) -> None:
        with pytest.raises(ValueError):
            redis_key(None, "cache")  # type: ignore[arg-type]

    def test_empty_parts_raises(self) -> None:
        with pytest.raises(ValueError):
            redis_key("t1")

    def test_cross_tenant_keys_differ(self) -> None:
        assert redis_key("t1", "cache") != redis_key("t2", "cache")


class TestRedisSharedKey:
    def test_single_part(self) -> None:
        assert (
            redis_shared_key("vllm_health")
            == f"{LUCAS_PREFIX}:{SHARED_TENANT_SENTINEL}:vllm_health"
        )

    def test_multi_part(self) -> None:
        assert (
            redis_shared_key("vllm_health", "endpoint")
            == f"{LUCAS_PREFIX}:{SHARED_TENANT_SENTINEL}:vllm_health:endpoint"
        )

    def test_no_parts_raises(self) -> None:
        with pytest.raises(ValueError):
            redis_shared_key()

    def test_shared_key_distinct_from_tenant_key(self) -> None:
        assert redis_shared_key("vllm_health") != redis_key("t1", "vllm_health")


class TestRedisKeyExtractTenant:
    def test_extract_tenant(self) -> None:
        key = redis_key("t1", "cache", "doc-42")
        assert redis_key_extract_tenant(key) == "t1"

    def test_shared_key_returns_none(self) -> None:
        key = redis_shared_key("vllm_health")
        assert redis_key_extract_tenant(key) is None

    def test_non_lucas_key_returns_none(self) -> None:
        assert redis_key_extract_tenant("aicm:cache_stats:t1:hit") is None

    def test_uuid_tenant(self) -> None:
        tid = UUID("12345678-1234-5678-1234-567812345678")
        key = redis_key(tid, "cache")
        assert redis_key_extract_tenant(key) == str(tid)


# ---------------------------------------------------------------------------
# Kafka envelope helper
# ---------------------------------------------------------------------------


class TestKafkaEnvelope:
    def test_adds_tenant_id_to_payload(self) -> None:
        result = kafka_envelope("t1", {"document_id": "d1"})
        assert result == {"document_id": "d1", "tenant_id": "t1"}

    def test_preserves_existing_keys(self) -> None:
        original = {"document_id": "d1", "event": "blocked", "count": 5}
        result = kafka_envelope("t1", original)
        assert result["document_id"] == "d1"
        assert result["event"] == "blocked"
        assert result["count"] == 5
        assert result["tenant_id"] == "t1"

    def test_does_not_mutate_input(self) -> None:
        original = {"document_id": "d1"}
        kafka_envelope("t1", original)
        assert "tenant_id" not in original

    def test_uuid_tenant_normalized(self) -> None:
        tid = UUID("12345678-1234-5678-1234-567812345678")
        result = kafka_envelope(tid, {"doc": "d1"})
        assert result["tenant_id"] == str(tid)

    def test_matching_existing_tenant_ok(self) -> None:
        # 이미 같은 값이면 conflict 없음.
        result = kafka_envelope("t1", {"tenant_id": "t1", "doc": "d1"})
        assert result["tenant_id"] == "t1"

    def test_mismatching_tenant_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id mismatch"):
            kafka_envelope("t1", {"tenant_id": "t2", "doc": "d1"})

    def test_overwrite_flag_allows_mismatch(self) -> None:
        result = kafka_envelope(
            "t1", {"tenant_id": "t2", "doc": "d1"}, overwrite=True
        )
        assert result["tenant_id"] == "t1"

    def test_none_tenant_raises(self) -> None:
        with pytest.raises(ValueError):
            kafka_envelope(None, {"doc": "d1"})  # type: ignore[arg-type]

    def test_non_dict_payload_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            kafka_envelope("t1", "not a dict")  # type: ignore[arg-type]


class TestKafkaPayloadGetTenant:
    def test_extracts_tenant(self) -> None:
        payload = {"tenant_id": "t1", "doc": "d1"}
        assert kafka_payload_get_tenant(payload) == "t1"

    def test_missing_returns_none(self) -> None:
        assert kafka_payload_get_tenant({"doc": "d1"}) is None

    def test_uuid_normalized(self) -> None:
        tid = uuid4()
        assert kafka_payload_get_tenant({"tenant_id": tid}) == str(tid)

    def test_non_dict_returns_none(self) -> None:
        assert kafka_payload_get_tenant("not a dict") is None  # type: ignore[arg-type]

    def test_empty_string_returns_sentinel(self) -> None:
        # 빈 문자열은 sentinel — 호출처에서 명시적 처리 필요.
        assert kafka_payload_get_tenant({"tenant_id": ""}) == SHARED_TENANT_SENTINEL


# ---------------------------------------------------------------------------
# Cross-store invariants — 동일 tenant_id 가 store 별로 분리되어야 함.
# ---------------------------------------------------------------------------


class TestCrossStoreInvariants:
    def test_minio_redis_kafka_all_include_same_tenant(self) -> None:
        tid = "t1"
        mk = minio_key(tid, "doc-42")
        rk = redis_key(tid, "cache", "doc-42")
        ke = kafka_envelope(tid, {"doc": "d1"})

        # 세 store 모두에서 tenant_id 가 추출 가능해야 함.
        assert mk.startswith(f"{tid}/")
        assert redis_key_extract_tenant(rk) == tid
        assert kafka_payload_get_tenant(ke) == tid

    def test_different_tenants_keys_isolated(self) -> None:
        # 동일 자원에 대해 두 tenant 의 key 가 절대 같으면 안 됨.
        assert minio_key("t1", "doc-42") != minio_key("t2", "doc-42")
        assert redis_key("t1", "cache", "k") != redis_key("t2", "cache", "k")
        e1 = kafka_envelope("t1", {"doc": "d1"})
        e2 = kafka_envelope("t2", {"doc": "d1"})
        assert e1["tenant_id"] != e2["tenant_id"]
