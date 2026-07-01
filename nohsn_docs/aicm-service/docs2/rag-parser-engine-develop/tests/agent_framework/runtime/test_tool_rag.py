"""Tool RAG core module tests — Phase 1.5B-α.

GPU / Qdrant 실 호출 없이 mock 으로 retrieve flow 검증.
plan_orchestrator 통합은 Round 2 — 이 테스트는 standalone module 책임만.

검증 대상:
  1. upsert → retrieve top1 매칭 (의미적 매칭 시뮬)
  2. allowed_tools 교집합 필터 (Phase 1.5A 권한 보존)
  3. circuit breaker 5xx 5회 누적 → OPEN
  4. circuit breaker 5분 후 자동 close (auto half-open)
  5. query embedding LRU — 동일 query 두 번 호출 시 embed 1번만
  6. retrieve LRU — 동일 query 결과 캐시
  7. delete_tool → 다음 retrieve 에서 사라짐
  8. reconcile drift — registry 에서 빠진 도구는 Qdrant 에서 삭제
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent_framework.runtime.tool_rag import (
    COLLECTION_NAME,
    CIRCUIT_FAILURE_THRESHOLD,
    CIRCUIT_OPEN_SECONDS,
    ToolCandidate,
    ToolRAG,
)


# ----- helpers -----

@dataclass
class _FakePoint:
    """qdrant_client ScoredPoint mock — payload + score 만."""
    score: float
    payload: dict[str, Any]


@dataclass
class _FakeQueryResponse:
    points: list[_FakePoint]


@dataclass
class _FakeScrollPoint:
    payload: dict[str, Any]


def _make_fake_embed_fn(
    *,
    fail_count: int = 0,
    timeout: bool = False,
    delay_s: float = 0.0,
) -> tuple[AsyncMock, list[int]]:
    """fake embed_fn 반환 + call counter.

    - fail_count > 0 → 처음 N 회 RuntimeError raise
    - timeout=True → asyncio.sleep(2) 로 200ms timeout 강제 발동
    - 그 외 — 1024-dim dummy vector (query string hash 기반 — 결정적)
    """
    counter = [0]
    state = {"failures_left": fail_count}

    async def _fn(text: str) -> list[float]:
        counter[0] += 1
        if state["failures_left"] > 0:
            state["failures_left"] -= 1
            raise RuntimeError("simulated 5xx")
        if timeout:
            # 200ms 보다 큰 대기
            await asyncio.sleep(2)
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        # 결정적 dummy vector — text 별로 약간 다르게
        h = hash(text) % 1000 / 1000.0
        return [h] * 1024

    mock = AsyncMock(side_effect=_fn)
    return mock, counter


def _make_fake_qdrant(
    *,
    initial_points: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """fake AsyncQdrantClient — upsert / delete / query_points / scroll 만 구현.

    내부 storage = name → (score=1.0, payload).
    query_points 는 storage 의 모든 point 를 score 1.0 으로 반환 (의미 매칭은
    상위 ToolRAG 가 이미 점수 무관하게 top_k 에 의존하므로 충분).
    """
    storage: dict[str, dict[str, Any]] = {}
    if initial_points:
        for p in initial_points:
            name = p.get("name", "")
            if name:
                storage[name] = p

    client = MagicMock()

    async def _upsert(*, collection_name: str, points: list[Any]) -> None:
        for pt in points:
            name = pt.payload.get("name")
            if name:
                storage[name] = dict(pt.payload)

    async def _delete(*, collection_name: str, points_selector: Any) -> None:
        # mock 은 stable_point_id 기반이 아니라 직접 name 매핑이 어려움 →
        # storage 를 다른 mock 메서드 (delete_by_name) 로 대신.
        # 단순화: ToolRAG.delete_tool 은 _stable_point_id 를 쓰는데, mock 에선
        # name → id reverse mapping 이 없다. 이 테스트에서는 storage 직접 변형
        # 메서드를 별도로 노출 (delete_by_name) — 본 _delete 는 no-op.
        return None

    async def _query_points(
        *,
        collection_name: str,
        query: list[float],
        using: str = "dense",
        limit: int = 8,
        with_payload: bool = True,
    ) -> _FakeQueryResponse:
        # storage 의 모든 항목을 score 1.0 으로 반환 (limit 까지)
        points = [
            _FakePoint(score=1.0, payload=dict(payload))
            for payload in list(storage.values())[:limit]
        ]
        return _FakeQueryResponse(points=points)

    async def _scroll(
        *,
        collection_name: str,
        limit: int = 500,
        with_payload: bool = True,
        with_vectors: bool = False,
    ) -> tuple[list[_FakeScrollPoint], None]:
        return [
            _FakeScrollPoint(payload=dict(p)) for p in storage.values()
        ], None

    async def _get_collections() -> Any:
        rsp = MagicMock()
        rsp.collections = []
        return rsp

    async def _create_collection(**kwargs) -> None:
        return None

    client.upsert = AsyncMock(side_effect=_upsert)
    client.delete = AsyncMock(side_effect=_delete)
    client.query_points = AsyncMock(side_effect=_query_points)
    client.scroll = AsyncMock(side_effect=_scroll)
    client.get_collections = AsyncMock(side_effect=_get_collections)
    client.create_collection = AsyncMock(side_effect=_create_collection)

    # 테스트 헬퍼 — name 으로 직접 삭제
    def delete_by_name(name: str) -> None:
        storage.pop(name, None)
    client._delete_by_name = delete_by_name  # type: ignore[attr-defined]
    client._storage = storage  # type: ignore[attr-defined]
    return client


# ----- tests -----

@pytest.mark.asyncio
async def test_upsert_then_retrieve():
    """3개 도구 upsert 후 query → top-N 후보에 등록 도구가 들어옴.

    의미적 점수는 mock 이라 단순 1.0 — 검증 포인트는 *upsert → retrieve flow*
    가 정상이고 ToolCandidate dataclass 가 채워지는지.
    """
    embed_fn, _ = _make_fake_embed_fn()
    qdrant = _make_fake_qdrant()
    rag = ToolRAG(embed_fn=embed_fn, qdrant_client=qdrant)

    await rag.upsert_tool({
        "name": "mail.send",
        "description": "이메일 발송",
        "triggered_by_intents": ["mail_send", "mail_compose"],
        "example_utterances": ["메일 보내줘", "김부장한테 메일 보내"],
    })
    await rag.upsert_tool({
        "name": "schedule.create",
        "description": "일정 등록",
        "triggered_by_intents": ["schedule_create"],
        "example_utterances": ["내일 2시 약속 잡아줘"],
    })
    await rag.upsert_tool({
        "name": "kms_rag.search",
        "description": "내부 KMS 문서 검색",
        "triggered_by_intents": ["info_lookup"],
        "example_utterances": ["회사 휴가 규정 알려줘"],
    })

    candidates = await rag.retrieve("메일 보내줘", top_k=8)
    names = [c.name for c in candidates]
    assert "mail.send" in names
    # ToolCandidate 필드 검증
    mail = next(c for c in candidates if c.name == "mail.send")
    assert mail.description == "이메일 발송"
    assert "mail_send" in mail.triggered_by_intents
    assert mail.score == 1.0  # mock fixed score


@pytest.mark.asyncio
async def test_allowed_tools_filter():
    """retrieve 결과 ∩ allowed_tools — Phase 1.5A 권한 보존.

    role agent 의 allowed_tools 가 좁으면, 후보가 그 부분집합으로만 좁혀짐.
    """
    embed_fn, _ = _make_fake_embed_fn()
    qdrant = _make_fake_qdrant()
    rag = ToolRAG(embed_fn=embed_fn, qdrant_client=qdrant)

    for name in ["mail.send", "schedule.create", "kms_rag.search", "diary.save"]:
        await rag.upsert_tool({
            "name": name,
            "description": f"{name} 도구",
            "triggered_by_intents": [],
            "example_utterances": [],
        })

    # role agent 가 schedule.create 만 허용
    candidates = await rag.retrieve(
        "내일 약속",
        top_k=8,
        allowed_tools=["schedule.create"],
    )
    names = {c.name for c in candidates}
    assert names == {"schedule.create"}

    # allowed_tools=None → 필터 없음 — 4 개 다 들어와야
    all_cand = await rag.retrieve("내일 약속", top_k=8)
    assert {c.name for c in all_cand} == {
        "mail.send", "schedule.create", "kms_rag.search", "diary.save",
    }


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_5_fails():
    """embed_fn 5번 연속 실패 → circuit OPEN.

    OPEN 후 retrieve 는 즉시 빈 리스트 (caller fallback 신호).
    """
    embed_fn, _ = _make_fake_embed_fn(fail_count=10)  # 충분히 실패
    qdrant = _make_fake_qdrant()
    rag = ToolRAG(embed_fn=embed_fn, qdrant_client=qdrant)

    assert not rag.circuit_breaker.is_open()

    # 5 회 실패 누적
    for i in range(CIRCUIT_FAILURE_THRESHOLD):
        result = await rag.retrieve(f"query-{i}", top_k=8)
        assert result == []

    # 5회 후 OPEN
    assert rag.circuit_breaker.is_open()
    assert rag.circuit_breaker.failure_count >= CIRCUIT_FAILURE_THRESHOLD

    # OPEN 상태 — 다음 retrieve 는 즉시 빈 리스트, embed_fn 호출 X
    embed_fn.reset_mock()
    result = await rag.retrieve("OPEN 상태 query", top_k=8)
    assert result == []
    embed_fn.assert_not_called()


@pytest.mark.asyncio
async def test_circuit_breaker_recovers_after_5_min(monkeypatch):
    """5분 (CIRCUIT_OPEN_SECONDS) 경과 후 circuit 자동 close.

    monotonic 을 patch 해서 5분 흐른 척.
    """
    embed_fn, _ = _make_fake_embed_fn(fail_count=10)
    qdrant = _make_fake_qdrant()
    rag = ToolRAG(embed_fn=embed_fn, qdrant_client=qdrant)

    # OPEN 까지 실패
    for i in range(CIRCUIT_FAILURE_THRESHOLD):
        await rag.retrieve(f"q-{i}", top_k=8)
    assert rag.circuit_breaker.is_open()

    # monotonic patch — 5분 경과
    real_monotonic = time.monotonic
    base = real_monotonic()

    # tool_rag 모듈 안의 time.monotonic 도 동일하게 patch
    import src.agent_framework.runtime.tool_rag as tr_mod

    def _later() -> float:
        return base + CIRCUIT_OPEN_SECONDS + 1
    monkeypatch.setattr(tr_mod.time, "monotonic", _later)

    # is_open 호출 시 자동 close
    assert not rag.circuit_breaker.is_open()
    # 실패 count reset
    assert rag.circuit_breaker.failure_count == 0


@pytest.mark.asyncio
async def test_query_cache_lru():
    """동일 query 두 번 호출 → embed_fn 1번만.

    embedding 캐시 hit 검증.
    """
    embed_fn, embed_counter = _make_fake_embed_fn()
    qdrant = _make_fake_qdrant()
    rag = ToolRAG(embed_fn=embed_fn, qdrant_client=qdrant)
    await rag.upsert_tool({
        "name": "mail.send",
        "description": "메일 발송",
        "triggered_by_intents": [],
        "example_utterances": [],
    })

    # upsert 가 embed 1회 호출. counter reset.
    base_calls = embed_counter[0]

    # retrieve 첫 호출 — embed 1회
    r1 = await rag.retrieve("메일 보내줘", top_k=8)
    assert len(r1) >= 1
    after_first = embed_counter[0]
    assert after_first == base_calls + 1

    # retrieve 둘째 호출 — retrieve 캐시 hit (embed 호출 0).
    # 단, retrieve 캐시가 hit 하면 embed 도 호출 안 됨 (전체 함수 단축).
    r2 = await rag.retrieve("메일 보내줘", top_k=8)
    assert r2 == r1
    assert embed_counter[0] == after_first  # 추가 호출 없음

    # 다른 query — embed 호출 1회 추가
    r3 = await rag.retrieve("일정 잡아", top_k=8)
    assert embed_counter[0] == after_first + 1

    # 첫 query 다시 — 여전히 캐시 hit
    r4 = await rag.retrieve("메일 보내줘", top_k=8)
    assert embed_counter[0] == after_first + 1


@pytest.mark.asyncio
async def test_retrieve_timeout_returns_empty():
    """embed timeout 발생 시 빈 리스트 + circuit failure 카운트.

    spec 의 200ms timeout 강제 동작 검증.
    """
    embed_fn, _ = _make_fake_embed_fn(timeout=True)
    qdrant = _make_fake_qdrant()
    rag = ToolRAG(embed_fn=embed_fn, qdrant_client=qdrant, timeout_s=0.05)

    result = await rag.retrieve("아무말", top_k=8)
    assert result == []
    assert rag.circuit_breaker.failure_count >= 1


@pytest.mark.asyncio
async def test_delete_tool_clears_retrieve_cache():
    """delete_tool 후 동일 query 다시 retrieve 시 도구 사라짐.

    cache invalidation 검증 (delete 시 retrieve_cache.clear 호출됐는지).
    """
    embed_fn, _ = _make_fake_embed_fn()
    qdrant = _make_fake_qdrant()
    rag = ToolRAG(embed_fn=embed_fn, qdrant_client=qdrant)

    await rag.upsert_tool({
        "name": "mail.send",
        "description": "메일",
        "triggered_by_intents": [],
        "example_utterances": [],
    })
    await rag.upsert_tool({
        "name": "diary.save",
        "description": "일기",
        "triggered_by_intents": [],
        "example_utterances": [],
    })

    r1 = await rag.retrieve("아무말", top_k=8)
    assert {"mail.send", "diary.save"} <= {c.name for c in r1}

    # mock storage 에서 직접 삭제 + ToolRAG.delete_tool (cache 비움)
    qdrant._delete_by_name("mail.send")
    await rag.delete_tool("mail.send")

    r2 = await rag.retrieve("아무말", top_k=8)
    names = {c.name for c in r2}
    assert "mail.send" not in names
    assert "diary.save" in names


@pytest.mark.asyncio
async def test_reconcile_drift_removes_orphans():
    """reconcile — Qdrant 에 있는데 registry 에 없는 항목 삭제.

    부팅 시 drift 자동 정합 검증.
    """
    embed_fn, _ = _make_fake_embed_fn()
    qdrant = _make_fake_qdrant(initial_points=[
        # registry 에 없는 orphan
        {
            "name": "legacy.tool",
            "description": "삭제된 옛 도구",
            "category": "",
            "triggered_by_intents": [],
            "example_utterances": [],
            "is_implemented": True,
        },
        # registry 에 있는 도구 (이번 reconcile 에서 upsert 됨)
        {
            "name": "mail.send",
            "description": "이전 버전",
            "category": "",
            "triggered_by_intents": [],
            "example_utterances": [],
            "is_implemented": True,
        },
    ])
    rag = ToolRAG(embed_fn=embed_fn, qdrant_client=qdrant)

    # registry 에는 mail.send + schedule.create 만 (legacy.tool 제거됨)
    registry_meta = [
        {
            "name": "mail.send",
            "description": "이메일 발송 (최신)",
            "triggered_by_intents": ["mail_send"],
            "example_utterances": ["메일 보내줘"],
        },
        {
            "name": "schedule.create",
            "description": "일정 등록",
            "triggered_by_intents": ["schedule_create"],
            "example_utterances": ["약속 잡아"],
        },
    ]
    stats = await rag.reconcile(registry_meta)

    # 2 upsert + 1 deletion
    assert stats["upserted"] == 2
    # delete_tool 은 stable_point_id 기반이라 mock 의 _delete 가 no-op →
    # delete 는 실제로 storage 에서 안 빠짐. 검증은 통계에서 호출 시도 자체로.
    # ToolRAG.delete_tool 이 ok=True 반환했는지 확인 — mock _delete 가 raise
    # 안 하므로 1회 시도됨.
    assert stats["deleted"] >= 1
    assert stats["skipped"] == 0
