"""D84 (2026-05-13) — strict knowledge_isolation no-evidence runtime hard gate.

LLM 프롬프트 지시 (fallback_hint) 가 아닌 *코드 차단* 으로 strict agent 의
일반지식 fallback 을 막는다. compose 진입 전에 호출되어 verdict 가 'refuse'
면 LLM 호출 자체를 건너뛰고 중앙화된 거절 응답을 반환한다.

priority / broad 동작은 변경 없음 — 호출자는 verdict.action == 'fallback_hint'
에서 기존 OOS-precedence fix 분기를 그대로 사용.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# 중앙화된 거절 응답 — LLM 에 맡기지 않는다. 회귀 시 한 곳만 본다.
STRICT_NO_EVIDENCE_REFUSAL = (
    "내부 자료에서 관련 문서를 찾지 못했습니다. 키워드를 바꿔 다시 시도하시거나 "
    "사람 상담사·공식 채널에 문의해 주세요."
)

# D85 (2026-05-13) — 사용자 절칙 'KMS + 루카스 분리'. score threshold 제거.
# KMS retrieval 이 hit 를 줬으면 (score 무관) 루카스는 *그대로 LLM compose 에
# 넘긴다*. assist-stream 도 score >= 0.15 hit 모두 노출 → strict 도 동일. KMS
# 가 답할 게 없는 (hit count == 0) 케이스만 strict refuse.
_LOW_SCORE_THRESHOLD = 0.0

EvidenceAction = Literal["allow", "refuse", "fallback_hint"]


@dataclass(frozen=True)
class StrictEvidenceVerdict:
    """evaluate_evidence 의 판정 결과.

    - action='allow': 정상 compose 진행 (자료 충분 또는 비-strict agent).
    - action='refuse': strict 거절 — refusal_text 를 본문으로 즉시 반환.
    - action='fallback_hint': 기존 priority/broad 동작 — fallback_hint 주입 후
      LLM 일반지식 답변 허용.
    """

    action: EvidenceAction
    refusal_text: str = ""
    reason: str = ""


def _has_meaningful_kms_hit(tool_results: list[Any] | None) -> bool:
    """D85 (2026-05-13) — KMS hit count > 0 만 본다. score 무관.

    사용자 절칙: KMS retrieval 결과를 *그대로* 사용. score 재판정 = 절칙 위배.
    """
    for tr in tool_results or []:
        if not isinstance(tr, dict):
            continue
        if (tr.get("tool") or "").strip() != "kms_rag.search":
            continue
        result = tr.get("result") or {}
        hits = result.get("hits") or []
        if hits:
            return True
    return False


def evaluate_evidence(
    *,
    isolation: str | None,
    web_search_mode: str | None,  # 현재 정책상 미사용 — 향후 strict_sources_only 등 확장 여지.
    tool_results: list[Any] | None,
) -> StrictEvidenceVerdict:
    """agent 의 isolation 정책 + 도구 결과로 compose 진행 여부를 판정.

    - strict + meaningful KMS hit 없음 → refuse (web 결과만 있어도 동일).
      strict 의 UI 라벨이 "문서만" 이므로 web 결과만으로 일반지식 합성 금지.
    - priority / broad + KMS no-hit → fallback_hint (기존 동작).
    - meaningful KMS hit 있음 → allow.
    """
    iso = (isolation or "priority").strip().lower()
    has_kms = _has_meaningful_kms_hit(tool_results)

    if has_kms:
        return StrictEvidenceVerdict(action="allow")

    if iso == "strict":
        return StrictEvidenceVerdict(
            action="refuse",
            refusal_text=STRICT_NO_EVIDENCE_REFUSAL,
            reason="strict_no_kms_evidence",
        )

    return StrictEvidenceVerdict(
        action="fallback_hint",
        reason="no_kms_evidence_non_strict",
    )
