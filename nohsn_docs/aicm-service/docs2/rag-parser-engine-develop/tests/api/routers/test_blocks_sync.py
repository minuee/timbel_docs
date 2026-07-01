"""PUT /blocks/{id} — ES + Qdrant payload 동기 단위 테스트."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_sync_block_to_indexes_calls_both():
    """_sync_block_to_indexes 가 _es_update / _qdrant_set_payload 를 모두 호출."""
    from src.api.routers.blocks import _sync_block_to_indexes

    with (
        patch("src.api.routers.blocks._es_update", new_callable=AsyncMock) as es_mock,
        patch(
            "src.api.routers.blocks._qdrant_set_payload", new_callable=AsyncMock
        ) as qd_mock,
    ):
        await _sync_block_to_indexes(
            block_id="bid-1",
            collection="aicm_test_blocks",
            payload={"content": "수정", "block_type": "table"},
        )
        es_mock.assert_called_once()
        qd_mock.assert_called_once()


@pytest.mark.asyncio
async def test_sync_block_to_indexes_passes_correct_payload():
    """_sync_block_to_indexes 가 올바른 payload 로 두 함수를 호출."""
    from src.api.routers.blocks import _sync_block_to_indexes

    payload = {"content": "변경된 내용"}

    with (
        patch("src.api.routers.blocks._es_update", new_callable=AsyncMock) as es_mock,
        patch(
            "src.api.routers.blocks._qdrant_set_payload", new_callable=AsyncMock
        ) as qd_mock,
    ):
        await _sync_block_to_indexes(
            block_id="bid-2",
            collection="aicm_myorg_blocks",
            payload=payload,
        )
        # ES 는 es_index (build_block_es_index_name 결과), block_id, payload 순
        _, es_call_kwargs = es_mock.call_args
        # positional args
        es_args = es_mock.call_args.args
        assert "bid-2" in es_args
        assert payload in es_args

        qd_args = qd_mock.call_args.args
        assert "aicm_myorg_blocks" in qd_args
        assert "bid-2" in qd_args
        assert payload in qd_args


@pytest.mark.asyncio
async def test_es_update_handles_exception_gracefully():
    """_es_update 는 ES 예외 발생 시 raise 하지 않고 경고 로그만."""
    from src.api.routers.blocks import _es_update

    with patch(
        "src.api.routers.blocks.logger"
    ) as mock_logger, patch(
        "elasticsearch.AsyncElasticsearch"
    ) as mock_es_cls:
        mock_es_cls.return_value.update = AsyncMock(side_effect=Exception("connection error"))
        mock_es_cls.return_value.close = AsyncMock()
        # should not raise
        await _es_update("test_index", "bid-x", {"content": "test"})
        mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_qdrant_set_payload_handles_exception_gracefully():
    """_qdrant_set_payload 는 Qdrant 예외 발생 시 raise 하지 않고 경고 로그만.

    QdrantClient 는 함수 내부에서 import 되므로 패키지 레벨이 아닌
    함수 내부 import 경로 'qdrant_client.QdrantClient' 로 패치.
    """
    from unittest.mock import MagicMock
    from src.api.routers.blocks import _qdrant_set_payload

    mock_client = MagicMock()
    mock_client.set_payload.side_effect = Exception("qdrant down")

    with patch("src.api.routers.blocks.logger") as mock_logger, patch(
        "qdrant_client.QdrantClient", return_value=mock_client
    ):
        await _qdrant_set_payload("aicm_test_blocks", "bid-y", {"block_type": "text"})
        mock_logger.warning.assert_called_once()
