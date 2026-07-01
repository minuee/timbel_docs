"""피드백 분석기 — 사용자 수정 패턴을 분석하여 분류 개선.

GAP-PROV-04 참조.

주간 배치:
  1. lifecycle_feedback에서 최근 수정 패턴 수집
  2. 오분류 패턴 분석 (어떤 nature가 자주 수정되는지)
  3. Category synonyms 자동 보강 제안
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.core.models.lifecycle_feedback import LifecycleFeedback

logger = get_logger(__name__)


class FeedbackAnalyzer:
    """사용자 피드백 패턴을 분석하여 분류 품질 개선 인사이트를 제공한다."""

    def __init__(self, db: AsyncSession) -> None:
        """분석기를 초기화한다.

        Args:
            db: 비동기 DB 세션.
        """
        self._db = db

    async def analyze_weekly(
        self,
        tenant_id: uuid.UUID,
        days: int = 7,
    ) -> dict[str, Any]:
        """주간 피드백 분석을 수행한다.

        Args:
            tenant_id: 분석 대상 테넌트 ID.
            days: 분석 기간 (기본 7일).

        Returns:
            total_feedbacks, correction_patterns, suggested_synonym_additions 키를 포함하는
            분석 결과 딕셔너리.
        """
        since = datetime.utcnow() - timedelta(days=days)

        # 1. 최근 피드백 수집
        stmt = (
            select(LifecycleFeedback)
            .where(
                LifecycleFeedback.tenant_id == tenant_id,
                LifecycleFeedback.created_at >= since,
            )
            .order_by(LifecycleFeedback.created_at.desc())
        )
        result = await self._db.execute(stmt)
        feedbacks = result.scalars().all()

        total = len(feedbacks)
        if total == 0:
            return {
                "total_feedbacks": 0,
                "period_days": days,
                "correction_patterns": [],
                "suggested_synonym_additions": [],
            }

        # 2. field_name별 수정 빈도
        field_counts: Counter[str] = Counter()
        nature_transitions: Counter[str] = Counter()
        category_corrections: list[dict[str, Any]] = []

        for fb in feedbacks:
            field_counts[fb.field_name] += 1

            if fb.field_name == "nature" and fb.old_value and fb.new_value:
                old_val = fb.old_value.get("value", "unknown")
                new_val = fb.new_value.get("value", "unknown")
                nature_transitions[f"{old_val} -> {new_val}"] += 1

            if fb.field_name == "domain_category_ids" and fb.new_value:
                category_corrections.append({
                    "block_id": str(fb.block_id),
                    "old": fb.old_value,
                    "new": fb.new_value,
                    "reason": fb.reason,
                })

        # 3. 가장 많이 수정되는 패턴 식별
        correction_patterns = [
            {
                "field_name": field,
                "count": count,
                "percentage": round(count / total * 100, 1),
            }
            for field, count in field_counts.most_common()
        ]

        # 4. Nature 전환 패턴 (가장 빈번한 오분류)
        top_nature_transitions = [
            {"transition": trans, "count": count}
            for trans, count in nature_transitions.most_common(10)
        ]

        # 5. Category synonyms 보강 제안 생성
        suggestions = self._generate_synonym_suggestions(category_corrections)

        logger.info(
            "feedback_analysis_complete",
            tenant_id=str(tenant_id),
            total_feedbacks=total,
            period_days=days,
        )

        return {
            "total_feedbacks": total,
            "period_days": days,
            "correction_patterns": correction_patterns,
            "nature_transitions": top_nature_transitions,
            "suggested_synonym_additions": suggestions,
        }

    async def get_correction_rate(
        self,
        tenant_id: uuid.UUID,
        days: int = 30,
    ) -> dict[str, Any]:
        """일정 기간 동안의 수정률을 계산한다.

        Args:
            tenant_id: 대상 테넌트 ID.
            days: 분석 기간.

        Returns:
            총 블럭 수 대비 수정된 블럭 수 비율.
        """
        since = datetime.utcnow() - timedelta(days=days)

        # 수정된 고유 블럭 수
        corrected_stmt = (
            select(func.count(func.distinct(LifecycleFeedback.block_id)))
            .where(
                LifecycleFeedback.tenant_id == tenant_id,
                LifecycleFeedback.created_at >= since,
            )
        )
        corrected_count = (await self._db.execute(corrected_stmt)).scalar() or 0

        # 전체 피드백 수
        total_stmt = (
            select(func.count())
            .select_from(LifecycleFeedback)
            .where(
                LifecycleFeedback.tenant_id == tenant_id,
                LifecycleFeedback.created_at >= since,
            )
        )
        total_feedbacks = (await self._db.execute(total_stmt)).scalar() or 0

        return {
            "period_days": days,
            "corrected_blocks": corrected_count,
            "total_feedbacks": total_feedbacks,
        }

    @staticmethod
    def _generate_synonym_suggestions(
        category_corrections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """카테고리 수정 패턴에서 동의어 보강 제안을 생성한다.

        Args:
            category_corrections: 카테고리 수정 이력 목록.

        Returns:
            제안 목록. 각 항목은 reason 기반으로 키워드를 추출한 것.
        """
        suggestions: list[dict[str, Any]] = []
        reasons = [c["reason"] for c in category_corrections if c.get("reason")]

        if not reasons:
            return suggestions

        # 사유에서 반복 키워드 추출 (간단한 빈도 기반)
        word_counter: Counter[str] = Counter()
        for reason in reasons:
            words = [w.strip() for w in reason.split() if len(w.strip()) >= 2]
            word_counter.update(words)

        # 2회 이상 등장하는 키워드를 동의어 후보로 제안
        for word, count in word_counter.most_common(20):
            if count >= 2:
                suggestions.append({
                    "keyword": word,
                    "frequency": count,
                    "suggestion": f"'{word}'을(를) 관련 카테고리의 동의어로 추가 검토",
                })

        return suggestions
