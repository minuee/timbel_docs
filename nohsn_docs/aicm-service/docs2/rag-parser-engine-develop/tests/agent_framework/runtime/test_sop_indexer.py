"""SOP 인덱스 빌더 테스트.

Qdrant client / embedding fn / docs loader 모두 mock 으로 우회. chunk
splitting 의 heading-aware 동작 + idempotent point id + collection naming
+ upsert payload shape 검증.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.agent_framework.runtime.sop_indexer import (
    SopChunkPayload,
    _stable_point_id,
    build_index,
    split_markdown_by_heading,
)
from src.agent_framework.tools.kms_sop import build_sop_collection_name


_TENANT_ID = uuid4()
_REPO_A = uuid4()
_DOC_A = uuid4()


# ---- split_markdown_by_heading -----------------------------------------------


def test_split_markdown_basic_h2_h3():
    md = """\
# 미용실 SOP

## rules
- 친근한 톤

## time_policy
- 영업시간 10-20

### 점심
- 12-13 휴무

## escalation_channels
- 원장 직통 02-1234-5678
"""
    chunks = split_markdown_by_heading(md, min_chars=0)  # disable merge
    headings = [(sec, head) for sec, head, _ in chunks]
    assert ("rules", "rules") in headings
    assert ("time_policy", "time_policy") in headings
    assert ("time_policy", "점심") in headings
    assert ("escalation_channels", "escalation_channels") in headings


def test_split_long_section_breaks():
    """target_chars 초과 시 paragraph 단위로 split."""
    body = ("문장입니다. " * 100 + "\n\n") * 5  # 충분히 길게
    md = f"## big\n\n{body}"
    chunks = split_markdown_by_heading(md, target_chars=400, max_chars=600)
    # 같은 heading 으로 여러 chunk.
    big_chunks = [c for c in chunks if c[1] == "big"]
    assert len(big_chunks) >= 2


def test_split_short_chunks_merged():
    """min_chars 미만은 인접 chunk 와 merge."""
    md = """\
## a
짧.

