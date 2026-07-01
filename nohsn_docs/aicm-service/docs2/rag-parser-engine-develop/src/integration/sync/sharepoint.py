"""SharePoint 동기화 커넥터 — Microsoft Graph API 기반."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from src.common.logging import get_logger
from src.integration.resilience.circuit_breaker import CircuitBreaker
from src.integration.sync.base import BaseSyncConnector
from src.integration.sync.models import RemoteDocumentMeta

log = get_logger(__name__)

# Microsoft Graph API 엔드포인트
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


class SharePointConfig(BaseModel):
    """SharePoint 동기화 설정.

    config dict에서 파싱:
    - azure_tenant_id: Azure AD 테넌트 ID
    - client_id: 앱 등록 클라이언트 ID
    - client_secret: 앱 등록 클라이언트 시크릿
    - site_id: SharePoint 사이트 ID (선택, site_url 대체 가능)
    - site_url: SharePoint 사이트 URL (예: contoso.sharepoint.com:/sites/team)
    - drive_id: 드라이브 ID (선택, 기본 드라이브 사용)
    - folder_path: 동기화 대상 폴더 경로 (선택, 루트부터)
    """

    azure_tenant_id: str
    client_id: str
    client_secret: str
    site_id: str | None = None
    site_url: str | None = None
    drive_id: str | None = None
    folder_path: str | None = None


class SharePointConnector(BaseSyncConnector):
    """Microsoft Graph API를 통한 SharePoint 문서 동기화.

    OAuth2 Client Credentials Flow로 인증.
    Delta query로 증분 변경 감지.
    """

    SUPPORTED_EXTENSIONS = {
        ".pdf", ".docx", ".doc", ".xlsx", ".xls",
        ".pptx", ".ppt", ".txt", ".csv", ".hwp",
    }

    def __init__(self, config: dict) -> None:
        self._config = SharePointConfig(**config)
        self._client = httpx.AsyncClient(timeout=30.0)
        self._access_token: str | None = None
        self._site_id: str | None = self._config.site_id
        self._drive_id: str | None = self._config.drive_id
        self._delta_link: str | None = None
        self._circuit_breaker = CircuitBreaker(
            name="sharepoint_sync",
            failure_threshold=5,
            recovery_timeout=30.0,
            half_open_max_calls=3,
        )

    async def authenticate(self) -> None:
        """Azure AD OAuth2 Client Credentials Flow로 액세스 토큰 발급."""
        token_url = TOKEN_URL.format(tenant_id=self._config.azure_tenant_id)

        response = await self._client.post(
            token_url,
            data={
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        response.raise_for_status()
        token_data = response.json()
        self._access_token = token_data["access_token"]

        log.info("sharepoint_authenticated", azure_tenant=self._config.azure_tenant_id)

        # site_id가 없으면 site_url로 조회
        if not self._site_id and self._config.site_url:
            self._site_id = await self._resolve_site_id()

        # drive_id가 없으면 기본 드라이브 조회
        if not self._drive_id and self._site_id:
            self._drive_id = await self._resolve_default_drive()

    async def list_documents(self) -> list[RemoteDocumentMeta]:
        """SharePoint 드라이브의 모든 문서 메타데이터 조회."""
        if not self._drive_id:
            raise RuntimeError("drive_id가 설정되지 않았습니다. authenticate()를 먼저 호출하세요.")

        folder_path = self._config.folder_path or ""
        if folder_path:
            url = f"{GRAPH_BASE_URL}/drives/{self._drive_id}/root:/{folder_path}:/children"
        else:
            url = f"{GRAPH_BASE_URL}/drives/{self._drive_id}/root/children"

        documents: list[RemoteDocumentMeta] = []
        await self._collect_items_recursive(url, documents)

        log.info("sharepoint_list_documents", count=len(documents))
        return documents

    async def download(self, remote_id: str) -> bytes:
        """Graph API로 파일 다운로드."""
        url = f"{GRAPH_BASE_URL}/drives/{self._drive_id}/items/{remote_id}/content"
        response = await self._graph_request("GET", url)
        return response.content

    async def get_changes_since(
        self, since: datetime
    ) -> list[RemoteDocumentMeta]:
        """Delta query로 변경된 문서 조회.

        최초 호출 시 전체 목록을 반환하고, 이후 호출 시 증분만 반환.
        """
        if self._delta_link:
            url = self._delta_link
        else:
            url = f"{GRAPH_BASE_URL}/drives/{self._drive_id}/root/delta"

        documents: list[RemoteDocumentMeta] = []

        while url:
            response = await self._graph_request("GET", url)
            data = response.json()

            for item in data.get("value", []):
                if item.get("file") and self._is_supported_file(item.get("name", "")):
                    modified_at = self._parse_datetime(
                        item.get("lastModifiedDateTime")
                    )
                    if modified_at and modified_at > since:
                        documents.append(
                            RemoteDocumentMeta(
                                remote_id=item["id"],
                                name=item["name"],
                                modified_at=modified_at,
                                size_bytes=item.get("size"),
                                mime_type=item.get("file", {}).get("mimeType"),
                            )
                        )

            # 페이지네이션 또는 delta link 갱신
            url = data.get("@odata.nextLink")
            if "@odata.deltaLink" in data:
                self._delta_link = data["@odata.deltaLink"]

        log.info(
            "sharepoint_get_changes",
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

    def _headers(self) -> dict[str, str]:
        """Graph API 인증 헤더."""
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _graph_request(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        """Graph API 요청 래퍼 (circuit breaker 적용)."""
        return await self._circuit_breaker.call(
            self._graph_request_inner, method, url, **kwargs
        )

    async def _graph_request_inner(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        """Graph API 실제 요청."""
        response = await self._client.request(
            method, url, headers=self._headers(), **kwargs
        )
        response.raise_for_status()
        return response

    async def _resolve_site_id(self) -> str:
        """site_url로 site_id 조회."""
        url = f"{GRAPH_BASE_URL}/sites/{self._config.site_url}"
        response = await self._graph_request("GET", url)
        site_id = response.json()["id"]
        log.info("sharepoint_site_resolved", site_id=site_id)
        return site_id

    async def _resolve_default_drive(self) -> str:
        """사이트의 기본 드라이브 ID 조회."""
        url = f"{GRAPH_BASE_URL}/sites/{self._site_id}/drive"
        response = await self._graph_request("GET", url)
        drive_id = response.json()["id"]
        log.info("sharepoint_drive_resolved", drive_id=drive_id)
        return drive_id

    async def _collect_items_recursive(
        self,
        url: str,
        documents: list[RemoteDocumentMeta],
    ) -> None:
        """폴더 내 아이템을 재귀적으로 수집."""
        response = await self._graph_request("GET", url)
        data = response.json()

        for item in data.get("value", []):
            if item.get("folder"):
                # 하위 폴더 재귀 탐색
                child_url = (
                    f"{GRAPH_BASE_URL}/drives/{self._drive_id}"
                    f"/items/{item['id']}/children"
                )
                await self._collect_items_recursive(child_url, documents)
            elif item.get("file") and self._is_supported_file(item.get("name", "")):
                documents.append(
                    RemoteDocumentMeta(
                        remote_id=item["id"],
                        name=item["name"],
                        modified_at=self._parse_datetime(
                            item.get("lastModifiedDateTime")
                        ),
                        size_bytes=item.get("size"),
                        mime_type=item.get("file", {}).get("mimeType"),
                    )
                )

        # 페이지네이션 처리
        next_link = data.get("@odata.nextLink")
        if next_link:
            await self._collect_items_recursive(next_link, documents)

    def _is_supported_file(self, name: str) -> bool:
        """지원 확장자 파일 여부."""
        return any(name.lower().endswith(ext) for ext in self.SUPPORTED_EXTENSIONS)

    @staticmethod
    def _parse_datetime(dt_str: str | None) -> datetime | None:
        """ISO 8601 문자열을 datetime으로 변환."""
        if not dt_str:
            return None
        # Graph API는 UTC ISO 형식 반환
        dt_str = dt_str.rstrip("Z")
        return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
