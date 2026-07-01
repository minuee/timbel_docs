"""Ambiguity resolver — 다중 의도 시 짧은 확인 질문.

§C #6 (모호 발화 해석). intent classifier 가 다중 라벨을 반환했을 때,
사용자에게 어느 의도였는지 짧게 확인. 가능하면 yes/no 분기.

규칙 (rule-based — LLM 불필요, 빠른 반응):
 - 1 개 intent → resolve 안 함 (None)
 - 2~3 개 intent → "둘 중 어느 거? A 인가요, B 인가요?" 형식
 - 4+ 개 intent → "여러 가지로 들립니다. 가장 가까운 건? A / B / C 중에서…"
 - confidence 가 의도 사이 매우 가깝거나 (gap < 0.1), 최고 confidence 가 0.65 미만일 때만 발동.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntentCandidate:
    label: str
    description: str
    confidence: float


@dataclass(frozen=True)
class AmbiguityResolution:
    """resolver 결과.

    needs_confirm : True 면 question 을 사용자에게 보여 줘야 함.
    question : 사용자에게 보낼 짧은 확인 질문 (Korean).
    options : 보기 라벨 [A, B, ...]
    """

    needs_confirm: bool
    question: str
    options: list[str]


class AmbiguityResolver:
    """다중 의도 → 짧은 확인 질문 합성기."""

    def __init__(
        self,
        *,
        max_confidence_floor: float = 0.65,
        gap_threshold: float = 0.1,
    ):
        self.max_confidence_floor = max_confidence_floor
        self.gap_threshold = gap_threshold

    def resolve(self, candidates: list[IntentCandidate]) -> AmbiguityResolution:
        """조건 만족 시 question + options. 아니면 needs_confirm=False."""
        if not candidates or len(candidates) == 1:
            return AmbiguityResolution(False, "", [])

        sorted_c = sorted(candidates, key=lambda c: c.confidence, reverse=True)
        top = sorted_c[0]
        # 1) 최고가 충분히 명확하고
        # 2) 두 번째와 충분히 차이 나면 모호하지 않음.
        if (
            top.confidence >= self.max_confidence_floor
            and (top.confidence - sorted_c[1].confidence) >= self.gap_threshold
        ):
            return AmbiguityResolution(False, "", [])

        # 모호 — 상위 2~3 개를 옵션으로
        chosen = sorted_c[:3]
        descs = [c.description.strip() for c in chosen if c.description.strip()]
        if not descs:
            return AmbiguityResolution(False, "", [])

        if len(descs) == 2:
            q = f"두 가지로 들립니다. '{descs[0]}' 인가요, 아니면 '{descs[1]}' 인가요?"
        else:
            joined = " / ".join(f"'{d}'" for d in descs)
            q = f"여러 가지 의미로 들립니다. {joined} 중에서 어떤 것을 말씀하시는 건가요?"

        return AmbiguityResolution(True, q, descs)
