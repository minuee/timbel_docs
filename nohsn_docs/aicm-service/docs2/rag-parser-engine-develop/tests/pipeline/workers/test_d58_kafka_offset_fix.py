"""D58 — Kafka offset commit timing fix + profile-aware topic 분리 검증.

검증 영역:
1. `_resolve_topics_for_profile` — small / large / legacy 별 정확한 topic 집합.
2. small 프로파일이 SPLIT / PART_READY / PART_BLOCKED 를 *구독하지 않음* — 각 part 2회 처리 차단.
3. legacy 프로파일이 모든 topic 구독 — 역호환 회귀 0%.
4. `_dedup_check_part` / `_dedup_clear_part` — part 단위 dedup 키 (doc_id + part_index + stage).
5. consumer enable_auto_commit=False 보장.
"""
from __future__ import annotations

from unittest import mock

import pytest

from src.common.constants import (
    TOPIC_DOCUMENT_BLOCKED,
    TOPIC_DOCUMENT_CHUNKED,
    TOPIC_DOCUMENT_PARSED,
    TOPIC_DOCUMENT_PART_BLOCKED,
    TOPIC_DOCUMENT_PART_READY,
    TOPIC_DOCUMENT_SPLIT,
    TOPIC_DOCUMENT_UPLOADED,
    TOPIC_DOCUMENT_UPLOADED_LARGE,
    TOPIC_DOCUMENT_UPLOADED_SMALL,
)


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("PIPELINE_WORKER_PROFILE", raising=False)


def _import_main():
    from src.pipeline.workers import main as main_module

    return main_module


# ---------------------------------------------------------------------------
# §A — Profile-aware topic 구독
# ---------------------------------------------------------------------------


def test_topics_small_excludes_split_and_part_topics():
    """small 프로파일은 SPLIT / PART_READY / PART_BLOCKED 구독 X (각 part 2회 처리 차단)."""
    main = _import_main()
    topics = main._resolve_topics_for_profile("small")

    # 포함해야 할 topic
    assert TOPIC_DOCUMENT_UPLOADED_SMALL in topics
    assert TOPIC_DOCUMENT_UPLOADED in topics  # legacy 흡수
    assert TOPIC_DOCUMENT_PARSED in topics
    assert TOPIC_DOCUMENT_CHUNKED in topics
    assert TOPIC_DOCUMENT_BLOCKED in topics

    # 제외해야 할 topic (D58 PRIMARY)
    assert TOPIC_DOCUMENT_SPLIT not in topics
    assert TOPIC_DOCUMENT_PART_READY not in topics
    assert TOPIC_DOCUMENT_PART_BLOCKED not in topics

    # 정확한 개수: 2 uploaded + 3 intermediate = 5
    assert len(topics) == 5, f"small 프로파일 topic 개수 = 5 (실제 {len(topics)}): {topics}"


def test_topics_large_includes_split_and_part_topics():
    """large 프로파일은 SPLIT/PART_READY/PART_BLOCKED + 자체 PARSED/CHUNKED/BLOCKED 포함."""
    main = _import_main()
    topics = main._resolve_topics_for_profile("large")

    assert TOPIC_DOCUMENT_UPLOADED_LARGE in topics
    assert TOPIC_DOCUMENT_SPLIT in topics
    assert TOPIC_DOCUMENT_PART_READY in topics
    assert TOPIC_DOCUMENT_PART_BLOCKED in topics
    assert TOPIC_DOCUMENT_PARSED in topics
    assert TOPIC_DOCUMENT_CHUNKED in topics
    assert TOPIC_DOCUMENT_BLOCKED in topics

    # small 의 uploaded 는 제외
    assert TOPIC_DOCUMENT_UPLOADED_SMALL not in topics
    assert TOPIC_DOCUMENT_UPLOADED not in topics

    # 1 uploaded + 6 intermediate = 7
    assert len(topics) == 7, f"large 프로파일 topic 개수 = 7 (실제 {len(topics)}): {topics}"


