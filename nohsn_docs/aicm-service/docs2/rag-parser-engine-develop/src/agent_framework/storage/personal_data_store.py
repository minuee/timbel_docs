"""개인 데이터 (schedule + expense + health) 통합 조회 layer.

Wave Insight 의 cross-domain 분석에서 사용. 4 analytics skill
(schedule_analyzer / expense_analyzer / lifestyle_pattern_analyzer / health_advisor)
이 동일 인터페이스로 기간(period_start ~ period_end) 데이터를 가져온다.

기간 단위는 ``date`` (YYYY-MM-DD). user_schedules 만 datetime 이라
``scheduled_at::date`` 로 캐스팅 후 비교.

side-effect: read-only. write 는 expense_logger / schedule_personal /
diary_personal / 향후 health_logger 등 전용 skill 에 위임.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text


class PersonalDataStore:
    """schedule / expense / health 통합 read-only 저장소.

    db_session 은 sync 또는 async sqlalchemy session/connection.
    호출자가 결정. 내부에서는 ``execute(text(...), params)`` 만 사용해
    동기/비동기 양쪽에 호환되도록 설계 (테스트는 mock object).

    실 연동 시:
    - sync: ``Session.execute(...).mappings().all()``
    - async: ``await AsyncSession.execute(...).mappings().all()``
    호출자 측에서 await 여부를 결정. 본 store 는 단순 query 캡슐화.
    """

    def __init__(self, db_session: Any):
        self.db = db_session

    # ------------------------------------------------------------------
    # raw 조회 (기간별)
    # ------------------------------------------------------------------

    async def get_schedules_in_period(
        self, account_id: str | UUID, start: date, end: date
    ) -> list[dict]:
        """user_schedules — 기간 내 일정 (시각 포함)."""
        result = self.db.execute(
            text(
                """
                SELECT id, scheduled_at, title, category, metadata
                  FROM user_schedules
                 WHERE account_id = :a
                   AND scheduled_at::date BETWEEN :s AND :e
                 ORDER BY scheduled_at
                """
            ),
            {"a": str(account_id), "s": start, "e": end},
        )
        rows = self._materialize(result)
        return [dict(r) for r in rows]

    async def get_expenses_in_period(
        self,
        account_id: str | UUID,
        start: date,
        end: date,
        *,
        scope_group: str | None = None,
    ) -> list[dict]:
        """expense_ledger — 기간 내 지출.

        ``scope_group`` 명시 시 해당 scope (personal / sole_proprietor /
        company / business) 만 반환. None 이면 모든 scope (legacy 호출자
        호환). codex 검토(2026-04-28): 개인 분석에서 sole_prop 비용이
        섞이지 않도록 호출측에서 명시 권장.
        """
        sql = (
            "SELECT id, date, category, amount_krw, description, payment_method, "
            "scope_group FROM expense_ledger "
            "WHERE account_id = :a AND date BETWEEN :s AND :e"
        )
        params: dict[str, Any] = {"a": str(account_id), "s": start, "e": end}
        if scope_group is not None:
            sql += " AND scope_group = :sg"
            params["sg"] = scope_group
        sql += " ORDER BY date"
        result = self.db.execute(text(sql), params)
        rows = self._materialize(result)
        return [dict(r) for r in rows]

    async def get_health_logs_in_period(
        self, account_id: str | UUID, start: date, end: date
    ) -> list[dict]:
        """health_log — 기간 내 자가기록 (운동/수면/식사/복약)."""
        result = self.db.execute(
            text(
                """
                SELECT id, date, kind, value_text, value_numeric, metadata
                  FROM health_log
                 WHERE account_id = :a
                   AND date BETWEEN :s AND :e
                 ORDER BY date, kind
                """
            ),
            {"a": str(account_id), "s": start, "e": end},
        )
        rows = self._materialize(result)
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 요약 집계 (skill 의 render 단에서 활용)
    # ------------------------------------------------------------------

    async def expense_summary_by_category(
        self,
        account_id: str | UUID,
        start: date,
        end: date,
        *,
        scope_group: str | None = None,
    ) -> dict[str, dict[str, int]]:
        """카테고리별 지출 합계 + 건수. ``scope_group`` 명시 시 해당 scope 만."""
        sql = (
            "SELECT category, COUNT(*) AS cnt, SUM(amount_krw) AS total "
            "FROM expense_ledger "
            "WHERE account_id = :a AND date BETWEEN :s AND :e"
        )
        params: dict[str, Any] = {"a": str(account_id), "s": start, "e": end}
        if scope_group is not None:
            sql += " AND scope_group = :sg"
            params["sg"] = scope_group
        sql += " GROUP BY category ORDER BY total DESC"
        result = self.db.execute(text(sql), params)
        rows = self._materialize(result)
        return {
            r["category"]: {
                "count": int(r["cnt"]),
                "total_krw": int(r["total"] or 0),
            }
            for r in rows
        }

    async def schedule_summary_by_category(
        self, account_id: str | UUID, start: date, end: date
    ) -> dict[str, int]:
        """일정 카테고리별 건수 (회의/식사/운동/병원/...)."""
        result = self.db.execute(
            text(
                """
                SELECT COALESCE(category, '미분류') AS category, COUNT(*) AS cnt
                  FROM user_schedules
                 WHERE account_id = :a
                   AND scheduled_at::date BETWEEN :s AND :e
                 GROUP BY category
                 ORDER BY cnt DESC
                """
            ),
            {"a": str(account_id), "s": start, "e": end},
        )
        rows = self._materialize(result)
        return {r["category"]: int(r["cnt"]) for r in rows}

    async def health_summary_by_kind(
        self, account_id: str | UUID, start: date, end: date
    ) -> dict[str, int]:
        """건강로그 종류별 건수."""
        result = self.db.execute(
            text(
                """
                SELECT kind, COUNT(*) AS cnt
                  FROM health_log
                 WHERE account_id = :a
                   AND date BETWEEN :s AND :e
                 GROUP BY kind
                 ORDER BY cnt DESC
                """
            ),
            {"a": str(account_id), "s": start, "e": end},
        )
        rows = self._materialize(result)
        return {r["kind"]: int(r["cnt"]) for r in rows}

    # ------------------------------------------------------------------
    # 내부 helper — sync/async 결과를 통일된 list[Mapping] 으로 변환.
    # ------------------------------------------------------------------

    @staticmethod
    def _materialize(result: Any) -> list[dict]:
        """sqlalchemy Result 를 list[dict] 로 변환.

        - sync Result: ``.mappings().all()`` → list of RowMapping
        - mock 객체: ``.mappings().all()`` 그대로 반환하도록 stub 구현
        - 이미 list[dict] 인 경우 그대로 반환.
        """
        if isinstance(result, list):
            return result
        mapper = getattr(result, "mappings", None)
        if mapper is None:
            return list(result)
        rows = mapper().all()
        return [dict(r) for r in rows]
