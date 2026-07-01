"""확신도 등급 시스템 — 분류 확신도를 4단계 등급으로 매핑.

GAP-PROV-02 참조.

등급 기준:
  SOLID   (>=0.9) : 높은 확신, 기본 펼침
  GOOD    (>=0.75): 양호, 기본 펼침
  CAUTION (>=0.6) : 주의, 기본 접힘
  LOW     (<0.6)  : 낮은 확신, 기본 접힘 + "분류 수정" 버튼 표시
"""

from __future__ import annotations

from typing import Any


class ConfidenceGrade:
    """확신도 등급 상수."""

    SOLID = "solid"
    GOOD = "good"
    CAUTION = "caution"
    LOW = "low"


def grade_confidence(confidence: float) -> dict[str, Any]:
    """확신도를 4단계 등급으로 변환한다.

    Args:
        confidence: 0.0~1.0 범위의 확신도 값.

    Returns:
        grade, icon, label, expanded 키를 포함하는 딕셔너리.
        LOW 등급에는 show_edit=True가 추가된다.
    """
    if confidence >= 0.9:
        return {
            "grade": ConfidenceGrade.SOLID,
            "icon": "check_circle",
            "label": "높은 확신",
            "expanded": True,
        }
    elif confidence >= 0.75:
        return {
            "grade": ConfidenceGrade.GOOD,
            "icon": "bolt",
            "label": "양호",
            "expanded": True,
        }
    elif confidence >= 0.6:
        return {
            "grade": ConfidenceGrade.CAUTION,
            "icon": "warning",
            "label": "주의",
            "expanded": False,
        }
    else:
        return {
            "grade": ConfidenceGrade.LOW,
            "icon": "error",
            "label": "낮은 확신",
            "expanded": False,
            "show_edit": True,
        }