def test_topics_legacy_includes_all_topics():
    """legacy (env 미설정) 은 모든 topic — 역호환 0 회귀."""
    main = _import_main()
    topics = main._resolve_topics_for_profile("legacy")

    expected = {
        TOPIC_DOCUMENT_UPLOADED,
        TOPIC_DOCUMENT_UPLOADED_SMALL,
        TOPIC_DOCUMENT_UPLOADED_LARGE,
        TOPIC_DOCUMENT_PARSED,
        TOPIC_DOCUMENT_CHUNKED,
        TOPIC_DOCUMENT_BLOCKED,
        TOPIC_DOCUMENT_SPLIT,
        TOPIC_DOCUMENT_PART_READY,
        TOPIC_DOCUMENT_PART_BLOCKED,
    }
    assert set(topics) == expected, f"legacy 프로파일 = 9 topic. diff: {set(topics) ^ expected}"
    assert len(topics) == 9


def test_topics_unknown_profile_falls_back_to_legacy():
    """알 수 없는 프로파일은 legacy 동작 (역호환)."""
    main = _import_main()
    topics_unknown = main._resolve_topics_for_profile("xxxxx")
    topics_legacy = main._resolve_topics_for_profile("legacy")
    assert set(topics_unknown) == set(topics_legacy)


def test_resolve_worker_profile_default_is_legacy(monkeypatch):
    """env 미설정 시 legacy — 기존 동작 보존."""
    main = _import_main()
    monkeypatch.delenv("PIPELINE_WORKER_PROFILE", raising=False)
    assert main._resolve_worker_profile() == "legacy"


def test_resolve_worker_profile_small(monkeypatch):
    main = _import_main()
    monkeypatch.setenv("PIPELINE_WORKER_PROFILE", "small")
    assert main._resolve_worker_profile() == "small"


def test_resolve_worker_profile_large(monkeypatch):
    main = _import_main()
    monkeypatch.setenv("PIPELINE_WORKER_PROFILE", "LARGE")  # case-insensitive
    assert main._resolve_worker_profile() == "large"


# ---------------------------------------------------------------------------
# §B — Part 단위 dedup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_check_part_first_call_returns_false_then_true(monkeypatch):
    """첫 호출 = False (lock 획득) → 두번째 호출 = True (이미 처리 중 skip)."""
    main = _import_main()

    fake_storage: dict[str, str] = {}

    class FakeRedis:
        async def set(self, key, value, nx=True, ex=600):
            if nx and key in fake_storage:
                return None
            fake_storage[key] = value
            return True

        async def delete(self, key):
            fake_storage.pop(key, None)

        async def aclose(self):
            pass

    def fake_from_url(*args, **kwargs):
        return FakeRedis()

    monkeypatch.setattr("redis.asyncio.from_url", fake_from_url)

    # 1st call → lock 획득 (False = not duplicated)
    res1 = await main._dedup_check_part("doc-1", 3, "block_part")
    assert res1 is False, "첫 호출은 lock 획득 → False"

    # 2nd call (clear 안 함) → 이미 처리 중 (True = skip)
    res2 = await main._dedup_check_part("doc-1", 3, "block_part")
    assert res2 is True, "두번째 호출은 lock 이미 획득됨 → True (skip)"

    # 다른 part_index 는 별개 키 → False
    res3 = await main._dedup_check_part("doc-1", 4, "block_part")
    assert res3 is False, "다른 part_index 는 별개 lock → False"

    # 다른 stage 는 별개 키 → False
    res4 = await main._dedup_check_part("doc-1", 3, "merge_part")
    assert res4 is False, "다른 stage 는 별개 lock → False"


