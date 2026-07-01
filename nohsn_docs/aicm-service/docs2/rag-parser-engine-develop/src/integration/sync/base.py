"""동기화 커넥터 추상 베이스 클래스."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.integration.sync.models import RemoteDocumentMeta


class BaseSyncConnector(ABC):
    """외부 문서 소스와의 동기화를 위한 추상 커넥터.

    각 구현체(SharePoint, Confluence 등)는 이 인터페이스를 따른다.
    """

    @abstractmethod
    async def authenticate(self) -> None:
        """소스 인증. OAuth2 토큰 발급 등 초기화 수행."""

    @abstractmethod
    async def list_documents(self) -> list[RemoteDocumentMeta]:
        """원격 소스의 모든 문서 메타데이터 목록 조회."""

    @abstractmethod
    async def download(self, remote_id: str) -> bytes:
        """원격 문서 다운로드. 파일 바이너리 반환."""

    @abstractmethod
    async def get_changes_since(
        self, since: datetime
    ) -> list[RemoteDocumentMeta]:
        """지정 시간 이후 변경된 문서 목록 조회 (증분 동기화용)."""

    @abstractmethod
    async def close(self) -> None:
        """리소스 정리. HTTP 클라이언트 등 종료."""
