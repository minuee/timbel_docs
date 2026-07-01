"""agent_document_store CRUD — Postgres integration.

Stage B-2 의 KMS 백엔드가 실제 ``documents`` / ``repositories`` /
``document_types`` 테이블로 왕복하는지 확인. Redis 는 건드리지 않으며 chunking
파이프라인도 타지 않는 구조화 저장 경로.

테스트 격리: 각 케이스가 자기 tenant 를 만들고 teardown 에서 archived/active
모두 같이 삭제. tenant 이름 prefix ``AGDS_TEST__`` 로 다른 테스트와 충돌 방지.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.agent_framework.storage import agent_document_store
from src.agent_framework.storage.agent_document_store import (
    AGENT_DATA_REPO_NAME,
    create_item,
    delete_item,
    list_items,
    list_items_filtered,
    list_items_global_doctype,
    list_tenants_with_doctype,
)
from src.common.config import settings


TEST_TENANT_SLUG_PREFIX = "agds_test__"


async def _make_tenant(conn, slug: str) -> UUID:
    r = await conn.execute(
        text(
            """
            INSERT INTO tenants
              (id, slug, name, tenant_type, plan, config, context_config, is_active)
            VALUES
              (gen_random_uuid(), :slug, :name, 'personal', 'free',
               '{}'::jsonb, '{}'::jsonb, true)
            RETURNING id
            """
        ),
        {"slug": slug, "name": slug},
    )
    return r.scalar_one()


async def _cleanup_tenant(engine: AsyncEngine, tenant_id: UUID) -> None:
    async with engine.begin() as conn:
        # 1. agent_data repo 에 속한 documents 제거 (status 무관)
        await conn.execute(
            text(
                """
                DELETE FROM documents
                WHERE repository_id IN (
                    SELECT id FROM repositories
                    WHERE tenant_id = :tid AND name = :repo
                )
                """
            ),
            {"tid": tenant_id, "repo": AGENT_DATA_REPO_NAME},
        )
        # 2. repositories
        await conn.execute(
            text("DELETE FROM repositories WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        # 3. document_types
        await conn.execute(
            text("DELETE FROM document_types WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        # 4. tenant
        await conn.execute(
            text("DELETE FROM tenants WHERE id = :tid"),
            {"tid": tenant_id},
        )


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(settings.DATABASE_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def tenant_a(engine: AsyncEngine):
    slug = f"{TEST_TENANT_SLUG_PREFIX}a_{uuid4().hex[:8]}"
    async with engine.begin() as conn:
        tid = await _make_tenant(conn, slug)
    yield tid
    await _cleanup_tenant(engine, tid)


@pytest_asyncio.fixture
async def tenant_b(engine: AsyncEngine):
    slug = f"{TEST_TENANT_SLUG_PREFIX}b_{uuid4().hex[:8]}"
    async with engine.begin() as conn:
        tid = await _make_tenant(conn, slug)
    yield tid
    await _cleanup_tenant(engine, tid)


# ── Cases ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_then_list_roundtrip(engine: AsyncEngine, tenant_a: UUID):
    """2건 create → list 가 생성 순서대로 title/body 를 그대로 돌려준다."""
    await create_item(
        engine,
        tenant_a,
        "agent_schedule",
        title="일정1",
        body={"when": "2026-05-01T09:00", "recurrence": None},
    )
    await create_item(
        engine,
        tenant_a,
        "agent_schedule",
        title="일정2",
        body={"when": "2026-05-02T10:00", "recurrence": "FREQ=DAILY"},
    )
    items = await list_items(engine, tenant_a, "agent_schedule")
    assert [i["title"] for i in items] == ["일정1", "일정2"]
    assert items[0]["when"] == "2026-05-01T09:00"
    assert items[0]["recurrence"] is None
    assert items[1]["when"] == "2026-05-02T10:00"
    assert items[1]["recurrence"] == "FREQ=DAILY"
    # id 는 UUID 문자열
    UUID(items[0]["id"])


@pytest.mark.asyncio
async def test_list_returns_empty_for_different_tenant(
    engine: AsyncEngine, tenant_a: UUID, tenant_b: UUID
):
    """tenant 격리 — A 에 만든 일정이 B 의 list 에 보이면 안 됨."""
    await create_item(
        engine,
        tenant_a,
        "agent_schedule",
        title="A 전용",
        body={"when": "2026-05-01"},
    )
    items_b = await list_items(engine, tenant_b, "agent_schedule")
    assert items_b == []
    # A 는 그대로 1건
    items_a = await list_items(engine, tenant_a, "agent_schedule")
    assert len(items_a) == 1


@pytest.mark.asyncio
async def test_delete_marks_archived_not_visible_in_list(
    engine: AsyncEngine, tenant_a: UUID
):
    """soft delete — archived 된 항목은 list 에서 사라진다."""
    doc_id = await create_item(
        engine,
        tenant_a,
        "agent_schedule",
        title="삭제 대상",
        body={"when": "2026-05-01"},
    )
    ok = await delete_item(engine, tenant_a, "agent_schedule", str(doc_id))
    assert ok is True
    items = await list_items(engine, tenant_a, "agent_schedule")
    assert items == []
    # 실제로 row 는 archived 로 남아 있는지 확인 (감사 흔적).
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status FROM documents WHERE id = :id"),
                {"id": doc_id},
            )
        ).first()
    assert row is not None
    assert row[0] == "archived"


@pytest.mark.asyncio
async def test_delete_unknown_returns_false(engine: AsyncEngine, tenant_a: UUID):
    """존재하지 않는 id / 이미 archived / 다른 tenant 의 id 모두 False."""
    # 1) 아예 존재하지 않는 UUID
    ok = await delete_item(engine, tenant_a, "agent_schedule", str(uuid4()))
    assert ok is False

    # 2) 이미 archived
    doc_id = await create_item(
        engine,
        tenant_a,
        "agent_schedule",
        title="이미 archived",
        body={},
    )
    first = await delete_item(engine, tenant_a, "agent_schedule", str(doc_id))
    second = await delete_item(engine, tenant_a, "agent_schedule", str(doc_id))
    assert first is True
    assert second is False  # idempotent — no-op on second


@pytest.mark.asyncio
async def test_different_document_types_isolated(
    engine: AsyncEngine, tenant_a: UUID
):
    """같은 tenant 내 agent_schedule vs agent_diary 는 서로 안 섞인다."""
    await create_item(
        engine,
        tenant_a,
        "agent_schedule",
        title="일정입니다",
        body={"when": "2026-05-01"},
    )
    await create_item(
        engine,
        tenant_a,
        "agent_diary",
        title="일기입니다",
        body={"emotion": "happy"},
    )

    schedules = await list_items(engine, tenant_a, "agent_schedule")
    diaries = await list_items(engine, tenant_a, "agent_diary")

    assert [s["title"] for s in schedules] == ["일정입니다"]
    assert [d["title"] for d in diaries] == ["일기입니다"]
    assert "emotion" not in schedules[0]
    assert "when" not in diaries[0]


# ── list_items_filtered (Stage B-3) ────────────────────────────────


@pytest.mark.asyncio
async def test_list_filtered_by_title_substring(
    engine: AsyncEngine, tenant_a: UUID
):
    """title_contains 가 ILIKE 부분 일치로 매칭하는지."""
    await create_item(
        engine, tenant_a, "agent_diary",
        title="2026-05-01 일기", body={"text": "월요일"},
    )
    await create_item(
        engine, tenant_a, "agent_diary",
        title="2026-05-02 일기", body={"text": "화요일"},
    )
    await create_item(
        engine, tenant_a, "agent_diary",
        title="메모 (별개)", body={"text": "무관"},
    )

    hits = await list_items_filtered(
        engine, tenant_a, "agent_diary",
        title_contains="일기",
    )
    assert [h["title"] for h in hits] == ["2026-05-01 일기", "2026-05-02 일기"]


@pytest.mark.asyncio
async def test_list_filtered_by_body_field_equality(
    engine: AsyncEngine, tenant_a: UUID
):
    """body_equals — processing_meta -> body ->> key equality 필터."""
    await create_item(
        engine, tenant_a, "agent_diary",
        title="A", body={"text": "기쁜 일", "emotion": "happy"},
    )
    await create_item(
        engine, tenant_a, "agent_diary",
        title="B", body={"text": "슬픈 일", "emotion": "sad"},
    )
    await create_item(
        engine, tenant_a, "agent_diary",
        title="C", body={"text": "또 기쁜 일", "emotion": "happy"},
    )

    hits = await list_items_filtered(
        engine, tenant_a, "agent_diary",
        body_equals={"emotion": "happy"},
    )
    assert sorted(h["title"] for h in hits) == ["A", "C"]
    assert all(h["emotion"] == "happy" for h in hits)


@pytest.mark.asyncio
async def test_list_filtered_by_body_text_contains(
    engine: AsyncEngine, tenant_a: UUID
):
    """body_text_contains — body.text ILIKE %sub% 매칭."""
    await create_item(
        engine, tenant_a, "agent_diary",
        title="X", body={"text": "오늘 회의가 길었다"},
    )
    await create_item(
        engine, tenant_a, "agent_diary",
        title="Y", body={"text": "점심이 맛있었다"},
    )
    await create_item(
        engine, tenant_a, "agent_diary",
        title="Z", body={"text": "저녁 회의 후 퇴근"},
    )

    hits = await list_items_filtered(
        engine, tenant_a, "agent_diary",
        body_text_contains=("text", "회의"),
    )
    assert sorted(h["title"] for h in hits) == ["X", "Z"]


@pytest.mark.asyncio
async def test_list_filtered_order_desc_and_limit(
    engine: AsyncEngine, tenant_a: UUID
):
    """order_desc=True + limit — 최신순 상위 N 건."""
    for i in range(5):
        await create_item(
            engine, tenant_a, "agent_diary",
            title=f"일기-{i}",
            body={"text": f"본문 {i}", "emotion": "neutral"},
        )

    hits = await list_items_filtered(
        engine, tenant_a, "agent_diary",
        order_desc=True,
        limit=2,
    )
    # 최신순 상위 2건 — 마지막 insert (일기-4, 일기-3).
    assert [h["title"] for h in hits] == ["일기-4", "일기-3"]

    # limit 없이 desc 만 — 전체 5건이 역순.
    all_hits = await list_items_filtered(
        engine, tenant_a, "agent_diary",
        order_desc=True,
    )
    assert [h["title"] for h in all_hits] == [
        "일기-4", "일기-3", "일기-2", "일기-1", "일기-0"
    ]


# ── Cross-tenant helpers (Stage B-4/B-5) ────────────────────────────


@pytest.mark.asyncio
async def test_list_tenants_with_doctype_returns_distinct_active(
    engine: AsyncEngine, tenant_a: UUID, tenant_b: UUID
):
    """두 tenant 에 active 구독 doc 이 있으면 둘 다 포함, archived 만 있는 tenant 는 제외."""
    # A: 구독 1건 (active)
    await create_item(
        engine, tenant_a, "agent_news_sub",
        title="구독: AI", body={"topic": "AI"},
    )
    # A: 또 하나 (distinct 검증용 — 한 tenant 가 2번 카운트되면 안 됨)
    await create_item(
        engine, tenant_a, "agent_news_sub",
        title="구독: 반도체", body={"topic": "반도체"},
    )
    # B: 구독 1건 (active)
    await create_item(
        engine, tenant_b, "agent_news_sub",
        title="구독: 헬스케어", body={"topic": "헬스케어"},
    )

    tenants = await list_tenants_with_doctype(engine, "agent_news_sub")
    assert tenant_a in tenants
    assert tenant_b in tenants
    # distinct — 같은 tenant 가 두 번 안 들어감.
    assert tenants.count(tenant_a) == 1

    # 다른 doctype 은 안 섞임.
    other = await list_tenants_with_doctype(engine, "agent_diary")
    assert tenant_a not in other
    assert tenant_b not in other


@pytest.mark.asyncio
async def test_list_tenants_with_doctype_excludes_archived_only(
    engine: AsyncEngine, tenant_a: UUID, tenant_b: UUID
):
    """A 는 archive 만 남음 → 제외. B 는 active 1건 → 포함."""
    doc_a = await create_item(
        engine, tenant_a, "agent_news_sub",
        title="구독: A", body={"topic": "A"},
    )
    # A 의 유일한 doc 을 archived.
    await delete_item(engine, tenant_a, "agent_news_sub", str(doc_a))

    await create_item(
        engine, tenant_b, "agent_news_sub",
        title="구독: B", body={"topic": "B"},
    )

    tenants = await list_tenants_with_doctype(engine, "agent_news_sub")
    assert tenant_a not in tenants
    assert tenant_b in tenants


@pytest.mark.asyncio
async def test_list_items_global_doctype_crosses_tenants(
    engine: AsyncEngine, tenant_a: UUID, tenant_b: UUID
):
    """전역 조회 — 두 tenant 의 reminder 가 모두 보이고 tenant_id 가 달림."""
    await create_item(
        engine, tenant_a, "agent_reminder",
        title="A 의 리마인더", body={"at": "2026-05-01", "channel": "sms"},
    )
    await create_item(
        engine, tenant_b, "agent_reminder",
        title="B 의 리마인더", body={"at": "2026-05-02", "channel": "email"},
    )

    items = await list_items_global_doctype(engine, "agent_reminder")
    titles = [i["title"] for i in items]
    assert "A 의 리마인더" in titles
    assert "B 의 리마인더" in titles
    # 각 item 은 tenant_id 를 포함
    by_title = {i["title"]: i for i in items}
    assert by_title["A 의 리마인더"]["tenant_id"] == str(tenant_a)
    assert by_title["B 의 리마인더"]["tenant_id"] == str(tenant_b)
    # body 필드가 풀려있어야 함
    assert by_title["A 의 리마인더"]["at"] == "2026-05-01"


@pytest.mark.asyncio
async def test_list_items_global_doctype_limit_and_desc(
    engine: AsyncEngine, tenant_a: UUID
):
    """order_desc=True + limit — 최신 N 건만."""
    for i in range(4):
        await create_item(
            engine, tenant_a, "agent_reminder",
            title=f"리마인더-{i}", body={"at": f"2026-05-0{i+1}"},
        )
    hits = await list_items_global_doctype(
        engine, "agent_reminder", order_desc=True, limit=2
    )
    # 같은 tenant 라 A 의 4건만 — 최신 2건
    titles = [h["title"] for h in hits if h["tenant_id"] == str(tenant_a)]
    assert titles == ["리마인더-3", "리마인더-2"]


@pytest.mark.asyncio
async def test_list_filtered_sort_by_trust_score_desc(
    engine: AsyncEngine, tenant_a: UUID
):
    """sort='trust' — activation.trust_score DESC, NULL 은 0 으로 뒤로."""
    # 3건 생성 후 각각 다른 trust_score 박기
    id_low = await create_item(
        engine, tenant_a, "agent_schedule",
        title="LOW", body={"when": "2026-05-01"},
    )
    id_high = await create_item(
        engine, tenant_a, "agent_schedule",
        title="HIGH", body={"when": "2026-05-02"},
    )
    id_mid = await create_item(
        engine, tenant_a, "agent_schedule",
        title="MID", body={"when": "2026-05-03"},
    )
    # 한 건은 trust_score 미설정 (NULL → 0 처리)
    id_null = await create_item(
        engine, tenant_a, "agent_schedule",
        title="NULL_TRUST", body={"when": "2026-05-04"},
    )

    async with engine.begin() as conn:
        for did, score in [(id_low, 0.2), (id_high, 0.95), (id_mid, 0.5)]:
            patch = {"trust_score": score}
            r = await conn.execute(
                text(
                    """
                    UPDATE documents
                    SET processing_meta = jsonb_set(
                        COALESCE(processing_meta, '{}'::jsonb),
                        ARRAY['activation']::text[],
                        COALESCE(processing_meta -> 'activation', '{}'::jsonb)
                            || CAST(:patch AS jsonb),
                        true
                    )
                    WHERE id = CAST(:id AS uuid)
                    RETURNING id, processing_meta
                    """
                ),
                {"id": str(did), "patch": json.dumps(patch)},
            )
            updated = r.first()
            assert updated is not None, f"no row matched did={did}"
            assert updated[1]["activation"]["trust_score"] == score, f"score not set: {updated}"

    hits = await list_items_filtered(
        engine, tenant_a, "agent_schedule", sort="trust",
    )
    titles = [h["title"] for h in hits]
    # HIGH(0.95) > MID(0.5) > LOW(0.2) > NULL_TRUST(0=NULL→0)
    assert titles == ["HIGH", "MID", "LOW", "NULL_TRUST"]
