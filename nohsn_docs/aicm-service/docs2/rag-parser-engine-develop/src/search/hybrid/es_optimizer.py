"""Elasticsearch 인덱스 최적화."""

from __future__ import annotations

from typing import Any

from elasticsearch import AsyncElasticsearch

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


class ESOptimizer:
    """
    Elasticsearch 인덱스 최적화 관리.

    - 인덱스 템플릿 (샤드/레플리카 설정)
    - Refresh 간격 조정 (벌크 인덱싱 vs 실시간)
    - Force merge (읽기 중심 인덱스)
    - ILM(Index Lifecycle Management) 정책
    """

    # 기본 인덱스 설정
    DEFAULT_NUMBER_OF_SHARDS: int = 1
    DEFAULT_NUMBER_OF_REPLICAS: int = 1
    BULK_REFRESH_INTERVAL: str = "30s"
    REALTIME_REFRESH_INTERVAL: str = "1s"

    # ILM 정책 이름
    ILM_POLICY_NAME: str = "aicm_search_chunks_policy"

    def __init__(self, client: AsyncElasticsearch | None = None) -> None:
        self._client = client

    async def _get_client(self) -> AsyncElasticsearch:
        """지연 초기화된 ES 클라이언트 반환."""
        if self._client is None:
            self._client = AsyncElasticsearch(
                hosts=[settings.ELASTICSEARCH_URL],
            )
        return self._client

    async def create_index_template(
        self,
        template_name: str = "aicm_chunks_template",
        index_patterns: list[str] | None = None,
        number_of_shards: int | None = None,
        number_of_replicas: int | None = None,
    ) -> None:
        """
        최적화된 인덱스 템플릿 생성.

        이 템플릿은 aicm_* 패턴에 매칭되는 모든 인덱스에 자동 적용.

        Args:
            template_name: 템플릿 이름
            index_patterns: 매칭 패턴 (기본 ["aicm_*_chunks"])
            number_of_shards: 샤드 수 (기본 1)
            number_of_replicas: 레플리카 수 (기본 1)
        """
        client = await self._get_client()
        effective_patterns = index_patterns or ["aicm_*_chunks"]
        effective_shards = number_of_shards or self.DEFAULT_NUMBER_OF_SHARDS
        effective_replicas = number_of_replicas or self.DEFAULT_NUMBER_OF_REPLICAS

        template_body: dict[str, Any] = {
            "index_patterns": effective_patterns,
            "template": {
                "settings": {
                    "number_of_shards": effective_shards,
                    "number_of_replicas": effective_replicas,
                    "refresh_interval": self.REALTIME_REFRESH_INTERVAL,
                    "analysis": {
                        "analyzer": {
                            "korean": {
                                "type": "custom",
                                "tokenizer": "nori_tokenizer",
                                "filter": ["nori_readingform", "lowercase"],
                            }
                        }
                    },
                },
                "mappings": {
                    "properties": {
                        "content": {"type": "text", "analyzer": "korean"},
                        "document_title": {"type": "text", "analyzer": "korean"},
                        "section_title": {"type": "text", "analyzer": "korean"},
                        "category_ids": {"type": "keyword"},
                        "document_type": {"type": "keyword"},
                        "document_id": {"type": "keyword"},
                        "chunk_id": {"type": "keyword"},
                        "source_location": {"type": "object", "enabled": True},
                        "category_names": {"type": "keyword"},
                        "metadata": {"type": "object", "enabled": False},
                    }
                },
            },
            "priority": 100,
        }

        await client.indices.put_index_template(
            name=template_name,
            body=template_body,
        )

        log.info(
            "es_index_template_created",
            template=template_name,
            patterns=effective_patterns,
            shards=effective_shards,
            replicas=effective_replicas,
        )

    async def set_refresh_interval(
        self,
        index_name: str,
        interval: str | None = None,
        bulk_mode: bool = False,
    ) -> None:
        """
        인덱스 refresh 간격 조정.

        bulk_mode=True: 30s (벌크 인덱싱 중 성능 최적화)
        bulk_mode=False: 1s (실시간 검색)

        Args:
            index_name: 인덱스 이름
            interval: 직접 지정 (예: "5s", "30s", "-1")
            bulk_mode: True면 벌크 모드 (30s), False면 실시간 모드 (1s)
        """
        client = await self._get_client()

        if interval is not None:
            effective_interval = interval
        elif bulk_mode:
            effective_interval = self.BULK_REFRESH_INTERVAL
        else:
            effective_interval = self.REALTIME_REFRESH_INTERVAL

        await client.indices.put_settings(
            index=index_name,
            settings={"index": {"refresh_interval": effective_interval}},
        )

        log.info(
            "es_refresh_interval_set",
            index=index_name,
            interval=effective_interval,
            bulk_mode=bulk_mode,
        )

    async def force_merge(
        self,
        index_name: str,
        max_num_segments: int = 1,
    ) -> dict[str, Any]:
        """
        읽기 중심 인덱스에 대해 force merge 수행.

        세그먼트를 합쳐 검색 성능 최적화.
        주의: CPU/IO 부하가 높으므로 유휴 시간에 실행 권장.

        Args:
            index_name: 인덱스 이름
            max_num_segments: 목표 세그먼트 수 (기본 1)

        Returns:
            merge 결과 정보
        """
        client = await self._get_client()

        log.info(
            "es_force_merge_start",
            index=index_name,
            max_num_segments=max_num_segments,
        )

        result = await client.indices.forcemerge(
            index=index_name,
            max_num_segments=max_num_segments,
        )

        log.info(
            "es_force_merge_completed",
            index=index_name,
            result=dict(result) if result else {},
        )

        return dict(result) if result else {}

    async def create_ilm_policy(
        self,
        policy_name: str | None = None,
        hot_max_age: str = "30d",
        warm_min_age: str = "30d",
        delete_min_age: str = "365d",
    ) -> None:
        """
        ILM(Index Lifecycle Management) 정책 생성.

        Hot -> Warm -> Delete 라이프사이클:
        - Hot: 실시간 인덱싱 + 검색 (기본 30일)
        - Warm: 읽기 전용, force merge, 레플리카 축소 (30일 이후)
        - Delete: 오래된 인덱스 삭제 (365일 이후)

        Args:
            policy_name: 정책 이름
            hot_max_age: Hot 단계 최대 기간
            warm_min_age: Warm 단계 전환 시점
            delete_min_age: Delete 단계 전환 시점
        """
        client = await self._get_client()
        effective_policy_name = policy_name or self.ILM_POLICY_NAME

        policy_body: dict[str, Any] = {
            "policy": {
                "phases": {
                    "hot": {
                        "min_age": "0ms",
                        "actions": {
                            "rollover": {
                                "max_age": hot_max_age,
                                "max_primary_shard_size": "50gb",
                            },
                            "set_priority": {"priority": 100},
                        },
                    },
                    "warm": {
                        "min_age": warm_min_age,
                        "actions": {
                            "shrink": {"number_of_shards": 1},
                            "forcemerge": {"max_num_segments": 1},
                            "allocate": {"number_of_replicas": 0},
                            "set_priority": {"priority": 50},
                        },
                    },
                    "delete": {
                        "min_age": delete_min_age,
                        "actions": {
                            "delete": {},
                        },
                    },
                },
            },
        }

        await client.ilm.put_lifecycle(
            name=effective_policy_name,
            body=policy_body,
        )

        log.info(
            "es_ilm_policy_created",
            policy=effective_policy_name,
            hot_max_age=hot_max_age,
            warm_min_age=warm_min_age,
            delete_min_age=delete_min_age,
        )

    async def apply_ilm_policy(
        self,
        index_name: str,
        policy_name: str | None = None,
    ) -> None:
        """인덱스에 ILM 정책 적용."""
        client = await self._get_client()
        effective_policy_name = policy_name or self.ILM_POLICY_NAME

        await client.indices.put_settings(
            index=index_name,
            settings={
                "index": {
                    "lifecycle": {
                        "name": effective_policy_name,
                    },
                },
            },
        )

        log.info(
            "es_ilm_policy_applied",
            index=index_name,
            policy=effective_policy_name,
        )

    async def get_index_stats(self, index_name: str) -> dict[str, Any]:
        """
        인덱스 상세 통계 조회.

        문서 수, 크기, 세그먼트 수 등.
        """
        client = await self._get_client()

        stats = await client.indices.stats(index=index_name)
        index_stats = stats.get("indices", {}).get(index_name, {})
        primaries = index_stats.get("primaries", {})

        return {
            "index_name": index_name,
            "docs_count": primaries.get("docs", {}).get("count", 0),
            "docs_deleted": primaries.get("docs", {}).get("deleted", 0),
            "store_size_bytes": primaries.get("store", {}).get("size_in_bytes", 0),
            "segments_count": primaries.get("segments", {}).get("count", 0),
            "search_query_total": primaries.get("search", {}).get("query_total", 0),
            "search_query_time_ms": primaries.get("search", {}).get("query_time_in_millis", 0),
            "indexing_total": primaries.get("indexing", {}).get("index_total", 0),
            "indexing_time_ms": primaries.get("indexing", {}).get("index_time_in_millis", 0),
        }

    async def get_index_settings(self, index_name: str) -> dict[str, Any]:
        """인덱스 현재 설정 조회."""
        client = await self._get_client()
        result = await client.indices.get_settings(index=index_name)
        return dict(result.get(index_name, {}).get("settings", {}))
