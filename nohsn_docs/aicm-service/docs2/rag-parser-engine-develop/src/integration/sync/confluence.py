"""Confluence 동기화 커넥터 — Atlassian REST API v2 기반."""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

from src.common.logging import get_logger
from src.integration.resilience.circuit_breaker import CircuitBreaker
from src.integration.sync.base import BaseSyncConnector
from src.integration.sync.models import RemoteDocumentMeta

log = get_logger(__name__)


class ConfluenceConfig(BaseModel):
    """Confluence 동기화 설정.

    config dict에서 파싱:
    - base_url: Confluence 인스턴스 URL (예: https://your-domain.atlassian.net/wiki)
    - email: API 인증 이메일
    - api_token: Atlassian API 토큰
    - space_keys: 동기화 대상 스페이스 키 목록
    - include_labels: 포함할 라벨 목록 (선택, 비어있으면 전체)
    - exclude_labels: 제외할 라벨 목록 (선택)
    """

    base_url: str
    email: str
    api_token: str
    space_keys: list[str]
    include_labels: list[str] = []
    exclude_labels: list[str] = []


class ConfluenceConnector(BaseSyncConnector):
    """Atlassian REST API를 통한 Confluence 페이지 동기화.

    Basic auth(이메일 + API 토큰) 또는 Bearer 토큰 인증.
    CQL(Confluence Query Language) 기반 변경 감지.
    페이지 콘텐츠를 HTML로 가져와 AICM 파이프라인에 전달.
    """

    def __init__(self, config: dict) -> None:
        self._config = ConfluenceConfig(**config)
        self._base_url = self._config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30.0)
        self._circuit_breaker = CircuitBreaker(
            name="confluence_sync",
            failure_threshold=5,
            recovery_timeout=30.0,
            half_open_max_calls=3,
        )

    async def authenticate(self) -> None:
        """Confluence 인증 확인. /wiki/rest/api/user/current 호출."""
        url = f"{self._base_url}/rest/api/user/current"
        response = await self._circuit_breaker.call(
            self._client.get, url, headers=self._auth_headers()
        )
        response.raise_for_status()
        user = response.json()
        log.info(
            "confluence_authenticated",
            user=user.get("displayName", "unknown"),
            base_url=self._base_url,
        )

    async def list_documents(self) -> list[RemoteDocumentMeta]:
        """모든 대상 스페이스의 페이지 메타데이터 조회."""
        documents: list[RemoteDocumentMeta] = []

        for space_key in self._config.space_keys:
            cql = f'space="{space_key}" AND type=page'
            if self._config.include_labels:
                labels = " OR ".join(
                    f'label="{lbl}"' for lbl in self._config.include_labels
                )
                cql += f" AND ({labels})"
            if self._config.exclude_labels:
                for lbl in self._config.exclude_labels:
                    cql += f' AND label!="{lbl}"'

            pages = await self._cql_search(cql)
            documents.extend(pages)

        log.info("confluence_list_documents", count=len(documents))
        return documents

    async def download(self, remote_id: str) -> bytes:
        """페이지 콘텐츠를 HTML(storage format)로 다운로드.

        반환되는 bytes는 UTF-8 인코딩된 HTML.
        AICM 파이프라인에서 HTML 파서로 처리한다.
        """
        url = (
            f"{self._base_url}/rest/api/content/{remote_id}"
            f"?expand=body.storage,metadata.labels"
        )
        response = await self._circuit_breaker.call(
            self._client.get, url, headers=self._auth_headers()
        )
        response.raise_for_status()
        data = response.json()

        title = data.get("title", "")
        html_body = data.get("body", {}).get("storage", {}).get("value", "")

        # 제목 + HTML 본문을 하나의 HTML 문서로 조립
        full_html = f"<html><head><title>{title}</title></head><body><h1>{title}</h1>{html_body}</body></html>"
        return full_html.encode("utf-8")

    async def get_changes_since(
        self, since: datetime
    ) -> list[RemoteDocumentMeta]:
        """CQL로 지정 시간 이후 변경된 페이지 조회."""
        documents: list[RemoteDocumentMeta] = []

        # CQL에서 사용할 날짜 포맷: yyyy-MM-dd HH:mm
        since_str = since.strftime("%Y-%m-%d %H:%M")

        for space_key in self._config.space_keys:
            cql = (
                f'space="{space_key}" AND type=page '
                f'AND lastModified>="{since_str}"'
            )
            if self._config.include_labels:
                labels = " OR ".join(
                    f'label="{lbl}"' for lbl in self._config.include_labels
                )
                cql += f" AND ({labels})"

            pages = await self._cql_search(cql)
            documents.extend(pages)

        log.info(
            "confluence_get_changes",
            since=since.isoformat(),
            changed_count=len(documents),
        )
        return documents

    async def close(self) -> None:
        """HTTP 클라이언트 종료."""
        await self._client.aclose()

    # -----------------------------------------------------------------------
    # 내부 헬퍼
    # -----------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """Basic auth 헤더 생성."""
        credentials = f"{self._config.email}:{self._config.api_token}"
        b64_creds = base64.b64encode(credentials.encode()).decode()
        return {
            "Authorization": f"Basic {b64_creds}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _cql_search(self, cql: str) -> list[RemoteDocumentMeta]:
        """CQL 검색으로 페이지 목록 조회 (페이지네이션 지원)."""
        documents: list[RemoteDocumentMeta] = []
        start = 0
        limit = 50

        while True:
            url = (
                f"{self._base_url}/rest/api/content/search"
                f"?cql={cql}&start={start}&limit={limit}"
                f"&expand=version,history.lastUpdated"
            )
            response = await self._circuit_breaker.call(
                self._client.get, url, headers=self._auth_headers()
            )
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                break

            for page in results:
                modified_at = self._extract_modified_at(page)
                documents.append(
                    RemoteDocumentMeta(
                        remote_id=page["id"],
                        name=page.get("title", ""),
                        modified_at=modified_at,
                        mime_type="text/html",
                    )
                )

            # 페이지네이션
            total_size = data.get("totalSize", 0)
            start += limit
            if start >= total_size:
                break

        return documents

    @staticmethod
    def _extract_modified_at(page: dict) -> datetime | None:
        """페이지 수정일 추출."""
        try:
            when = (
                page.get("history", {})
                .get("lastUpdated", {})
                .get("when", "")
            )
            if when:
                # Confluence는 ISO 8601 형식 반환
                return datetime.fromisoformat(
                    when.replace("Z", "+00:00")
                )
            # version.when fallback
            version_when = page.get("version", {}).get("when", "")
            if version_when:
                return datetime.fromisoformat(
                    version_when.replace("Z", "+00:00")
                )
        except (ValueError, KeyError):
            pass
        return None