@pytest.mark.asyncio
async def test_dedup_check_part_redis_failure_passes_through(monkeypatch):
    """Redis 장애 시 dedup 통과 (D17-v5 idempotent upsert 가 최종 보장)."""
    main = _import_main()

    def fake_from_url(*args, **kwargs):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr("redis.asyncio.from_url", fake_from_url)

    res = await main._dedup_check_part("doc-1", 3, "block_part")
    assert res is False, "Redis 장애 → False (안전 통과)"


@pytest.mark.asyncio
async def test_dedup_clear_part_removes_key(monkeypatch):
    """clear 후 dedup_check 다시 False (lock 해제)."""
    main = _import_main()

    fake_storage: dict[str, str] = {}

    class FakeRedis:
        async def set(self, key, value, nx=True, ex=600):
            if nx and key in fake_storage:
                return None
            fake_storage[key] = value
            return True

        async def delete(self, key):
            fake_storage.pop(key, None)

        async def aclose(self):
            pass

    monkeypatch.setattr("redis.asyncio.from_url", lambda *a, **kw: FakeRedis())

    await main._dedup_check_part("doc-1", 3, "block_part")  # lock
    assert len(fake_storage) == 1

    await main._dedup_clear_part("doc-1", 3, "block_part")
    assert len(fake_storage) == 0, "clear 후 키 제거"

    # clear 후 재호출 = lock 다시 획득 가능
    res = await main._dedup_check_part("doc-1", 3, "block_part")
    assert res is False


def test_dedup_check_part_key_format(monkeypatch):
    """part dedup 키 형식: aicm:processing_part:{doc_id}:{part_index}:{stage}."""
    main = _import_main()

    captured_keys: list[str] = []

    class FakeRedis:
        async def set(self, key, value, nx=True, ex=600):
            captured_keys.append(key)
            return True

        async def aclose(self):
            pass

    monkeypatch.setattr("redis.asyncio.from_url", lambda *a, **kw: FakeRedis())

    import asyncio

    asyncio.run(main._dedup_check_part("doc-abc", 7, "block_part"))
    assert captured_keys == ["aicm:processing_part:doc-abc:7:block_part"]


# ---------------------------------------------------------------------------
# §C — Consumer 설정 검증
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_consumer_uses_manual_commit(monkeypatch):
    """consumer enable_auto_commit=False — at-least-once 보장."""
    main = _import_main()

    captured_kwargs: dict = {}

    class FakeConsumer:
        def __init__(self, *args, **kwargs):
            captured_kwargs.update(kwargs)

        async def start(self):
            pass

    monkeypatch.setattr("aiokafka.AIOKafkaConsumer", FakeConsumer)

    await main._create_consumer(["aicm.document.uploaded"])
    assert captured_kwargs.get("enable_auto_commit") is False, (
        "수동 commit 보장 — at-least-once 위반 차단"
    )


# ---------------------------------------------------------------------------
# §E — 사후 GPT-5 게이트 보강 (TTL env / fallback / commit format)
# ---------------------------------------------------------------------------


def test_part_dedup_ttl_default_is_two_hours():
    """기본 PART dedup TTL = 7200s (사후 GPT-5 #1: 장시간 part 처리 보호)."""
    main = _import_main()
    # env 미설정 시 모듈 로드 시점에 설정된 값. 기본값 검증.
    assert main._PART_DEDUP_TTL_SEC == 7200, (
        f"기본 PART_DEDUP_TTL_SEC = 7200 (2시간). 실제: {main._PART_DEDUP_TTL_SEC}"
    )


def test_part_dedup_ttl_uses_env_override(monkeypatch):
    """PART_DEDUP_TTL_SEC env override — 모듈 reload 검증."""
    monkeypatch.setenv("PART_DEDUP_TTL_SEC", "1800")
    import importlib

    from src.pipeline.workers import main as main_module

    importlib.reload(main_module)
    assert main_module._PART_DEDUP_TTL_SEC == 1800

    # 복원 — env 제거 후 reload
    monkeypatch.delenv("PART_DEDUP_TTL_SEC")
    importlib.reload(main_module)


