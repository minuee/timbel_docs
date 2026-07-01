"""P0.3 codex P1-1 hardening — citation reconciliation post-stream.

engine 은 LLM 토큰 스트림 시작 *전* 에 ``event: citations`` 를 emit (chrome 이벤트
분리 원칙). 그 시점에는 본문에 [N] 마커가 박힐지 backend 가 알 수 없다. 스트림
종료 후 본문 텍스트에서 ``\\[(\\d+)\\]`` 마커를 추출해 본문에 실제로 박힌 [N]
번호의 citation 만 ``referenced=True`` 로 반환하고, 박히지 않은 항목은 *drop*
(R7 — 거절 답변에 출처 표시 차단). 본문엔 박혔지만 매칭 citation 이 없는 번호
(orphan) 는 별도 리스트로 반환한다.

R7 (2026-05-07) — 시맨틱 변경: ``items`` 는 이제 *used_items* 만 (referenced=True).
unused 는 ``reconcile_citation_references_with_unused`` 로 별도 조회.

회귀 케이스:
1) 정상 — 본문 [1] + citations [1, 2] → [1] only (used_items)
2) orphan — 본문 [3] + citations [1, 2] → orphans=[3], used_items=[]
3) 모두 사용 — 본문 [1][2] + citations [1, 2] → 둘 다 used_items
4) 본문 마커 0개 — citations [1, 2] → used_items=[] (R7 — 거절 답변 case)
5) 빈 본문 + 빈 citations → 빈 결과
"""
from __future__ import annotations


def test_reconciliation_returns_only_used_citations():
    """R7 — 본문에 [1] 만 있으면 used_items 에 [1] 만. number=2 는 drop."""
    from src.agent_framework.runtime.grounding import reconcile_citation_references

    citations = [
        {"id": "c1", "number": 1, "document_title": "A"},
        {"id": "c2", "number": 2, "document_title": "B"},
    ]
    body = "우리는 [1] 사용합니다."

    used_items, orphans = reconcile_citation_references(citations, body)
    assert orphans == []
    assert len(used_items) == 1
    assert used_items[0]["number"] == 1
    assert used_items[0]["referenced"] is True


def test_reconciliation_flags_orphan_marker():
    """본문에 [3] 박혔는데 citations 에 number=3 없음 → orphans=[3], used=[].

    LLM 이 잘못된 번호를 사용했을 때 backend 가 운영 가시성 확보.
    """
    from src.agent_framework.runtime.grounding import reconcile_citation_references

    citations = [
        {"id": "c1", "number": 1, "document_title": "A"},
        {"id": "c2", "number": 2, "document_title": "B"},
    ]
    body = "우리는 [3] 사용합니다."

    used_items, orphans = reconcile_citation_references(citations, body)
    assert orphans == [3], f"expected orphan [3], got {orphans}"
    assert used_items == []  # 본문 [3] 매칭 없음, [1][2] 도 미사용 → drop


def test_reconciliation_all_markers_used():
    from src.agent_framework.runtime.grounding import reconcile_citation_references

    citations = [
        {"id": "c1", "number": 1},
        {"id": "c2", "number": 2},
    ]
    body = "이건 [1] 또 [2] 둘 다 활용합니다."

    used_items, orphans = reconcile_citation_references(citations, body)
    assert orphans == []
    assert len(used_items) == 2
    assert all(c["referenced"] for c in used_items)


def test_reconciliation_no_markers_in_body():
    """R7 — LLM 이 마커 누락 (거절 답변 등) → used_items=[]. citations 0건 표시."""
    from src.agent_framework.runtime.grounding import reconcile_citation_references

    citations = [
        {"id": "c1", "number": 1},
        {"id": "c2", "number": 2},
    ]
    body = "이 상담은 도메인 외 문의입니다."

    used_items, orphans = reconcile_citation_references(citations, body)
    assert orphans == []
    assert used_items == []  # R7 — 거절 답변 → citation 미표시


def test_reconciliation_preserves_input_fields():
    """used_items 는 입력 citation 의 모든 필드를 보존하고 ``referenced`` 만 추가."""
    from src.agent_framework.runtime.grounding import reconcile_citation_references

    citations = [
        {
            "id": "c1",
            "number": 1,
            "document_title": "휴가규정",
            "snippet": "연 15일",
            "score": 0.9,
            "block_type": "manual",
        },
    ]
    body = "연 15일 [1]"
    used_items, _ = reconcile_citation_references(citations, body)
    assert used_items[0]["document_title"] == "휴가규정"
    assert used_items[0]["snippet"] == "연 15일"
    assert used_items[0]["score"] == 0.9
    assert used_items[0]["referenced"] is True


def test_reconciliation_empty_inputs():
    from src.agent_framework.runtime.grounding import reconcile_citation_references

    used_items, orphans = reconcile_citation_references([], "")
    assert used_items == []
    assert orphans == []


def test_reconciliation_repeated_marker_does_not_duplicate_orphan():
    """같은 [3] 가 본문에 2회 박혀도 orphan 리스트엔 1개만."""
    from src.agent_framework.runtime.grounding import reconcile_citation_references

    citations = [{"id": "c1", "number": 1}]
    body = "[3] 그리고 또 [3]"
    _, orphans = reconcile_citation_references(citations, body)
    assert orphans == [3]


def test_extract_marker_numbers_handles_multidigit():
    """LLM 이 [10] 같은 두 자리 마커도 사용 가능 — pattern 일반화 검증."""
    from src.agent_framework.runtime.grounding import extract_marker_numbers

    used = extract_marker_numbers("자료 [1] [10] 결합 [2]")
    assert used == {1, 10, 2}


def test_reconciliation_with_unused_returns_separated():
    """R7 — admin trace 용 with_unused 변형은 used + unused + orphans 모두 반환."""
    from src.agent_framework.runtime.grounding import (
        reconcile_citation_references_with_unused,
    )

    citations = [
        {"id": "c1", "number": 1},
        {"id": "c2", "number": 2},
        {"id": "c3", "number": 3},
    ]
    body = "[1] 매칭, [2] 도 매칭."
    used, unused, orphans = reconcile_citation_references_with_unused(
        citations, body
    )
    assert {c["number"] for c in used} == {1, 2}
    assert all(c["referenced"] is True for c in used)
    assert {c["number"] for c in unused} == {3}
    assert all(c["referenced"] is False for c in unused)
    assert orphans == []