## b
이것도 짧.
"""
    chunks = split_markdown_by_heading(md, min_chars=20)
    # merge 됐으면 1 chunk, 아니면 2.
    assert len(chunks) <= 2


def test_split_empty_input():
    assert split_markdown_by_heading("") == []


def test_split_h1_ignored():
    """H1 (문서 제목) 는 chunk heading 으로 사용 X — 다음 H2 가 anchor."""
    md = "# 제목\n\n## section1\n본문\n"
    chunks = split_markdown_by_heading(md, min_chars=0)
    assert chunks[0][1] == "section1"
    # H1 도 별도 chunk 로 안 만들어짐.
    assert all(c[1] != "제목" for c in chunks)


# ---- stable_point_id --------------------------------------------------------


def test_stable_point_id_idempotent():
    a = _stable_point_id(_DOC_A, 0, "deadbeef" * 8)
    b = _stable_point_id(_DOC_A, 0, "deadbeef" * 8)
    assert a == b


def test_stable_point_id_differs_by_index():
    a = _stable_point_id(_DOC_A, 0, "x")
    b = _stable_point_id(_DOC_A, 1, "x")
    assert a != b


# ---- SopChunkPayload --------------------------------------------------------


def test_payload_to_dict_shape():
    p = SopChunkPayload(
        repo_id=str(_REPO_A),
        document_id=str(_DOC_A),
        chunk_index=3,
        heading="rules",
        text="body",
        section="rules",
    )
    d = p.to_dict()
    assert d["repo_id"] == str(_REPO_A)
    assert d["chunk_index"] == 3
    assert d["heading"] == "rules"
    assert d["text"] == "body"


# ---- build_index ------------------------------------------------------------


def _make_qdrant_mock():
    client = MagicMock()
    client.get_collection = AsyncMock(side_effect=Exception("not found"))
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_build_index_empty_repos():
    """repo_ids 비면 즉시 빈 결과 — Qdrant 호출 X."""
    client = _make_qdrant_mock()
    emb = AsyncMock(return_value=([0.1] * 1024, {}))
    loader = AsyncMock(return_value=[])

    stats = await build_index(
        _TENANT_ID,
        [],
        qdrant_client=client,
        embedding_fn=emb,
        docs_loader=loader,
    )
    assert stats["doc_count"] == 0
    assert stats["chunk_count"] == 0
    client.get_collection.assert_not_called()


@pytest.mark.asyncio
async def test_build_index_creates_collection_and_upserts():
    """document → chunks → embedding → upsert 풀 체인."""
    client = _make_qdrant_mock()
    emb = AsyncMock(return_value=([0.1] * 1024, {}))
    # 충분히 긴 body — min_chars merge 우회. heading 별 chunk 분리 보장.
    body_a = "친근한 톤을 유지합니다. " * 30
    body_b = "원장 직통 02-1234-5678 평일 10-18시 응답. " * 30
    loader = AsyncMock(
        return_value=[
            (
                _DOC_A,
                _REPO_A,
                "미용실 SOP",
                f"## rules\n{body_a}\n\n## escalation\n{body_b}",
            )
        ]
    )

    stats = await build_index(
        _TENANT_ID,
        [_REPO_A],
        qdrant_client=client,
        embedding_fn=emb,
        docs_loader=loader,
    )

    assert stats["doc_count"] == 1
    assert stats["chunk_count"] >= 2  # rules + escalation
    assert stats["upserted"] == stats["chunk_count"]
    # collection 이름 검증
    create_kwargs = client.create_collection.await_args.kwargs
    assert create_kwargs["collection_name"] == build_sop_collection_name(_TENANT_ID)
    # upsert 호출 확인
    upsert_kwargs = client.upsert.await_args.kwargs
    assert upsert_kwargs["collection_name"] == build_sop_collection_name(_TENANT_ID)
    points = upsert_kwargs["points"]
    assert len(points) >= 2
    payload = points[0].payload
    assert payload["repo_id"] == str(_REPO_A)
    assert payload["document_id"] == str(_DOC_A)
    assert "heading" in payload
    assert "text" in payload


@pytest.mark.asyncio
async def test_build_index_collection_exists_no_create():
    """get_collection 성공 시 create 호출 X."""
    client = MagicMock()
    client.get_collection = AsyncMock()  # 성공
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()

    emb = AsyncMock(return_value=([0.1] * 1024, {}))
    loader = AsyncMock(
        return_value=[(_DOC_A, _REPO_A, "t", "## r\n본문")]
    )

    await build_index(
        _TENANT_ID,
        [_REPO_A],
        qdrant_client=client,
        embedding_fn=emb,
        docs_loader=loader,
    )
    client.create_collection.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_index_embed_failure_records_error():
    """embedding 실패 시 errors 누적, 다른 chunk 는 계속."""
    client = _make_qdrant_mock()

    call_count = {"n": 0}

    async def emb(text):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("embed fail")
        return ([0.2] * 1024, {})

    body_a = "본문1입니다. 충분히 긴 텍스트. " * 30
    body_b = "본문2입니다. 다른 내용으로. " * 30
    loader = AsyncMock(
        return_value=[
            (_DOC_A, _REPO_A, "t", f"## a\n{body_a}\n\n## b\n{body_b}"),
        ]
    )
    stats = await build_index(
        _TENANT_ID,
        [_REPO_A],
        qdrant_client=client,
        embedding_fn=emb,
        docs_loader=loader,
    )
    assert any("embed" in e for e in stats["errors"])
    # 1개는 성공해서 upsert 됐어야.
    assert stats["upserted"] == 1


@pytest.mark.asyncio
async def test_build_index_idempotent_point_ids():
    """같은 document + chunk_index + body 면 같은 point id."""
    client = _make_qdrant_mock()
    emb = AsyncMock(return_value=([0.1] * 1024, {}))
    md = "## rules\n같은 본문 내용"
    loader = AsyncMock(return_value=[(_DOC_A, _REPO_A, "t", md)])

    await build_index(
        _TENANT_ID,
        [_REPO_A],
        qdrant_client=client,
        embedding_fn=emb,
        docs_loader=loader,
    )
    first_id = client.upsert.await_args.kwargs["points"][0].id

    client.upsert.reset_mock()
    await build_index(
        _TENANT_ID,
        [_REPO_A],
        qdrant_client=client,
        embedding_fn=emb,
        docs_loader=loader,
    )
    second_id = client.upsert.await_args.kwargs["points"][0].id
    assert first_id == second_id
