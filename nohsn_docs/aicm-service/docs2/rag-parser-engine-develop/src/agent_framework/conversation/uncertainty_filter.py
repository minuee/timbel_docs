"""Uncertainty filter — 답변 불확실 시 사용자에게 명시적으로 표시.

§C #3 (불확실성 표현). confidence 가 임계값 미만이면 답변 앞에 prepend:
 "확실하지 않습니다, 다시 한 번 확인하시는 것을 권합니다. 제가 이해한 바로는—"

또는 SSE event: uncertainty 로 별도 발화 가능. 본 모듈은 텍스트 변환만 담당하고
emitter(엔진) 에서 어느 경로로 보낼지 결정한다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 임계값 라벨 (chat ui spec §4.3)
TRUST_HIGH = 0.85
TRUST_MID = 0.65
TRUST_LOW = 0.0


@dataclass(frozen=True)
class UncertaintyDecision:
    """confidence 평가 결과.

    label : "high" | "mid" | "low"
    prepend : 답변 앞에 붙일 안내 문구 (low 만 채워짐).
    badge : UI 시그널용 라벨 ("🟢 신뢰" / "🟡 보통" / "⚠️ 불확실").
    """

    label: str
    prepend: str
    badge: str


class UncertaintyFilter:
    """confidence 신호로 불확실성 메시지 prepend 여부를 결정.

    confidence 계산 (3 신호 평균) 은 여기서 하지 않음 — 외부에서 계산해 넣음.
    """

    def __init__(
        self,
        *,
        threshold_high: float = TRUST_HIGH,
        threshold_mid: float = TRUST_MID,
        prepend_text: str | None = None,
    ):
        if threshold_mid >= threshold_high:
            raise ValueError("threshold_mid 는 threshold_high 미만이어야 합니다.")
        self.threshold_high = threshold_high
        self.threshold_mid = threshold_mid
        self.prepend_text = (
            prepend_text
            or "확실하지 않습니다, 다시 한 번 확인해 주시기 바랍니다. 제가 이해한 바로는,"
        )

    def evaluate(self, confidence: float) -> UncertaintyDecision:
        """confidence (0~1) 를 라벨로."""
        c = max(0.0, min(1.0, float(confidence)))
        if c >= self.threshold_high:
            return UncertaintyDecision(label="high", prepend="", badge="🟢 신뢰")
        if c >= self.threshold_mid:
            return UncertaintyDecision(label="mid", prepend="", badge="🟡 보통")
        return UncertaintyDecision(
            label="low", prepend=self.prepend_text, badge="⚠️ 불확실"
        )

    def apply(self, text: str, confidence: float) -> str:
        """필요 시 prepend 적용. high/mid 는 변경 없음."""
        d = self.evaluate(confidence)
        if d.prepend:
            sep = " " if not text or not text[0].isspace() else ""
            return d.prepend + sep + text
        return text