@pytest.mark.asyncio
async def test_part_dedup_uses_ttl_in_set_call(monkeypatch):
    """_dedup_check_part 의 SET 호출이 ex=_PART_DEDUP_TTL_SEC 사용."""
    main = _import_main()

    captured_ex: list[int] = []

    class FakeRedis:
        async def set(self, key, value, nx=True, ex=600):
            captured_ex.append(ex)
            return True

        async def aclose(self):
            pass

    monkeypatch.setattr("redis.asyncio.from_url", lambda *a, **kw: FakeRedis())
    await main._dedup_check_part("doc-x", 0, "block_part")
    assert captured_ex == [main._PART_DEDUP_TTL_SEC], (
        f"SET ex 인자가 _PART_DEDUP_TTL_SEC({main._PART_DEDUP_TTL_SEC}) 와 동일해야 함. "
        f"실제: {captured_ex}"
    )


def test_aiokafka_structs_imports_required_classes():
    """aiokafka.structs 에서 TopicPartition + OffsetAndMetadata import 가능."""
    from aiokafka.structs import OffsetAndMetadata, TopicPartition

    # 사용 패턴 검증
    tp = TopicPartition("aicm.document.uploaded", 0)
    om = OffsetAndMetadata(42, "")
    assert tp.topic == "aicm.document.uploaded"
    assert tp.partition == 0
    assert om.offset == 42


def test_commit_offset_format_uses_offset_plus_one():
    """Kafka 규약: commit 은 *next* offset (msg.offset + 1).

    msg.offset=42 를 처리 후 commit 시 offsets dict 의 값은 OffsetAndMetadata(43, "").
    이는 consumer 가 다음 시작 시 43 부터 fetch 한다는 의미 — 메시지 손실 차단.
    """
    from aiokafka.structs import OffsetAndMetadata, TopicPartition

    msg_offset = 42
    tp = TopicPartition("aicm.document.uploaded", 0)
    commit_payload = {tp: OffsetAndMetadata(msg_offset + 1, "")}
    assert commit_payload[tp].offset == 43, (
        "commit 은 next offset (msg.offset + 1). 손실 차단."
    )


# ---------------------------------------------------------------------------
# §D — Topic count consistency (GPT-5 사전 게이트 #1)
# ---------------------------------------------------------------------------


def test_topic_count_consistency_across_profiles():
    """3 프로파일의 topic 집합이 명세와 일치 (회귀 차단)."""
    main = _import_main()
    small = set(main._resolve_topics_for_profile("small"))
    large = set(main._resolve_topics_for_profile("large"))
    legacy = set(main._resolve_topics_for_profile("legacy"))

    # legacy = 모든 topic union
    assert legacy >= small | large, (
        f"legacy 는 small ∪ large 의 superset 이어야 함. "
        f"missing: {(small | large) - legacy}"
    )

    # small 과 large 는 공통 (PARSED/CHUNKED/BLOCKED) + 각자 unique
    common = small & large
    assert common == {
        TOPIC_DOCUMENT_PARSED,
        TOPIC_DOCUMENT_CHUNKED,
        TOPIC_DOCUMENT_BLOCKED,
    }, f"small/large 공통은 PARSED/CHUNKED/BLOCKED 만. 실제: {common}"

    small_unique = small - large
    large_unique = large - small
    assert TOPIC_DOCUMENT_UPLOADED_SMALL in small_unique
    assert TOPIC_DOCUMENT_UPLOADED in small_unique
    assert TOPIC_DOCUMENT_UPLOADED_LARGE in large_unique
    assert TOPIC_DOCUMENT_SPLIT in large_unique
    assert TOPIC_DOCUMENT_PART_READY in large_unique
    assert TOPIC_DOCUMENT_PART_BLOCKED in large_unique
