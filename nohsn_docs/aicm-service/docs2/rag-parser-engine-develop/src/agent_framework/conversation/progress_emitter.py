"""Progress emitter — 처리 시간 임계 기반 progress 안내.

§C #2 (진행 메시지). 처리 >3초 시 "검색 중", >10초 시 "조금 더 걸려요"
등을 발화. 본 모듈은 임계 평가만 하고, SSE 발화는 호출자가 담당.

Stateful — 같은 turn 안에서 같은 임계 메시지를 중복으로 보내지 않게 추적.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 임계 (ms, 메시지) — 정렬된 순서로 진행
DEFAULT_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (3000, "검색 중입니다…"),
    (7000, "분석 중입니다. 잠시만 기다려 주세요."),
    (15000, "조금 더 걸리고 있습니다. 결과가 곧 도착합니다."),
)


@dataclass
class _State:
    fired_indices: set[int] = field(default_factory=set)


class ProgressEmitter:
    """처리 시간을 받아 발화할 progress 메시지를 산출.

    사용:
        emitter = ProgressEmitter()
        msg = emitter.tick(elapsed_ms=4200)
        if msg: yield {"event": "progress", "data": {"text": msg}}
    """

    def __init__(self, thresholds: tuple[tuple[int, str], ...] | None = None):
        # 정렬된 사본 — 호출자 실수로 비정렬을 줘도 안전.
        self.thresholds = tuple(sorted(thresholds or DEFAULT_THRESHOLDS))
        self._state = _State()

    def tick(self, elapsed_ms: float) -> str | None:
        """경과 시간에서 발화 가능한 가장 늦은 임계 메시지 1개 (한 번만) 반환.

        반환된 임계는 다시 발화하지 않음. 임계 사이를 건너뛴 경우 (예: 0→8000ms)
        가장 큰 미발화 임계를 한 번만 발화 (이전 미발화 임계는 skip).
        """
        if elapsed_ms < 0:
            return None
        # 이번 호출에 발화할 후보 — 임계 ≤ elapsed 이고 아직 안 보낸 것 중 최댓값
        candidate_idx: int | None = None
        for i, (th, _) in enumerate(self.thresholds):
            if elapsed_ms >= th and i not in self._state.fired_indices:
                candidate_idx = i  # 마지막에 일치한 것 → 가장 큰 임계
        if candidate_idx is None:
            return None
        # candidate 보다 작은 미발화 임계도 모두 fired 로 마크 (skip).
        for i in range(candidate_idx + 1):
            self._state.fired_indices.add(i)
        return self.thresholds[candidate_idx][1]

    def reset(self) -> None:
        self._state = _State()
