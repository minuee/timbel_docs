"""Retrieval Gate — KMS RAG 호출 직전 skip 결정 (PR-A ❼).

페르소나 답변 분기와 chat_v1 citations 빌드 두 곳에서 RAG 검색이 매 턴 강제 실행되어
일정·캘린더 같은 비검색 도메인에 무관 citations (예: "Postgres 백업 정책.md") 가
첨부되는 버그 차단.

게이트 결정은 두 단:
  (a) base: skill.retrieval == "none"|"tool" → skip.
  (b) 안전망: skill.retrieval == "kms" 여도 intent classifier 가
      "이 발화는 검색 불필요" 판정 시 skip.

본 모듈은 *순수 결정 함수* 만 노출. LLM 호출은 호출자가 미리 실행해 결과 (search:bool)
를 주입한다 — 테스트 결정성 + LLM 의존 격리. classifier 호출 자체는
``src.search.intent_classifier.classify_intent`` 재사용.

"발사/발화" 같은 군대 어휘 금지 — 이벤트 명은 ``grounding_skipped`` (송출/emit 어휘).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetrievalDecision:
    """게이트 결정.

    - ``proceed``: True 면 RAG 검색 진행, False 면 skip.
    - ``reason_key``: 결정 사유 키 (event payload 와 로깅에 사용).
    """

    proceed: bool
    reason_key: str

    def to_skip_event(self) -> dict[str, Any]:
        """skip 결정을 SSE trace 이벤트 dict 로 변환.

        프런트 TraceStrip 이 ``event: grounding_skipped`` 를 받으면
        "검색 생략" 라벨을 표시. 본문 (token) 채널과 분리됨.
        """
        return {
            "event": "grounding_skipped",
            "data": {"reason": self.reason_key},
        }


def decide_retrieval(
    *,
    skill_retrieval: str | None,
    intent_search_needed: bool | None,
) -> RetrievalDecision:
    """게이트 결정 — 검색 진행 여부.

    Parameters
    ----------
    skill_retrieval : str | None
        활성 SkillV2 의 ``retrieval`` 메타. ``none``/``kms``/``tool`` 또는 None.
        None/unknown 값은 conservative 하게 ``kms`` 처럼 취급 (회귀 안전).
    intent_search_needed : bool | None
        ``src.search.intent_classifier.classify_intent`` 의 ``search`` 필드.
        호출자가 미리 실행한 결과. None 이면 classifier 호출 skip 으로 간주
        (예: skill 메타가 이미 none/tool 이라 base 게이트에서 끝남).

    Returns
    -------
    RetrievalDecision
        ``proceed=False`` + ``reason_key`` (skill_retrieval_none |
        skill_retrieval_tool | intent_classifier_non_search), 또는
        ``proceed=True`` + ``ok_kms_search_needed``.
    """
    # base 게이트
    if skill_retrieval == "none":
        return RetrievalDecision(proceed=False, reason_key="skill_retrieval_none")
    if skill_retrieval == "tool":
        return RetrievalDecision(proceed=False, reason_key="skill_retrieval_tool")

    # skill_retrieval in {"kms", None, unknown} → 안전망 단계로
    if intent_search_needed is False:
        return RetrievalDecision(
            proceed=False, reason_key="intent_classifier_non_search"
        )

    # search=True 또는 classifier 미호출 — 진행
    return RetrievalDecision(proceed=True, reason_key="ok_kms_search_needed")
