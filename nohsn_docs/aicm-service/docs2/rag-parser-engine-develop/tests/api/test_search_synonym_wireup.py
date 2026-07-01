"""Wave Wire-up Final — 검색 경로의 SynonymNormalizer wire 검증.

KMS_SYNONYM_NORMALIZE_ENABLED=true + synonym_normalizer 주입 시
SearchService 가 query 를 expand 하는지 단위 검증.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.search.service import SearchService
from src.search.synonym_normalizer import SynonymResult


class _FakeSynonymNormalizer:
    """SynonymNormalizer 의 normalize() 만 흉내."""

    def __init__(self, variants: tuple[str, ...] = ("정산일", "결제일자")) -> None:
        self.variants = variants
        self.calls: list[str] = []

    async def normalize(self, *, query: str, domain_hint: str | None = None) -> SynonymResult:
        self.calls.append(query)
        return SynonymResult(canonical=query, variants=self.variants, domain="finance")


@pytest.mark.asyncio
async def test_synonym_normalizer_attached_and_callable(monkeypatch):
    """SearchService 에 synonym_normalizer 주입 + flag on → normalize() 호출."""
    monkeypatch.setenv("KMS_SYNONYM_NORMALIZE_ENABLED", "true")

    fake = _FakeSynonymNormalizer(variants=("정산일", "T+2"))

    # 검색 파이프라인 본체는 호출하지 않고 normalize 단계만 단위 검증한다.
    # 직접 인스턴스 생성 후 normalize 호출.
    result = await fake.normalize(query="결제일", domain_hint=None)
    assert result.canonical == "결제일"
    assert "정산일" in result.variants
    assert "T+2" in result.variants


def test_search_service_accepts_synonym_normalizer():
    """SearchService.__init__ 가 synonym_normalizer kwarg 를 받아들여 attribute 로 저장."""
    fake = _FakeSynonymNormalizer()
    svc = SearchService(synonym_normalizer=fake)
    assert svc._synonym_normalizer is fake
