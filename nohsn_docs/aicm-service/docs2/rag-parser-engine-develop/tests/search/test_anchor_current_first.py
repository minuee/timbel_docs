"""콜봇 앵커 current-query-first 회귀 테스트.

이슈: 멀티턴에서 직전 턴의 상품명이 현재 질문의 상품을 덮어써(lag-by-one) 엉뚱한
문서로 스코프됨(AWS 5건 플립 재현). 수정: 현재 발화로 먼저 앵커를 잡고, 현재 발화가
상품을 못 잡은 경우(상품명 없는 발화)에만 이력 포함 폴백.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.search.service import SearchService


def _svc(side_effect):
    svc = SearchService.__new__(SearchService)
    svc._keyword_searcher = SimpleNamespace(
        resolve_documents_by_title=AsyncMock(side_effect=side_effect)
    )
    return svc


@pytest.mark.asyncio
async def test_current_query_fund_wins_over_history():
    # 현재 발화에 상품명("한국투자")이 있으면, 이력의 직전 상품("하나코리아")으로 스코프되면 안 된다.
    def fake(text, *a, **k):
        # 현재 발화만일 때(이력 미포함) 한국투자 매칭, 이력 결합 텍스트면 하나코리아가 더 강함
        if "하나코리아" in text:
            return [("doc_hana", 5.0)]
        return [("doc_korea", 3.0)]

    svc = _svc(fake)
    request = SimpleNamespace(
        query="한국투자테크 펀드 클래스 C 총 보수",
        conversation_history=[{"role": "user", "content": "하나코리아 수수료"}],
    )
    out = await svc._resolve_anchor_doc_ids(request, "idx", None, "t1")
    assert out == ["doc_korea"]
    # 현재 발화로 앵커를 잡았으므로 이력 포함 재시도(2차 호출)는 없어야 한다.
    assert svc._keyword_searcher.resolve_documents_by_title.await_count == 1


@pytest.mark.asyncio
async def test_fundless_query_falls_back_to_history():
    # 현재 발화에 상품명이 없으면(앵커 미해석) 이력 포함 폴백으로 직전 상품을 앵커링한다.
    def fake(text, *a, **k):
        if "한국투자" in text:  # 이력 포함 결합 텍스트
            return [("doc_korea", 3.0)]
        return []  # 현재 발화("총 보수 얼마야")만으로는 매칭 없음

    svc = _svc(fake)
    request = SimpleNamespace(
        query="총 보수 얼마야",
        conversation_history=[{"role": "user", "content": "한국투자테크 펀드 클래스 C"}],
    )
    out = await svc._resolve_anchor_doc_ids(request, "idx", None, "t1")
    assert out == ["doc_korea"]
    # 1차(현재 발화) 미해석 -> 2차(이력 포함) 재시도 = 총 2회
    assert svc._keyword_searcher.resolve_documents_by_title.await_count == 2
